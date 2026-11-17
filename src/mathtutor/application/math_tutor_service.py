"""MathTutor application service — the deterministic student turn core.

Design doc §3/§4.1: the application service is the *only* coordinator of a
student turn; model calls never control the core flow and core stages call
services directly. This slice implements stages ``parse`` → ``ground``
(identity grounding for MVP) → ``solve_and_verify`` → attestation commit.

Stage results that are not fully verified fail closed: no attestation, no
reference solution, no student-model update.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mathtutor.application.verification_backend import (
    InProcessVerificationBackend,
    VerificationBackend,
    VerificationBackendError,
)
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    VerificationDecision,
    VerifiedSolutionRef,
)
from mathtutor.repositories.solution_repository import (
    ProblemRepository,
    SolutionRepository,
)
from mathtutor.repositories.sqlite_math_facts import (
    SQLiteProblemRepository,
    SQLiteSolutionRepository,
)
from mathtutor.solving import parse_problem, solve_problem

SubmitResultKind = Literal[
    "verified", "unverified_blocked", "unsupported", "ambiguous", "unparseable"
]


@dataclass(frozen=True, slots=True)
class SubmitProblemResult:
    kind: SubmitResultKind
    problem: MathProblem | None = None
    candidate: MathSolutionCandidate | None = None
    decision: VerificationDecision | None = None
    verified_ref: VerifiedSolutionRef | None = None
    reason: str = ""
    code: str = ""


class MathTutorApplicationService:
    """Stateless coordinator over the parse → solve → verify → commit stages."""

    def __init__(
        self,
        problems: ProblemRepository | None = None,
        solutions: SolutionRepository | None = None,
        verification_backend: VerificationBackend | None = None,
        *,
        engine=None,
    ) -> None:
        from mathtutor.infrastructure.memory_database import create_memory_engine
        from mathtutor.repositories.uow import MathTutorUow

        if engine is None and problems is not None:
            engine = getattr(getattr(problems, "_uow", None), "engine", None)
        if engine is None and solutions is not None:
            engine = getattr(getattr(solutions, "_uow", None), "engine", None)
        self._owned_engine = (
            create_memory_engine()
            if engine is None and (problems is None or solutions is None)
            else None
        )
        engine = engine or self._owned_engine
        uow = MathTutorUow(engine) if engine is not None else None
        self.problems: ProblemRepository = problems or SQLiteProblemRepository(uow)
        self.solutions: SolutionRepository = solutions or SQLiteSolutionRepository(uow)
        self.verification_backend = (
            verification_backend or InProcessVerificationBackend()
        )

    async def aclose(self) -> None:
        """Release the private ephemeral database, when construction created one."""
        if self._owned_engine is not None:
            await self._owned_engine.dispose()
            self._owned_engine = None

    async def submit_problem(self, text: str) -> SubmitProblemResult:
        """Parse, solve, verify and (only then) commit the verified reference.

        Async since Phase 1 (SQLite repositories); the parse/solve/verify
        computation itself stays deterministic and synchronous — only the
        persistence points await.
        """
        outcome = parse_problem(text)
        if outcome.kind == "ambiguous":
            return SubmitProblemResult("ambiguous", reason=outcome.reason)
        if outcome.kind == "unparseable":
            return SubmitProblemResult("unparseable", reason=outcome.reason)
        if outcome.kind == "unsupported":
            return SubmitProblemResult(
                "unsupported", reason=outcome.reason, code=outcome.code
            )
        parsed = outcome.problem
        assert parsed is not None

        problem = await self.problems.get_or_create(
            MathProblem.canonicalize(
                problem_type=parsed.problem_type,
                normalized_ast=parsed.normalized_ast,
                display_latex=parsed.display_latex,
            )
        )
        await self.solutions.save_problem(problem)

        solved = solve_problem(problem, parsed)
        if solved.kind == "unsupported":
            return SubmitProblemResult(
                "unsupported", problem=problem, reason=solved.reason, code=solved.code
            )
        candidate = solved.candidate
        assert candidate is not None

        try:
            decision = await self.verification_backend.verify(problem, candidate)
        except VerificationBackendError as exc:
            return SubmitProblemResult(
                "unverified_blocked",
                problem=problem,
                candidate=candidate,
                reason=f"验证服务不可用（fail closed）: {type(exc).__name__}",
            )
        if decision.verdict != "VERIFIED":
            return SubmitProblemResult(
                "unverified_blocked",
                problem=problem,
                candidate=candidate,
                decision=decision,
                reason="未通过独立验证（fail closed）",
            )

        ref = await self.solutions.issue_attestation(problem, candidate, decision)
        return SubmitProblemResult(
            "verified",
            problem=problem,
            candidate=candidate,
            decision=decision,
            verified_ref=ref,
        )
