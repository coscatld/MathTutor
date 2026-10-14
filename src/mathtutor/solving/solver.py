"""Solver dispatch: produce a candidate solution for a parsed problem.

Deterministic fast path (design doc §7.1: model availability may never be
required for the core solve step). Emits JSON-safe steps and a final answer
bound into a :class:`MathSolutionCandidate`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import MathSolutionCandidate
from mathtutor.solving import nodes as n
from mathtutor.solving.parser import ParsedProblem
from mathtutor.solving.strategies import arithmetic, inequality, linear, polynomial, quadratic, linear_system

_Strategy = Callable[[ParsedProblem], tuple[tuple[dict[str, Any], ...], dict[str, Any]]]


def _quadratic_inequality_solve(parsed):
    from mathtutor.solving import quadratic_inequality
    return quadratic_inequality.solve(parsed)

_STRATEGIES: dict[str, _Strategy] = {
    "arithmetic": arithmetic.solve,
    "polynomial": polynomial.solve,
    "linear": linear.solve,
    "linear_inequality": inequality.solve,
    "quadratic_inequality": _quadratic_inequality_solve,
    "quadratic": quadratic.solve,
    "linear_system": linear_system.solve,
}


@dataclass(frozen=True, slots=True)
class SolveOutcome:
    kind: str  # "solved" | "unsupported"
    candidate: MathSolutionCandidate | None = None
    reason: str = ""

    @classmethod
    def solved(cls, candidate: MathSolutionCandidate) -> "SolveOutcome":
        return cls("solved", candidate)

    @classmethod
    def unsupported(cls, reason: str) -> "SolveOutcome":
        return cls("unsupported", None, reason)


def solve_problem(problem: MathProblem, parsed: ParsedProblem) -> SolveOutcome:
    """Run the deterministic strategy for ``problem.problem_type``."""
    strategy = _STRATEGIES.get(problem.problem_type)
    if strategy is None:
        return SolveOutcome.unsupported(f"题族 {problem.problem_type} 没有可用的求解策略")
    try:
        steps, final_answer = strategy(parsed)
    except n.MathDomainError as exc:
        return SolveOutcome.unsupported(str(exc))
    except n.MathComplexityError as exc:
        return SolveOutcome.unsupported(str(exc))
    candidate = MathSolutionCandidate.canonicalize(
        problem_id=problem.problem_id,
        strategy=problem.problem_type,
        steps=steps,
        final_answer=final_answer,
    )
    return SolveOutcome.solved(candidate)
