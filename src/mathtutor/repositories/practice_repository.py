"""Practice catalog repository: exercises, releases, offers (Phase 5).

Contract and binding validation for SQLite practice storage. An
:class:`ExerciseRelease` is only created inside the same short transaction
as the VERIFIED attestation it binds (Parser → Solver → Verifier →
Release Attestation → Release → Offer). The SQLite implementation
(``repositories/sqlite_practice.py``) shares this contract and adds
durability + CAS on offer acceptance.

Owner isolation mirrors the session store: every offer query carries
``student_id`` and the client never supplies it.

The SQLite implementation keeps the exact verified bytes
(problem / candidate / ref) per release so child-cycle judging can resolve
the release's OWN snapshot — never "the newest attestation of the problem".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from mathtutor.domain.hashing import content_hash
from mathtutor.domain.practice import Exercise, ExerciseRelease
from mathtutor.domain.practice_recommendation import PracticeRecommendation
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    SolutionAttestation,
    VerificationDecision,
    VerifiedSolutionRef,
)
from mathtutor.domain.tutoring import PracticeOffer
from mathtutor.repositories.solution_repository import AttestationDeniedError

# Excluding an assessment label does not erase its prior submission/exposure.
SEEN_PROBLEM_EVENT_TYPES = frozenset(
    {
        "problem_started",
        "attempt_submitted",
        "attempt_assessed",
        "help_presented",
        "help_possibly_exposed",
    }
)


def validate_release_binding(
    problem: MathProblem,
    candidate: MathSolutionCandidate,
    decision: VerificationDecision,
) -> None:
    """Re-validate every hash binding BEFORE a release may exist (fail closed).

    Identical rules to the attestation repositories: the release gate never
    trusts the caller's claims — problem hash, candidate binding and the
    VERIFIED verdict must all re-check against the persisted bytes.
    """
    if decision.verdict != "VERIFIED":
        raise AttestationDeniedError(f"拒绝 release：verdict={decision.verdict}")
    if any(check.status == "failed" for check in decision.checks):
        raise AttestationDeniedError("拒绝 release：存在失败检查")
    if decision.candidate_id != candidate.candidate_id:
        raise AttestationDeniedError("decision 与 candidate 不一致")
    if decision.candidate_payload_hash != candidate.payload_hash:
        raise AttestationDeniedError("decision 绑定的 candidate 哈希不一致")
    if candidate.problem_id != problem.problem_id:
        raise AttestationDeniedError("candidate 绑定的 problem_id 不一致")
    if decision.problem_content_hash != problem.content_hash:
        raise AttestationDeniedError("decision 绑定的 problem 哈希不一致")


def build_verified_ref(
    problem: MathProblem,
    candidate: MathSolutionCandidate,
    decision: VerificationDecision,
) -> VerifiedSolutionRef:
    """Deterministic VerifiedSolutionRef for an in-memory attestation."""
    attestation = SolutionAttestation(
        decision_id=decision.decision_id,
        problem_id=problem.problem_id,
        problem_content_hash=problem.content_hash,
        candidate_id=candidate.candidate_id,
        candidate_payload_hash=candidate.payload_hash,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        attestation_hash=content_hash(
            {
                "decision_id": decision.decision_id,
                "problem_id": problem.problem_id,
                "problem_content_hash": problem.content_hash,
                "candidate_id": candidate.candidate_id,
                "candidate_payload_hash": candidate.payload_hash,
                "policy_id": decision.policy_id,
                "policy_version": decision.policy_version,
            }
        ),
    )
    return VerifiedSolutionRef(
        verification_log_id=decision.decision_id,
        problem_id=problem.problem_id,
        problem_content_hash=problem.content_hash,
        solution_candidate_id=candidate.candidate_id,
        solution_payload_hash=candidate.payload_hash,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        attestation_hash=attestation.attestation_hash,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def practice_problem_surface(problem: MathProblem, exercise: Exercise) -> MathProblem:
    """Project the release-bound task statement, without changing math facts.

    Different arithmetic tasks may share a folded canonical value. Their
    student-facing instructions live on the immutable exercise, not that
    global fact. Reparse and check its canonical binding before projection.
    """
    from mathtutor.solving.parser import parse_problem

    parsed = parse_problem(exercise.problem_statement)
    if parsed.kind != "parsed" or parsed.problem is None:
        raise AttestationDeniedError("练习原始题干无法恢复")
    snapshot = MathProblem.canonicalize(
        problem_type=parsed.problem.problem_type,
        normalized_ast=parsed.problem.normalized_ast,
        display_latex=parsed.problem.display_latex,
    )
    if snapshot.content_hash != problem.content_hash:
        raise AttestationDeniedError("练习题干与验证快照不一致")
    return problem.model_copy(update={"display_latex": parsed.problem.display_latex})


class PracticeRepository(Protocol):
    """Async practice-catalog contract (Phase 5, §11.3)."""

    async def resolve_problem(self, problem: MathProblem) -> MathProblem: ...

    async def save_release_bundle(
        self,
        *,
        problem: MathProblem,
        candidate: MathSolutionCandidate,
        decision: VerificationDecision,
        exercise: Exercise,
        release: ExerciseRelease,
        outbox_events: list[dict[str, Any]],
    ) -> tuple[VerifiedSolutionRef, ExerciseRelease]: ...

    async def create_offer(
        self, offer: PracticeOffer, outbox_events: list[dict[str, Any]] = ()
    ) -> None: ...

    async def begin_recommendation(
        self, recommendation: PracticeRecommendation
    ) -> tuple[PracticeRecommendation, bool]: ...

    async def complete_recommendation(
        self,
        recommendation: PracticeRecommendation,
        offer: PracticeOffer,
        outbox_events: list[dict[str, Any]],
        *,
        unseen_for_student: str | None = None,
    ) -> None: ...

    async def fail_recommendation(
        self, recommendation: PracticeRecommendation
    ) -> None: ...

    async def recommendations_for_student(
        self, student_id: str, parent_cycle_id: UUID | None = None
    ) -> list[PracticeRecommendation]: ...

    async def recommendation_for_offer(
        self, student_id: str, offer_id: UUID
    ) -> PracticeRecommendation | None: ...

    async def recover_preparing_recommendations(self) -> int: ...

    async def load_release(self, release_id: UUID) -> ExerciseRelease | None: ...

    async def load_exercise(self, exercise_id: UUID) -> Exercise | None: ...

    async def find_exercise_by_content_hash(
        self, content_hash: str
    ) -> Exercise | None: ...

    async def latest_release_for_exercise(
        self, exercise_id: UUID
    ) -> ExerciseRelease | None: ...

    async def load_offer(self, offer_id: UUID) -> PracticeOffer | None: ...

    async def offers_for_student(self, student_id: str) -> list[PracticeOffer]: ...

    async def seen_problem_revisions(self, student_id: str) -> frozenset[str]: ...

    async def offers_for_student_with_detail(
        self, student_id: str
    ) -> list[tuple[PracticeOffer, Exercise | None]]: ...

    async def mark_offer_declined(self, student_id: str, offer_id: UUID) -> bool: ...

    async def accept_offer(self, student_id: str, offer_id: UUID) -> bool: ...

    async def load_exact_verified(
        self, release: ExerciseRelease
    ) -> tuple[MathProblem, MathSolutionCandidate, VerifiedSolutionRef] | None: ...

    async def list_outbox(self) -> list[dict[str, Any]]: ...


__all__ = [
    "PracticeRepository",
    "build_verified_ref",
    "validate_release_binding",
]
