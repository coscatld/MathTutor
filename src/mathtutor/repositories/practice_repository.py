"""Practice catalog repository: exercises, releases, offers (Phase 5).

Contract + in-memory implementation. The release gate lives HERE: an
:class:`ExerciseRelease` is only created inside the same short transaction
as the VERIFIED attestation it binds (Parser → Solver → Verifier →
Release Attestation → Release → Offer). The SQLite implementation
(``repositories/sqlite_practice.py``) shares this contract and adds
durability + CAS on offer acceptance.

Owner isolation mirrors the session store: every offer query carries
``student_id`` and the client never supplies it.

The in-memory implementation also keeps the exact verified bytes
(problem / candidate / ref) per release so child-cycle judging can resolve
the release's OWN snapshot — never "the newest attestation of the problem".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4

from mathtutor.domain.hashing import content_hash
from mathtutor.domain.practice import Exercise, ExerciseRelease
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    SolutionAttestation,
    VerificationDecision,
    VerifiedSolutionRef,
)
from mathtutor.domain.tutoring import PracticeOffer
from mathtutor.repositories.solution_repository import AttestationDeniedError
from mathtutor.security.scopes import student_uuid


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


class PracticeRepository(Protocol):
    """Async practice-catalog contract (Phase 5, §11.3)."""

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

    async def load_release(self, release_id: UUID) -> ExerciseRelease | None: ...

    async def load_exercise(self, exercise_id: UUID) -> Exercise | None: ...

    async def find_exercise_by_content_hash(self, content_hash: str) -> Exercise | None: ...

    async def latest_release_for_exercise(
        self, exercise_id: UUID
    ) -> ExerciseRelease | None: ...

    async def load_offer(self, offer_id: UUID) -> PracticeOffer | None: ...

    async def offers_for_student(self, student_id: str) -> list[PracticeOffer]: ...

    async def offers_for_student_with_detail(
        self, student_id: str
    ) -> list[tuple[PracticeOffer, Exercise | None]]: ...

    async def mark_offer_declined(self, student_id: str, offer_id: UUID) -> bool: ...

    async def accept_offer(self, student_id: str, offer_id: UUID) -> bool: ...

    async def load_exact_verified(
        self, release: ExerciseRelease
    ) -> tuple[MathProblem, MathSolutionCandidate, VerifiedSolutionRef] | None: ...

    async def list_outbox(self) -> list[dict[str, Any]]: ...


class InMemoryPracticeRepository:
    """Process-local practice catalog (dev/tests).

    Mirrors the SQLite layout: exercises unique by content hash, releases
    with status lifecycle, owner-scoped offers, and the exact verified
    bytes per release for exact-snapshot judging.
    """

    def __init__(self) -> None:
        self._problems: dict[str, MathProblem] = {}
        self._candidates: dict[str, MathSolutionCandidate] = {}
        self._refs: dict[str, VerifiedSolutionRef] = {}
        self._exercises: dict[str, Exercise] = {}
        self._releases: dict[str, ExerciseRelease] = {}
        self._releases_by_exercise: dict[str, list[str]] = {}
        self._offers: dict[str, PracticeOffer] = {}
        self.outbox: list[dict[str, Any]] = []

    # ----------------------------------------------------------- release gate

    async def save_release_bundle(
        self,
        *,
        problem: MathProblem,
        candidate: MathSolutionCandidate,
        decision: VerificationDecision,
        exercise: Exercise,
        release: ExerciseRelease,
        outbox_events: list[dict[str, Any]] = (),
    ) -> tuple[VerifiedSolutionRef, ExerciseRelease]:
        """Issue the attestation + exercise + release atomically (in-memory).

        Fail closed on ANY binding mismatch; the outbox rows are appended to
        the same logical commit (mirror of the SQLite single transaction).
        """
        validate_release_binding(problem, candidate, decision)
        ref = build_verified_ref(problem, candidate, decision)

        self._problems[str(problem.problem_id)] = problem
        self._candidates[str(candidate.candidate_id)] = candidate
        self._refs[str(ref.verification_log_id)] = ref
        self._exercises[str(exercise.exercise_id)] = exercise
        final = release.model_copy(
            update={
                "solution_candidate_id": candidate.candidate_id,
                "verification_log_id": ref.verification_log_id,
                "status": "released",
                "released_at": release.released_at or datetime.now(timezone.utc),
            }
        )
        self._releases[str(final.release_id)] = final
        self._releases_by_exercise.setdefault(str(exercise.exercise_id), []).append(
            str(final.release_id)
        )
        # Supersede an older released version of the SAME exercise (bytes
        # differ — save_release_bundle is only called for changed bytes);
        # their ACTIVE offers are REVOKED in the same logical commit (§7.9).
        superseded_ids: list[str] = []
        for old in self._released_for_exercise(exercise.exercise_id):
            if old.release_id != final.release_id:
                self._releases[str(old.release_id)] = old.model_copy(
                    update={"status": "superseded"}
                )
                superseded_ids.append(str(old.release_id))
        if superseded_ids:
            for offer_id, offer in list(self._offers.items()):
                if (
                    str(offer.exercise_release_id) in superseded_ids
                    and offer.status == "ACTIVE"
                ):
                    self._offers[offer_id] = offer.model_copy(
                        update={"status": "REVOKED"}
                    )
        self.outbox.extend(dict(e) for e in outbox_events)
        return ref, final

    def _released_for_exercise(self, exercise_id: UUID) -> list[ExerciseRelease]:
        out: list[ExerciseRelease] = []
        for rid in self._releases_by_exercise.get(str(exercise_id), []):
            release = self._releases.get(rid)
            if release is not None and release.status == "released":
                out.append(release)
        return out

    # ----------------------------------------------------------------- offers

    async def create_offer(
        self, offer: PracticeOffer, outbox_events: list[dict[str, Any]] = ()
    ) -> None:
        self._offers[str(offer.offer_id)] = offer
        self.outbox.extend(dict(e) for e in outbox_events)

    async def load_offer(self, offer_id: UUID) -> PracticeOffer | None:
        return self._offers.get(str(offer_id))

    async def offers_for_student(self, student_id: str) -> list[PracticeOffer]:
        owner = str(student_uuid(student_id))
        return [
            offer
            for offer in self._offers.values()
            if str(offer.student_id) == owner
        ]

    async def offers_for_student_with_detail(
        self, student_id: str
    ) -> list[tuple[PracticeOffer, Exercise | None]]:
        owner = str(student_uuid(student_id))
        out: list[tuple[PracticeOffer, Exercise | None]] = []
        for offer in self._offers.values():
            if str(offer.student_id) != owner:
                continue
            release = self._releases.get(str(offer.exercise_release_id))
            exercise = (
                self._exercises.get(str(release.exercise_id))
                if release is not None
                else None
            )
            out.append((offer, exercise))
        out.sort(key=lambda pair: pair[0].offered_at, reverse=True)
        return out

    async def mark_offer_declined(self, student_id: str, offer_id: UUID) -> bool:
        offer = self._offers.get(str(offer_id))
        if offer is None or str(offer.student_id) != str(student_uuid(student_id)):
            return False
        if offer.status == "ACTIVE":
            self._offers[str(offer_id)] = offer.model_copy(update={"status": "REVOKED"})
            return True
        return False

    async def accept_offer(self, student_id: str, offer_id: UUID) -> bool:
        """Offer accept CAS parity (ACTIVE + owner + not expired)."""
        from datetime import datetime, timezone

        offer = self._offers.get(str(offer_id))
        if offer is None or str(offer.student_id) != str(student_uuid(student_id)):
            return False
        if offer.status != "ACTIVE":
            return False
        if offer.expires_at <= datetime.now(timezone.utc):
            return False
        self._offers[str(offer_id)] = offer.model_copy(
            update={
                "status": "ACCEPTED",
                "consumed_at": datetime.now(timezone.utc),
            }
        )
        return True

    # ---------------------------------------------------------------- reads

    async def load_release(self, release_id: UUID) -> ExerciseRelease | None:
        return self._releases.get(str(release_id))

    async def load_exercise(self, exercise_id: UUID) -> Exercise | None:
        return self._exercises.get(str(exercise_id))

    async def find_exercise_by_content_hash(
        self, content_hash: str
    ) -> Exercise | None:
        for exercise in self._exercises.values():
            if exercise.content_hash == content_hash:
                return exercise
        return None

    async def latest_release_for_exercise(
        self, exercise_id: UUID
    ) -> ExerciseRelease | None:
        ids = self._releases_by_exercise.get(str(exercise_id), [])
        if not ids:
            return None
        return self._releases.get(ids[-1])

    async def load_exact_verified(
        self, release: ExerciseRelease
    ) -> tuple[MathProblem, MathSolutionCandidate, VerifiedSolutionRef] | None:
        if release.solution_candidate_id is None or release.verification_log_id is None:
            return None
        exercise = await self.load_exercise(release.exercise_id)
        if exercise is None:
            return None
        problem = self._problems.get(str(exercise.problem_id))
        candidate = self._candidates.get(str(release.solution_candidate_id))
        ref = self._refs.get(str(release.verification_log_id))
        if problem is None or candidate is None or ref is None:
            return None
        return problem, candidate, ref

    async def list_outbox(self) -> list[dict[str, Any]]:
        return list(self.outbox)

    # ---------------------------------------------------------------- reset

    async def clear(self) -> None:
        self._problems.clear()
        self._candidates.clear()
        self._refs.clear()
        self._exercises.clear()
        self._releases.clear()
        self._releases_by_exercise.clear()
        self._offers.clear()
        self.outbox.clear()

    def clear_sync(self) -> None:
        self._problems.clear()
        self._candidates.clear()
        self._refs.clear()
        self._exercises.clear()
        self._releases.clear()
        self._releases_by_exercise.clear()
        self._offers.clear()
        self.outbox.clear()


__all__ = [
    "InMemoryPracticeRepository",
    "PracticeRepository",
    "build_verified_ref",
    "validate_release_binding",
]
