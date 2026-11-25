"""Bounded learning episodes: response patterns, independent recall and transfer.

Only the server chooses the current item, clock and evidence grade.  These
records never update mastery/DKT.  A finite item catalog also bounds saved
history; read/resume cannot reset exposure or the first opportunity.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from mathtutor.learning import diagnostic_probes as probes
from mathtutor.learning import linear_review, review_items, review_schedule
from mathtutor.learning.knowledge_tracing.events import valid_events
from mathtutor.learning.knowledge_tracing.service import StudentStateService
from mathtutor.learning.knowledge_tracing.schema import learning_loop_episodes as episodes
from mathtutor.repositories.sqlite_runtime import ensure_student

POLICY = "learning_loop_v1"
MAX_RECEIPTS = 64
DOMAINS = {**probes.DOMAIN_LABELS, linear_review.DOMAIN: {"zh": "一元一次方程", "en": "Linear equations"}}


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("Learning clock must include a timezone")
    return value.astimezone(timezone.utc).isoformat()


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


class LearningLoopService:
    def __init__(self, engine, *, clock=None):
        self.engine = engine
        self.history = StudentStateService(engine)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self):
        return _date(_iso(self.clock()))

    @staticmethod
    def _domain(domain):
        if domain not in DOMAINS:
            raise ValueError("Unsupported learning-loop domain")

    async def _load(self, conn, sid, domain):
        return (await conn.execute(select(episodes.c.payload).where(
            episodes.c.student_id == str(sid), episodes.c.domain == domain))).scalar_one_or_none()

    async def _old_linear_anchor(self, conn, sid):
        history = await self.history.events(sid, conn=conn)
        return next((event for event in valid_events(history) if linear_review.eligible(event)), None)

    async def _seen_revisions(self, conn, sid):
        return {event.problem_revision for event in await self.history.events(sid, conn=conn)}

    async def read(self, sid, *, conn=None):
        if conn is None:
            async with self.engine.connect() as db:
                return await self.read(sid, conn=db)
        now = self._now()
        rows = []
        for domain, labels in DOMAINS.items():
            payload = await self._load(conn, sid, domain)
            if payload is None and domain == linear_review.DOMAIN:
                anchor = await self._old_linear_anchor(conn, sid)
                payload = linear_review.seeded(anchor) if anchor else None
            rows.append({"domain": domain, "label_zh": labels["zh"], "label_en": labels["en"],
                         "episode": self._public(payload, now) if payload else None})
        return {"schema_version": POLICY, "server_time": _iso(now), "domains": rows}

    def _public(self, payload, now):
        payload = self._upgraded(payload)
        compatible = self._compatible(payload)
        # A different catalog cannot interpret old probe IDs. Preserve those
        # records, but never run them through today's rule engine on reads.
        arithmetic = payload["domain"] in probes.DOMAINS
        diagnostic = probes.diagnostic_state(payload["domain"], payload["diagnosis"]) if compatible and arithmetic else {
            "status": "uncertain", "supported_rule": None, "answered": len(payload.get("diagnosis", []))}
        supported = diagnostic["supported_rule"]
        if payload.get("diagnostic_interrupted") or payload.get("pattern_retracted"):
            diagnostic = {**diagnostic, "status": "uncertain"}
            supported = None
        labels = probes.RULE_LABELS.get(supported) or {
            "zh": "当前证据还不能区分错因，可以继续用新题检查。",
            "en": "The evidence does not yet distinguish a cause; continue with a fresh problem.",
        }
        if not arithmetic and compatible:
            labels = {"zh": "你在普通辅导中首次独立解出一道新方程。复测从这次作答起算。",
                      "en": "You solved a new equation independently on your first attempt in tutoring. Reviews start from that response."}
        elif not compatible:
            labels = {"zh": "这轮的原始依据或版本已停用。已有作答保存在历史记录中。",
                      "en": "The original evidence or version for this check has been retired. Earlier responses are saved."}
        question = probes.public_probe(review_items.get_probe(payload["current_probe"])) if compatible and payload["current_probe"] else None
        due = payload["due_at"]
        return {"episode_id": payload["episode_id"], "domain": payload["domain"],
                "phase": payload["phase"] if compatible else "exhausted", "question": question,
                "due_at": due, "can_start": bool(compatible and payload["phase"] == "waiting" and due and now >= _date(due)),
                "diagnostic": {"status": diagnostic["status"], "answered": diagnostic["answered"],
                               "label_zh": labels["zh"], "label_en": labels["en"]},
                "evidence": dict(payload["evidence"]), "review_round": payload["review_round"],
                "schedule": review_schedule.public_schedule(payload) if compatible else None,
                "archive_reason": None if compatible else ("source_excluded" if payload.get("schedule_version") == "source_excluded" else "retired"),
                "source_cycle_id": payload.get("source_cycle_id") if compatible else None,
                "observations": self._observations(payload) if compatible and payload["phase"] != "diagnose" else [],
                "feedback": deepcopy(payload.get("feedback"))}

    @staticmethod
    def _observations(payload):
        rows = []
        for event in reversed(payload["attempts"]):
            if event["correctness"] != "incorrect":
                continue
            probe = review_items.get_probe(event["probe_id"])
            rows.append({
                "probe_id": probe.probe_id, "statement": probe.statement, "response": event["answer"],
                "category": ("method_transfer" if probe.purpose == "transfer" else
                             "conditions" if probe.domain == linear_review.DOMAIN else "calculation"),
                "relation": probe.relation, "independent": event["independent"], "occurred_at": event["occurred_at"],
            })
            if len(rows) == 3:
                break
        return rows

    @staticmethod
    def _issue(payload, phase, probe):
        if probe is None or len(payload["served_ids"]) >= probes.MAX_CATALOG_SIZE:
            payload.update(phase="exhausted", current_probe=None, due_at=None)
            return
        if probe.probe_id in payload["served_ids"]:
            raise ValueError("Repeated or over-budget learning item")
        payload["served_ids"].append(probe.probe_id)
        payload.update(phase=phase, current_probe=probe.probe_id, current_helped=False, due_at=None)

    @classmethod
    def _followup(cls, payload, phase, seen_revisions=()):
        probe = review_items.choose(payload["domain"], phase, payload["review_round"],
                                    payload["served_ids"], payload["attempts"], seen_revisions)
        cls._issue(payload, phase, probe)

    async def _save(self, conn, sid, domain, original, updated):
        # Cancellation delivered before the durable mutation aborts the transaction.
        await asyncio.sleep(0)
        changed = await conn.execute(episodes.update().where(
            episodes.c.student_id == str(sid), episodes.c.domain == domain,
            episodes.c.payload == original).values(payload=updated))
        if changed.rowcount != 1:
            raise ValueError("Learning progress changed; reload before continuing")
        await asyncio.sleep(0)

    async def start(self, sid, domain):
        self._domain(domain)
        now = self._now()
        async with self.engine.begin() as conn:
            original = await self._load(conn, sid, domain)
            if original is None and domain == linear_review.DOMAIN:
                anchor = await self._old_linear_anchor(conn, sid)
                if not anchor:
                    raise ValueError("Solve a new linear equation independently in tutoring first")
                await linear_review.register(conn, anchor)
                original = await self._load(conn, sid, domain)
            if original is None:
                await ensure_student(conn, student_id=str(sid))
                payload = {"policy": POLICY, "probe_policy": probes.POLICY_VERSION, "episode_id": str(uuid4()),
                    "domain": domain, "phase": "diagnose", "current_probe": None, "current_helped": False,
                    "due_at": None, "updated_at": _iso(now), "diagnosis": [], "served_ids": [],
                    "exposed_ids": [], "attempts": [], "receipts": [], "feedback": None,
                    "schedule_version": review_schedule.VERSION, "anchor_at": None, "checkpoints": {},
                    "review_round": 0, "evidence": {"independent_practice": 0, "delayed_review": 0, "structural_transfer": 0}}
                seen = await self._seen_revisions(conn, sid)
                excluded = [p.probe_id for p in probes.catalog(domain) if review_items.seen_in_tutoring(p, seen)]
                self._issue(payload, "diagnose", probes.choose_probe(domain, (), excluded))
                await asyncio.sleep(0)
                await conn.execute(insert(episodes).values(student_id=str(sid), domain=domain, payload=payload)
                    .on_conflict_do_nothing())
            else:
                updated = deepcopy(self._upgraded(original))
                if not self._compatible(updated):
                    raise ValueError("This saved learning episode is available as history")
                if updated["phase"] == "waiting" and updated["due_at"] and now >= _date(updated["due_at"]):
                    updated["review_due_at"] = updated["due_at"]
                    self._followup(updated, "review", await self._seen_revisions(conn, sid))
                    updated.update(updated_at=_iso(now), feedback=None)
                if updated != original:
                    await self._save(conn, sid, domain, original, updated)
            return await self.read(sid, conn=conn)

    @staticmethod
    def _upgraded(payload):
        if payload.get("policy") == POLICY and payload.get("probe_policy") == probes.POLICY_VERSION:
            return review_schedule.upgrade(payload)
        return payload

    @staticmethod
    def _compatible(payload):
        return (payload.get("policy") == POLICY and payload.get("probe_policy") == probes.POLICY_VERSION
                and payload.get("schedule_version") == review_schedule.VERSION)

    async def submit(self, sid, *, domain, episode_id, probe_id, request_id, answer=None, help_requested=False):
        self._domain(domain)
        now = self._now()
        kind = "help" if help_requested else "answer"
        fingerprint = hashlib.sha256(json.dumps([kind, episode_id, probe_id, answer], ensure_ascii=False).encode()).hexdigest()
        async with self.engine.begin() as conn:
            stored = await self._load(conn, sid, domain)
            if not stored or stored["episode_id"] != episode_id:
                raise ValueError("This learning episode is unavailable or belongs to another learner")
            original = self._upgraded(stored)
            if not self._compatible(original):
                raise ValueError("This saved learning episode is available as history")
            receipt = next((r for r in original["receipts"] if r["request_id"] == request_id), None)
            if receipt:
                if receipt["fingerprint"] != fingerprint:
                    raise ValueError("A submitted request cannot be changed")
                return await self.read(sid, conn=conn)
            if original["current_probe"] != probe_id or original["phase"] not in {"diagnose", "practice", "review", "transfer"}:
                raise ValueError("This question has already changed; reload before continuing")
            if now < _date(original["updated_at"]):
                raise ValueError("The system clock moved backwards; try again after it catches up")
            probe = review_items.get_probe(probe_id)
            if probe.domain != domain:
                raise ValueError("Question belongs to a different learning domain")
            updated = deepcopy(original)
            phase = original["phase"]
            seen_revisions = await self._seen_revisions(conn, sid)
            if help_requested:
                if probe_id not in updated["exposed_ids"]:
                    updated["exposed_ids"].append(probe_id)
                updated["current_helped"] = True
                updated["feedback"] = {"kind": "help", "probe_id": probe_id, "statement": probe.statement, "independent": False, **review_items.feedback(probe)}
                if phase == "diagnose":
                    # Teaching invalidates the fixed-rule assumption across diagnostic probes.
                    updated["diagnostic_interrupted"] = True
                    self._followup(updated, "practice", seen_revisions)
            else:
                assessed = review_items.assess(probe, answer)
                seen_in_tutoring = review_items.seen_in_tutoring(probe, seen_revisions)
                independent = not original["current_helped"] and probe_id not in original["exposed_ids"] and not seen_in_tutoring
                result = assessed["correctness"]
                if result == "unknown":
                    updated["feedback"] = {"kind": "unknown", "probe_id": probe_id, "statement": probe.statement}
                else:
                    event = {"probe_id": probe_id, "phase": phase, "answer": assessed["normalized_answer"],
                        "correctness": result, "independent": independent, "occurred_at": _iso(now),
                        "relation": probe.relation}
                    updated["attempts"].append(event)
                    if len(updated["attempts"]) > probes.MAX_CATALOG_SIZE:
                        raise ValueError("Learning history budget exceeded")
                    updated["feedback"] = {"kind": result, "probe_id": probe_id, "statement": probe.statement,
                        "independent": independent, **review_items.feedback(probe)}
                    if seen_in_tutoring:
                        updated["feedback"]["seen_in_tutoring"] = True
                    if phase == "diagnose":
                        updated["diagnosis"].append({"probe_id": probe_id, "answer": assessed["normalized_answer"], "independent": independent})
                        excluded = [p.probe_id for p in probes.catalog(domain) if review_items.seen_in_tutoring(p, seen_revisions)]
                        next_probe = probes.choose_probe(domain, updated["diagnosis"], [*updated["served_ids"], *excluded])
                        if next_probe is not None:
                            self._issue(updated, "diagnose", next_probe)
                            updated["feedback"] = {"kind": "recorded", "probe_id": probe_id, "statement": probe.statement}
                        else:
                            self._followup(updated, "practice", seen_revisions)
                    else:
                        pattern = (probes.diagnostic_state(domain, original["diagnosis"])["supported_rule"]
                                   if domain in probes.DOMAINS else None)
                        if probe.purpose != "transfer" and independent and pattern and pattern not in assessed["matching_rules"]:
                            updated["pattern_retracted"] = True
                        self._advance(updated, phase, independent and result == "correct", now, seen_revisions)
                    if updated["feedback"]["kind"] != "recorded" and probe_id not in updated["exposed_ids"]:
                        updated["exposed_ids"].append(probe_id)
            updated["receipts"] = [*updated["receipts"], {"request_id": request_id, "fingerprint": fingerprint}][-MAX_RECEIPTS:]
            updated["updated_at"] = _iso(now)
            await self._save(conn, sid, domain, stored, updated)
            return await self.read(sid, conn=conn)

    @classmethod
    def _advance(cls, payload, phase, independent_success, now, seen_revisions=()):
        if not independent_success:
            # A fresh problem and a new independent attempt are needed. Old
            # success timestamps remain historical evidence, not current mastery.
            cls._followup(payload, "practice", seen_revisions)
            return
        if phase == "practice":
            payload["evidence"]["independent_practice"] += 1
            if not payload.get("anchor_at"):
                payload["anchor_at"] = _iso(now)
            review_schedule.schedule_next(payload, now)
        elif phase == "review":
            if not payload.get("review_due_at") or now < _date(payload["review_due_at"]):
                raise ValueError("A delayed review cannot be certified before its due time")
            record = review_schedule.checkpoint(payload)
            if not record.get("reviewed_at"):
                payload["evidence"]["delayed_review"] += 1
            record.update(reviewed_at=_iso(now), review_probe_id=payload["current_probe"])
            cls._followup(payload, "transfer", seen_revisions)
        elif phase == "transfer":
            review_schedule.checkpoint(payload).update(completed_at=_iso(now), transfer_probe_id=payload["current_probe"])
            payload["evidence"]["structural_transfer"] += 1
            payload["review_round"] += 1
            if payload["review_round"] == len(review_schedule.DAYS):
                payload.update(phase="complete", current_probe=None, due_at=None)
            else:
                review_schedule.schedule_next(payload, now)

    async def export_summary(self, sid):
        public = await self.read(sid)
        return [{"domain": row["domain"], "phase": row["episode"]["phase"],
                 "due_at": row["episode"]["due_at"], "review_round": row["episode"]["review_round"],
                 "diagnostic_status": row["episode"]["diagnostic"]["status"],
                 "evidence": row["episode"]["evidence"]}
                for row in public["domains"] if row["episode"]]
