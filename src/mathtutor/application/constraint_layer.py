"""Constraint evaluation between MathParser and Tutor.

Parser failure is not semantic ambiguity. Clarification is allowed only when
at least two reasonable readings exist, they disagree on the answer, and the
current utterance cannot disambiguate them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from mathtutor.application.input_normalizer import NormalizedInput, normalize_input
from mathtutor.solving.parser import ParseOutcome, parse_problem

_CJK = re.compile(r"[\u4e00-\u9fff]")
_CONCEPT_CARRIER = re.compile(r"(解释|为什么|为何|怎么会|如何理解|什么意思|能不能|是否可以)")
_ADVANCED_LATEX = re.compile(
    r"\\(lim|sin|cos|tan|log|ln|sum|int|infty|to|overline|begin)\b"
)
_JUXTAPOSED_NUMBER = re.compile(r"相邻的 number 与 number")
_JUXTAPOSED_VAR = re.compile(r"相邻的 var 与 var")
_RADICAL_SCOPE = re.compile(
    r"根号\s*([A-Za-z0-9]+)\s*(?:\+|加)\s*([A-Za-z0-9]+)",
    re.IGNORECASE,
)


class ConstraintStatus(StrEnum):
    PASS = "PASS"
    REPAIRED = "REPAIRED"
    SOFT_FAIL = "SOFT_FAIL"
    NEED_CLARIFICATION = "NEED_CLARIFICATION"
    HARD_FAIL = "HARD_FAIL"


@dataclass(frozen=True, slots=True)
class AmbiguousReading:
    label: str
    rendering: str


@dataclass(frozen=True, slots=True)
class ConstraintResult:
    status: ConstraintStatus
    raw_text: str
    normalized_text: str
    repairs: tuple[str, ...]
    parse: ParseOutcome | None = None
    interpretations: tuple[AmbiguousReading, ...] = ()
    clarification_prompt: str = ""
    reason: str = ""

    @property
    def solver_text(self) -> str:
        return self.normalized_text or self.raw_text


def evaluate_constraints(text: str) -> ConstraintResult:
    """Normalize → parse → decide. Never maps parser failure to clarification."""
    normalized = normalize_input(text)
    if not normalized.normalized.strip() and not str(text or "").strip():
        return ConstraintResult(
            status=ConstraintStatus.HARD_FAIL,
            raw_text=normalized.raw,
            normalized_text="",
            repairs=normalized.repairs,
            reason="empty_input",
        )

    parse = parse_problem(normalized.normalized)
    ambiguity = _semantic_ambiguity(normalized, parse)
    if ambiguity is not None:
        return ambiguity

    if parse.kind == "parsed" and parse.problem is not None:
        status = (
            ConstraintStatus.REPAIRED if normalized.repairs else ConstraintStatus.PASS
        )
        return ConstraintResult(
            status=status,
            raw_text=normalized.raw,
            normalized_text=normalized.normalized,
            repairs=normalized.repairs,
            parse=parse,
            reason="structured_parse",
        )

    if parse.kind == "unsupported" and not _soft_fail_candidate(normalized, parse):
        return ConstraintResult(
            status=ConstraintStatus.SOFT_FAIL,
            raw_text=normalized.raw,
            normalized_text=normalized.normalized,
            repairs=normalized.repairs,
            parse=parse,
            reason="unsupported_family",
        )

    if _soft_fail_candidate(normalized, parse) or parse.kind == "unparseable":
        return ConstraintResult(
            status=ConstraintStatus.SOFT_FAIL,
            raw_text=normalized.raw,
            normalized_text=normalized.normalized,
            repairs=normalized.repairs,
            parse=parse,
            reason="parser_failed",
        )

    if not normalized.normalized.strip():
        return ConstraintResult(
            status=ConstraintStatus.HARD_FAIL,
            raw_text=normalized.raw,
            normalized_text="",
            repairs=normalized.repairs,
            parse=parse,
            reason="empty_after_normalize",
        )

    return ConstraintResult(
        status=ConstraintStatus.SOFT_FAIL,
        raw_text=normalized.raw,
        normalized_text=normalized.normalized,
        repairs=normalized.repairs,
        parse=parse,
        reason=parse.reason or parse.kind,
    )


def _semantic_ambiguity(
    normalized: NormalizedInput, parse: ParseOutcome
) -> ConstraintResult | None:
    """True ambiguity: ≥2 readings, different answers, no local disambiguation."""
    source = f"{normalized.raw} {normalized.normalized}"
    radical = _RADICAL_SCOPE.search(source)
    if radical:
        inner, rest = radical.group(1), radical.group(2)
        prompt = f"这里的根号是作用于 {inner}，还是作用于 {inner}+{rest}？"
        return _clarification(
            normalized,
            parse,
            (
                AmbiguousReading(f"sqrt({inner})+{rest}", f"\\sqrt{{{inner}}}+{rest}"),
                AmbiguousReading(f"sqrt({inner}+{rest})", f"\\sqrt{{{inner}+{rest}}}"),
            ),
            prompt,
            "radical_scope",
        )

    if parse.kind != "ambiguous":
        return None

    reason = parse.reason or ""
    if _JUXTAPOSED_NUMBER.search(reason):
        left, right = _juxtaposed_operands(normalized.normalized, r"(\d+)\s+(\d+)")
        if left and right:
            prompt = f"这里的 {left} 和 {right} 是两位数 {left}{right}，还是 {left} 乘 {right}？"
            return _clarification(
                normalized,
                parse,
                (
                    AmbiguousReading("concat", f"{left}{right}"),
                    AmbiguousReading("product", f"{left}\\times{right}"),
                ),
                prompt,
                "juxtaposed_numbers",
            )
    if _JUXTAPOSED_VAR.search(reason):
        left, right = _juxtaposed_operands(normalized.normalized, r"\b([A-Za-z])\s+([A-Za-z])\b")
        if not left:
            glued = re.search(r"\b([A-Za-z])([A-Za-z])\b", normalized.normalized)
            if glued:
                left, right = glued.group(1), glued.group(2)
        if left and right:
            prompt = f"这里的 {left} 和 {right} 是相乘，还是两个不同的未知数？"
            return _clarification(
                normalized,
                parse,
                (
                    AmbiguousReading("product", f"{left}{right}"),
                    AmbiguousReading("two-variables", f"{left}, {right}"),
                ),
                prompt,
                "juxtaposed_variables",
            )
    return None


def _clarification(
    normalized: NormalizedInput,
    parse: ParseOutcome,
    interpretations: tuple[AmbiguousReading, ...],
    prompt: str,
    reason: str,
) -> ConstraintResult:
    return ConstraintResult(
        status=ConstraintStatus.NEED_CLARIFICATION,
        raw_text=normalized.raw,
        normalized_text=normalized.normalized,
        repairs=normalized.repairs,
        parse=parse,
        interpretations=interpretations,
        clarification_prompt=prompt,
        reason=reason,
    )


def _juxtaposed_operands(text: str, pattern: str) -> tuple[str, str]:
    match = re.search(pattern, text)
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def _soft_fail_candidate(normalized: NormalizedInput, parse: ParseOutcome) -> bool:
    blob = f"{normalized.raw} {normalized.normalized}"
    if parse.kind == "unsupported":
        return bool(_CONCEPT_CARRIER.search(blob) or _CJK.search(normalized.raw))
    if parse.kind == "unparseable":
        return True
    return False


__all__ = [
    "AmbiguousReading",
    "ConstraintResult",
    "ConstraintStatus",
    "evaluate_constraints",
]
