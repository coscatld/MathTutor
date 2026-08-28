"""Solution candidates, verification decisions and attestations.

The verifier returns a decision; only the repository can issue an
attestation over the persisted immutable bytes. Planner, attempt verifier
and release gate accept only :class:`VerifiedSolutionRef` — never a bare
solution payload (design doc §6.1).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.domain.hashing import content_hash

Verdict = Literal[
    "VERIFIED",
    "PARTIALLY_VERIFIED",
    "AMBIGUOUS",
    "UNSUPPORTED",
    "FAILED",
]
CheckStatus = Literal["passed", "failed", "skipped"]


class MathSolutionCandidate(BaseModel):
    """A solution candidate produced by a solver strategy (trust domain 1)."""

    model_config = ConfigDict(frozen=True)

    candidate_id: UUID = Field(default_factory=uuid4)
    problem_id: UUID
    strategy: str
    steps: tuple[dict[str, Any], ...] = ()
    final_answer: dict[str, Any]
    payload_hash: str = ""

    @classmethod
    def canonicalize(
        cls,
        problem_id: UUID,
        strategy: str,
        steps: tuple[dict[str, Any], ...],
        final_answer: dict[str, Any],
    ) -> "MathSolutionCandidate":
        candidate = cls(
            problem_id=problem_id,
            strategy=strategy,
            steps=steps,
            final_answer=final_answer,
        )
        payload = {
            "problem_id": problem_id,
            "strategy": strategy,
            "steps": steps,
            "final_answer": final_answer,
        }
        object.__setattr__(candidate, "payload_hash", content_hash(payload))
        return candidate


class VerificationCheck(BaseModel):
    """One executed check of a verification policy."""

    model_config = ConfigDict(frozen=True)

    name: str
    status: CheckStatus
    detail: str = ""


class VerificationDecision(BaseModel):
    """The verifier's decision over one candidate (trust domain 2 boundary)."""

    model_config = ConfigDict(frozen=True)

    decision_id: UUID = Field(default_factory=uuid4)
    problem_id: UUID
    problem_content_hash: str
    candidate_id: UUID
    candidate_payload_hash: str
    policy_id: str
    policy_version: str
    verdict: Verdict
    checks: tuple[VerificationCheck, ...] = ()
    payload_hash: str = ""

    @classmethod
    def canonicalize(
        cls,
        problem_id: UUID,
        problem_content_hash: str,
        candidate_id: UUID,
        candidate_payload_hash: str,
        policy_id: str,
        policy_version: str,
        verdict: Verdict,
        checks: tuple[VerificationCheck, ...],
    ) -> "VerificationDecision":
        decision = cls(
            problem_id=problem_id,
            problem_content_hash=problem_content_hash,
            candidate_id=candidate_id,
            candidate_payload_hash=candidate_payload_hash,
            policy_id=policy_id,
            policy_version=policy_version,
            verdict=verdict,
            checks=checks,
        )
        payload = {
            "problem_id": problem_id,
            "problem_content_hash": problem_content_hash,
            "candidate_id": candidate_id,
            "candidate_payload_hash": candidate_payload_hash,
            "policy_id": policy_id,
            "policy_version": policy_version,
            "verdict": verdict,
            "checks": [c.model_dump() for c in checks],
        }
        object.__setattr__(decision, "payload_hash", content_hash(payload))
        return decision


class SolutionAttestation(BaseModel):
    """Repository-issued attestation binding decision bytes (trust domain 2)."""

    model_config = ConfigDict(frozen=True)

    attestation_id: UUID = Field(default_factory=uuid4)
    decision_id: UUID
    problem_id: UUID
    problem_content_hash: str
    candidate_id: UUID
    candidate_payload_hash: str
    policy_id: str
    policy_version: str
    attestation_hash: str = ""


class VerifiedSolutionRef(BaseModel):
    """The only handle downstream consumers may accept (design doc §10)."""

    model_config = ConfigDict(frozen=True)

    verification_log_id: UUID
    problem_id: UUID
    problem_content_hash: str
    solution_candidate_id: UUID
    solution_payload_hash: str
    policy_id: str
    policy_version: str
    attestation_hash: str


__all__ = [
    "MathSolutionCandidate",
    "SolutionAttestation",
    "VerificationCheck",
    "VerificationDecision",
    "VerifiedSolutionRef",
]
