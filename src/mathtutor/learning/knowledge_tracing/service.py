"""Owner-scoped, transaction-aware event and prediction service.

``conn`` can be the existing assessment short transaction, so facts and v2
events commit together. Projection/model failures are isolated from the facts;
every summary can be rebuilt from append-only events. No UI/cache is a source.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert

from .events import FEATURE_SCHEMA, GRAPH_VERSION, LABEL_POLICY, BASELINE_POLICY, LearningEvent, baseline_prediction, evidence_summary, ordered_attempts, utcnow, valid_events
from .schema import learning_events, learning_predictions, student_state_snapshots, learning_generations


class StudentStateService:
    def __init__(self, engine, model_path: str | Path | None = None, source_package: str | Path | None = None):
        self.engine = engine
        self.tracker = None
        self.model_status = "not_trained"
        if model_path:
            try:
                from .runtime import LSTMTracker
                self.tracker = LSTMTracker.load(model_path)
                self.model_status = "shadow"
            except (ImportError, OSError, ValueError, KeyError, TypeError):
                self.model_status = "unavailable_fallback"
        # Bundled research model: shadow only, no teaching control, and no
        # probability for MathTutor tasks until a reviewed target mapping exists.
        self.source_model = None
        self.source_model_status = "not_bundled"
        if source_package:
            try:
                from .model_package import SourceModelPackage
                self.source_model = SourceModelPackage(source_package)
                self.source_model_status = "shadow"
            except (ImportError, OSError, ValueError, KeyError, TypeError):
                self.source_model_status = "unavailable_fallback"

    @property
    def dkt_mode(self) -> str:
        """Overall DKT state; any loaded model is shadow, never policy."""
        if self.tracker is not None or self.source_model is None:
            return self.model_status
        return self.source_model_status

    def source_model_summary(self) -> dict:
        if self.source_model is None:
            return {"status": self.source_model_status, "controls_teaching": False}
        return {**self.source_model.identity, "status": self.source_model_status}

    @classmethod
    async def create_memory(cls, model_path=None):
        """Tests use the identical storage algorithm, not a second fake model."""
        from sqlalchemy.ext.asyncio import create_async_engine
        from .schema import metadata
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        return cls(engine, model_path)

    async def append_event(self, event: LearningEvent, *, conn=None):
        """Trusted application lifecycle/self-report events; no client payloads."""
        if event.event_type in {"attempt_assessed", "evidence_invalidated", "attempt_submitted"}:
            raise ValueError("use the assessment/invalidation API for learning labels")
        async with self._transaction(conn) as db:
            result = await self._append(db, event)
            await self._checkpoint(db, event.student_id)
            return result

    @asynccontextmanager
    async def _transaction(self, conn=None):
        if conn is not None:
            yield conn
        else:
            async with self.engine.begin() as opened:
                yield opened

    async def events(self, student_id: str, *, conn=None) -> list[LearningEvent]:
        async with self._transaction(conn) as db:
            rows = (await db.execute(select(learning_events.c.payload).where(
                learning_events.c.student_id == str(student_id)).order_by(learning_events.c.event_seq))).scalars().all()
            return ordered_attempts([LearningEvent.model_validate(x) for x in rows])

    @staticmethod
    def _exposure_facts(history, problem_revision):
        helps = [x for x in valid_events(history) if x.problem_revision == str(problem_revision)
                 and x.event_type in {"help_possibly_exposed", "help_presented"}]
        presented_ids = {x.delivery_id for x in helps if x.event_type == "help_presented" and x.delivery_id}
        uncertain = any(x.event_type == "help_possibly_exposed"
            and (not x.delivery_id or x.delivery_id not in presented_ids) for x in helps)
        uncertain = uncertain or any(x.event_type == "attempt_assessed" and x.provenance_uncertain
            and x.graph_version == "legacy_unmapped" and x.problem_revision == str(problem_revision)
            for x in valid_events(history))
        return helps, uncertain, any(x.target_answer_exposed for x in helps)

    async def exposure_context(self, student_id, problem_revision, *, conn=None):
        """One canonical-task source for controller/Planner and label policy."""
        history = await self.events(str(student_id), conn=conn)
        helps, uncertain, exposed = self._exposure_facts(history, problem_revision)
        return {"problem_revision": str(problem_revision), "target_answer_exposed": exposed,
                "help_exposed": bool(helps), "provenance_uncertain": uncertain,
                "assistance_level": 5 if exposed else 1 if helps else 0,
                "prior_help_event_ids": [x.event_id for x in helps]}

    async def _existing(self, db, student_id, event_id):
        row = (await db.execute(select(learning_events.c.payload).where(
            learning_events.c.student_id == str(student_id), learning_events.c.event_id == event_id))).scalar_one_or_none()
        return LearningEvent.model_validate(row) if row else None

    async def _append(self, db, event: LearningEvent):
        existing = await self._existing(db, event.student_id, event.event_id)
        if existing:
            ignored = {"event_seq", "occurred_at"}
            if existing.model_dump(exclude=ignored) != event.model_dump(exclude=ignored):
                raise ValueError("learning event id reused with different facts")
            return existing
        last = (await db.execute(select(func.max(learning_events.c.event_seq)).where(
            learning_events.c.student_id == event.student_id))).scalar() or 0
        event = event.model_copy(update={"event_seq": last + 1})
        await db.execute(learning_events.insert().values(student_id=event.student_id,
            event_id=event.event_id, event_seq=event.event_seq, event_type=event.event_type,
            cycle_id=event.cycle_id, payload=event.model_dump(mode="json")))
        if getattr(self, "stage_review", None) is not None:
            await self.stage_review.on_event(db, event)
        return event

    async def _recurrent_state(self, db, student_id, history):
        tracker = self.tracker
        if tracker is None:
            return None
        state, cutoff = tracker.initialize(), 0
        row = (await db.execute(select(student_state_snapshots.c.payload).where(
            student_state_snapshots.c.student_id == str(student_id)))).scalar_one_or_none()
        # Corrections require full replay, even if a newer checkpoint exists.
        has_correction = any(x.event_type == "evidence_invalidated" for x in history)
        if row and not has_correction and row.get("last_event_seq", 0) <= max((x.event_seq for x in history), default=0):
            try:
                state = tracker.restore(row, student_id=str(student_id))
                cutoff = row["last_event_seq"]
            except (ValueError, KeyError, TypeError):
                pass
        for event in valid_events(history):
            if event.event_seq > cutoff and event.event_type != "attempt_submitted":
                state = tracker.update(state, event)
        return state

    async def prepare_prediction(
        self, student_id, *, prediction_id, session_id, cycle_id, problem_id,
        problem_revision, item_family_id, skill_ids, difficulty=None, at_presentation=False, conn=None,
    ) -> dict:
        """Persist the prediction before verification, with no outcome input."""
        student_id = str(student_id)
        context = {"session_id": str(session_id), "cycle_id": str(cycle_id),
                   "problem_id": str(problem_id), "problem_revision": str(problem_revision),
                   "item_family_id": item_family_id, "skill_ids": list(skill_ids), "difficulty": difficulty}
        async with self._transaction(conn) as db:
            existing = (await db.execute(select(learning_predictions.c.payload).where(
                learning_predictions.c.student_id == student_id,
                learning_predictions.c.prediction_id == prediction_id))).scalar_one_or_none()
            if existing:
                if existing["item_context"] != context:
                    raise ValueError("prediction id reused for another item")
                return existing
            history = await self.events(student_id, conn=db)
            cutoff = max((x.event_seq for x in history), default=0)
            result = {"prediction_id": prediction_id, "student_id": student_id,
                "history_cutoff_seq": cutoff, "predicted_at": utcnow(), "item_context": context,
                "model_version": self.tracker.model_version if self.tracker else "evidence_tracker_v2",
                "policy_source": "evidence_tracker_v2", "mode": self.model_status,
                "baseline_probability": baseline_prediction(history, skill_ids),
                "shadow_probability": None, "prediction_label": None,
                "feature_schema_version": FEATURE_SCHEMA, "graph_version": GRAPH_VERSION}
            result.update(label_policy_version=LABEL_POLICY, baseline_policy=BASELINE_POLICY)
            if self.tracker:
                try:
                    if self.tracker.graph_version != GRAPH_VERSION or any(x.graph_version != self.tracker.graph_version for x in history):
                        raise ValueError("graph_version_mismatch")
                    state = await self._recurrent_state(db, student_id, history)
                    result["shadow_probability"] = self.tracker.predict(state, context)
                except (ValueError, KeyError, TypeError, ArithmeticError):
                    result["mode"] = "out_of_coverage_fallback"
            result["prediction_timing"] = "before_task_display" if at_presentation else "legacy_before_assessment"
            if at_presentation:
                # Frozen target contract is separate from the existing evidence baseline.
                # Source DKT weights do not certify MathTutor task equivalence.
                observed = [x for x in history if x.event_type != "attempt_submitted"]
                last = observed[-1] if observed else None
                result["frozen_forecast"] = {
                    "presentation_id": prediction_id, "task_identity": str(problem_revision),
                    "query_sha256": hashlib.sha256(json.dumps(context, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                    "visible_event_boundary": cutoff,
                    "state_cutoff": {"event_id": last.event_id, "event_seq": last.event_seq} if last else None,
                    "state_scope": "existing_product_event_tracker",
                    "model_identity": result["model_version"],
                    "probability": None, "probability_source": "none",
                    "coverage_status": "unsupported_target", "product_runtime_enabled": False,
                    "reason": "target_task_mapping_and_predictor_not_validated",
                    "shadow_model": self.source_model_summary(),
                }
            await db.execute(learning_predictions.insert().values(
                student_id=student_id, prediction_id=prediction_id,
                history_cutoff_seq=cutoff, payload=result))
            return result

    async def presentation(self, student_id, cycle_id, *, conn=None):
        """Lookup only. A response path may never invent an earlier presentation."""
        async with self._transaction(conn) as db:
            return (await db.execute(select(learning_predictions.c.payload).where(
                learning_predictions.c.student_id == str(student_id),
                learning_predictions.c.prediction_id == f"presentation:{cycle_id}"))).scalar_one_or_none()

    async def record_submission(self, student_id, *, event_id, session_id, cycle_id, problem_id,
                                problem_revision, item_family_id, skill_ids, response_fingerprint,
                                prediction_id="", task_purpose="practice", conn=None):
        """Durable first-slot reservation before parsing/judging; supplies no correctness.

        Raw text is retained by the existing owner-scoped request journal. This fact
        binds its request identity and digest, and survives a judge failure.
        """
        async with self._transaction(conn) as db:
            event = LearningEvent(event_id=event_id, student_id=str(student_id), session_id=str(session_id),
                cycle_id=str(cycle_id), event_type="attempt_submitted", problem_id=str(problem_id),
                problem_revision=str(problem_revision), item_family_id=item_family_id, skill_ids=tuple(skill_ids),
                response_fingerprint=response_fingerprint, prediction_id=prediction_id, task_purpose=task_purpose,
                supervision_policy_version="first_content_submission_v1")
            return await self._append(db, event)

    async def record_attempt(
        self, student_id, *, session_id, cycle_id, problem_id, problem_revision,
        item_family_id, skill_ids, assessment_id, attempt_id, correctness,
        completion_scope="full_problem", subgoal_id="", prediction_id=None,
        event_id=None, provenance_uncertain=False, active_response_ms=None,
        difficulty=None, misconception_codes=(), verified_error_skill_ids=(),
        task_purpose="practice", graph_version=GRAPH_VERSION, leakage_group_id="", time_gap_ms=None,
        response_fingerprint="", submission_event_id="", response_format="free_response", conn=None,
    ) -> LearningEvent:
        student_id, cycle_id = str(student_id), str(cycle_id)
        event_id = event_id or f"attempt:{attempt_id}"
        normalized = "unknown" if correctness in {None, "undetermined", "ungradable", "unknown"} else correctness
        async with self._transaction(conn) as db:
            existing = await self._existing(db, student_id, event_id)
            if existing:
                if (existing.attempt_id != str(attempt_id) or existing.assessment_id != str(assessment_id)
                        or existing.correctness != normalized or existing.problem_revision != str(problem_revision)
                        or existing.problem_id != str(problem_id) or existing.cycle_id != cycle_id):
                    raise ValueError("attempt identity conflict")
                return existing
            history = await self.events(student_id, conn=db)
            submission = None
            if submission_event_id:
                submission = next((x for x in history if x.event_id == submission_event_id), None)
                if (submission is None or submission.event_type != "attempt_submitted"
                        or submission.problem_revision != str(problem_revision) or submission.cycle_id != cycle_id
                        or submission.problem_id != str(problem_id)):
                    raise ValueError("submission binding mismatch")
                if any(x.event_type == "attempt_assessed" and x.submission_event_id == submission_event_id for x in history):
                    raise ValueError("submission already assessed")
            # Invalidating an assessment cannot erase the fact of its submission.
            prior_task_attempt = any(x.problem_revision == str(problem_revision)
                and x.event_type in {"attempt_submitted", "attempt_assessed"}
                and (submission is None or x.event_seq < submission.event_seq) for x in history)
            repeated = bool(response_fingerprint) and any(
                x.event_type == "attempt_assessed" and x.problem_revision == str(problem_revision)
                and x.response_fingerprint == response_fingerprint and x.completion_scope == completion_scope
                for x in valid_events(history))
            # A new tab/conversation/cycle cannot erase exposure to the SAME
            # canonical task. A genuinely new problem revision starts clean;
            # sharing a topic/family alone never transfers answer exposure.
            helps, uncertain, answer_exposed = self._exposure_facts(history, problem_revision)
            uncertain = provenance_uncertain or uncertain
            kind = "post_solution" if answer_exposed else "unknown" if uncertain or normalized == "unknown" else "assisted" if helps else "independent"
            prediction_id = prediction_id or f"prediction:{attempt_id}"
            prediction = await self.prepare_prediction(student_id, prediction_id=prediction_id,
                session_id=session_id, cycle_id=cycle_id, problem_id=problem_id,
                problem_revision=problem_revision, item_family_id=item_family_id,
                skill_ids=skill_ids, difficulty=difficulty, conn=db)
            event = await self._append(db, LearningEvent(
                event_id=event_id, student_id=student_id, session_id=str(session_id), cycle_id=cycle_id,
                event_type="attempt_assessed", problem_id=str(problem_id), problem_revision=str(problem_revision),
                item_family_id=item_family_id, skill_ids=tuple(skill_ids), assessment_id=str(assessment_id),
                leakage_group_id=leakage_group_id, time_gap_ms=time_gap_ms,
                attempt_id=str(attempt_id), prediction_id=prediction_id, correctness=normalized,
                response_fingerprint=response_fingerprint, duplicate_response=repeated,
                prior_task_attempt=prior_task_attempt, submission_event_id=submission_event_id,
                supervision_policy_version=LABEL_POLICY,
                completion_scope=completion_scope, subgoal_id=subgoal_id, evidence_kind=kind,
                target_answer_exposed_before_attempt=answer_exposed,
                prior_help_event_ids=tuple(x.event_id for x in helps), provenance_uncertain=uncertain,
                active_response_ms=active_response_ms, difficulty=difficulty,
                misconception_codes=tuple(misconception_codes), verified_error_skill_ids=tuple(verified_error_skill_ids),
                task_purpose=task_purpose, graph_version=graph_version,
                response_format=response_format,
            ))
            # Label is associated only after the immutable pre-outcome forecast.
            presentation_id = f"presentation:{cycle_id}"
            label = int(normalized == "correct") if event.independent_target else None
            if "observed_event_seq" not in prediction and (
                    prediction_id != presentation_id or completion_scope == "full_problem"):
                prediction = {**prediction, "assessment_id": str(assessment_id),
                              "observed_event_seq": event.event_seq, "prediction_label": label}
                await db.execute(learning_predictions.update().where(
                    learning_predictions.c.student_id == student_id,
                    learning_predictions.c.prediction_id == prediction_id).values(payload=prediction))
            # Presentation-time forecast is labelled once. Later help or a
            # repeated success cannot overwrite the first independent failure.
            presented = (await db.execute(select(learning_predictions.c.payload).where(
                learning_predictions.c.student_id == student_id,
                learning_predictions.c.prediction_id == presentation_id))).scalar_one_or_none()
            if presented and completion_scope == "full_problem" and not presented.get("observed_event_seq"):
                presented = {**presented, "observed_event_seq": event.event_seq,
                    "assessment_id": str(assessment_id), "prediction_label": label}
                await db.execute(learning_predictions.update().where(
                    learning_predictions.c.student_id == student_id,
                    learning_predictions.c.prediction_id == presentation_id).values(payload=presented))
            await self._checkpoint(db, student_id)
            return event

    async def record_help(
        self, student_id, *, event_id, session_id, cycle_id, problem_id, problem_revision,
        item_family_id, skill_ids, event_type="help_presented", help_kind="hint",
        target_answer_exposed=False, target_answer_authorized=None, request_id="",
        delivery_id="", subgoal_id="", graph_version=GRAPH_VERSION, conn=None,
    ) -> LearningEvent:
        if event_type not in {"help_requested", "help_committed", "help_possibly_exposed", "help_presented"}:
            raise ValueError("invalid help delivery phase")
        async with self._transaction(conn) as db:
            event = await self._append(db, LearningEvent(event_id=event_id, student_id=str(student_id),
                session_id=str(session_id), cycle_id=str(cycle_id), event_type=event_type,
                problem_id=str(problem_id), problem_revision=str(problem_revision), item_family_id=item_family_id,
                skill_ids=tuple(skill_ids), help_kind=help_kind, target_answer_exposed=target_answer_exposed,
                target_answer_authorized=target_answer_authorized, request_id=request_id,
                delivery_id=delivery_id, subgoal_id=subgoal_id, graph_version=graph_version))
            await self._checkpoint(db, str(student_id))
            return event

    async def invalidate(self, student_id, *, event_id, invalidates_event_id, conn=None):
        async with self._transaction(conn) as db:
            original = await self._existing(db, str(student_id), invalidates_event_id)
            if original is None:
                raise ValueError("cannot invalidate another owner's or missing event")
            if original.event_type != "attempt_assessed":
                raise ValueError("only assessment evidence can be excluded")
            event = LearningEvent(event_id=event_id, student_id=str(student_id), session_id=original.session_id,
                cycle_id=original.cycle_id, event_type="evidence_invalidated", problem_id=original.problem_id,
                problem_revision=original.problem_revision, item_family_id=original.item_family_id,
                invalidates_event_id=invalidates_event_id)
            await self._append(db, event)
            predictions = (await db.execute(select(learning_predictions).where(
                learning_predictions.c.student_id == str(student_id)))).mappings().all()
            for row in predictions:
                payload = row["payload"]
                if payload.get("assessment_id") == original.assessment_id:
                    await db.execute(learning_predictions.update().where(
                        learning_predictions.c.student_id == str(student_id),
                        learning_predictions.c.prediction_id == row["prediction_id"]
                    ).values(payload={**payload, "label_excluded": True, "label_exclusion_event_id": event_id}))
            await self._checkpoint(db, str(student_id))

    async def _checkpoint(self, db, student_id):
        history = await self.events(student_id, conn=db)
        last = max((x.event_seq for x in history), default=0)
        snapshot = {"student_id": student_id, "last_event_seq": last, "model_version": "evidence_tracker_v2",
                    "feature_schema_version": FEATURE_SCHEMA, "graph_version": GRAPH_VERSION}
        if self.tracker:
            try:
                state = await self._recurrent_state(db, student_id, history)
                snapshot = self.tracker.snapshot(state, student_id=student_id, last_event_seq=last)
            except (ValueError, KeyError, TypeError, ArithmeticError):
                snapshot["tracker_status"] = "unavailable_fallback"
        snapshot["evidence_summary"] = evidence_summary(history)
        values = {k: snapshot[k] for k in ("student_id", "last_event_seq", "model_version", "feature_schema_version", "graph_version")}
        values["payload"] = snapshot
        await db.execute(insert(student_state_snapshots).values(**values).on_conflict_do_update(
            index_elements=["student_id"], set_=values))

    async def prepare_replay(self, student_id):
        """Capture a deletion generation together with immutable replay input."""
        student_id = str(student_id)
        async with self.engine.begin() as db:
            await db.execute(insert(learning_generations).values(student_id=student_id, generation=0)
                .on_conflict_do_nothing(index_elements=["student_id"]))
            generation = (await db.execute(select(learning_generations.c.generation).where(
                learning_generations.c.student_id == student_id))).scalar_one()
            history = await self.events(student_id, conn=db)
        version = self.tracker.model_version if self.tracker else "evidence_tracker_v2"
        snapshot = {"student_id": student_id, "model_version": version,
            "last_event_seq": max((e.event_seq for e in history), default=0),
            "feature_schema_version": FEATURE_SCHEMA, "graph_version": GRAPH_VERSION}
        if self.tracker:
            recurrent = self.tracker.initialize()
            for event in valid_events(history):
                if event.event_type != "attempt_submitted":
                    recurrent = self.tracker.update(recurrent, event)
            snapshot = self.tracker.snapshot(recurrent, student_id=student_id,
                                             last_event_seq=snapshot["last_event_seq"])
        snapshot["evidence_summary"] = evidence_summary(history)
        snapshot["learning_generation"] = generation
        return snapshot

    async def commit_replay(self, snapshot):
        """CAS applies equally to manual replay and future model-package jobs."""
        sid = snapshot["student_id"]
        version = self.tracker.model_version if self.tracker else "evidence_tracker_v2"
        if snapshot["model_version"] != version:
            return False
        async with self.engine.begin() as db:
            # First acquire the SQLite write transaction with a conditional
            # update. Deletion and CAS cannot pass each other at commit time.
            matched = await db.execute(learning_generations.update().where(
                learning_generations.c.student_id == sid,
                learning_generations.c.generation == snapshot["learning_generation"]
            ).values(generation=learning_generations.c.generation))
            if matched.rowcount != 1:
                return False
            last = (await db.execute(select(func.max(learning_events.c.event_seq)).where(
                learning_events.c.student_id == sid))).scalar() or 0
            if last != snapshot["last_event_seq"]:
                return False
            values = {k: snapshot[k] for k in ("student_id", "last_event_seq", "model_version", "feature_schema_version", "graph_version")}
            values["payload"] = snapshot
            await db.execute(insert(student_state_snapshots).values(**values).on_conflict_do_update(
                index_elements=["student_id"], set_=values))
        return True

    async def recompute(self, student_id):
        for _ in range(3):
            snapshot = await self.prepare_replay(student_id)
            if await self.commit_replay(snapshot):
                return {"ok": True, "last_event_seq": snapshot["last_event_seq"],
                        "learning_generation": snapshot["learning_generation"]}
        raise ValueError("learning history changed during replay")

    async def summary(self, student_id, *, conn=None):
        async with self._transaction(conn) as db:
            history = await self.events(str(student_id), conn=db)
            result = evidence_summary(history)
            result.update({"policy_source": "evidence_tracker_v2", "dkt_mode": self.dkt_mode,
                           "dkt_controls_teaching": False, "dkt_source_model": self.source_model_summary(),
                           "training_data": {
                "events": len(history), "independent_targets": sum(x.independent_target for x in valid_events(history)),
                "uncertain_provenance": sum(x.provenance_uncertain for x in valid_events(history)),
            }})
            return result

    async def import_legacy(self, student_id, *, conn=None):
        """Preserve known assessments; never infer old exposure chronology.

        Existing legacy tables remain unchanged. Rows are idempotent and
        excluded from the independent training target, even when old L0 was
        recorded, because old max-level is not a delivery timeline.
        """
        from mathtutor.infrastructure.schema import attempts, mastery_evidence, tutoring_cycles, verification_logs, math_problems
        async with self._transaction(conn) as db:
            known_attempts = {event.attempt_id for event in await self.events(str(student_id), conn=db)
                              if event.event_type == "attempt_assessed"}
            rows = (await db.execute(select(mastery_evidence, attempts.c.cycle_id, tutoring_cycles.c.session_id,
                tutoring_cycles.c.problem_id, math_problems.c.problem_id.label("verified_problem_id"),
                math_problems.c.content_hash.label("canonical_revision"), math_problems.c.problem_type.label("verified_family")
                ).select_from(mastery_evidence.join(attempts,
                    mastery_evidence.c.attempt_id == attempts.c.attempt_id).join(tutoring_cycles,
                    attempts.c.cycle_id == tutoring_cycles.c.cycle_id).outerjoin(verification_logs,
                    (mastery_evidence.c.attempt_assessment_log_id == verification_logs.c.log_id)
                    & (verification_logs.c.attempt_id == attempts.c.attempt_id)).outerjoin(math_problems,
                    verification_logs.c.problem_id == math_problems.c.problem_id)).where(
                    mastery_evidence.c.student_id == str(student_id), attempts.c.student_id == str(student_id),
                    tutoring_cycles.c.student_id == str(student_id)).order_by(mastery_evidence.c.created_at))).mappings().all()
            count = 0
            for row in rows:
                identity = f"legacy:{row['evidence_id']}"
                if await self._existing(db, str(student_id), identity):
                    continue
                # Any v2 event identity is valid: do not assume applications
                # used the optional default ``attempt:{id}`` event_id shape.
                if row["attempt_id"] in known_attempts:
                    continue
                await self._append(db, LearningEvent(event_id=identity, student_id=str(student_id),
                    session_id=row["session_id"], cycle_id=row["cycle_id"], event_type="attempt_assessed",
                    occurred_at=row["created_at"], problem_id=row["verified_problem_id"] or row["problem_id"] or "legacy_unknown",
                    problem_revision=row["canonical_revision"] or "legacy_unknown", item_family_id=row["verified_family"] or "legacy_unknown",
                    skill_ids=(row["skill_id"],), assessment_id=row["attempt_assessment_log_id"], attempt_id=row["attempt_id"],
                    correctness=row["correctness"], evidence_kind="unknown", provenance_uncertain=True,
                    completion_scope="subgoal" if row["correctness"] == "partial" else "full_problem",
                    graph_version="legacy_unmapped"))
                count += 1
                known_attempts.add(row["attempt_id"])
            if count:
                await self._checkpoint(db, str(student_id))
            return count
