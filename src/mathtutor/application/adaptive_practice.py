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

from typing import Any, Protocol, Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.application.context_assembler import ContextAssembler
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
    weakest = min(context.current_mastery, key=lambda entry: entry.mastery, default=None)
    mastery_line = (
        f"当前掌握度最低的技能是 {weakest.skill_id}（{weakest.mastery:.2f}）"
        if weakest is not None
        else "暂无掌握度数据"
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

    async def generate_candidates(
        self,
        student_id: str,
        *,
        target_skill_ids: Sequence[str] = (),
        target_concept_ids: Sequence[str] = (),
        count: int = 1,
        query_hint: str = "",
    ) -> list[CandidateExercise]:
        """Assemble the REQUIRED+OPTIONAL context and hand it to the generator."""
        node_ids = list(target_skill_ids) + list(target_concept_ids)
        hint = query_hint or " ".join(node_ids)
        assembled = await self._assembler.assemble(
            student_id=student_id,
            intent=RetrievalIntent.GENERATE_PRACTICE,
            query_hint=hint,
            node_ids=node_ids or None,
        )
        context = practice_context_from_assembled(
            assembled,
            target_skill_ids=tuple(target_skill_ids),
            target_concept_ids=tuple(target_concept_ids),
            desired_difficulty=self._desired_difficulty,
        )
        return await self._generator.generate(context, count=count)

    async def prepare_offer(
        self,
        student_id: str,
        *,
        parent_cycle_id: UUID,
        target_skill_ids: Sequence[str] = (),
        target_concept_ids: Sequence[str] = (),
        count: int = 1,
        ttl: "Any | None" = None,
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

        if self._release_service is None:
            raise PracticeOfferError("release_service 未配置")
        candidates = await self.generate_candidates(
            student_id,
            target_skill_ids=target_skill_ids,
            target_concept_ids=target_concept_ids,
            count=count,
        )
        if not candidates:
            raise PracticeOfferError("无法生成候选练习题")

        last_error: Exception | None = None
        chain = None
        for candidate in candidates:
            try:
                chain = await self._release_service.release_candidate(
                    candidate,
                    source_type=source_type_for_generated_by(candidate.generated_by),
                )
                break
            except ReleaseDeniedError as exc:  # try the next candidate
                last_error = exc
        if chain is None:
            raise PracticeOfferError(
                f"没有候选通过发布门（fail closed：{last_error}）"
            )

        ttl = ttl or OFFER_TTL
        offer = PracticeOffer(
            student_id=student_uuid(student_id),
            parent_cycle_id=parent_cycle_id,
            exercise_release_id=chain.release.release_id,
            target_mapping_ids=chain.exercise.target_mapping_ids,
            stage_policy_version="mt-stage-v0",
            status="ACTIVE",
            expires_at=datetime.now(timezone.utc) + ttl,
        )
        await self._release_service.create_offer(
            offer,
            outbox_events=[
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
                    },
                }
            ],
        )
        return offer


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

    document_context: DocumentContextSelection | None = (
        assembled.user_documents[0] if assembled.user_documents else None
    )

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


__all__ = [
    "AdaptivePracticeService",
    "CandidateExercise",
    "CandidateExerciseGenerator",
    "FakeCandidateExerciseGenerator",
    "practice_context_from_assembled",
]
