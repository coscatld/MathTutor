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
from mathtutor.solving.budget import MAX_TEXT_CHARS
from mathtutor.solving.parser import ParsedProblem, normalize_math_problem_text, parse_problem, stored_math_ast

AttemptAnswerKind = Literal["value", "equation", "linear_system", "empty_root_set", "root_values", "inequality", "undeterminable", "inequality_set", "inequality_relation"]

# uuid5 namespace for deterministic attempt ids: attempt_id = f(submission_id),
# so a replayed submission yields the SAME attempt identity end to end —
# the repository derives the persisted row id from the same function, keeping
# the assessment/observation/evidence foreign keys consistent.
ATTEMPT_ID_NAMESPACE = UUID("5e4f2a1b-8c3d-4e6a-9f0b-1d2c3e4f5a6b")


MAX_WORKING_LINES = 16

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
    r"|∈|≠|!=|\\ne|全体实数|任意实数|一切实数|所有实数|^\s*[Rℝ]\s*$|空集|∅", re.IGNORECASE)


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
    isolated_variable: bool | None = None

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
    carries the typed answer or a bounded sequence of numbered answers,
    including unparsed lines. No unrecognized line is discarded.
    """
    if len(raw_text) > MAX_TEXT_CHARS:
        parsed_steps = ({"kind": "unparsed", "reason": f"作答超过 {MAX_TEXT_CHARS} 个字符，请分段提交。"},)
    else:
        lines = [(number, line.strip()) for number, line in enumerate(raw_text.splitlines(), 1) if line.strip()]
        if len(lines) > MAX_WORKING_LINES:
            parsed_steps = ({"kind": "unparsed", "reason": f"一次可核验 {MAX_WORKING_LINES} 行，请分段提交。"},)
        elif len(lines) > 1 and any(re.search(r"[=＝<>≤≥]", line) for _, line in lines):
            # Keep a root list or union continued across a line break as a single answer.
            if all(re.search(r"(?:[,，;；]|或|or|∪)$", text, re.I) for _, text in lines[:-1]):
                parsed_steps = (_answer_step(raw_text.strip()),)
            else:
                parsed_steps = tuple({**_answer_step(text), "line": number} for number, text in lines)
        else:
            parsed_steps = (_answer_step(raw_text.strip()),)
    return StudentAttempt.canonicalize(
        attempt_submission_id=attempt_submission_id,
        student_id=student_id,
        cycle_id=cycle_id,
        parsed_steps=parsed_steps,
        attempt_index=attempt_index,
    )


def _isolates_variable(text: str, variable: str) -> bool:
    """Preserve the written form before canonical sums can remove variable terms."""
    sides = re.split(r"<=|>=|[=<>≤≥]", normalize_math_problem_text(text))
    if len(sides) != 2:
        return False
    left, right = sides
    for subject, value in ((left, right), (right, left)):
        subject = subject.strip()
        while subject.startswith("(") and subject.endswith(")"):
            subject = subject[1:-1].strip()
        if subject == variable and not re.search(r"[A-Za-z]", re.sub(r"\\[A-Za-z]+", "", value)):
            return True
    return False


def _answer_step(stripped: str) -> dict:
    from mathtutor.application.input_normalizer import normalize_input

    if "\n" not in stripped:
        spelling = normalize_input(stripped)
        # Square brackets are meaningful interval endpoints in an answer.
        if set(spelling.repairs) <= {"unicode-width", "operator-alias", "superscript-power", "whitespace",
                                       "latex-inline-paren", "latex-display-bracket", "latex-inline-dollar", "latex-display-dollar"}:
            stripped = spelling.normalized
    rational = r"[+-]?\d{1,18}(?:/\d{1,18})?"
    two_roots = re.fullmatch(
        rf"([a-z])(?:_?[12₁₂])?\s*=\s*({rational})\s*(?:[,，;；]|或|or)\s*(?:\1(?:_?[12₁₂])?\s*=\s*)?({rational})",
        stripped, flags=re.IGNORECASE)
    root_variable = two_roots.group(1) if two_roots else ""
    if two_roots:
        stripped = f"{two_roots.group(2)},{two_roots.group(3)}"
    if re.search(r"(?<![<>!])=", stripped) and re.search(r"(?:≠|!=|\\ne|[,，;；].*(?:[<>≤≥]))", stripped):
        return {"kind": "unparsed", "reason": "这一行带有额外定义域条件；请分开写出等式以及允许的取值范围。"}
    inequality_answer = _inequality_answer(stripped)
    if inequality_answer is not None:
        return {"kind": "answer", "parse_kind": "inequality", **inequality_answer}
    interval = stripped[:1] in {"(", "["} and "," in stripped and not re.search(r"[=<>≤≥]", stripped)
    if not two_roots and (_SET_ANSWER.search(stripped) or interval):
        if len(stripped) > 200:
            return {"kind": "unparsed", "reason": "解集写法过长，请单独提交完整区间。"}
        return {"kind": "answer", "parse_kind": "inequality_set", "text": stripped}
    if re.fullmatch(rf"{rational}\s*[,，]\s*{rational}", stripped):
        try:
            roots = [Fraction(value.strip()) for value in stripped.replace("，", ",").split(",")]
            return {"kind": "answer", "parse_kind": "root_values", "variable": root_variable,
                    "roots": [{"n": r.numerator, "d": r.denominator} for r in roots]}
        except (ValueError, ZeroDivisionError):
            return {"kind": "unparsed", "reason": "根的数值无效"}
    if stripped.lower() in EMPTY_ROOT_SET_TOKENS:
        return {"kind": "answer", "parse_kind": "empty_root_set"}
    outcome = parse_problem(stripped)
    if outcome.kind == "unsupported" and stripped.count("=") == 1:
        from mathtutor.solving.parser import parse_linear_equation_fragment
        fragment = parse_linear_equation_fragment(stripped)
        if fragment.kind == "parsed":
            outcome = fragment
    if outcome.kind != "parsed" or outcome.problem is None:
        return {"kind": "unparsed", "parse_outcome": outcome.kind, "reason": outcome.reason or "作答无法识别"}
    parsed = outcome.problem
    if parsed.relation:
        kind = "inequality_relation"
    elif isinstance(parsed.ast, n.LinearSystem):
        kind = "linear_system"
    elif isinstance(parsed.ast, n.Equation):
        kind = "equation"
    else:
        kind = "value"
    step = {"kind": "answer", "parse_kind": kind, "problem_type": parsed.problem_type,
            "normalized_ast": parsed.normalized_ast, "variable": parsed.variable, "display_latex": parsed.display_latex}
    if kind in {"equation", "inequality_relation"} and parsed.variable:
        step["isolated_variable"] = _isolates_variable(stripped, parsed.variable)
    return step


def interpret_attempt(attempt: StudentAttempt) -> ParsedAttempt:
    """Decode an attempt's ``parsed_steps`` back into a typed reading.

    This is the single decoder the verifier uses; it is inverse to
    :func:`parse_student_attempt` and fails closed on malformed steps.
    """
    steps = attempt.parsed_steps
    if not steps:
        return ParsedAttempt.undeterminable("作答没有解析步骤")
    if len(steps) != 1:
        return ParsedAttempt.undeterminable("多行作答需要逐行核验")
    return interpret_step(steps[0])


def interpret_step(step: dict) -> ParsedAttempt:
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
            return ParsedAttempt("root_values", root_values=tuple(Fraction(r["n"], r["d"]) for r in roots),
                                 answer_variable=str(step.get("variable", "")))
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
    if parse_kind not in ("value", "equation", "linear_system", "inequality_relation"):
        return ParsedAttempt.undeterminable(f"未知的解析类型: {parse_kind!r}")
    try:
        ast = n.from_dict(stored_math_ast(step["normalized_ast"]))
    except (KeyError, ValueError, TypeError) as exc:
        return ParsedAttempt.undeterminable(f"规范化答案不可回放: {exc}")
    parsed = ParsedProblem(
        problem_type=step["problem_type"],
        ast=ast,
        normalized_ast=step["normalized_ast"],
        display_latex=str(step.get("display_latex", "")),
        variable=step.get("variable"),
        relation=step["normalized_ast"].get("relation"),
    )
    return ParsedAttempt(parse_kind, parsed, isolated_variable=step.get("isolated_variable"))


__all__ = ["AttemptAnswerKind", "EMPTY_ROOT_SET_TOKENS", "ParsedAttempt", "interpret_attempt", "parse_student_attempt"]
