"""TutorOutputGuard — the last line before the student sees anything (Phase 3D).

Checks scalar results, roots, polynomial forms and system assignments against
verified solution material. Merely mentioning a source constant is not answer
exposure. Guard mode also catches unauthorized equivalent solution equations;
delivery mode records only an actually revealed complete target answer.

On detection: deterministic fallback per level (design doc §7.2 — no LLM
retry loops). L5 is the only level allowed to carry the full solution.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from mathtutor.domain.solution import MathSolutionCandidate, VerifiedSolutionRef
from mathtutor.domain.tutoring import TutorAction
from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
from mathtutor.pedagogy.guard_math import (
    equation_roots,
    parse_fragment,
)
from mathtutor.pedagogy.tutor_writer import TutorWriterCandidate
from mathtutor.solving import nodes as n
from mathtutor.solving.strategies import _common as common


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

    def _detect_leak(self, text: str, candidate: MathSolutionCandidate, *, target_answer_only=False) -> str | None:
        """Compare actual answer assertions, not numbers occurring in a prompt.

        Delivery uses ``target_answer_only=True``: a useful intermediate
        equation is help, not a full-answer exposure. Guarding additionally
        rejects unauthorized equivalent solution equations. Both paths exclude
        the source statement reconstructed from verified candidate material.
        """
        final = candidate.final_answer
        kind = final.get("kind")
        fragments = _answer_fragments(text)
        asserted = bool(_ANSWER_ASSERTION.search(text))
        if kind == "rational":
            expected = common.frac_from_dict(final["value"])
            source = candidate.steps[-1].get("expr") if candidate.steps else None
            for fragment in fragments:
                parts = fragment.split("=")
                options = parts[-1:] if len(parts) > 1 else parts
                for part in options:
                    parsed = parse_fragment(part)
                    if parsed and source == n.to_dict(parsed.ast) and not asserted and len(parts) == 1 and not _bare_answer(text, part):
                        continue
                    if _scalar(part) == expected and (len(parts) > 1 or asserted or _bare_answer(text, part)):
                        return "final_arithmetic_value"
        elif kind == "polynomial":
            expected = _nonzero_coefficients(common.coeffs_from_dict(final["coeffs"]))
            variable = final["var"]
            source = candidate.steps[0].get("expr") if candidate.steps else None
            for fragment in fragments:
                for part in fragment.split("="):
                    parsed = parse_fragment(part)
                    if not parsed or isinstance(parsed.ast, n.Equation):
                        continue
                    if source == n.to_dict(parsed.ast) and not asserted:
                        continue
                    coeffs = n.poly_coeffs(parsed.ast, variable)
                    if coeffs is not None and _nonzero_coefficients(coeffs) == expected:
                        return "final_polynomial_form"
        elif kind == "assignments":
            values = {name: common.frac_from_dict(value) for name, value in final["values"].items()}
            observed = {}
            for fragment in fragments:
                pair = _assignment(fragment)
                if pair and pair[0] in values and pair[1] == values[pair[0]]:
                    observed[pair[0]] = pair[1]
            if observed and (not target_answer_only or len(observed) == len(values)):
                return "final_system_assignments" if len(observed) == len(values) else "partial_solution_assignment"
        elif kind == "roots":
            roots = final.get("roots", ())
            if not roots and re.search(r"无实(?:数)?根|没有实数解|无实数解|空集|∅", text):
                return "empty_root_set"
            expected = {_root_key(root) for root in roots}
            seen = set()
            variable = str(final.get("latex", "x=")).split("=", 1)[0].strip() or "x"
            for fragment in fragments:
                pair = _assignment(fragment)
                if pair and pair[0] == variable:
                    key = _root_key(common.rational_root(pair[1]))
                    if key in expected:
                        seen.add(key)
                # Symbolic surds use their server-authored exact rendering;
                # no floating-point approximation decides algebraic equality.
                for root in roots:
                    rendered = common.root_latex(root, variable)
                    if _math_key(fragment) == _math_key(rendered):
                        seen.add(_root_key(root))
                value = _scalar(fragment)
                if value is not None and (asserted or _bare_answer(text, fragment)):
                    key = _root_key(common.rational_root(value))
                    if key in expected:
                        seen.add(key)
                if not target_answer_only:
                    parsed = parse_fragment(fragment)
                    if parsed and not _original_equation(parsed, candidate):
                        actual = equation_roots(parsed)
                        if actual is not None and expected and {_root_key(root) for root in actual} == expected:
                            return "equivalent_equation"
            if seen and (not target_answer_only or seen == expected):
                return "final_answer_value"
        return None


_ANSWER_ASSERTION = re.compile(r"(?:答案|结果|解|根)(?:最后)?(?:就)?(?:是|为|等于|[:：])|最终(?:会)?(?:得到|得出)|所以(?:可得)?|answer\s*(?:is|=|:)", re.IGNORECASE)


def _answer_fragments(text):
    # LaTeX wrappers/spacing do not become mathematical variable names.
    text = re.sub(r"\\text\{[^}]*\}", "，", text)
    text = re.sub(r"\\(?:quad|qquad|left|right|,|;|!|\(|\)|\[|\])", " ", text)
    text = re.sub(r"([A-Za-z])_(?:\{\d+\}|\d+)", r"\1", text)
    return [part.strip() for part in re.findall(r"[A-Za-z0-9+*/^=().{}\\√−\-\s]+", text)
            if part.strip() and any(ch.isdigit() or ch.isalpha() for ch in part)]


def _scalar(text):
    parsed = parse_fragment(text.strip())
    if not parsed or parsed.problem_type != "arithmetic":
        return None
    try:
        value = n.evaluate(parsed.ast)
        return Fraction(value.n, value.d)
    except (n.MathDomainError, n.MathComplexityError, ValueError, ZeroDivisionError):
        return None


def _assignment(fragment):
    parts = fragment.split("=")
    if len(parts) != 2:
        return None
    for name, expression in (parts, parts[::-1]):
        name = name.strip()
        if re.fullmatch(r"[A-Za-z]", name):
            value = _scalar(expression)
            if value is not None:
                return name, value
    return None


def _bare_answer(text, fragment):
    return _math_key(text.strip(" 。.!！\n")) == _math_key(fragment)


def _math_key(text):
    text = re.sub(r"\\(?:quad|qquad|left|right|\(|\)|\[|\])", "", text)
    text = re.sub(r"√(\d+)", r"\\sqrt{\1}", text)
    return re.sub(r"\s+", "", text).replace("$", "").replace("=0+", "=").replace("=0-", "=-")


def _root_key(root):
    return json.dumps(root, sort_keys=True, separators=(",", ":"))


def _nonzero_coefficients(coefficients):
    return {key: value for key, value in coefficients.items() if value}


def _original_equation(parsed, candidate):
    if not isinstance(parsed.ast, n.Equation) or not parsed.variable or not candidate.steps:
        return False
    before = candidate.steps[0].get("before")
    if not before:
        coefficients = candidate.steps[0]
        if all(key in coefficients for key in ("a", "b", "c")):
            actual = n.equation_difference(parsed.ast, parsed.variable)
            expected = {2: common.frac_from_dict(coefficients["a"]),
                        1: common.frac_from_dict(coefficients["b"]), 0: common.frac_from_dict(coefficients["c"])}
            return actual is not None and _nonzero_coefficients(actual) == _nonzero_coefficients(expected)
        return False
    try:
        lhs, rhs = common.equation_sides(parsed.ast, parsed.variable)
        a, b = _nonzero_coefficients(lhs), _nonzero_coefficients(rhs)
        source_lhs = _nonzero_coefficients(common.coeffs_from_dict(before["lhs"]))
        source_rhs = _nonzero_coefficients(common.coeffs_from_dict(before["rhs"]))
        return (a == source_lhs and b == source_rhs) or (a == source_rhs and b == source_lhs)
    except (n.MathDomainError, ValueError, KeyError):
        return False


__all__ = [
    "ForbiddenDisclosureSet",
    "GuardedTutorUtterance",
    "TutorOutputGuard",
    "build_forbidden_set",
]
