"""Check the mathematical statements inside model-written explanations.

Every checkable formula goes through the shared ``verify_math`` core:

- an equality without variables (``3×4+2 = 14``) is arithmetic;
- an equality that holds for every value (``(x+1)^2 = x^2+2x+1``) is an
  identity;
- any other equation or inequality is a derivation step, checked for the same
  solution set as the anchor: the bound problem when there is one, otherwise
  the first equation of the explanation (a premise, not a claim).

Prose is never verified here. The result decides the notice shown above the
text and marks each refuted formula in place.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from mathtutor.application.math_verification import MathCheck, verify_math
from mathtutor.application.problem_recovery import UNVERIFIED_NOTICE

logger = logging.getLogger(__name__)

MAX_CLAIMS = 40
_DERIVATION_TYPES = {"linear", "quadratic", "linear_system", "linear_inequality", "quadratic_inequality"}

_LATEX_SPAN = re.compile(r"\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|\$([^$\n]+?)\$", re.S)
_PLAIN_SPAN = re.compile(r"[0-9A-Za-z(（][0-9A-Za-z\s+\-−*/^(){}（）.=<>≤≥×÷·²³]*(?:=|<|>|≤|≥)[0-9A-Za-z\s+\-−*/^(){}（）.=<>≤≥×÷·²³]*[0-9A-Za-z)}）²³]")
_QUOTED = re.compile(r"「[^」]*」")
_ARROWS = re.compile(r"\\Rightarrow|\\implies|\\Longrightarrow|\\to|⇒|→|∴|\\therefore|\\quad|;|；|,\s|，(?![^=<>]*或)")
_NEW_EXAMPLE = re.compile(r"例如|比如|举个例子|再看|另一个|换一道|类似地")
_RELATION = re.compile(r"<=|>=|≤|≥|<|>")
_IDENTITY_CUE = re.compile(r"展开|化简|因式分解|分解因式|公式|恒等|合并同类项|配方")
_ROOT = re.compile(r"^\s*([A-Za-z])\s*=\s*([-+]?\d+(?:[./]\d+)?)\s*$")
_ROOT_JOIN = re.compile(r"^\s*(?:或|或者|or|，|,|和|及)\s*$")
_FUNCTION_VALUE = re.compile(r"[fghFGH]\s*\(")
_DERIVATION_CUE = re.compile(r"得到|得出|得(?=\s*$)|所以|因此|因而|故|解得|化为|可得|两边|移项|除以|同乘|等价|推出|代入|整理|⇒|\\Rightarrow|\\implies")
_INDEPENDENT_CUE = re.compile(r"端点|分界|边界|定义域|分别|第一[支段]|第二[支段]|候选|令|设|已知")


@dataclass(frozen=True)
class Statement:
    text: str          # normalized for the parser
    shown: str         # the span as it appeared
    end: int           # offset in the source text, for in-place marks
    new_example: bool  # an explicit "for example" cue precedes it
    identity_cue: bool = False  # "expand / simplify / factor" precedes it
    derivation_cue: bool = False
    independent_cue: bool = False


@dataclass
class Certification:
    verified: int = 0
    unchecked: int = 0
    refuted: list[tuple[Statement, str]] = field(default_factory=list)

    @property
    def checked_any(self) -> bool:
        return bool(self.verified or self.refuted)

    def counts(self) -> dict[str, int]:
        return {"verified": self.verified, "unchecked": self.unchecked, "refuted": len(self.refuted)}


def _normalize(span: str) -> str:
    text = span
    for old, new in {"\\left": "", "\\right": "", "\\cdot": "*", "\\times": "*", "\\div": "/", "×": "*", "·": "*",
                     "÷": "/", "−": "-", "（": "(", "）": ")", "²": "^2", "³": "^3", "\\le": "<=", "\\ge": ">=",
                     "\\leq": "<=", "\\geq": ">=", "≤": "<=", "≥": ">=", "\\,": "", "\\!": "", "\\;": ""}.items():
        text = text.replace(old, new)
    text = re.sub(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}", r"((\1)/(\2))", text)
    text = re.sub(r"\^\{([^{}]*)\}", r"^(\1)", text)
    text = re.sub(r"\\text\{\s*(或|or)\s*\}", r"或", text)
    text = re.sub(r"\\text\{[^{}]*\}|\\mathrm\{[^{}]*\}", "", text)
    text = text.replace("{", "(").replace("}", ")")
    return " ".join(text.split()).strip(" .。")


def extract_statements(text: str) -> list[Statement]:
    """Formulas with a relation, in reading order, split at arrows and commas.

    Text in 「」 quotes the student and is not the tutor's claim.
    """
    text = _QUOTED.sub(lambda m: " " * len(m.group(0)), text)
    spans: list[tuple[int, int, str]] = []
    for match in _LATEX_SPAN.finditer(text):
        spans.append((match.start(), match.end(), next(g for g in match.groups() if g is not None)))
    covered = [(a, b) for a, b, _ in spans]
    for match in _PLAIN_SPAN.finditer(text):
        if any(a <= match.start() < b for a, b in covered):
            continue
        body = match.group(0)
        if re.search(r"[A-Za-z]{2,}", body):  # English words, not single-letter variables
            continue
        spans.append((match.start(), match.end(), body))
    spans = _merge_root_lists(sorted(spans), text)
    statements: list[Statement] = []
    previous_end = 0
    for start, end, body in spans:
        # Cues count only between the previous formula and this one.
        prefix = text[max(previous_end, start - 30):start]
        cue, identity_cue = bool(_NEW_EXAMPLE.search(prefix)), bool(_IDENTITY_CUE.search(prefix))
        previous_end = end
        for index, part in enumerate(_ARROWS.split(body)):
            normalized = _normalize(part)
            if not normalized or not re.search(r"=|<|>", normalized) or "\\" in normalized:
                continue
            statements.append(Statement(normalized, part.strip(), end, cue and index == 0, identity_cue and index == 0,
                bool(_DERIVATION_CUE.search(prefix)) or index > 0, bool(_INDEPENDENT_CUE.search(prefix))))
    return statements[:MAX_CLAIMS]


def _merge_root_lists(spans, text):
    """``$x=2$ 或 $x=3$`` states one root set, not two separate answers."""
    merged: list[tuple[int, int, str]] = []
    for start, end, body in spans:
        if merged:
            last_start, last_end, last_body = merged[-1]
            previous = re.split(r"或|，|,", last_body)[-1]
            a, b = _ROOT.match(_normalize(previous)), _ROOT.match(_normalize(body))
            if a and b and a.group(1) == b.group(1) and _ROOT_JOIN.match(text[last_end:start]):
                merged[-1] = (last_start, end, f"{last_body}或{body}")
                continue
        merged.append((start, end, body))
    return merged


def anchor_for(problem) -> tuple[str, str] | None:
    """The bound problem as a derivation anchor the parser can read."""
    if problem is None or problem.problem_type not in _DERIVATION_TYPES:
        return None
    latex = problem.display_latex
    return problem.problem_type, latex if problem.problem_type == "linear_system" else _normalize(latex)


def _has_variable(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text))


async def _identity(backend, left: str, right: str) -> MathCheck:
    return await verify_math(backend, left, right)


async def certify(text: str, backend, *, anchor: tuple[str, str] | None = None) -> Certification:
    """Verify every checkable statement. ``anchor`` is (problem_type, solver text)."""
    result = Certification()
    chain_anchor = anchor[1] if anchor and anchor[0] in _DERIVATION_TYPES else None
    variables = set(re.findall(r"[A-Za-z]", chain_anchor or ""))
    contextual_math = anchor is None and bool(re.search(r"函数|零点|定义域|分段|参数|[fghFGH]\s*(?:\\!?\s*)?\(", text))
    for statement in extract_statements(text):
        source = statement.text
        if _FUNCTION_VALUE.search(source):
            # A function value is not implicit multiplication by its argument.
            result.unchecked += 1
            continue
        relation = _RELATION.search(source)
        root_list = "或" in source
        if not relation and not root_list and source.count("=") >= 2:
            parts = [p.strip() for p in source.split("=")]
            if any(not p for p in parts):
                result.unchecked += 1
                continue
            # x = 7-3 = 4: an equation x = 4 plus arithmetic 7-3 = 4.
            tail = parts[1:]
            for left, right in zip(tail, tail[1:]):
                await _record(result, statement, await _identity(backend, left, right), "这两边并不相等")
            source = f"{parts[0]}={parts[-1]}"
        if not relation and not root_list:
            left, right = (p.strip() for p in source.split("=", 1))
            if not _has_variable(source):
                await _record(result, statement, await _identity(backend, left, right), "计算结果不对")
                continue
            identity = await _identity(backend, left, right)
            if identity.status == "verified":
                result.verified += 1
                continue
            if statement.identity_cue and _has_variable(left) and _has_variable(right):
                # "Expand / simplify / factor" claims equality for every value.
                await _record(result, statement, identity, "两边不是恒等的")
                continue
        # A derivation step: same solution set as the anchor.
        own = set(re.findall(r"[A-Za-z]", source))
        if contextual_math:
            # Function discussions mix definitions, domains, sample points,
            # candidates and conclusions. There is no reliable single
            # equation anchor for them; only identities/arithmetic above
            # are machine-checkable without a bound exercise.
            result.unchecked += 1
            continue
        if chain_anchor is None or statement.new_example or statement.independent_cue or (variables and not own <= variables):
            chain_anchor, variables = source, own  # a premise starts a new chain
            result.unchecked += 1
            continue
        if anchor is None and not statement.derivation_cue:
            # Distinct endpoint values and branch conditions are not an
            # assertion of equivalence between their solution sets.
            chain_anchor, variables = source, own
            result.unchecked += 1
            continue
        check = await verify_math(backend, chain_anchor, source)
        reason = "漏掉了解" if "missing_root" in check.signals else "和前面的方程（不等式）不等价"
        await _record(result, statement, check, reason)
    if result.refuted:
        logger.info("math_claims refuted=%d verified=%d unchecked=%d",
                    len(result.refuted), result.verified, result.unchecked)
    return result


async def _record(result: Certification, statement: Statement, check: MathCheck, reason: str) -> None:
    if check.status == "verified":
        result.verified += 1
    elif check.status == "refuted":
        result.refuted.append((statement, reason))
    else:
        result.unchecked += 1


VERIFIED_NOTICE = "> 本段讲解中的 {n} 处算式已由本地验证器逐一核对；文字说明未经核验。"
PARTIAL_NOTICE = "> 本段讲解未经逐句数学核验。其中 {n} 处算式已由本地验证器核对，{m} 处无法自动核对。"
REFUTED_NOTICE = "> ⚠️ 本段讲解中有 {k} 处算式没有通过本地验证器核对，已在原处标出，请不要照抄。"
_NOTICE_PREFIX = re.compile(r"^> (?:本段讲解|⚠️ 本段讲解)[^\n]*\n\n")


def strip_notice(text: str) -> str:
    return _NOTICE_PREFIX.sub("", text, count=1)


def notice_for(result: Certification) -> str:
    if result.refuted:
        return REFUTED_NOTICE.format(k=len(result.refuted))
    if result.verified and not result.unchecked:
        return VERIFIED_NOTICE.format(n=result.verified)
    if result.verified:
        return PARTIAL_NOTICE.format(n=result.verified, m=result.unchecked)
    return UNVERIFIED_NOTICE


def annotate(text: str, result: Certification) -> str:
    """Put the notice on top and a mark right after each refuted formula."""
    body = strip_notice(text)
    offset = len(text) - len(body)
    marks: dict[int, list[str]] = {}
    for statement, reason in result.refuted:
        marks.setdefault(statement.end - offset, []).append(f"「{statement.shown}」{reason}")
    for end in sorted(marks, reverse=True):
        if 0 <= end <= len(body):
            body = body[:end] + f"（⚠️ 核验未通过：{'；'.join(marks[end])}）" + body[end:]
    return f"{notice_for(result)}\n\n{body}"


_SENTENCE_END = re.compile(r"[。！？!?；;\n]")


class VerifiedPreview:
    """Release streamed text one complete sentence at a time.

    A prefix is shown only when its math delimiters are closed and every
    formula in it passes ``certify``. The first refuted prefix stops the
    preview; the full answer then goes through the normal check and repair,
    and the final message replaces whatever was shown.
    """

    def __init__(self, backend, emit, *, anchor: tuple[str, str] | None = None):
        self.backend, self.emit, self.anchor = backend, emit, anchor
        self.released = ""
        self.stopped = False

    async def __call__(self, text: str) -> None:
        from mathtutor.application.tutor_runtime import _unfinished_surface
        if self.stopped:
            return
        ends = [m.end() for m in _SENTENCE_END.finditer(text)]
        candidate = next((text[:end] for end in reversed(ends) if not _unfinished_surface(text[:end].rstrip())), "")
        if len(candidate.strip()) <= len(self.released.strip()):
            return
        result = await certify(candidate, self.backend, anchor=self.anchor)
        if result.refuted:
            self.stopped = True
            return
        self.released = candidate
        await self.emit(candidate.rstrip())


def repair_request(result: Certification) -> str:
    items = "；".join(f"「{statement.shown}」{reason}" for statement, reason in result.refuted)
    return (f"你上一条回答里有算式没有通过本地验证器核对：{items}。请改正这些算式后重新完整回答原问题。"
            "只输出改正后的回答，不要提到核对过程。")


async def certify_and_annotate(text: str, backend, *, anchor: tuple[str, str] | None = None,
                               regenerate=None) -> tuple[str, Certification]:
    """Check, and on a refuted formula ask the model once to correct itself.

    ``regenerate(feedback) -> str`` makes one extra model call. The corrected
    text is kept only if it has fewer refuted formulas; anything still wrong
    is marked in place. The turn gets exactly one extra step for the repair,
    and a failed repair call leaves the turn as it was.
    """
    from mathtutor.application.tutor_runtime import current_turn, note_turn

    body = strip_notice(text)
    result = await certify(body, backend, anchor=anchor)
    if result.refuted and regenerate is not None:
        turn = current_turn.get()
        saved = (turn.finish_reason, turn.status, turn.final_text, turn.error_code) if turn else None
        if turn is not None:
            turn.max_steps = max(turn.max_steps, turn.steps_used) + 1
        try:
            corrected = strip_notice(await regenerate(repair_request(result)) or "")
        except Exception:
            logger.warning("math_claims repair call failed")
            corrected = ""
        retried = await certify(corrected, backend, anchor=anchor) if corrected.strip() else None
        improved = retried is not None and len(retried.refuted) < len(result.refuted)
        note_turn(repair={"attempted": 1, "succeeded": int(improved and not retried.refuted)})
        if improved:
            body, result = corrected, retried
        elif turn is not None and saved:
            turn.finish_reason, turn.status, turn.final_text, turn.error_code = saved
    note_turn(formulas=result.counts())
    return annotate(body, result), result


__all__ = ["Certification", "Statement", "VerifiedPreview", "anchor_for", "annotate", "repair_request", "certify", "certify_and_annotate", "extract_statements",
           "notice_for", "strip_notice"]
