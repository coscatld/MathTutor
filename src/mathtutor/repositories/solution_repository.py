"""Repository interfaces with in-memory implementations.

Design doc §6.1: the verifier returns a *decision*; only the repository can
issue an attestation over the persisted immutable bytes. ``issue_attestation``
re-validates the decision, the problem hash and the candidate hash against
its own stored records and raises (fail closed) unless everything is
``VERIFIED`` and bound.

The interfaces are async since Phase 1 (the SQLite implementations use
aiosqlite); the in-memory implementations share the same async contract.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from mathtutor.domain.hashing import content_hash
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    SolutionAttestation,
    VerificationDecision,
    VerifiedSolutionRef,
)


class AttestationDeniedError(Exception):
    """Attestation refused: the decision was not VERIFIED or hashes do not bind."""


class ProblemRepository(Protocol):
    async def get_or_create(self, problem: MathProblem) -> MathProblem: ...

    async def get(self, problem_id: UUID) -> MathProblem | None: ...


class SolutionRepository(Protocol):
    async def save_problem(self, problem: MathProblem) -> None: ...

    async def issue_attestation(
        self,
        problem: MathProblem,
        candidate: MathSolutionCandidate,
        decision: VerificationDecision,
    ) -> VerifiedSolutionRef: ...

    async def get_attestation(self, verification_log_id: UUID) -> VerifiedSolutionRef | None: ...

    async def get_attestation_for_problem(self, problem_id: UUID) -> VerifiedSolutionRef | None: ...

    async def get_problem(self, problem_id: UUID) -> MathProblem | None: ...


class InMemoryProblemRepository:
    """Canonical problems are unique by content hash (design doc §12)."""

    def __init__(self) -> None:
        self._by_id: dict[UUID, MathProblem] = {}
        self._by_hash: dict[str, MathProblem] = {}

    async def get_or_create(self, problem: MathProblem) -> MathProblem:
        existing = self._by_hash.get(problem.content_hash)
        if existing is not None:
            return existing
        self._by_hash[problem.content_hash] = problem
        self._by_id[problem.problem_id] = problem
        return problem

    async def get(self, problem_id: UUID) -> MathProblem | None:
        return self._by_id.get(problem_id)


class InMemorySolutionRepository:
    """Immutable stores; attestations only for bound, VERIFIED decisions."""

    def __init__(self, problems: InMemoryProblemRepository | None = None) -> None:
        self._problems = problems or InMemoryProblemRepository()
        self._attestations: dict[UUID, VerifiedSolutionRef] = {}
        self._by_problem: dict[UUID, VerifiedSolutionRef] = {}
        self._attestation_records: dict[UUID, SolutionAttestation] = {}

    async def save_problem(self, problem: MathProblem) -> None:
        await self._problems.get_or_create(problem)

    async def issue_attestation(
        self,
        problem: MathProblem,
        candidate: MathSolutionCandidate,
        decision: VerificationDecision,
    ) -> VerifiedSolutionRef:
        stored = await self._problems.get(problem.problem_id) or await self._problems.get_or_create(problem)
        if stored.content_hash != problem.content_hash:
            raise AttestationDeniedError("problem 哈希与已存储记录不一致")
        if stored.content_hash != decision.problem_content_hash:
            raise AttestationDeniedError("decision 绑定的 problem 哈希不一致")
        if decision.candidate_id != candidate.candidate_id:
            raise AttestationDeniedError("decision 与 candidate 不一致")
        if decision.candidate_payload_hash != candidate.payload_hash:
            raise AttestationDeniedError("decision 绑定的 candidate 哈希不一致")
        if candidate.problem_id != problem.problem_id:
            raise AttestationDeniedError("candidate 绑定的 problem_id 不一致")
        if decision.verdict != "VERIFIED":
            raise AttestationDeniedError(f"拒绝签发：verdict={decision.verdict}")
        if any(check.status == "failed" for check in decision.checks):
            raise AttestationDeniedError("拒绝签发：存在失败检查")

        payload = {
            "decision_id": decision.decision_id,
            "problem_id": problem.problem_id,
            "problem_content_hash": stored.content_hash,
            "candidate_id": candidate.candidate_id,
            "candidate_payload_hash": candidate.payload_hash,
            "policy_id": decision.policy_id,
            "policy_version": decision.policy_version,
        }
        attestation = SolutionAttestation(
            decision_id=decision.decision_id,
            problem_id=problem.problem_id,
            problem_content_hash=stored.content_hash,
            candidate_id=candidate.candidate_id,
            candidate_payload_hash=candidate.payload_hash,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            attestation_hash=content_hash(payload),
        )
        ref = VerifiedSolutionRef(
            verification_log_id=decision.decision_id,
            problem_id=problem.problem_id,
            problem_content_hash=stored.content_hash,
            solution_candidate_id=candidate.candidate_id,
            solution_payload_hash=candidate.payload_hash,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            attestation_hash=attestation.attestation_hash,
        )
        self._attestations[ref.verification_log_id] = ref
        self._by_problem[problem.problem_id] = ref
        self._attestation_records[ref.verification_log_id] = attestation
        return ref

    async def get_attestation(self, verification_log_id: UUID) -> VerifiedSolutionRef | None:
        return self._attestations.get(verification_log_id)

    async def get_attestation_for_problem(self, problem_id: UUID) -> VerifiedSolutionRef | None:
        return self._by_problem.get(problem_id)

    async def get_problem(self, problem_id: UUID) -> MathProblem | None:
        return await self._problems.get(problem_id)


__all__ = [
    "AttestationDeniedError",
    "InMemoryProblemRepository",
    "InMemorySolutionRepository",
    "ProblemRepository",
    "SolutionRepository",
]
