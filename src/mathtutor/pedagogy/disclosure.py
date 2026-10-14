"""SolutionDisclosureProjector — L0-L5 capability minimization (Phase 3B).

The projector is a DATA boundary, not a prompt boundary: the writer NEVER
sees the full solution and is "told not to leak". The projected context
structurally cannot contain what the level does not allow:

    L0  writer sees nothing solution-related
    L1  concept hint only (names, definitions — no target steps)
    L2  strategy hint only (method direction — no concrete results)
    L3  exactly one approved next step
    L4  the approved step prefix
    L5  the complete verified solution

The projector consumes a VERIFIED candidate's content; callers must have
obtained it through the attested ref (fail closed if the ref is missing).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.domain.solution import MathSolutionCandidate, VerifiedSolutionRef
from mathtutor.domain.tutoring import TutorAction
from mathtutor.pedagogy.exceptions import DisclosurePolicyViolation


def _fraction_latex(payload: dict[str, Any]) -> str:
    numerator = int(payload["n"])
    denominator = int(payload["d"])
    return str(numerator) if denominator == 1 else f"\\frac{{{numerator}}}{{{denominator}}}"


def _display_step(step: dict[str, Any], index: int, variable: str) -> dict[str, str]:
    """Minimize one verifier step to student-facing presentation fields.

    This is a one-way projection: transforms, coefficient payloads and AST
    dictionaries stay inside the verified candidate and never reach the L5
    writer.  Presentation failure falls back to the server-authored label,
    never to ``repr(step)``.
    """
    text = str(step.get("label") or f"第 {index} 步")
    latex = ""
    try:
        from mathtutor.solving import nodes as n
        from mathtutor.solving.strategies import _common as c

        if "expr" in step and "value" in step:
            latex = f"{n.to_latex(n.from_dict(step['expr']))} = {_fraction_latex(step['value'])}"
        elif "after" in step:
            after = step["after"]
            lhs = n.poly_to_latex(c.coeffs_from_dict(after["lhs"]), variable)
            rhs = n.poly_to_latex(c.coeffs_from_dict(after["rhs"]), variable)
            latex = f"{lhs} = {rhs}"
        elif "expr" in step and "coeffs" in step:
            latex = n.poly_to_latex(c.coeffs_from_dict(step["coeffs"]), variable)
        elif "discriminant" in step:
            latex = f"\\Delta = {_fraction_latex(step['discriminant'])}"
        elif "roots" in step:
            roots = list(step.get("roots") or ())
            latex = " \\text{或} ".join(c.root_latex(root, variable) for root in roots)
            if not roots:
                latex = "\\text{无实数解}"
        elif step.get("kind") == "eliminate":
            row = step["result_row"]
            latex = f"{_fraction_latex(row[0])}{step['variable']} = {_fraction_latex(row[2])}"
        elif step.get("kind") == "solve_variable":
            latex = f"{step['variable']} = {_fraction_latex(step['value'])}"
        elif step.get("kind") == "back_substitution":
            latex = f"{_fraction_latex(step['coefficient'])}{step['variable']} = {_fraction_latex(step['rhs'])}"
        elif step.get("kind") == "substitution":
            latex = r",\quad ".join(f"{name}={_fraction_latex(value)}" for name, value in step["values"].items())
    except (KeyError, TypeError, ValueError):
        latex = ""
    return {"display_text": text, "display_latex": latex}


def _display_final_answer(answer: dict[str, Any]) -> dict[str, str]:
    latex = str(answer.get("latex") or "")
    return {"display_text": "最终答案", "display_latex": latex}


class DisclosedSolutionContext(BaseModel):
    """Everything the writer is allowed to see for one action (§7.2)."""

    model_config = ConfigDict(frozen=True)

    assistance_level: Literal[0, 1, 2, 3, 4, 5]
    concept_hint: str | None = None
    strategy_hint: str | None = None
    approved_step: dict[str, Any] | None = None
    approved_prefix: tuple[dict[str, Any], ...] = ()
    full_solution: dict[str, Any] | None = None


class SolutionDisclosureProjector:
    """Deterministic projection from a verified solution to an allowed view."""

    def project(
        self,
        verified_ref: VerifiedSolutionRef | None,
        candidate: MathSolutionCandidate | None,
        action: TutorAction,
        *,
        concept_hint: str = "",
        strategy_hint: str = "",
    ) -> DisclosedSolutionContext:
        """Project the candidate to exactly what ``action`` permits.

        Fail closed: any level that needs solution content (L3+) without a
        verified ref raises instead of silently projecting nothing.
        """
        level = action.effective_assistance_level

        if level == 0:
            return DisclosedSolutionContext(assistance_level=0)

        if level == 1:
            return DisclosedSolutionContext(
                assistance_level=1,
                concept_hint=concept_hint or None,
            )

        if level == 2:
            return DisclosedSolutionContext(
                assistance_level=2,
                strategy_hint=strategy_hint or None,
            )

        # L3+: solution content is required — the verified chain must exist.
        if verified_ref is None or candidate is None:
            raise DisclosurePolicyViolation(
                f"level {level} requires a verified solution reference"
            )

        steps = candidate.steps

        if level == 3:
            index = min(action.target_step_index or 0, max(len(steps) - 1, 0))
            return DisclosedSolutionContext(
                assistance_level=3,
                approved_step=steps[index] if steps else None,
            )

        if level == 4:
            cut = min(len(steps), action.target_step_index + 1 if action.target_step_index else len(steps) - 1)
            cut = max(cut, 1)
            return DisclosedSolutionContext(
                assistance_level=4,
                approved_prefix=steps[:cut],
            )

        if level == 5:
            final_answer = dict(candidate.final_answer)
            variable = str(final_answer.get("var") or final_answer.get("variable") or "")
            if not variable:
                # Equation answer LaTeX is server-authored (e.g. ``y = 2``).
                # Recover only its identifier for display; ``x`` is the safe
                # MVP fallback for arithmetic/no-variable answers.
                prefix = str(final_answer.get("latex") or "").split("=", 1)[0].strip()
                variable = prefix if prefix.isidentifier() else "x"
            return DisclosedSolutionContext(
                assistance_level=5,
                full_solution={
                    "steps": [
                        _display_step(dict(step), index, variable)
                        for index, step in enumerate(steps, 1)
                    ],
                    "final_answer": _display_final_answer(final_answer),
                },
            )

        raise DisclosurePolicyViolation(f"unknown assistance level {level}")


__all__ = [
    "DisclosedSolutionContext",
    "DisclosurePolicyViolation",
    "SolutionDisclosureProjector",
]
