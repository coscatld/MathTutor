"""Repository interfaces for SQLite storage.

Design doc §6.1: the verifier returns a *decision*; only the repository can
issue an attestation over the persisted immutable bytes. ``issue_attestation``
re-validates the decision, the problem hash and the candidate hash against
its own stored records and raises (fail closed) unless everything is
``VERIFIED`` and bound.

The interfaces are async since Phase 1 (the SQLite implementations use
aiosqlite), for both durable and ephemeral databases.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import (
    MathSolutionCandidate,
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

    async def get_attestation(
        self, verification_log_id: UUID
    ) -> VerifiedSolutionRef | None: ...

    async def get_attestation_for_problem(
        self, problem_id: UUID
    ) -> VerifiedSolutionRef | None: ...

    async def get_problem(self, problem_id: UUID) -> MathProblem | None: ...


__all__ = [
    "AttestationDeniedError",
    "ProblemRepository",
    "SolutionRepository",
]
