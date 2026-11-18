"""Lossless input normalization for Tutor utterances.

This layer never decides intent, never asks for clarification, and never
interprets operator *scope*. It only rewrites equivalent *forms* so later
stages see a stable character inventory.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_UNICODE_OPERATORS = {
    "\u00d7": "*",  # ×
    "\u2715": "*",
    "\u2716": "*",
    "\u2a2f": "*",
    "\u22c5": "*",  # ⋅
    "\u00b7": "*",  # ·
    "\u2219": "*",
    "\u2022": "*",
    "\u00f7": "/",  # ÷
    "\u2215": "/",
    "\u2044": "/",
    "\u2212": "-",  # −
    "\u2013": "-",
    "\u2014": "-",
    "\uff0b": "+",
    "\uff0d": "-",
    "\uff0a": "*",
    "\uff0f": "/",
    "\uff1d": "=",
    "\uff1f": "?",
    "\uff08": "(",
    "\uff09": ")",
    "\u3000": " ",
}

_LATEX_OPERATOR_ALIASES = (
    (re.compile(r"\\times\b"), "*"),
    (re.compile(r"\\cdot\b"), "*"),
    (re.compile(r"\\div\b"), "/"),
    (re.compile(r"\\left"), ""),
    (re.compile(r"\\right"), ""),
    (re.compile(r"\\[,;!]|\\quad|\\qquad"), " "),
)

_WRAPPERS = (
    (re.compile(r"^\\\[\s*(.*?)\s*\\\]$", re.DOTALL), "latex-display-bracket"),
    (re.compile(r"^\\\(\s*(.*?)\s*\\\)$", re.DOTALL), "latex-inline-paren"),
    (re.compile(r"^\$\$\s*(.*?)\s*\$\$$", re.DOTALL), "latex-display-dollar"),
    (re.compile(r"^\$\s*(.*?)\s*\$$", re.DOTALL), "latex-inline-dollar"),
    (re.compile(r"^\[\s*(.*?)\s*\]$", re.DOTALL), "square-bracket-wrap"),
)

_INFIX_WORDS = (
    (re.compile(r"(?<=[0-9A-Za-z)\]])\s*乘以?\s*(?=[0-9A-Za-z(\\])"), "*"),
    (re.compile(r"(?<=[0-9A-Za-z)\]])\s*除以\s*(?=[0-9A-Za-z(\\])"), "/"),
    (re.compile(r"(?<=[0-9A-Za-z)\]])\s*加\s*(?=[0-9A-Za-z(\\])"), "+"),
    (re.compile(r"(?<=[0-9A-Za-z)\]])\s*减\s*(?=[0-9A-Za-z(\\])"), "-"),
)

_TRAILING_QUESTION = re.compile(r"[?？]+$")
_TRAILING_EQUALS = re.compile(r"=+\s*$")
_ARITHMETIC_QUESTION = re.compile(r"^([0-9.\s+*/^()−-]+)(?:等于几|等于多少|是多少|结果是多少)$")
_SUPERSCRIPT = re.compile(r"(?<=[0-9A-Za-z)）])[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+")
_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
_LEADING_TASK = re.compile(
    r"^(?:(?:请|帮我)?(?:计算|求解|解方程|解不等式|化简|因式分解|求根(?!号)|求值|求极限|证明|展开|求(?!根号)|解(?=\s*[0-9A-Za-z(\\]))|"
    r"(?:please\s+)?(?:solve|calculate|compute|evaluate|simplify|expand|factor)(?:\s+(?:the\s+)?(?:equation|inequality|expression))?\b)\s*", re.I
)


@dataclass(frozen=True, slots=True)
class NormalizedInput:
    raw: str
    normalized: str
    repairs: tuple[str, ...]


def normalize_input(text: str) -> NormalizedInput:
    """Return a losslessly rewritten form of ``text`` plus the repairs applied."""
    raw = str(text or "")
    powers = _SUPERSCRIPT.sub(lambda m: "^(" + m.group().translate(_SUPERSCRIPT_DIGITS) + ")", raw)
    current = "".join(character if "\u2080" <= character <= "\u209f" or character in "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻"
                      else unicodedata.normalize("NFKC", character) for character in powers).strip()
    repairs: list[str] = []
    if powers != raw:
        repairs.append("superscript-power")
    if current != raw.strip():
        repairs.append("unicode-width")

    current, wrapper_repairs = _unwrap_delimiters(current)
    repairs.extend(wrapper_repairs)

    rewritten = _rewrite_operators(current)
    if rewritten != current:
        repairs.append("operator-alias")
        current = rewritten

    if current.count("=") >= 2:
        current = re.sub(r"(?<=[^\s])\s*\n\s*(?=[^\s])", ";", current)
    compact = " ".join(current.split())
    if compact != current:
        repairs.append("whitespace")
        current = compact

    stripped = _LEADING_TASK.sub("", current).strip()
    if stripped != current:
        repairs.append("task-wrapper")
        current = stripped
    stripped = _TRAILING_QUESTION.sub("", current).strip()
    if stripped != current:
        repairs.append("trailing-question")
        current = stripped
    arithmetic_question = _ARITHMETIC_QUESTION.fullmatch(current)
    if arithmetic_question:
        current = arithmetic_question[1].strip()
        repairs.append("arithmetic-question")
    stripped = (_TRAILING_EQUALS.sub("", current).strip()
                if not re.search(r"[A-Za-z]", re.sub(r"\\(?:frac|sqrt)\b", "", current)) else current)
    if stripped != current:
        repairs.append("trailing-equals")
        current = stripped

    return NormalizedInput(raw=raw, normalized=current, repairs=tuple(dict.fromkeys(repairs)))


def _unwrap_delimiters(text: str) -> tuple[str, list[str]]:
    repairs: list[str] = []
    current = text
    changed = True
    while changed and current:
        changed = False
        for pattern, name in _WRAPPERS:
            match = pattern.fullmatch(current)
            if match:
                inner = match.group(1).strip()
                if inner:
                    current = inner
                    repairs.append(name)
                    changed = True
                    break
    return current, repairs


def _rewrite_operators(text: str) -> str:
    chars: list[str] = []
    for char in text:
        chars.append(_UNICODE_OPERATORS.get(char, char))
    current = "".join(chars)
    for pattern, replacement in _LATEX_OPERATOR_ALIASES:
        current = pattern.sub(replacement, current)
    for pattern, replacement in _INFIX_WORDS:
        current = pattern.sub(replacement, current)
    return current


def normalize_math_problem_text(text: str) -> str:
    """Compatibility wrapper used by the parser and older call sites."""
    return normalize_input(text).normalized


__all__ = ["NormalizedInput", "normalize_input", "normalize_math_problem_text"]
