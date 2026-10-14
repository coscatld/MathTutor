"""The single ``verify_math`` core shared by the knowledge tool and the
explanation claim checker.

It parses the expression, solves it with the deterministic solver, requires
the isolated verifier to accept that solution, then assesses ``answer`` the
same way a student attempt is assessed. Nothing here writes learning facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

_NIL = UUID(int=0)


@dataclass(frozen=True, slots=True)
class MathCheck:
    """``status``: verified | refuted | unchecked."""

    status: str
    correctness: str = ""
    signals: tuple[str, ...] = ()
    reason: str = ""


class ExpressionNotVerifiable(ValueError):
    """The expression itself cannot be solved and verified."""


async def verified_problem(backend, expression: str):
    from mathtutor.domain.problem import MathProblem
    from mathtutor.solving.parser import parse_problem
    from mathtutor.solving.solver import solve_problem

    parsed = parse_problem(expression)
    raw = parsed.problem
    if parsed.kind != "parsed" or raw is None:
        raise ExpressionNotVerifiable(parsed.kind)
    problem = MathProblem.canonicalize(problem_type=raw.problem_type, normalized_ast=raw.normalized_ast,
                                       display_latex=raw.display_latex)
    candidate = solve_problem(problem, raw).candidate
    verdict = await backend.verify(problem, candidate)
    if verdict.verdict != "VERIFIED":
        raise ExpressionNotVerifiable(verdict.verdict)
    return problem, candidate


async def assess_answer(backend, problem, candidate, answer: str):
    from mathtutor.learning.attempt_parser import parse_student_attempt

    attempt = parse_student_attempt(attempt_submission_id=uuid4(), student_id=_NIL, cycle_id=uuid4(),
                                    raw_text=answer, attempt_index=1)
    return await backend.verify_attempt(attempt, problem, candidate)


async def verify_math(backend, expression: str, answer: str) -> MathCheck:
    """Check ``answer`` against ``expression``.

    An equivalent intermediate equation counts as verified; a partial answer
    that drops a root or any other mismatch is refuted.
    """
    try:
        problem, candidate = await verified_problem(backend, expression)
        assessed = await assess_answer(backend, problem, candidate, answer)
    except ExpressionNotVerifiable as exc:
        return MathCheck("unchecked", reason=str(exc))
    except (ValueError, TypeError, ArithmeticError) as exc:
        return MathCheck("unchecked", reason=type(exc).__name__)
    correctness = assessed.correctness.value
    signals = tuple(assessed.signals)
    if correctness == "correct" or (correctness == "partial" and set(signals) <= {"equivalent_equation"}):
        return MathCheck("verified", correctness, signals)
    if correctness in {"incorrect", "partial"}:
        return MathCheck("refuted", correctness, signals)
    return MathCheck("unchecked", correctness, signals, reason="undetermined")


__all__ = ["ExpressionNotVerifiable", "MathCheck", "assess_answer", "verified_problem", "verify_math"]
