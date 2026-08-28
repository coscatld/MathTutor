"""TutorOutputGuard — the last line before the student sees anything (Phase 3D).

Checks three leakage classes against the verified solution:

1. final-answer leakage (values/roots appearing anywhere),
2. unapproved-step leakage (an approved-level text that contains equation
   fragments equivalent to the answer),
3. mathematically equivalent disclosure (e.g. ``x-2=0`` for answer ``x=2``
   — detected by canonical ROOT-SET equality, not string search).

On detection: deterministic fallback per level (design doc §7.2 — no LLM
retry loops). L5 is the only level allowed to carry the full solution.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from mathtutor.domain.solution import MathSolutionCandidate, VerifiedSolutionRef
from mathtutor.domain.tutoring import TutorAction
from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
from mathtutor.pedagogy.guard_math import (
    equation_roots,
    extract_math_fragments,
    numeric_values,
    parse_fragment,
)
from mathtutor.pedagogy.tutor_writer import TutorWriterCandidate


class GuardedTutorUtterance(BaseModel):
    """The only student-visible teaching text (guarded, deterministic)."""

    model_config = ConfigDict(frozen=True)

    text: str
    assistance_level: int
    action: str
    fallback_used: bool = False
    leak: str | None = None


_FALLBACKS: dict[int, str] = {
    0: "先自己想一想，把你能写的步骤写下来，我会帮你检查。",
    1: "先回忆一下这个知识点的定义，再看看题目中哪些条件可以使用。",
    2: "先确定应该使用哪一种解题方法，再进行具体计算。",
    3: "先完成当前这一小步，再把结果发给我。",
    4: "先检查你已经完成的步骤，再继续下一步。",
}


@dataclass(frozen=True, slots=True)
class ForbiddenDisclosureSet:
    """Everything the current level must NOT reveal."""

    final_answer: dict[str, Any]
    root_values: frozenset[str]  # canonical root dicts (exact)
    answer_values: frozenset[str]  # exact Fraction strings (final answer only)


def build_forbidden_set(candidate: MathSolutionCandidate) -> ForbiddenDisclosureSet:
    """Extract the exact answer/root content from a VERIFIED candidate.

    ``final_answer`` shape (solver strategies): ``{"kind": "roots",
    "roots": ({kind: rational|surd, value: ...}, ...)}``.
    """
    answer = candidate.final_answer
    roots: list[dict[str, Any]] = []
    if isinstance(answer, dict) and answer.get("kind") == "roots":
        roots = [r for r in answer.get("roots", []) if isinstance(r, dict)]
    values: set[str] = set()
    for root in roots:
        if root.get("kind") == "rational":
            value = root.get("value")
            if isinstance(value, dict):  # Rational serialization {"n": .., "d": ..}
                values.add(f"{value.get('n')}/{value.get('d')}")
            else:
                values.add(str(value))
    return ForbiddenDisclosureSet(
        final_answer=dict(answer),
        root_values=frozenset(str(r) for r in roots),
        answer_values=frozenset(values),
    )


class TutorOutputGuard:
    """Guard the writer candidate against the disclosure level."""

    def guard_or_fallback(
        self,
        *,
        candidate: TutorWriterCandidate,
        candidate_solution: MathSolutionCandidate | None,
        disclosure: DisclosedSolutionContext,
        action: TutorAction,
    ) -> GuardedTutorUtterance:
        level = disclosure.assistance_level

        # L5 is the only level authorized to carry the full solution: the
        # projector already granted it, so there is nothing left to leak —
        # the guard passes the content through BY DESIGN (not by omission).
        if level >= 5:
            return GuardedTutorUtterance(
                text=candidate.text,
                assistance_level=level,
                action=action.action,
            )

        if candidate_solution is not None:
            leak = self._detect_leak(candidate.text, candidate_solution)
            if leak is not None:
                fallback = _FALLBACKS.get(level) or _FALLBACKS[3]
                return GuardedTutorUtterance(
                    text=fallback,
                    assistance_level=level,
                    action=action.action,
                    fallback_used=True,
                    leak=leak,
                )

        return GuardedTutorUtterance(
            text=candidate.text,
            assistance_level=level,
            action=action.action,
        )

    # ------------------------------------------------------------ detection

    def _detect_leak(self, text: str, candidate: MathSolutionCandidate) -> str | None:
        """Return the leak class name, or None when clean."""
        forbidden = build_forbidden_set(candidate)

        # 1. Exact final-answer values appearing as numbers (2, 4/2, 2.0 …).
        answer_fractions: set[Fraction] = set()
        for value in forbidden.answer_values:
            try:
                answer_fractions.add(Fraction(value))
            except (ValueError, ZeroDivisionError):
                continue
        text_values = numeric_values(text)
        if text_values & answer_fractions:
            return "final_answer_value"

        # 2. Equation fragments whose canonical root set equals the answer
        #    (catches x=2, x-2=0, 2-x=0, 2x=4 … for answer {2}).
        answer_roots = (
            {str(r) for r in candidate.final_answer.get("roots", [])}
            if isinstance(candidate.final_answer, dict) and candidate.final_answer.get("kind") == "roots"
            else set()
        )
        for fragment in extract_math_fragments(text):
            parsed = parse_fragment(fragment)
            if parsed is None:
                continue
            roots = equation_roots(parsed)
            if roots is None:
                # An arithmetic expression fragment could still BE the answer
                # (e.g. "4/2"); its value was already caught by check 1.
                continue
            root_strings = {str(r) for r in roots}
            if answer_roots and root_strings == answer_roots:
                return "equivalent_equation"

        return None


__all__ = [
    "ForbiddenDisclosureSet",
    "GuardedTutorUtterance",
    "TutorOutputGuard",
    "build_forbidden_set",
]
