"""Keep advanced mathematical operations out of the algebra-only parser.

A polynomial inside a derivative or extremum question is the object of that
operation, not a request to simplify the polynomial.  This recognizer selects
the teaching path only; it never solves the task or certifies its answer.
"""
from __future__ import annotations

import re


_CHINESE_OPERATION = re.compile(r"求导|导数|微分|积分|极限|极值|最[大小]值|最值|单调性|驻点|拐点|凹凸性")
_ENGLISH_OPERATION = re.compile(
    r"\b(?:differentiat(?:e|ion|ing)|derivatives?|integrat(?:e|ion|ing)|integrals?|limits?|"
    r"maxima|minima|maximum|minimum|extrema|extremums?|stationary\s+points?|critical\s+points?|"
    r"turning\s+points?|monotonicity|concavity|inflection\s+points?)\b", re.I)
_MATH_CONTEXT = re.compile(
    r"[=+*/^<>∫∞]|\d|[A-Za-z][⁰¹²³⁴⁵⁶⁷⁸⁹]|\\(?:frac|sqrt|lim|sum|int)\b"
    r"|\b(?:function|polynomial|equation|expression|curve|sine|cosine|logarithm|calculus)\b"
    r"|\b(?:[xyt]|sin|cos|tan|ln|log|exp)\s*(?:\b|\()", re.I)


def requires_unstructured_math(text: str) -> bool:
    """Recognize a math operation which the structured problem AST omits."""
    source = str(text or "")
    return bool(_CHINESE_OPERATION.search(source) or
                (_ENGLISH_OPERATION.search(source) and _MATH_CONTEXT.search(source)))
