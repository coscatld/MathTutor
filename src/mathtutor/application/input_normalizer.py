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
    (re.compile(r"(?<=[\w)\]])\s*乘以?\s*(?=[\w(\\])"), "*"),
    (re.compile(r"(?<=[\w)\]])\s*除以\s*(?=[\w(\\])"), "/"),
    (re.compile(r"(?<=[\w)\]])\s*加\s*(?=[\w(\\])"), "+"),
    (re.compile(r"(?<=[\w)\]])\s*减\s*(?=[\w(\\])"), "-"),
)

_TRAILING_QUESTION = re.compile(r"[?？]+$")
_TRAILING_EQUALS = re.compile(r"=+\s*$")
_LEADING_TASK = re.compile(
    r"^(?:请|帮我)?(?:计算|求解|解方程|化简|因式分解|求根(?!号)|求值|求极限|证明|解不等式|展开|求(?!根号))\s*"
)


@dataclass(frozen=True, slots=True)
class NormalizedInput:
    raw: str
    normalized: str
    repairs: tuple[str, ...]


def normalize_input(text: str) -> NormalizedInput:
    """Return a losslessly rewritten form of ``text`` plus the repairs applied."""
    raw = str(text or "")
    current = unicodedata.normalize("NFKC", raw).strip()
    repairs: list[str] = []
    if current != raw.strip():
        repairs.append("unicode-width")

    current, wrapper_repairs = _unwrap_delimiters(current)
    repairs.extend(wrapper_repairs)

    rewritten = _rewrite_operators(current)
    if rewritten != current:
        repairs.append("operator-alias")
        current = rewritten

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
    stripped = _TRAILING_EQUALS.sub("", current).strip()
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
