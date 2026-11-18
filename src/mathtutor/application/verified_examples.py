"""Bounded local computations over formulas in the current public question."""
from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass

from mathtutor.application.teaching_intent import negates_solution
from mathtutor.application.verification_backend import VerificationBackend, VerificationBackendError
from mathtutor.domain.dual_channel_gate import MathState, SourceState
from mathtutor.domain.problem import MathProblem
from mathtutor.pedagogy.disclosure import display_solution
from mathtutor.solving.budget import ParseBudget
from mathtutor.solving.parser import parse_problem
from mathtutor.solving.solver import solve_problem

MAX_EXAMPLES = 2
VERIFY_TIMEOUT = 1.0
_FAMILIES = {"arithmetic", "polynomial", "linear", "quadratic", "linear_system"}
_DELIMITED = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|\$([^$\n]+?)\$", re.S)
_CONTEXT = re.compile(
    r"[<>≤≥≠]|证明|反例|条件|设|若|如果|且|或|当|整数|正数|负数|正根|负根|自然数|非零|非负|非正|"
    r"实数|复数|有理|无理|偶数|奇数|范围|约束|满足|取值|大于|小于|多于|少于|低于|高于|超过|至少|至多|介于|之间|以上|以下|只|仅|"
    r"定义域|参数|矩阵|行列式|概率|百分|是否|对吗|声称|认为|不要|不要求|提示|不告诉|别给|"
    r"\b(?:if|when|assum\w*|given|where|or|with|subject|satisf\w*|such|real|complex|even|odd|"
    r"integer|nonzero|nonnegative|positive|negative|greater|less|larger|smaller|above|below|over|under|between|only|at least|at most|"
    r"no more than|no fewer than|not more than|not less than|exceed\w*|prove|proof|matrix|hint\w*|"
    r"determinant|probability|percent|true|false|claim\w*|wrong|without|don't)\b", re.I)
_TEX = re.compile(r"\\(?:begin\{cases\}|end\{cases\}|(?:frac|sqrt|left|right|cdot|times|div)\b)|\\\\")
_BARE = re.compile(rf"(?:{_TEX.pattern}|[0-9]+(?:\.[0-9]+)?|\.[0-9]+|"
                   r"(?<![A-Za-z_])[xyzXYZ](?![A-Za-z0-9_])|[\s+\-−*/^(){}\[\]_=;；,，×÷·²³%％!|<>√∫∑π±])+")
_PROSE_PREFIX = frozenset("about calculate compute consider evaluate expand simplify solve explain show example "
                          "expression equation does is can for of and separately independently why please equals".split())
_LIMIT = re.compile(r"(?:只|仅)(?:解释|讲解|讲|说)?(?:思路|方法)|(?:别|不要|先不)[^，,。;；\n]{0,12}(?:解出|算出)|"
                    r"\b(?:only|just)\s+explain\b[^.!?;\n]{0,24}\b(?:method|approach|strategy)\b", re.I)
_AMBIGUOUS_DIVISION = re.compile(r"/\s*(?:\d+(?:\.\d+)?|\([^()]+\))\s*(?:[xyzXYZ(]|\\left)")


@dataclass(frozen=True)
class VerifiedExample:
    span_start: int
    span_end: int
    source_text: str
    problem_type: str
    problem_latex: str
    steps: tuple[tuple[str, str], ...]
    answer_latex: str
    question_hash: str
    problem_hash: str
    candidate_hash: str
    verification_hash: str
    verification_policy: str
    source_state: SourceState = SourceState.NONE
    math_state: MathState = MathState.CORRECT


def _bare_span(question: str, match: re.Match) -> tuple[int, int] | None:
    start, end = match.span()
    while start < end and question[start] in " \t\r\n,;；，":
        start += 1
    while end > start and question[end - 1] in " \t\r\n,;；，":
        end -= 1
    if (start == end or (start and re.match(r"[A-Za-z0-9_\\.]", question[start - 1]))
            or re.match(r"[A-Za-z0-9_\\]|\.[A-Za-z0-9_]", question[end:])):
        return None
    prefix = re.search(r"(\\?[A-Za-z_][A-Za-z0-9_]*)\s*$", question[:start])
    if prefix and prefix.group(1).lower() not in _PROSE_PREFIX:
        return None
    return start, end


