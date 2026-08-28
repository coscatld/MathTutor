"""SQLite implementations of the math-fact repositories (Phase 1C).

Same contract as ``solution_repository`` (now async): problems are unique by
content hash, and attestations are issued ONLY for bound, VERIFIED decisions
with every hash re-validated against the persisted bytes — fail closed.

Reads/writes run inside the caller's UoW transaction (short scope).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from mathtutor.domain.hashing import content_hash
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    SolutionAttestation,
    VerificationDecision,
    VerifiedSolutionRef,
)
from mathtutor.infrastructure.schema import (
    math_problems,
    solution_candidates,
    verification_logs,
)
from mathtutor.repositories.solution_repository import AttestationDeniedError

_SCHEMA_VERSION = "1"
_CANONICALIZATION_VERSION = "1"


def _problem_from_row(row: Any) -> MathProblem:
    return MathProblem(
        problem_id=UUID(row.problem_id),
        schema_version=row.schema_version,
        canonicalization_version=row.canonicalization_version,
        problem_type=row.problem_type,
        normalized_ast=row.normalized_ast,
        display_latex=row.display_latex,
        content_hash=row.content_hash,
    )


async def upsert_math_problem(conn: AsyncConnection, problem: MathProblem) -> MathProblem:
    """Insert or fetch the canonical problem (unique by content hash)."""
    existing = (
        await conn.execute(
            select(math_problems).where(math_problems.c.content_hash == problem.content_hash)
        )
    ).first()
    if existing is not None:
        return _problem_from_row(existing)
    await conn.execute(
        math_problems.insert().values(
            problem_id=str(problem.problem_id),
            schema_version=problem.schema_version,
            canonicalization_version=problem.canonicalization_version,
            problem_type=problem.problem_type,
            normalized_ast=problem.normalized_ast,
            display_latex=problem.display_latex,
            content_hash=problem.content_hash,
        )
    )
    return problem


async def insert_solution_candidate(conn: AsyncConnection, candidate: MathSolutionCandidate) -> None:
    from datetime import datetime, timezone

    await conn.execute(
        solution_candidates.insert().values(
            candidate_id=str(candidate.candidate_id),
            problem_id=str(candidate.problem_id),
            steps=candidate.steps,
            final_answer=candidate.final_answer,
            payload_hash=candidate.payload_hash,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )


async def issue_solution_attestation(
    conn: AsyncConnection,
    problem: MathProblem,
    candidate: MathSolutionCandidate,
    decision: VerificationDecision,
) -> VerifiedSolutionRef:
    """Persist the verification log + attestation; re-validate every binding.

    Identical fail-closed rules to the in-memory repository — the SQLite
    implementation adds persistence, not trust.
    """
    from datetime import datetime, timezone

    row = (
        await conn.execute(
            select(math_problems).where(math_problems.c.problem_id == str(problem.problem_id))
        )
    ).first()
    if row is None:
        row = (
            await conn.execute(
                select(math_problems).where(math_problems.c.content_hash == problem.content_hash)
            )
        ).first()
    if row is None:
        raise AttestationDeniedError("problem 未持久化，拒绝签发")
    stored = _problem_from_row(row)

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

    # FK order: candidate row first, then the verification log that binds it.
    await conn.execute(
        solution_candidates.insert().values(
            candidate_id=str(candidate.candidate_id),
            problem_id=str(candidate.problem_id),
            steps=candidate.steps,
            final_answer=candidate.final_answer,
            payload_hash=candidate.payload_hash,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )
    await conn.execute(
        verification_logs.insert().values(
            log_id=str(decision.decision_id),
            candidate_id=str(candidate.candidate_id),
            attempt_id=None,
            problem_id=str(problem.problem_id),
            verdict=decision.verdict,
            checks=[check.model_dump(mode="json") for check in decision.checks],
            attestation_hash=attestation.attestation_hash,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
    )

    return VerifiedSolutionRef(
        verification_log_id=decision.decision_id,
        problem_id=problem.problem_id,
        problem_content_hash=stored.content_hash,
        solution_candidate_id=candidate.candidate_id,
        solution_payload_hash=candidate.payload_hash,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        attestation_hash=attestation.attestation_hash,
    )


async def load_attestation_for_problem(
    conn: AsyncConnection, problem_id: UUID
) -> VerifiedSolutionRef | None:
    row = (
        await conn.execute(
            select(
                verification_logs,
                math_problems.c.content_hash,
                solution_candidates.c.payload_hash,
            )
            .join(math_problems, math_problems.c.problem_id == verification_logs.c.problem_id)
            .join(
                solution_candidates,
                solution_candidates.c.candidate_id == verification_logs.c.candidate_id,
            )
            .where(verification_logs.c.problem_id == str(problem_id))
            .where(verification_logs.c.attestation_hash.is_not(None))
            .order_by(verification_logs.c.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return VerifiedSolutionRef(
        verification_log_id=UUID(row.log_id),
        problem_id=problem_id,
        problem_content_hash=row.content_hash,
        solution_candidate_id=UUID(row.candidate_id),
        solution_payload_hash=row.payload_hash,
        policy_id="",
        policy_version="",
        attestation_hash=row.attestation_hash,
    )


async def load_problem(conn: AsyncConnection, problem_id: UUID) -> MathProblem | None:
    row = (
        await conn.execute(select(math_problems).where(math_problems.c.problem_id == str(problem_id)))
    ).first()
    return _problem_from_row(row) if row is not None else None


async def load_candidate(conn: AsyncConnection, candidate_id: UUID) -> MathSolutionCandidate | None:
    row = (
        await conn.execute(
            select(solution_candidates).where(solution_candidates.c.candidate_id == str(candidate_id))
        )
    ).first()
    if row is None:
        return None
    return MathSolutionCandidate(
        candidate_id=UUID(row.candidate_id),
        problem_id=UUID(row.problem_id),
        strategy="",
        steps=tuple(row.steps) if isinstance(row.steps, list) else (),
        final_answer=row.final_answer,
        payload_hash=row.payload_hash,
    )


async def load_verified_for_problem(
    conn: AsyncConnection, problem_id: UUID
) -> tuple[MathProblem, MathSolutionCandidate, VerifiedSolutionRef] | None:
    """Restore the full verified chain for a problem (Phase 3 restart-safe).

    problem + candidate + attested ref from the persisted bytes; returns
    None when no attested solution exists — callers fail closed.
    """
    row = (
        await conn.execute(
            select(
                verification_logs,
                math_problems.c.content_hash,
                solution_candidates.c.payload_hash,
            )
            .join(math_problems, math_problems.c.problem_id == verification_logs.c.problem_id)
            .join(
                solution_candidates,
                solution_candidates.c.candidate_id == verification_logs.c.candidate_id,
            )
            .where(verification_logs.c.problem_id == str(problem_id))
            .where(verification_logs.c.attestation_hash.is_not(None))
            .order_by(verification_logs.c.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    problem = await load_problem(conn, problem_id)
    candidate = await load_candidate(conn, UUID(row.candidate_id))
    if problem is None or candidate is None:
        return None
    ref = VerifiedSolutionRef(
        verification_log_id=UUID(row.log_id),
        problem_id=problem.problem_id,
        problem_content_hash=row.content_hash,
        solution_candidate_id=UUID(row.candidate_id),
        solution_payload_hash=row.payload_hash,
        policy_id="",
        policy_version="",
        attestation_hash=row.attestation_hash,
    )
    return problem, candidate, ref


class SQLiteProblemRepository:
    """ProblemRepository over the product database (short UoW transactions)."""

    def __init__(self, uow: Any) -> None:
        self._uow = uow

    async def get_or_create(self, problem: MathProblem) -> MathProblem:
        async with self._uow.transaction() as conn:
            return await upsert_math_problem(conn, problem)

    async def get(self, problem_id: UUID) -> MathProblem | None:
        async with self._uow.transaction() as conn:
            return await load_problem(conn, problem_id)


class SQLiteSolutionRepository:
    """SolutionRepository over the product database; attestation fail-closed
    rules identical to the in-memory implementation."""

    def __init__(self, uow: Any) -> None:
        self._uow = uow

    async def save_problem(self, problem: MathProblem) -> None:
        async with self._uow.transaction() as conn:
            await upsert_math_problem(conn, problem)

    async def issue_attestation(
        self,
        problem: MathProblem,
        candidate: MathSolutionCandidate,
        decision: VerificationDecision,
    ) -> VerifiedSolutionRef:
        async with self._uow.transaction() as conn:
            return await issue_solution_attestation(conn, problem, candidate, decision)

    async def get_attestation(self, verification_log_id: UUID) -> VerifiedSolutionRef | None:
        raise NotImplementedError("attestation lookup by log id lands with attempt judging")

    async def get_attestation_for_problem(self, problem_id: UUID) -> VerifiedSolutionRef | None:
        async with self._uow.transaction() as conn:
            return await load_attestation_for_problem(conn, problem_id)

    async def get_problem(self, problem_id: UUID) -> MathProblem | None:
        async with self._uow.transaction() as conn:
            return await load_problem(conn, problem_id)


__all__ = [
    "SQLiteProblemRepository",
    "SQLiteSolutionRepository",
    "insert_solution_candidate",
    "issue_solution_attestation",
    "load_attestation_for_problem",
    "load_problem",
    "upsert_math_problem",
]
