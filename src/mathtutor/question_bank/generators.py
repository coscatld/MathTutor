"""Deterministic practice generators for the question bank.

Each (family, template) yields problem texts the existing parser accepts.
The seed comes from the knowledge-point code, so ``<code>-<n>`` always names
the same problem. The service keeps only problems the verifier accepts.
"""
from __future__ import annotations

import hashlib
import random
from fractions import Fraction
from typing import Callable

Generator = Callable[[random.Random], tuple[str, int]]


def _rng(code: str, template: str) -> random.Random:
    digest = hashlib.sha256(f"{code}:{template}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def _signed(value: int) -> str:
    return f"+{value}" if value >= 0 else str(value)


def _frac(value: Fraction) -> str:
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


# --- arithmetic -------------------------------------------------------------

def add_within_10(r):
    a = r.randint(1, 8); b = r.randint(1, 10 - a)
    return (f"{a}+{b}", 1) if r.random() < .5 else (f"{a + b}-{b}", 1)

def add_within_20(r):
    a = r.randint(5, 9); b = r.randint(10 - a + 1, 9)
    return (f"{a}+{b}", 1) if r.random() < .5 else (f"{a + b}-{b}", 2)

def add_within_100(r):
    a = r.randint(12, 68); b = r.randint(11, 99 - a)
    return (f"{a}+{b}", 1) if r.random() < .5 else (f"{a + b}-{a}", 2)

def add_within_10000(r):
    a = r.randint(120, 4800); b = r.randint(110, 4900)
    return (f"{a}+{b}", 2) if r.random() < .5 else (f"{a + b}-{a}", 2)

def times_table(r):
    a = r.randint(2, 9); b = r.randint(2, 9)
    return (f"{a}*{b}", 1) if r.random() < .5 else (f"{a * b}/{a}", 1)

def mul_one_digit(r):
    return f"{r.randint(12, 999)}*{r.randint(2, 9)}", 2

def mul_two_digit(r):
    return f"{r.randint(11, 99)}*{r.randint(11, 99)}", 2

def mul_three_by_two(r):
    return f"{r.randint(101, 999)}*{r.randint(11, 99)}", 3

def div_one_digit(r):
    d = r.randint(2, 9); q = r.randint(12, 199)
    return f"{d * q}/{d}", 2

def div_two_digit(r):
    d = r.randint(11, 49); q = r.randint(3, 60)
    return f"{d * q}/{d}", 3

def mixed_operations(r):
    a, b, c = r.randint(2, 30), r.randint(2, 9), r.randint(2, 9)
    form = r.choice([f"{a}+{b}*{c}", f"({a}+{b})*{c}", f"{a * c}/{c}-{b}", f"{a}-{b}+{c}*{b}"])
    return form, 2

def decimal_add(r):
    a = Fraction(r.randint(11, 999), 10); b = Fraction(r.randint(11, 999), 100)
    return (f"{float(a):g}+{float(b):g}", 2) if r.random() < .5 else (f"{float(a + b):g}-{float(b):g}", 2)

def decimal_mul(r):
    return f"{r.randint(11, 99) / 10:g}*{r.randint(2, 19) / 10:g}", 2

def decimal_div(r):
    d = r.randint(2, 9) / 10; q = r.randint(11, 99) / 10
    return f"{round(d * q, 2):g}/{d:g}", 3

def fraction_add_same_den(r):
    d = r.randint(3, 12); a = r.randint(1, d - 1); b = r.randint(1, d - 1)
    return (f"{a}/{d}+{b}/{d}", 1) if r.random() < .5 else (f"{max(a, b)}/{d}-{min(a, b)}/{d}", 1)

def fraction_add_diff_den(r):
    d1, d2 = r.sample([2, 3, 4, 5, 6, 8, 9, 10, 12], 2)
    return f"{r.randint(1, d1 - 1)}/{d1}+{r.randint(1, d2 - 1)}/{d2}", 2

def fraction_mul(r):
    d1, d2 = r.sample([2, 3, 4, 5, 6, 7, 8, 9], 2)
    return f"{r.randint(1, d1 - 1)}/{d1}*{r.randint(1, d2 - 1)}/{d2}", 2

def fraction_div(r):
    d1, d2 = r.sample([2, 3, 4, 5, 6, 7, 8, 9], 2)
    return f"({r.randint(1, d1 - 1)}/{d1})/({r.randint(1, d2 - 1)}/{d2})", 3

def negative_numbers(r):
    a, b = r.randint(-20, 20), r.randint(-20, 20)
    op = r.choice(["+", "-", "*"])
    return f"({a}){op}({b})", 2

def rational_mixed(r):
    a, b, c = r.randint(-9, 9), r.randint(2, 6), r.randint(-9, 9)
    return f"({a})*{b}-({c})/{r.choice([1, 2, 3])}", 3


# --- polynomial ---------------------------------------------------------------

def combine_like_terms(r):
    v = r.choice("xyab")
    a, b, c, d = (r.randint(-9, 9) or 1 for _ in range(4))
    return f"{a}{v}{_signed(b)}+{c}{v}{_signed(d)}".replace("+-", "-"), 1

def expand_brackets(r):
    v = r.choice("xa")
    a, b, c = r.randint(2, 6), r.randint(-9, 9) or 1, r.randint(-9, 9) or 2
    return f"{a}({v}{_signed(b)}){_signed(c)}{v}", 2

def multiply_binomials(r):
    a, b = r.randint(-9, 9) or 1, r.randint(-9, 9) or 2
    return f"(x{_signed(a)})(x{_signed(b)})", 2

def square_of_binomial(r):
    a = r.randint(1, 9) * r.choice([1, -1])
    return f"(x{_signed(a)})^2", 2


# --- equations and inequalities ----------------------------------------------------

def one_step(r):
    x = r.randint(-9, 12); a = r.randint(2, 9)
    return (f"{a}x={a * x}", 1) if r.random() < .5 else (f"x{_signed(a)}={x + a}", 1)

def two_step(r):
    x = r.randint(-9, 12); a = r.randint(2, 9); b = r.randint(-15, 15) or 3
    return f"{a}x{_signed(b)}={a * x + b}", 1

def move_terms(r):
    x = r.randint(-9, 12); a, c = r.sample(range(2, 10), 2); b = r.randint(-12, 12)
    return f"{a}x{_signed(b)}={c}x{_signed((a - c) * x + b)}", 2

def brackets(r):
    x = r.randint(-6, 9); a = r.randint(2, 5); b = r.randint(-6, 6) or 1; c = r.randint(1, 9)
    return f"{a}(x{_signed(b)})={a * (x + b)}", 2 if c else 2

def fractions_linear(r):
    x = r.randint(-6, 9) * 6; a = r.choice([2, 3, 6]); b = r.randint(1, 9)
    return f"x/{a}{_signed(b)}={_frac(Fraction(x, a) + b)}", 3

def simple_equation(r):
    x = r.randint(2, 30); a = r.randint(2, 9); b = r.randint(1, 30)
    return f"{a}x+{b}={a * x + b}", 1

def ineq_one_step(r):
    a = r.randint(2, 9); b = r.randint(-9, 9); c = r.randint(-9, 20)
    return f"{a}x{_signed(b)}{r.choice(['>', '<', '>=', '<='])}{c}", 1

def ineq_flip_sign(r):
    a = r.randint(2, 9); b = r.randint(-9, 9); c = r.randint(-9, 20)
    return f"-{a}x{_signed(b)}{r.choice(['>', '<', '>=', '<='])}{c}", 2

def quad_factorable(r):
    p, q = r.sample(range(-9, 10), 2)
    return f"x^2{_signed(-(p + q))}x{_signed(p * q)}=0".replace("+0x", "").replace("-0x", ""), 2

def quad_complete_square(r):
    p = r.randint(-6, 6) or 2; k = r.choice([1, 4, 9, 16, 25])
    return f"(x{_signed(p)})^2={k}", 2

def quad_no_real_root(r):
    a = r.randint(1, 5); b = r.randint(1, 4) * 2
    return f"x^2+{b}x+{b * b // 4 + a}=0", 3

def quad_leading(r):
    a = r.randint(2, 4); p, q = r.sample(range(-5, 6), 2)
    return f"{a}x^2{_signed(-a * (p + q))}x{_signed(a * p * q)}=0".replace("+0x", "").replace("-0x", ""), 3

def qineq_outside(r):
    p, q = sorted(r.sample(range(-6, 7), 2))
    return f"x^2{_signed(-(p + q))}x{_signed(p * q)}{r.choice(['>', '>='])}0".replace("+0x", "").replace("-0x", ""), 2

def qineq_between(r):
    p, q = sorted(r.sample(range(-6, 7), 2))
    return f"x^2{_signed(-(p + q))}x{_signed(p * q)}{r.choice(['<', '<='])}0".replace("+0x", "").replace("-0x", ""), 2

def qineq_perfect_square(r):
    p = r.randint(-5, 5) or 1
    return f"x^2{_signed(-2 * p)}x+{p * p}{r.choice(['>', '<=', '<', '>='])}0", 3

def system_elimination(r):
    x, y = r.randint(-6, 8), r.randint(-6, 8); a, b = r.randint(1, 5), r.randint(1, 5)
    return f"{a}x+{b}y={a * x + b * y};x-y={x - y}", 2

def system_substitution(r):
    x, y = r.randint(-6, 8), r.randint(-6, 8); k = r.randint(2, 5)
    return f"y={k}x{_signed(y - k * x)};x+y={x + y}", 2


GENERATORS: dict[tuple[str, str], Generator] = {
    ("arithmetic", "add_within_10"): add_within_10, ("arithmetic", "add_within_20"): add_within_20,
    ("arithmetic", "add_within_100"): add_within_100, ("arithmetic", "add_within_10000"): add_within_10000,
    ("arithmetic", "times_table"): times_table, ("arithmetic", "mul_one_digit"): mul_one_digit,
    ("arithmetic", "mul_two_digit"): mul_two_digit, ("arithmetic", "mul_three_by_two"): mul_three_by_two,
    ("arithmetic", "div_one_digit"): div_one_digit, ("arithmetic", "div_two_digit"): div_two_digit,
    ("arithmetic", "mixed_operations"): mixed_operations, ("arithmetic", "decimal_add"): decimal_add,
    ("arithmetic", "decimal_mul"): decimal_mul, ("arithmetic", "decimal_div"): decimal_div,
    ("arithmetic", "fraction_add_same_den"): fraction_add_same_den,
    ("arithmetic", "fraction_add_diff_den"): fraction_add_diff_den,
    ("arithmetic", "fraction_mul"): fraction_mul, ("arithmetic", "fraction_div"): fraction_div,
    ("arithmetic", "negative_numbers"): negative_numbers, ("arithmetic", "rational_mixed"): rational_mixed,
    ("polynomial", "combine_like_terms"): combine_like_terms, ("polynomial", "expand_brackets"): expand_brackets,
    ("polynomial", "multiply_binomials"): multiply_binomials, ("polynomial", "square_of_binomial"): square_of_binomial,
    ("linear", "one_step"): one_step, ("linear", "two_step"): two_step, ("linear", "move_terms"): move_terms,
    ("linear", "brackets"): brackets, ("linear", "fractions"): fractions_linear,
    ("linear", "simple_equation"): simple_equation,
    ("linear_inequality", "one_step"): ineq_one_step, ("linear_inequality", "flip_sign"): ineq_flip_sign,
    ("quadratic", "factorable"): quad_factorable, ("quadratic", "complete_square"): quad_complete_square,
    ("quadratic", "no_real_root"): quad_no_real_root, ("quadratic", "leading_coefficient"): quad_leading,
    ("quadratic_inequality", "two_roots_outside"): qineq_outside,
    ("quadratic_inequality", "two_roots_between"): qineq_between,
    ("quadratic_inequality", "perfect_square"): qineq_perfect_square,
    ("linear_system", "elimination"): system_elimination, ("linear_system", "substitution"): system_substitution,
}


def tidy(text: str) -> str:
    """Write problems the way a textbook would: no ``+0`` terms, no ``1x``."""
    import re
    text = re.sub(r"[+-]0(?=[=<>;)]|$)", "", text)
    text = re.sub(r"(?<![\d./^])1(?=[a-z])", "", text)
    return text.replace("+-", "-").replace("--", "+")


def generate(code: str, family: str, template: str, count: int) -> list[tuple[str, int]]:
    """Up to ``count`` distinct candidate (text, difficulty) pairs, deterministic per point."""
    make = GENERATORS[(family, template)]
    rng, seen, out = _rng(code, template), set(), []
    for _ in range(count * 6):
        text, difficulty = make(rng)
        text = tidy(text)
        if text not in seen:
            seen.add(text)
            out.append((text, difficulty))
        if len(out) >= count:
            break
    return out


__all__ = ["GENERATORS", "generate"]