def _formula_spans(question: str) -> list[tuple[int, int]]:
    if len(question) > 4000 or _CONTEXT.search(question):
        return []
    spans, covered = [], []
    for match in _DELIMITED.finditer(question):
        group = next(i for i in range(1, 5) if match.group(i) is not None)
        spans.append(match.span(group))
        covered.append(match.span())
    for match in _BARE.finditer(question):
        if (not any(a < match.end() and match.start() < b for a, b in covered)
                and re.search(r"[+\-*/^=×÷·²³]|\\frac", match.group())):
            if span := _bare_span(question, match):
                spans.append(span)
    spans = sorted(spans)
    if len(spans) > MAX_EXAMPLES:
        return []
    if len(spans) == 2 and not re.search(r"分别|各自|\b(?:separately|independently)\b", question, re.I):
        return []
    accepted = []
    for start, end in spans:
        while start < end and question[start].isspace():
            start += 1
        while end > start and question[end - 1].isspace():
            end -= 1
        raw = question[start:end]
        plain = _TEX.sub("", raw)
        if (not 1 < len(raw) <= 160 or not re.search(r"[+\-*/^=×÷·²³]|\\frac", raw)
                or re.search(r"[^0-9xyzXYZ\s.+\-−*/^(){}=;；×÷·²³]", plain)
                or _AMBIGUOUS_DIVISION.search(raw.replace("÷", "/"))):
            continue
        accepted.append((start, end))
    return accepted


async def verified_examples(question: str, backend: VerificationBackend, *,
                            language: str = "zh", disclosure_allowed: bool = False) -> tuple[VerifiedExample, ...]:
    """Call only after the network guard; no source claims or learner-state writes."""
    if not disclosure_allowed or len(question) > 4000 or negates_solution(question) or _LIMIT.search(question):
        return ()
    examples = []
    deadline = asyncio.get_running_loop().time() + VERIFY_TIMEOUT
    try:
        async with asyncio.timeout(VERIFY_TIMEOUT):
            for start, end in _formula_spans(question):
                raw = question[start:end]
                parsed = parse_problem(raw, budget=ParseBudget(max_tokens=64, max_depth=12,
                                                              max_literal_digits=12, max_text_chars=160)).problem
                if parsed is None or parsed.problem_type not in _FAMILIES:
                    continue
                problem = MathProblem.canonicalize(problem_type=parsed.problem_type,
                    normalized_ast=parsed.normalized_ast, display_latex=parsed.display_latex)
                candidate = solve_problem(problem, parsed).candidate
                if candidate is None or asyncio.get_running_loop().time() >= deadline:
                    continue
                decision = await backend.verify(problem, candidate)
                if (asyncio.get_running_loop().time() >= deadline or decision.verdict != "VERIFIED"
                        or decision.problem_id != problem.problem_id
                        or decision.problem_content_hash != problem.content_hash
                        or decision.candidate_id != candidate.candidate_id
                        or decision.candidate_payload_hash != candidate.payload_hash):
                    continue
                shown = display_solution(candidate)
                steps = tuple((step["display_text"], step["display_latex"]) for step in shown["steps"])
                answer = shown["final_answer"]["display_latex"]
                if parsed.problem_type == "arithmetic":
                    steps = (("计算", f"{parsed.display_latex} = {answer}"),)
                if not answer or len(answer) > 600 or len(steps) > 12 or sum(len(a) + len(b) for a, b in steps) > 2400:
                    continue
                examples.append(VerifiedExample(start, end, raw, parsed.problem_type, parsed.display_latex,
                    steps, answer, hashlib.sha256(question.encode()).hexdigest(), problem.content_hash,
                    candidate.payload_hash, decision.payload_hash, f"{decision.policy_id}:{decision.policy_version}"))
    except (TimeoutError, VerificationBackendError):
        pass
    return tuple(examples)


def render_verified_examples(examples: tuple[VerifiedExample, ...], language: str = "zh") -> str:
    if not examples:
        return ""
    english = language == "en"
    lines = ["### MathTutor local verification" if english else "### MathTutor 本地核验",
             "The calculations below use the formulas in your question; this label covers only these calculations."
             if english else "以下计算来自当前提问中的数学式；核验范围仅限这里的计算步骤与结果。"]
    for example in examples:
        lines.extend(["", ("Compute" if english else "计算") + f"：${example.problem_latex}$"])
        for index, (text, latex) in enumerate(example.steps, 1):
            label = f"Step {index}" if english else text
            lines.append(f"{index}. {label}" + (f"：${latex}$" if latex else ""))
        lines.append(("Result" if english else "结果") + f"：${example.answer_latex}$")
    return "\n".join(lines)


__all__ = ["VerifiedExample", "verified_examples", "render_verified_examples"]
