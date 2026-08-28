"""Exercise release service — the verified-release gate (Phase 5, §7.2/§7.3).

The release chain is fixed and gated:

    CandidateExercise (UNVERIFIED by construction)
        → Parser → Solver → Verifier
        → validate_release_binding (every hash re-checked — fail closed)
        → save_release_bundle (ONE short transaction: upsert problem +
          attestation + exercise + release + supersede + revoke + outbox)
        → ExerciseRelease (status=released)
        → PracticeOffer

Rules enforced here:

- ``source_type`` (BANK/TEMPLATE/LLM) is a CLAIM on the exercise, never a
  trust grant — every candidate passes the IDENTICAL release gate.
- Releases are immutable: any bound-byte change (problem/solution/verifier/
  policy/license/provenance) yields a NEW release; the old one becomes
  SUPERSEDED and its ACTIVE offers are REVOKED — all in the same
  transaction as the new release (§7.3/§7.9).
- Idempotent republish: identical bytes → the existing release is returned
  (nothing re-issued, nothing superseded) — ``publish_seed_bank`` is safe
  to call any number of times.
- Exact snapshot: each release binds its OWN solution_candidate_id +
  verification_log_id; judging a child cycle uses THOSE bytes (§11.3).

LLM NEVER participates in verification or release authority: the verifier
is the deterministic checks pipeline and the attestation is issued by the
repository transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID, uuid4, uuid5

from mathtutor.application.adaptive_practice import CandidateExercise
from mathtutor.application.verification_backend import (
    AUTHORITATIVE_VERIFIER_VERSION,
    InProcessVerificationBackend,
    VerificationBackend,
    VerificationBackendError,
)
from mathtutor.domain.hashing import content_hash
from mathtutor.domain.practice import (
    Exercise,
    ExerciseRelease,
    exercise_content_hash,
)
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    VerificationDecision,
    VerifiedSolutionRef,
)
from mathtutor.learning.skills import (
    CONCEPT_LINEAR_EQUATIONS,
    CONCEPT_NUMBER_OPERATIONS,
    CONCEPT_POLYNOMIALS,
    CONCEPT_QUADRATIC_EQUATIONS,
    SKILL_ARITHMETIC,
    SKILL_LINEAR_EQUATION,
    SKILL_POLYNOMIAL_BASIC,
    SKILL_QUADRATIC_EQUATION,
    all_skill_ids,
)
from mathtutor.repositories.practice_repository import (
    PracticeRepository,
    validate_release_binding,
)
from mathtutor.solving import parse_problem, solve_problem
from mathtutor.solving.verifier import VerificationPolicy

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

OFFER_TTL = timedelta(days=7)

# Server-owned identity namespaces (stable — mapping ids MUST NOT change).
_EXERCISE_NS = uuid5(UUID(int=0), "mt-exercise")
_GROUNDING_NS = uuid5(UUID(int=0), "mt-problem-grounding")
_MAPPING_NS = uuid5(UUID(int=0), "mt-curriculum-mapping")

# Verifier identity — any change here (or via override) yields a release
# with a different verifier_hash → a NEW release (immutability §7.3).
VERIFIER_VERSION = AUTHORITATIVE_VERIFIER_VERSION

# Version of the application-level CandidateExercise -> immutable release
# gate.  This is a runtime/domain contract, not a user preference.
RELEASE_POLICY_VERSION = "mt-release-policy-v1"

# License claim for MVP practice items (binding hash covers it).
MVP_LICENSE_REF = "mt-license-mvp-v1"

# Seed-bank owner placeholder: seed items are global (student-independent);
# the release gate does not involve a student.
_SEED_STUDENT_NS = uuid5(UUID(int=0), "mt-seed-bank")


class ReleaseDeniedError(Exception):
    """The release gate refused a candidate (fail closed — no release)."""


class PracticeOfferError(Exception):
    """No offer could be prepared (no candidate passed the release gate)."""


@dataclass(frozen=True, slots=True)
class SeedBankItem:
    """One seed-bank exercise (BANK source) — statement + targets + family."""

    problem_statement: str
    difficulty: int
    skill_ids: tuple[str, ...]
    concept_ids: tuple[str, ...]


SEED_BANK: tuple[SeedBankItem, ...] = (
    SeedBankItem("3/4 + 1/2", 1, (SKILL_ARITHMETIC,), (CONCEPT_NUMBER_OPERATIONS,)),
    SeedBankItem("7/8 - 1/4", 1, (SKILL_ARITHMETIC,), (CONCEPT_NUMBER_OPERATIONS,)),
    SeedBankItem("(x + 1)^2", 2, (SKILL_POLYNOMIAL_BASIC,), (CONCEPT_POLYNOMIALS,)),
    SeedBankItem("2(x + 1) + 3", 2, (SKILL_POLYNOMIAL_BASIC,), (CONCEPT_POLYNOMIALS,)),
    SeedBankItem("2x + 3 = 7", 2, (SKILL_LINEAR_EQUATION,), (CONCEPT_LINEAR_EQUATIONS,)),
    SeedBankItem("3x - 5 = 4", 2, (SKILL_LINEAR_EQUATION,), (CONCEPT_LINEAR_EQUATIONS,)),
    SeedBankItem("x^2 - 5x + 6 = 0", 3, (SKILL_QUADRATIC_EQUATION,), (CONCEPT_QUADRATIC_EQUATIONS,)),
    SeedBankItem("x^2 - 4x + 4 = 0", 3, (SKILL_QUADRATIC_EQUATION,), (CONCEPT_QUADRATIC_EQUATIONS,)),
)

_ALL_CONCEPTS: tuple[str, ...] = (
    CONCEPT_NUMBER_OPERATIONS,
    CONCEPT_POLYNOMIALS,
    CONCEPT_LINEAR_EQUATIONS,
    CONCEPT_QUADRATIC_EQUATIONS,
)


def mapping_id_for_skill(skill_id: str) -> UUID:
    """Deterministic curriculum mapping id for a skill (server-owned)."""
    return uuid5(_MAPPING_NS, f"skill:{skill_id}")


def mapping_id_for_concept(concept_id: str) -> UUID:
    """Deterministic curriculum mapping id for a concept (server-owned)."""
    return uuid5(_MAPPING_NS, f"concept:{concept_id}")


def labels_for_mapping_ids(
    mapping_ids: Sequence[UUID],
) -> dict[str, list[str]]:
    """Reverse-map stable curriculum ids → labels for the /offers projection."""
    ids = set(str(m) for m in mapping_ids)
    return {
        "skill_labels": [
            skill_id
            for skill_id in all_skill_ids()
            if str(mapping_id_for_skill(skill_id)) in ids
        ],
        "concept_labels": [
            concept_id
            for concept_id in _ALL_CONCEPTS
            if str(mapping_id_for_concept(concept_id)) in ids
        ],
    }


@dataclass(frozen=True, slots=True)
class ReleaseChain:
    """Everything one released exercise snapshot binds (or its replay)."""

    problem: MathProblem
    candidate: MathSolutionCandidate
    decision: VerificationDecision | None  # None on idempotent replay
    ref: VerifiedSolutionRef
    exercise: Exercise
    release: ExerciseRelease


def _release_bytes(
    problem: MathProblem,
    candidate: MathSolutionCandidate,
    decision: VerificationDecision,
    exercise: Exercise,
    verifier_version: str,
    provenance: dict[str, str],
) -> dict[str, str]:
    """The 7 immutable bound-byte hashes of a release (§7.3).

    ANY change in any bound artifact changes one of these hashes → the
    release service issues a NEW release and supersedes the old one.
    ``provenance`` carries the candidate's source claim (generated_by +
    context_version) — a claim, never a trust grant.
    """
    return {
        "problem_hash": problem.content_hash,
        "solution_hash": candidate.payload_hash,
        "verification_policy_hash": content_hash(
            {
                "policy_id": decision.policy_id,
                "policy_version": decision.policy_version,
            }
        ),
        "verifier_hash": content_hash({"verifier_version": verifier_version}),
        "solution_candidate_hash": content_hash(
            {
                "strategy": candidate.strategy,
                "payload_hash": candidate.payload_hash,
            }
        ),
        "license_hash": content_hash({"license": exercise.license_ref}),
        "provenance_hash": content_hash(provenance),
    }


class ExerciseReleaseService:
    """The ONLY way an exercise enters the released catalog (§7.2)."""

    def __init__(
        self,
        repository: PracticeRepository | None = None,
        verification_backend: VerificationBackend | None = None,
    ) -> None:
        from mathtutor.repositories.practice_repository import (
            InMemoryPracticeRepository,
        )

        self.repository = repository or InMemoryPracticeRepository()
        self.verification_backend = verification_backend or InProcessVerificationBackend()

    # ----------------------------------------------------------- publish

    async def publish_seed_bank(self) -> dict[str, int]:
        """Publish every seed-bank item through the FULL release gate.

        Idempotent: identical bytes → the existing release is returned, no
        new rows, nothing superseded. Items that fail the gate (should not
        happen — the bank is curated) are counted, never silently dropped.
        """
        total = len(SEED_BANK)
        released = 0
        failed = 0
        for item in SEED_BANK:
            candidate = CandidateExercise(
                student_id=uuid5(_SEED_STUDENT_NS, "seed-bank"),
                problem_statement=item.problem_statement,
                skill_ids=item.skill_ids,
                concept_ids=item.concept_ids,
                difficulty=item.difficulty,
                generated_by="mt-bank-seed-v1",
            )
            try:
                await self.release_candidate(candidate, source_type="BANK")
                released += 1
            except ReleaseDeniedError:
                failed += 1
        return {"total": total, "released": released, "failed": failed}

    # ------------------------------------------------------- release gate

    async def release_candidate(
        self,
        candidate: CandidateExercise,
        *,
        source_type: str = "BANK",
        problem_statement: str | None = None,
        solution_candidate: MathSolutionCandidate | None = None,
        policy_id: str | None = None,
        policy_version: str | None = None,
        verifier_version: str | None = None,
    ) -> ReleaseChain:
        """Run one candidate through Parser → Solver → Verifier → Release.

        Fail closed at every stage; the repository issues the attestation
        and the release in ONE transaction (the release gate). ``source_type``
        is a claim on the exercise — the gate itself never looks at it.

        Overrides (problem_statement/solution_candidate/policy/verifier)
        are TEST/ops hooks that change the bound bytes; the release
        immutability rules apply to them exactly as to production bytes.
        """
        verifier_version = verifier_version or VERIFIER_VERSION

        # 1. Parser — the candidate statement must canonicalize.
        statement = problem_statement or candidate.problem_statement
        outcome = parse_problem(statement)
        if outcome.kind != "parsed":
            raise ReleaseDeniedError(
                f"候选语句无法解析（{outcome.kind}），拒绝发布: {statement!r}"
            )
        parsed = outcome.problem
        assert parsed is not None
        problem = MathProblem.canonicalize(
            problem_type=parsed.problem_type,
            normalized_ast=parsed.normalized_ast,
            display_latex=parsed.display_latex,
        )
        # Deterministic problem identity: the SAME canonical statement must
        # map to the SAME problem_id across republish calls (a fresh uuid4
        # per call would break content identity and idempotent republish).
        problem = problem.model_copy(
            update={
                "problem_id": uuid5(
                    _EXERCISE_NS, f"problem:{problem.content_hash}"
                )
            }
        )

        # 2. Solver (or explicit candidate bytes).
        if solution_candidate is None:
            solved = solve_problem(problem, parsed)
            if solved.kind == "unsupported":
                raise ReleaseDeniedError(
                    f"候选语句无法求解，拒绝发布: {statement!r}"
                )
            candidate_bytes = solved.candidate
            assert candidate_bytes is not None
        else:
            candidate_bytes = solution_candidate

        # 3. Verifier — independent checks; the verdict is authoritative.
        try:
            decision = await self.verification_backend.verify(problem, candidate_bytes)
        except VerificationBackendError as exc:
            raise ReleaseDeniedError(
                f"验证服务不可用，拒绝发布: {type(exc).__name__}"
            ) from exc
        if policy_id is not None or policy_version is not None:
            decision = decision.model_copy(
                update={
                    "policy_id": policy_id or decision.policy_id,
                    "policy_version": policy_version or decision.policy_version,
                }
            )

        # 4. Re-validate every hash binding BEFORE any write (fail closed).
        validate_release_binding(problem, candidate_bytes, decision)

        # 5. Exercise identity: content-bound, deterministic (§7.1).
        exercise = Exercise(
            exercise_id=uuid5(
                _EXERCISE_NS, exercise_content_hash(
                    problem_statement=statement,
                    problem_id=problem.problem_id,
                    difficulty=candidate.difficulty,
                    source_type=source_type,
                )
            ),
            problem_id=problem.problem_id,
            problem_grounding_id=uuid5(
                _GROUNDING_NS, f"{problem.problem_id}:{candidate.difficulty}"
            ),
            display_latex=problem.display_latex,
            difficulty=candidate.difficulty,
            target_mapping_ids=(
                tuple(mapping_id_for_skill(s) for s in candidate.skill_ids)
                + tuple(mapping_id_for_concept(c) for c in candidate.concept_ids)
            ),
            license_ref=MVP_LICENSE_REF,
            source_type=source_type,
            content_hash=exercise_content_hash(
                problem_statement=statement,
                problem_id=problem.problem_id,
                difficulty=candidate.difficulty,
                source_type=source_type,
            ),
            problem_statement=statement,
        )
        release = ExerciseRelease(
            release_id=uuid4(),
            exercise_id=exercise.exercise_id,
            **_release_bytes(
                problem,
                candidate_bytes,
                decision,
                exercise,
                verifier_version,
                {
                    "source_type": exercise.source_type,
                    "generated_by": candidate.generated_by,
                    "context_version": candidate.context_version,
                },
            ),
            status="draft",
        )

        # 6. Idempotency BEFORE attestation: identical bytes → existing.
        replay = await self._find_identical_release(exercise, release)
        if replay is not None:
            return replay

        # 7. THE release gate: ONE short transaction — attestation +
        #    exercise + release + supersede + revoke + outbox.
        ref, final = await self.repository.save_release_bundle(
            problem=problem,
            candidate=candidate_bytes,
            decision=decision,
            exercise=exercise,
            release=release,
            outbox_events=[
                {
                    "aggregate_type": "exercise_release",
                    "aggregate_id": str(release.release_id),
                    "aggregate_version": 1,
                    "event_sequence": 1,
                    "event_type": "exercise_release_issued",
                    "audience": "internal",
                    "payload": {
                        "exercise_id": str(exercise.exercise_id),
                        "status": "released",
                        "source_type": source_type,
                    },
                }
            ],
        )
        return ReleaseChain(
            problem=problem,
            candidate=candidate_bytes,
            decision=decision,
            ref=ref,
            exercise=exercise.model_copy(
                update={"exercise_id": final.exercise_id}
            ),
            release=final,
        )

    async def _find_identical_release(
        self, exercise: Exercise, release: ExerciseRelease
    ) -> ReleaseChain | None:
        """Idempotent republish: same exercise + identical bound bytes."""
        existing = await self.repository.find_exercise_by_content_hash(
            exercise.content_hash
        )
        if existing is None:
            return None
        latest = await self.repository.latest_release_for_exercise(
            existing.exercise_id
        )
        if latest is None:
            return None
        # Only a LIVE release replays (idempotency); a superseded/revoked
        # one must be re-issued so an offer can never bind a dead release.
        if latest.status != "released":
            return None
        for field in (
            "problem_hash",
            "solution_hash",
            "verification_policy_hash",
            "verifier_hash",
            "solution_candidate_hash",
            "license_hash",
            "provenance_hash",
        ):
            if getattr(latest, field) != getattr(release, field):
                return None
        exact = await self.repository.load_exact_verified(latest)
        if exact is None:
            return None
        problem, candidate, ref = exact
        return ReleaseChain(
            problem=problem,
            candidate=candidate,
            decision=None,
            ref=ref,
            exercise=existing,
            release=latest,
        )

    # ------------------------------------------------------------ offers

    async def create_offer(
        self,
        offer: Any,
        *,
        outbox_events: list[dict[str, Any]] | None = None,
    ) -> None:
        """Persist an ACTIVE offer bound to an exact release (one tx)."""
        await self.repository.create_offer(
            offer, outbox_events=outbox_events or []
        )


__all__ = [
    "ExerciseReleaseService",
    "OFFER_TTL",
    "PracticeOfferError",
    "ReleaseChain",
    "ReleaseDeniedError",
    "SEED_BANK",
    "SeedBankItem",
    "VERIFIER_VERSION",
    "labels_for_mapping_ids",
    "mapping_id_for_concept",
    "mapping_id_for_skill",
]
