"""Structured student-attempt parsing (Phase 4 learning loop, step 1).

The student's raw answer text is parsed with the SAME deterministic grammar
as problems (:func:`mathtutor.solving.parser.parse_problem`) so
mathematically equivalent spellings normalize identically — ``x=2``,
``4/2``, ``2.0`` and ``2=x`` all become the same canonical facts; equivalence
is decided in the verifier, not by string similarity.

Parse failure NEVER raises into the flow: an unparseable or ambiguous answer
becomes an explicit ``undeterminable`` signal (recorded in the attempt's
``parsed_steps``), which the verifier turns into an UNDETERMINED assessment.

Answer kinds (``ParsedAttempt.kind``):

- ``value``          — an expression without ``=`` (arithmetic value, or a
                      polynomial expression);
- ``equation``       — a single-variable equation (linear/quadratic);
- ``empty_root_set`` — the student explicitly claimed "no (real) roots"
                      (a fixed token list; the only non-grammar recognition);
- ``undeterminable`` — unparseable / ambiguous / out-of-family answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import re
from typing import Literal
from uuid import UUID, uuid5

from mathtutor.domain.attempt import StudentAttempt
from mathtutor.solving import nodes as n
from mathtutor.solving.parser import ParsedProblem, parse_problem

AttemptAnswerKind = Literal["value", "equation", "linear_system", "empty_root_set", "root_values", "inequality", "undeterminable", "inequality_set"]

# uuid5 namespace for deterministic attempt ids: attempt_id = f(submission_id),
# so a replayed submission yields the SAME attempt identity end to end —
# the repository derives the persisted row id from the same function, keeping
# the assessment/observation/evidence foreign keys consistent.
ATTEMPT_ID_NAMESPACE = UUID("5e4f2a1b-8c3d-4e6a-9f0b-1d2c3e4f5a6b")


_ANSWER_RELATION = (
    (">=", "ge"), ("<=", "le"), ("≥", "ge"), ("≤", "le"), (">", "gt"), ("<", "lt"),
)
_ANSWER_FLIP = {">": "<", "<": ">", ">=": "<=", "<=": ">=", "≥": "≤", "≤": "≥"}


def _relation_code(symbol: str) -> str:
    return dict(_ANSWER_RELATION)[symbol]


def _inequality_answer(text: str) -> dict | None:
    """Read one range. A constant on the left is flipped so the variable stays on the left."""
    relation = r"(?:>=|<=|≥|≤|>|<)"
    number = r"[+-]?\d{1,18}(?:/\d{1,18})?"
    forward = re.fullmatch(rf"([A-Za-z])\s*({relation})\s*({number})", text)
    backward = re.fullmatch(rf"({number})\s*({relation})\s*([A-Za-z])", text)
    if forward:
        variable, symbol, raw = forward.group(1), forward.group(2), forward.group(3)
    elif backward:
        raw, symbol, variable = backward.group(1), _ANSWER_FLIP[backward.group(2)], backward.group(3)
    else:
        return None
    try:
        value = Fraction(raw)
    except (ValueError, ZeroDivisionError):
        return None
    return {
        "relation": _relation_code(symbol),
        "variable": variable.lower(),
        "boundary": {"n": value.numerator, "d": value.denominator},
    }


_SET_ANSWER = re.compile(
    r"[<>≤≥].*(?:或|or|∪|[,，;；]).*[<>≤≥]|[-\d/]\s*(?:<=|<|≤)\s*[A-Za-z]\s*(?:<=|<|≤)\s*[-\d]"
    r"|≠|!=|\\ne|全体实数|任意实数|一切实数|所有实数|^\s*[Rℝ]\s*$|空集|∅", re.IGNORECASE)


def attempt_id_for(attempt_submission_id: UUID) -> UUID:
    """Deterministic attempt id derived from the submission id (uuid5)."""
    return uuid5(ATTEMPT_ID_NAMESPACE, f"attempt:{attempt_submission_id}")

# Canonical tokens students use to claim "the equation has no real roots".
# Deterministic fixed list — never a fuzzy string match.
EMPTY_ROOT_SET_TOKENS = frozenset(
    {
        "无实数解",
        "无实根",
        "无解",
        "没有实数解",
        "没有实根",
        "no real roots",
        "no real root",
        "no real solution",
        "no solution",
    }
)


@dataclass(frozen=True, slots=True)
class ParsedAttempt:
    """Typed representation of one student answer, decoded from parsed_steps."""

    kind: AttemptAnswerKind
    parsed: ParsedProblem | None = None
    reason: str = ""
    root_values: tuple[Fraction, ...] = ()
    relation: str = ""
    boundary: Fraction | None = None
    answer_variable: str = ""
    set_text: str = ""

    @classmethod
    def undeterminable(cls, reason: str) -> "ParsedAttempt":
        return cls("undeterminable", None, reason)


def parse_student_attempt(
    *,
    attempt_submission_id: UUID,
    student_id: UUID,
    cycle_id: UUID,
    raw_text: str,
    attempt_index: int,
) -> StudentAttempt:
    """Parse one raw answer into a :class:`StudentAttempt` with typed steps.

    The raw text is always preserved on the submission; ``parsed_steps``
    carries the structured reading: either one ``{"kind": "answer", ...}``
    step (with the canonical AST and parse kind) or one
    ``{"kind": "unparsed", ...}`` step carrying the fail-closed reason.
    """
    stripped = raw_text.strip()
    rational = r"[+-]?\d{1,18}(?:/\d{1,18})?"
    # Two roots of ONE variable written the way students write them —
    # "x=2或x=3", "x1=2, x2=3", "x=2,3" — read as the bare root list. The
    # variable letter must repeat, so a system answer "x=3, y=2" is untouched.
    two_roots = re.fullmatch(
        rf"([a-z])(?:_?[12₁₂])?\s*=\s*({rational})\s*(?:[,，;；]|或|or)\s*(?:\1(?:_?[12₁₂])?\s*=\s*)?({rational})",
        stripped, flags=re.IGNORECASE)
    if two_roots:
        stripped = f"{two_roots.group(2)},{two_roots.group(3)}"
    inequality_answer = _inequality_answer(stripped)
    if inequality_answer is None and not two_roots and _SET_ANSWER.search(stripped):
        # A solution set (two-sided, between, "≠", all reals). The quadratic
        # inequality verifier reads it against the problem's own variable.
        parsed_steps = ({"kind": "answer", "parse_kind": "inequality_set", "text": stripped[:200]},)
    elif inequality_answer is not None:
        parsed_steps = ({"kind": "answer", "parse_kind": "inequality", **inequality_answer},)
    elif re.fullmatch(rf"{rational}\s*[,，]\s*{rational}", stripped):
        try:
            roots = [Fraction(value.strip()) for value in stripped.replace("，", ",").split(",")]
            parsed_steps = ({"kind": "answer", "parse_kind": "root_values",
                             "roots": [{"n": r.numerator, "d": r.denominator} for r in roots]},)
        except (ValueError, ZeroDivisionError):
            parsed_steps = ({"kind": "unparsed", "reason": "根的数值无效"},)
    elif stripped.lower() in EMPTY_ROOT_SET_TOKENS:
        parsed_steps = ({"kind": "answer", "parse_kind": "empty_root_set"},)
    else:
        outcome = parse_problem(stripped)
        if outcome.kind == "unsupported" and stripped.count("=") == 1:
            from mathtutor.solving.parser import parse_linear_equation_fragment
            fragment = parse_linear_equation_fragment(stripped)
            if fragment.kind == "parsed":
                outcome = fragment
        if outcome.kind == "parsed" and outcome.problem is not None:
            parsed_problem = outcome.problem
            parse_kind = "linear_system" if isinstance(parsed_problem.ast, n.LinearSystem) else "equation" if isinstance(parsed_problem.ast, n.Equation) else "value"
            parsed_steps = (
                {
                    "kind": "answer",
                    "parse_kind": parse_kind,
                    "problem_type": parsed_problem.problem_type,
                    "normalized_ast": parsed_problem.normalized_ast,
                    "variable": parsed_problem.variable,
                    "display_latex": parsed_problem.display_latex,
                },
            )
        else:
            parsed_steps = (
                {
                    "kind": "unparsed",
                    "parse_outcome": outcome.kind,
                    "reason": outcome.reason or "作答无法识别",
                },
            )
    return StudentAttempt.canonicalize(
        attempt_submission_id=attempt_submission_id,
        student_id=student_id,
        cycle_id=cycle_id,
        parsed_steps=parsed_steps,
        attempt_index=attempt_index,
    )


def interpret_attempt(attempt: StudentAttempt) -> ParsedAttempt:
    """Decode an attempt's ``parsed_steps`` back into a typed reading.

    This is the single decoder the verifier uses; it is inverse to
    :func:`parse_student_attempt` and fails closed on malformed steps.
    """
    steps = attempt.parsed_steps
    if not steps:
        return ParsedAttempt.undeterminable("作答没有解析步骤")
    step = steps[0]
    if not isinstance(step, dict):
        return ParsedAttempt.undeterminable("解析步骤结构不识别")
    if step.get("kind") == "unparsed":
        return ParsedAttempt.undeterminable(str(step.get("reason", "作答无法识别")))
    if step.get("kind") != "answer":
        return ParsedAttempt.undeterminable(f"未知的作答步骤: {step.get('kind')!r}")
    parse_kind = step.get("parse_kind")
    if parse_kind == "root_values":
        try:
            roots = step["roots"]
            if len(roots) != 2:
                return ParsedAttempt.undeterminable("根集格式无效")
            return ParsedAttempt("root_values", root_values=tuple(Fraction(r["n"], r["d"]) for r in roots))
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return ParsedAttempt.undeterminable("根集格式无效")
    if parse_kind == "empty_root_set":
        return ParsedAttempt("empty_root_set")
    if parse_kind == "inequality_set":
        text = step.get("text")
        if not isinstance(text, str) or not text.strip():
            return ParsedAttempt.undeterminable("解集答案格式无效")
        return ParsedAttempt("inequality_set", set_text=text)
    if parse_kind == "inequality":
        try:
            boundary = Fraction(step["boundary"]["n"], step["boundary"]["d"])
            relation = str(step["relation"])
            variable = str(step["variable"])
            if relation not in {"gt", "ge", "lt", "le"} or not variable:
                return ParsedAttempt.undeterminable("不等式答案格式无效")
            return ParsedAttempt("inequality", relation=relation, boundary=boundary, answer_variable=variable)
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            return ParsedAttempt.undeterminable("不等式答案格式无效")
    if parse_kind not in ("value", "equation", "linear_system"):
        return ParsedAttempt.undeterminable(f"未知的解析类型: {parse_kind!r}")
    try:
        ast = n.from_dict(step["normalized_ast"])
    except (KeyError, ValueError, TypeError) as exc:
        return ParsedAttempt.undeterminable(f"规范化答案不可回放: {exc}")
    parsed = ParsedProblem(
        problem_type=step["problem_type"],
        ast=ast,
        normalized_ast=step["normalized_ast"],
        display_latex=str(step.get("display_latex", "")),
        variable=step.get("variable"),
    )
    return ParsedAttempt(parse_kind, parsed)


__all__ = ["AttemptAnswerKind", "EMPTY_ROOT_SET_TOKENS", "ParsedAttempt", "interpret_attempt", "parse_student_attempt"]
