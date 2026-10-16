"""Independent checks derived from question text, not author check expressions.

These regressions cover repeated roots, lost domain restrictions and tied
modes: arithmetic identities alone cannot establish those answer semantics.
"""
import json
import re
import statistics
from pathlib import Path

import sympy as sp


def questions(code):
    path = Path(__file__).parents[1] / "src/mathtutor/question_bank/curriculum_questions_v2.json"
    return json.loads(path.read_text(encoding="utf-8"))["questions"][code]


def test_statistics_answers_include_every_mode_and_the_actual_median():
    for row in questions("g8b-u5-p1"):
        values_text = re.search(r"数据(.+?)的中位数", row["text"]).group(1)
        values = [int(n) for n in re.findall(r"-?\d+", values_text)]
        answer = row["reference_answer"]
        median = int(re.search(r"中位数\s*(?:是|为)?\s*(-?\d+)", answer).group(1))
        mode_text = re.search(r"众数\s*(?:是|为)?\s*([^；。]+)", answer).group(1)
        modes = {int(n) for n in re.findall(r"-?\d+", mode_text)}
        assert median == statistics.median(values), row["id"]
        assert modes == set(statistics.multimode(values)), row["id"]


def test_equation_reference_roots_are_complete_including_repeated_root_cases():
    x = sp.Symbol("x")
    for code in ("g9a-u1-p1", "g9a-u1-p3"):
        for row in questions(code):
            expression = re.search(r"解方程：(.+?)=0", row["text"]).group(1)
            a, b, c = re.fullmatch(r"(\d*)x²-(\d+)x\+(\d+)", expression).groups()
            polynomial = (int(a) if a else 1) * x**2 - int(b) * x + int(c)
            expected = set(sp.solve(polynomial, x))
            published = {sp.Integer(n) for n in re.findall(r"x=(-?\d+)", row["reference_answer"])}
            assert published == expected, row["id"]


def test_fraction_simplification_keeps_the_original_excluded_point():
    x = sp.Symbol("x")
    for row in questions("g8a-u5-p2"):
        square, pole = map(int, re.search(r"\(x²-(\d+)\)/\(x-(\d+)\)", row["text"]).groups())
        answer = row["reference_answer"]
        result_constant = int(re.search(r"x\+(\d+)", answer).group(1))
        excluded = int(re.search(r"x≠(\d+)", answer).group(1))
        assert sp.cancel((x**2 - square) / (x - pole)) == x + result_constant
        assert excluded == pole
        assert (x - pole).subs(x, excluded) == 0
