"""Application boundary for authoritative solution verification.

The application layer knows that verification can be unavailable, but it
does not know whether the implementation uses a process, pipe, or queue.
Both implementations must execute the one mathematical authority in
``solving.verifier``.
"""

from __future__ import annotations

from typing import Protocol

from mathtutor.domain.problem import MathProblem
from mathtutor.domain.attempt import StudentAttempt
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    VerificationDecision,
)
from mathtutor.solving.verifier import verify
from mathtutor.learning.attempt_verifier import (
    AttemptAssessment,
    verify_attempt,
)

VERIFICATION_SCHEMA_VERSION = "mt-verification-ipc-v1"
AUTHORITATIVE_VERIFIER_VERSION = "mt-verifier-v1"


class VerificationBackendError(RuntimeError):
    """Verification did not complete authoritatively (fail closed)."""


class VerificationTimeoutError(VerificationBackendError):
    """The isolated computation exceeded its wall-clock budget."""


class VerificationWorkerCrashedError(VerificationBackendError):
    """The isolated verifier exited without a valid response."""


class VerificationResourceLimitError(VerificationBackendError):
    """The request exceeded a server-owned execution budget."""


class VerificationBackpressureError(VerificationBackendError):
    """The bounded verifier queue has no capacity."""


class VerificationMalformedResponseError(VerificationBackendError):
    """The worker returned bytes outside the typed response contract."""


class VerificationBackend(Protocol):
    async def verify(
        self,
        problem: MathProblem,
        candidate: MathSolutionCandidate,
    ) -> VerificationDecision: ...

    async def verify_attempt(
        self,
        student_attempt: StudentAttempt,
        problem: MathProblem,
        verified_candidate: MathSolutionCandidate,
    ) -> AttemptAssessment: ...


class InProcessVerificationBackend:
    """Explicit development/test backend; never an implicit worker fallback."""

    async def verify(
        self,
        problem: MathProblem,
        candidate: MathSolutionCandidate,
    ) -> VerificationDecision:
        return verify(problem, candidate)

    async def verify_attempt(
        self,
        student_attempt: StudentAttempt,
        problem: MathProblem,
        verified_candidate: MathSolutionCandidate,
    ) -> AttemptAssessment:
        return verify_attempt(student_attempt, problem, verified_candidate)


__all__ = [
    "AUTHORITATIVE_VERIFIER_VERSION",
    "InProcessVerificationBackend",
    "VerificationBackend",
    "VerificationBackendError",
    "VerificationBackpressureError",
    "VerificationMalformedResponseError",
    "VerificationResourceLimitError",
    "VerificationTimeoutError",
    "VerificationWorkerCrashedError",
    "VERIFICATION_SCHEMA_VERSION",
]
