"""Bounds checked before parsing recursion and exact numeric computation.

These are resource limits, not precision approximations. Accepted arithmetic
still uses exact rationals. Conservative intermediate bounds may reject an
expression whose eventual simplified result would have been small.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
from math import gcd

MAX_TOKENS = 256
MAX_PARSE_DEPTH = 64
MAX_TEXT_CHARS = 4096
MAX_LITERAL_DIGITS = 512
MAX_VALUE_BITS = 4096
MAX_EXPONENT = 4096


class MathComplexityError(Exception):
    """The expression exceeds a deterministic resource budget."""


@dataclass
class ParseBudget:
    max_tokens: int = MAX_TOKENS
    max_depth: int = MAX_PARSE_DEPTH
    max_literal_digits: int = MAX_LITERAL_DIGITS
    max_text_chars: int = MAX_TEXT_CHARS
    tokens: int = 0
    depth: int = 0

    def check_text(self, text: str) -> None:
        if len(text) > self.max_text_chars:
            raise MathComplexityError(f"输入超出长度预算（{self.max_text_chars}）")

    def token(self) -> None:
        if self.tokens >= self.max_tokens:
            raise MathComplexityError(f"输入超出记号预算（{self.max_tokens}）")
        self.tokens += 1

    def literal(self, digits: int) -> None:
        if digits > self.max_literal_digits:
            raise MathComplexityError(f"数字超出位数预算（{self.max_literal_digits}）")

    @contextmanager
    def nested(self):
        if self.depth >= self.max_depth:
            raise MathComplexityError(f"输入超出嵌套预算（{self.max_depth}）")
        self.depth += 1
        try:
            yield
        finally:
            self.depth -= 1


def check_integer(value: int) -> None:
    if value.bit_length() > MAX_VALUE_BITS:
        raise MathComplexityError(f"数值超出计算预算（{MAX_VALUE_BITS} bits）")


def check_product(left: int, right: int) -> None:
    """Bound the product before multiplying, including exact power-of-two bounds."""
    a, b = abs(left), abs(right)
    if not a or not b:
        return
    bits = a.bit_length() + b.bit_length()
    if a & (a - 1) == 0 or b & (b - 1) == 0:
        bits -= 1
    if bits > MAX_VALUE_BITS:
        raise MathComplexityError(f"乘法超出计算预算（{MAX_VALUE_BITS} bits）")


def check_power(base: int, exponent: int) -> None:
    if abs(exponent) > MAX_EXPONENT:
        raise MathComplexityError(f"指数超出计算预算（{MAX_EXPONENT}）")
    value = abs(base)
    bits = 1 if value <= 1 else (value.bit_length() - 1) * abs(exponent) + 1 if value & (value - 1) == 0 else value.bit_length() * abs(exponent)
    if bits > MAX_VALUE_BITS:
        raise MathComplexityError(f"幂运算超出计算预算（{MAX_VALUE_BITS} bits）")


def fraction_add(left: Fraction, right: Fraction) -> Fraction:
    common = gcd(left.denominator, right.denominator)
    a, b = left.denominator // common, right.denominator // common
    check_product(left.numerator, b)
    check_product(right.numerator, a)
    check_product(a, right.denominator)
    numerator = left.numerator * b + right.numerator * a
    # An addition of bounded operands can grow by at most one bit.
    check_integer(numerator)
    return Fraction(numerator, a * right.denominator)


def fraction_mul(left: Fraction, right: Fraction) -> Fraction:
    a = gcd(abs(left.numerator), right.denominator)
    b = gcd(abs(right.numerator), left.denominator)
    numerator_left, numerator_right = left.numerator // a, right.numerator // b
    denominator_left, denominator_right = left.denominator // b, right.denominator // a
    check_product(numerator_left, numerator_right)
    check_product(denominator_left, denominator_right)
    return Fraction(numerator_left * numerator_right, denominator_left * denominator_right)


def fraction_div(left: Fraction, right: Fraction) -> Fraction:
    return fraction_mul(left, Fraction(right.denominator, right.numerator))


def fraction_sub(left: Fraction, right: Fraction) -> Fraction:
    return fraction_add(left, -right)
