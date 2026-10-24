"""Adaptive practice — unified context assembly → candidate generation.

The generation flow (design §24) is fixed and gated:

    AdaptivePracticeService
        → ContextAssembler (intent=GENERATE_PRACTICE — policy REQUIRES
          Student Model / Curriculum / Misconception History / Recent
          Attempts; memory + documents OPTIONAL)
        → PracticeGenerationContext (typed DTO, every field sourced)
        → CandidateExerciseGenerator → CandidateExercise
        → Parser → Solver → Verifier → Release Attestation
        → ExerciseRelease → PracticeOffer

This round delivers the context assembly + the generator contract + a
deterministic fake generator. A CandidateExercise is UNVERIFIED by
construction — only the release gate (Phase 5) may turn verified
releases into PracticeOffers; personal KG and user documents never
bypass that gate. The LLM-backed generator (gateway role
PRACTICE_GENERATOR) is a later round — the role exists in the gateway;
nothing here blocks it.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.application.context_assembler import ContextAssembler
from mathtutor.application.retrieval_query import build_retrieval_query
from mathtutor.domain.assembled_context import (
    AssembledContext,
    ContextProvenance,
    DocumentContextSelection,
    MemoryContextEntry,
)
from mathtutor.domain.practice_context import (
    PRACTICE_CONTEXT_VERSION,
    ActiveMisconceptionEntry,
    AttemptSummaryEntry,
    ErrorPatternEntry,
    MasterySnapshotEntry,
    PersonalPreferenceContext,
    PracticeGenerationContext,
)
from mathtutor.domain.retrieval_policy import RetrievalIntent
from mathtutor.domain.practice_recommendation import MaterialDesignBasis, PracticeRecommendation, PracticePurpose


class CandidateExercise(BaseModel):
    """One generated practice candidate — UNVERIFIED by construction.

    Verification is a SEPARATE stage (Parser → Solver → Verifier →
    Release Attestation); a candidate carries no authority of its own.
    """

    model_config = ConfigDict(frozen=True)

    candidate_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    problem_statement: str
    skill_ids: tuple[str, ...] = ()
    concept_ids: tuple[str, ...] = ()
    difficulty: int = Field(ge=1, le=5)
    generated_by: str
    context_version: str = PRACTICE_CONTEXT_VERSION
    provenance: tuple[ContextProvenance, ...] = ()
    material_basis: tuple[MaterialDesignBasis, ...] = ()


class CandidateExerciseGenerator(Protocol):
    """Practice-candidate contract (fake today; LLM gateway role later)."""

    generated_by: str

    async def generate(
        self, context: PracticeGenerationContext, *, count: int = 1
    ) -> list[CandidateExercise]: ...


class FakeCandidateExerciseGenerator:
    """Deterministic candidate generator — no model, no network.

    Builds a statement from the ASSEMBLED context only: targets +
    weakest mastered skill + active misconception + difficulty. The
    output is deterministic for identical contexts (tests rely on it)
    and NEVER claims to be verified.
    """

    generated_by = "mt-fake-candidate-v1"

    async def generate(
        self, context: PracticeGenerationContext, *, count: int = 1
    ) -> list[CandidateExercise]:
        candidates: list[CandidateExercise] = []
        for index in range(count):
            candidates.append(
                CandidateExercise(
                    student_id=context.student_id,
                    problem_statement=_build_statement(context, index),
                    skill_ids=context.target_skill_ids,
                    concept_ids=context.target_concept_ids,
                    difficulty=context.desired_difficulty,
                    generated_by=self.generated_by,
                    context_version=context.context_version,
                    provenance=context.provenance,
                )
            )
        return candidates


def _build_statement(context: PracticeGenerationContext, index: int) -> str:
    targets = "、".join(
        list(context.target_skill_ids) + list(context.target_concept_ids)
    ) or "未指定知识点"
    # Verified attempt outcomes, not the uncalibrated legacy mastery estimate.
    misses: dict[str, int] = {}
    for entry in context.recent_attempt_summary:
        if entry.correctness in {"incorrect", "partial"}:
            misses[entry.skill_id] = misses.get(entry.skill_id, 0) + 1
    hardest = max(misses.items(), key=lambda item: item[1], default=None)
    mastery_line = (
        f"最近作答中出错最多的技能是 {hardest[0]}（{hardest[1]} 次）"
        if hardest is not None
        else "最近没有出错的作答记录"
    )
    misconception_line = (
        f"需重点纠正的易错规则：{'、'.join(entry.rule_id for entry in context.active_misconceptions)}"
        if context.active_misconceptions
        else "暂无激活的易错规则"
    )
    return (
        f"[练习候选 {index + 1}] 针对知识点：{targets}。难度等级 "
        f"{context.desired_difficulty}/5。{mastery_line}。{misconception_line}。"
        f"请完成一道相关的练习题。"
    )


class AdaptivePracticeService:
    """Unified context assembly for practice generation (design §24).

    The service OWNS the assembly: generators receive the typed
    PracticeGenerationContext and never query repositories directly.
    """

    def __init__(
        self,
        *,
        assembler: ContextAssembler,
        generator: CandidateExerciseGenerator | None = None,
        desired_difficulty: int = 2,
        release_service: "Any | None" = None,
    ) -> None:
        self._assembler = assembler
        self._generator = generator if generator is not None else FakeCandidateExerciseGenerator()
        self._desired_difficulty = desired_difficulty
        # Phase 5 (§7.5): the release gate this service drives. Imported
        # lazily at call time to avoid a module cycle with practice_release
        # (which imports CandidateExercise from THIS module).
        self._release_service = release_service
        self.initial_assessment = None
        self.student_state = None

    async def generate_candidates(
        self,
        student_id: str,
        *,
        target_skill_ids: Sequence[str] = (),
        target_concept_ids: Sequence[str] = (),
        count: int = 1,
        query_hint: str = "",
        problem_text: str = "",
        misconception_ids: Sequence[str] = (),
        purpose: PracticePurpose = "D",
        requested_difficulty: int | None = None,
        current_difficulty: int | None = None,
        excluded_problem_statements: Sequence[str] = (),
        excluded_problem_revisions: frozenset[str] = frozenset(),
        foundation_focus: str = "",
    ) -> list[CandidateExercise]:
        """Assemble the REQUIRED+OPTIONAL context and hand it to the generator."""
        assembled = await self.assemble_for_intent(
            student_id,
            intent=RetrievalIntent.GENERATE_PRACTICE,
            skill_ids=target_skill_ids,
            concept_ids=target_concept_ids,
            query_hint=query_hint,
            problem_text=problem_text,
            misconception_ids=misconception_ids,
        )
        context = practice_context_from_assembled(
            assembled,
            target_skill_ids=tuple(target_skill_ids),
            target_concept_ids=tuple(target_concept_ids),
            desired_difficulty=self._desired_difficulty,
        )
        from mathtutor.application.practice_policy import MAX_CANDIDATES, select_difficulty
        if self.student_state:
            # Choice observations inform the RULE, not the free-response DKT loss.
            from mathtutor.learning.knowledge_tracing.events import valid_events
            from mathtutor.learning.skills import skill_for_problem_type
            first = []
            for event in valid_events(await self.student_state.events(student_id)):
                if (event.event_type == "attempt_assessed" and event.evidence_kind == "independent"
                        and event.correctness in {"correct", "incorrect"} and event.completion_scope == "full_problem"
                        and event.task_purpose not in {"diagnostic", "error_analysis"}
                        and not (event.provenance_uncertain or event.duplicate_response or event.prior_task_attempt
                                 or event.target_answer_exposed_before_attempt)):
                    try:
                        family = skill_for_problem_type(event.item_family_id)
                    except ValueError:
                        continue
                    first.append(AttemptSummaryEntry(skill_id=family, correctness=event.correctness,
                        effective_assistance_level=0, attempt_index=1, created_at=event.occurred_at,
                        problem_id=event.problem_revision))
            context = context.model_copy(update={"recent_attempt_summary": tuple(first)})
        initial = await self.initial_assessment.starting_difficulty(student_id, target_skill_ids) if self.initial_assessment else None
        difficulty, _ = select_difficulty(context, purpose=purpose,
            baseline=current_difficulty or initial or self._desired_difficulty, requested=requested_difficulty)
        source_model = getattr(self.student_state, "source_model", None) if self.student_state else None
        if requested_difficulty is None and source_model is not None:
            from mathtutor.learning.knowledge_tracing.mapped_dkt import forecast_for
            trained = forecast_for(source_model, await self.student_state.events(student_id), target_skill_ids)
            from mathtutor.application.practice_policy import apply_dkt_difficulty
            difficulty, _ = apply_dkt_difficulty(difficulty, trained)
        context = context.model_copy(update={
            "desired_difficulty": difficulty, "practice_purpose": purpose,
            "excluded_problem_statements": tuple(excluded_problem_statements),
            "excluded_problem_revisions": excluded_problem_revisions,
            "foundation_focus": foundation_focus,
        })
        return (await self._generator.generate(context, count=min(MAX_CANDIDATES, max(1, count))))[:MAX_CANDIDATES]

    async def _seen_problem_revisions(self, student_id: str) -> frozenset[str]:
        """Full retained history for local eligibility, never model context text."""
        from mathtutor.repositories.practice_repository import SEEN_PROBLEM_EVENT_TYPES
        revisions = await self._release_service.repository.seen_problem_revisions(student_id)
        if self.student_state is not None:
            # The event store can be separate in development. Do not use
            # valid_events: excluding a verdict never makes its task unseen.
            events = await self.student_state.events(student_id)
            revisions |= frozenset(event.problem_revision for event in events
                if event.student_id == str(student_id) and event.event_type in SEEN_PROBLEM_EVENT_TYPES
                and event.problem_revision)
        return revisions

    async def assemble_for_intent(
        self,
        student_id: str,
        *,
        intent: RetrievalIntent,
        skill_ids: Sequence[str] = (),
        concept_ids: Sequence[str] = (),
        query_hint: str = "",
        problem_text: str = "",
        misconception_ids: Sequence[str] = (),
    ) -> AssembledContext:
        """Build the Chinese retrieval query and run the assembler.

        Skill codes stay on ``node_ids`` (curriculum filter). The lexical
        query is titles + aliases + the student's problem / misconceptions.
        """
        node_ids = list(skill_ids) + list(concept_ids)
        hint = query_hint.strip() or build_retrieval_query(
            skill_ids=skill_ids,
            concept_ids=concept_ids,
            problem_text=problem_text,
            misconception_ids=misconception_ids,
        )
        return await self._assembler.assemble(
            student_id=student_id,
            intent=intent,
            query_hint=hint,
            node_ids=node_ids or None,
        )

    async def prepare_offer(
        self,
        student_id: str,
        *,
        parent_cycle_id: UUID,
        target_skill_ids: Sequence[str] = (),
        target_concept_ids: Sequence[str] = (),
        count: int = 3,
        ttl: "Any | None" = None,
        problem_text: str = "",
        misconception_ids: Sequence[str] = (),
        query_hint: str = "",
        purpose: PracticePurpose = "D",
        target_revision: str = "",
        exposure_level: int = 0,
        full_task_completed: bool = False,
        prerequisite_skill_ids: Sequence[str] = (),
        foundation_focus: str = "",
        requested_difficulty: int | None = None,
        current_difficulty: int | None = None,
        review_due: bool = False,
        history_cutoff_seq: int | None = None,
        evidence_ids: Sequence[str] = (),
    ) -> Any:
        """Prepare ONE ACTIVE practice offer (§7.5).

        Flow: assembler → context → generate (deterministic fallback chain
        bank > template > LLM) → release gate (Parser → Solver → Verifier →
        Release Attestation → ExerciseRelease) → PracticeOffer ACTIVE with
        TTL. Only a candidate that passes the FULL release gate may become
        an offer; when none passes, ``PracticeOfferError`` (fail closed).
        """
        # Lazy imports: practice_release imports CandidateExercise from this
        # module — defer to call time to keep the module graph acyclic.
        from datetime import datetime, timezone

        from mathtutor.application.llm_candidate_generator import (
            source_type_for_generated_by,
        )
        from mathtutor.application.practice_release import (
            OFFER_TTL,
            PracticeOfferError,
            ReleaseDeniedError,
        )
        from mathtutor.domain.tutoring import PracticeOffer
        from mathtutor.security.scopes import student_uuid
        from mathtutor.application.practice_policy import MAX_CANDIDATES, resolve_practice_purpose, validate_targets
        from mathtutor.domain.hashing import content_hash

        if self._release_service is None:
            raise PracticeOfferError("release_service 未配置")
        try:
            purpose = resolve_practice_purpose(purpose,
                full_task_completed=full_task_completed, exposure_level=exposure_level,
                prerequisite_skill_ids=prerequisite_skill_ids, review_due=review_due)
            targets = validate_targets(prerequisite_skill_ids if purpose == "C" else target_skill_ids)
        except ValueError as exc:
            raise PracticeOfferError(str(exc)) from exc
        repository = self._release_service.repository
        from mathtutor.domain.practice_recommendation import RecommendationBasis
        placement = await self.initial_assessment.read(student_id) if self.initial_assessment else None
        resolved_revision = target_revision or content_hash({"problem": problem_text, "skills": targets})
        basis = RecommendationBasis(
            history_cutoff_seq=history_cutoff_seq, evidence_ids=tuple(dict.fromkeys(evidence_ids)),
            target_revision=resolved_revision, target_skill_ids=targets, purpose=purpose,
            reason_code="verified_error_history" if foundation_focus and evidence_ids else "parent_attempt" if evidence_ids else "related_task",
            initial_assessment_run_id=placement["run_id"] if placement and placement["status"] == "completed" else None,
            initial_assessment_policy=placement["policy_version"] if placement and placement["status"] == "completed" else None,
        ) if history_cutoff_seq is not None else None
        recommendation = PracticeRecommendation(
            student_id=student_uuid(student_id), parent_cycle_id=parent_cycle_id,
            purpose=purpose, target_revision=resolved_revision, basis=basis,
            target_skill_ids=targets, resume_parent_cycle_id=parent_cycle_id if purpose == "C" else None,
        )
        recommendation, claimed = await repository.begin_recommendation(recommendation)
        if not claimed:
            if recommendation.status == "ACTIVE" and recommendation.offer_id:
                existing = await repository.load_offer(recommendation.offer_id)
                if existing and existing.status == "ACTIVE":
                    return existing
            raise PracticeOfferError("该目的的练习正在准备，请勿重复请求")
        attempted = 0
        try:
            recent = await repository.offers_for_student_with_detail(student_id)
            requires_unseen = purpose in {"A1", "A2", "B"}
            used_revisions = await self._seen_problem_revisions(student_id) if requires_unseen else frozenset()
            # Review may deliberately reuse a task. Other purposes retain the
            # bounded near-duplicate/answer-copy guard as a separate constraint.
            excluded = [] if purpose == "E" else [problem_text] if problem_text else []
            if purpose != "E":
                excluded.extend(exercise.problem_statement for _, exercise in recent[:20] if exercise)
            candidates = await asyncio.wait_for(self.generate_candidates(
                student_id, target_skill_ids=targets,
                target_concept_ids=() if purpose == "C" else target_concept_ids,
                count=min(MAX_CANDIDATES, max(1, count)), query_hint=query_hint,
                problem_text=problem_text, misconception_ids=misconception_ids,
                purpose=purpose, requested_difficulty=requested_difficulty,
                current_difficulty=current_difficulty, excluded_problem_statements=excluded,
                excluded_problem_revisions=used_revisions,
                foundation_focus=foundation_focus,
            ), timeout=30)
            chain = None
            seen = set()
            from mathtutor.application.llm_candidate_generator import candidate_is_distinct, candidate_problem_revision
            for candidate in candidates[:MAX_CANDIDATES]:
                attempted += 1
                if (not set(targets).issubset(candidate.skill_ids) or candidate.student_id != student_uuid(student_id)
                        or candidate_problem_revision(candidate.problem_statement) in used_revisions
                        or not candidate_is_distinct(candidate.problem_statement, (*excluded, *seen))):
                    continue
                seen.add(candidate.problem_statement)
                try:
                    chain = await self._release_service.release_candidate(
                        candidate, source_type=source_type_for_generated_by(candidate.generated_by))
                    # Generation and verification may overlap another tab's
                    # submission/exposure. Check current facts, not the snapshot.
                    if requires_unseen:
                        used_revisions = await self._seen_problem_revisions(student_id)
                        if chain.problem.content_hash in used_revisions:
                            chain = None
                            continue
                    from mathtutor.application.multiple_choice import make_choices
                    make_choices(chain.problem, chain.candidate, salt=str(chain.release.release_id))
                    break
                except (ReleaseDeniedError, ValueError):
                    chain = None
                    continue
            if chain is None:
                raise PracticeOfferError("候选预算内暂无未见过且通过验证的新题；可重新请求或明确选择其他难度，原题结果保持不变"
                    if requires_unseen else "候选预算内没有通过技能匹配、去重与验证的练习；原题结果保持不变，可重试")
            offer = PracticeOffer(
                student_id=student_uuid(student_id), parent_cycle_id=parent_cycle_id,
                exercise_release_id=chain.release.release_id,
                target_mapping_ids=chain.exercise.target_mapping_ids,
                stage_policy_version="mt-stage-v2", status="ACTIVE",
                expires_at=datetime.now(timezone.utc) + (ttl or OFFER_TTL),
            )
            recommendation = recommendation.model_copy(update={
                "status": "ACTIVE", "offer_id": offer.offer_id, "candidate_count": attempted,
                "desired_difficulty": chain.exercise.difficulty,
                "material_basis": tuple(basis.model_dump(mode="json") for basis in candidate.material_basis),
                "decision_reason": ("到期复习允许重做旧题；目标技能与确定性发布门已检查" if purpose == "E" else
                    "离散难度、目标技能、完整历史新题检查与确定性发布门均已检查" if requires_unseen else
                    "离散难度、目标技能、近期去重与确定性发布门均已检查"),
                "updated_at": datetime.now(timezone.utc),
            })
            await repository.complete_recommendation(recommendation, offer, outbox_events=[
                {
                    "aggregate_type": "practice_offer",
                    "aggregate_id": str(offer.offer_id),
                    "aggregate_version": 1,
                    "event_sequence": 1,
                    "event_type": "practice_offer_issued",
                    "audience": "student",
                    "payload": {
                        "offer_id": str(offer.offer_id),
                        "parent_cycle_id": str(parent_cycle_id),
                        "expires_at": offer.expires_at.isoformat(),
                        "purpose": purpose,
                        "recommendation_id": str(recommendation.recommendation_id),
                    },
                }
            ], unseen_for_student=student_id if requires_unseen else None)
            return offer
        except asyncio.CancelledError:
            await asyncio.shield(repository.fail_recommendation(recommendation.model_copy(update={
                "status": "FAILED", "candidate_count": attempted,
                "failure_reason": "练习准备已取消，可重新请求",
                "updated_at": datetime.now(timezone.utc),
            })))
            raise
        except Exception as exc:
            failure = recommendation.model_copy(update={"status": "FAILED", "candidate_count": attempted,
                "failure_reason": "练习生成或验证未完成，原题结果保持不变，可重新请求练习",
                "updated_at": datetime.now(timezone.utc)})
            await repository.fail_recommendation(failure)
            if isinstance(exc, PracticeOfferError):
                raise
            raise PracticeOfferError(failure.failure_reason) from exc


def practice_context_from_assembled(
    assembled: AssembledContext,
    *,
    target_skill_ids: tuple[str, ...] = (),
    target_concept_ids: tuple[str, ...] = (),
    desired_difficulty: int = 2,
) -> PracticeGenerationContext:
    """Map the typed assembled context into the practice DTO (no raw rows).

    Field sources (documented per field in the DTO):
    - current_mastery            ← StudentModelContext.skill_mastery (REQUIRED)
    - active_misconceptions      ← StudentModelContext.active_misconception_rule_ids
                                   + observation history (confidence heuristic)
    - recent_error_patterns      ← MisconceptionContext (REQUIRED)
    - recent_attempt_summary     ← RecentAttemptsContext (REQUIRED)
    - personal_preferences       ← PersonalMemoryContext (OPTIONAL)
    - document_context           ← first DocumentContextSelection (OPTIONAL)
    """
    student_model = assembled.student_model
    mastery: list[MasterySnapshotEntry] = []
    if student_model is not None:
        wanted_skills = set(target_skill_ids) or None
        for entry in student_model.skill_mastery:
            if wanted_skills is None or entry.skill_id in wanted_skills:
                mastery.append(
                    MasterySnapshotEntry(skill_id=entry.skill_id, mastery=entry.mastery)
                )

    # Confidence for ACTIVE rules: derived from the observation history
    # (documented heuristic — one more observation ⇒ +0.1, capped 0.95;
    # no observations ⇒ reducer BASE_CONFIDENCE 0.75). The Student Model
    # remains the authoritative state; this only annotates the DTO.
    counts: dict[str, int] = {}
    if assembled.misconception_history is not None:
        for entry in assembled.misconception_history.entries:
            counts[entry.rule_id] = entry.observation_count
    active: list[ActiveMisconceptionEntry] = []
    if student_model is not None:
        for rule_id in student_model.active_misconception_rule_ids:
            count = counts.get(rule_id, 0)
            confidence = min(0.95, 0.55 + 0.1 * count) if count else 0.75
            active.append(ActiveMisconceptionEntry(rule_id=rule_id, confidence=confidence))

    error_patterns: list[ErrorPatternEntry] = []
    if assembled.misconception_history is not None:
        error_patterns = [
            ErrorPatternEntry(rule_id=entry.rule_id, occurrence_count=entry.observation_count)
            for entry in assembled.misconception_history.entries
        ]

    attempt_summary: list[AttemptSummaryEntry] = []
    if assembled.recent_attempts is not None:
        attempt_summary = [
            AttemptSummaryEntry(
                skill_id=entry.skill_id,
                correctness=entry.correctness,
                effective_assistance_level=entry.effective_assistance_level,
                attempt_index=entry.attempt_index,
                created_at=entry.created_at,
                problem_id=entry.problem_id,
            )
            for entry in assembled.recent_attempts.entries
        ]

    preferences: PersonalPreferenceContext | None = None
    if assembled.personal_memory is not None and assembled.personal_memory.entries:
        preferences = PersonalPreferenceContext(
            entries=tuple(
                MemoryContextEntry(
                    memory_id=entry.memory_id,
                    memory_type=entry.memory_type,
                    subject=entry.subject,
                    predicate=entry.predicate,
                    object_json=entry.object_json,
                    source_type=entry.source_type,
                    confidence=entry.confidence,
                )
                for entry in assembled.personal_memory.entries
            )
        )

    document_context = _merged_document_context(assembled.user_documents)

    return PracticeGenerationContext(
        student_id=assembled.student_id,
        target_skill_ids=target_skill_ids,
        target_concept_ids=target_concept_ids,
        current_mastery=tuple(mastery),
        active_misconceptions=tuple(active),
        recent_error_patterns=tuple(error_patterns),
        recent_attempt_summary=tuple(attempt_summary),
        desired_difficulty=desired_difficulty,
        personal_preferences=preferences,
        document_context=document_context,
        provenance=assembled.provenance,
    )


def _merged_document_context(
    selections: tuple[DocumentContextSelection, ...],
) -> DocumentContextSelection | None:
    """Flatten assembler selections; keep filename/page/sequence/score on chunks."""
    if not selections:
        return None
    chunks = []
    for selection in selections:
        for chunk in selection.chunks:
            filename = chunk.filename or selection.filename
            chunks.append(
                chunk if chunk.filename == filename else chunk.model_copy(update={"filename": filename})
            )
    first = selections[0]
    return DocumentContextSelection(
        document_id=first.document_id,
        filename=first.filename,
        chunks=tuple(chunks),
    )


__all__ = [
    "AdaptivePracticeService",
    "CandidateExercise",
    "CandidateExerciseGenerator",
    "FakeCandidateExerciseGenerator",
    "practice_context_from_assembled",
]
