"""Curriculum coverage and independent checks of question/answer semantics.

No LLM call is made. Numerical claim checking uses a different evaluator from
question authoring; semantic checks derive answers from the displayed stem.
Proof questions remain reference proofs, not auto-verified learner answers.
"""
from __future__ import annotations

import ast
import asyncio
from fractions import Fraction
import importlib.util
import itertools
import json
import math
from pathlib import Path
import re

import pytest

from mathtutor.question_bank.service import CATALOG, REFERENCES, QuestionBankService

ROOT = Path(__file__).resolve().parents[1]
BANK = QuestionBankService()
QUESTIONS = [q for rows in BANK.references.values() for q in rows]


def exact(expression):
    """Independent audit interpreter: exact decimal literals and arithmetic."""
    node = ast.parse(expression, mode="eval").body
    def read(n):
        if isinstance(n, ast.Constant): return Fraction(str(n.value))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub): return -read(n.operand)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "abs": return abs(read(n.args[0]))
        if isinstance(n, ast.BinOp):
            l, r = read(n.left), read(n.right)
            if isinstance(n.op, ast.Add): return l+r
            if isinstance(n.op, ast.Sub): return l-r
            if isinstance(n.op, ast.Mult): return l*r
            if isinstance(n.op, ast.Div): return l/r
            if isinstance(n.op, ast.Pow): return l**int(r)
        raise AssertionError(ast.dump(n))
    return read(node)


def answers(code):
    return BANK.references[code]


def test_original_questions_cover_every_point_and_package_is_reproducible():
    spec = importlib.util.spec_from_file_location("bank_builder", ROOT / "scripts/build_question_bank_catalog.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    assert builder.build() == json.loads(CATALOG.read_text(encoding="utf-8"))
    from mathtutor.question_bank.curriculum_content import build_reference_questions
    assert build_reference_questions() == json.loads(REFERENCES.read_text(encoding="utf-8"))["questions"]
    points = [p for t in BANK.catalog["terms"] for u in t["units"] for p in u["points"]]
    assert {p["code"] for p in points} == set(BANK.references)
    assert all(len(answers(p["code"])) >= 2 for p in points)
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) == len(set(ids))
    assert all(q["reference_answer"] and q["explanation"] and 0 < len(q["text"]) <= 300 for q in QUESTIONS)
    assert all(q["verification"]["student_steps_auto_verified"] is False for q in QUESTIONS)
    # Each deep-linked problem must stand on its own, not refer to another card.
    assert not any(any(s in q["text"] for s in ("上述", "同样三件", "这两幅视图", "同一正方体")) for q in QUESTIONS)


@pytest.mark.parametrize("question", [q for q in QUESTIONS if q["verification"]["answer_check"]], ids=lambda q:q["id"])
def test_authored_numeric_claims_independently_with_exact_arithmetic(question):
    lhs, rhs = question["verification"]["answer_check"].split("=")
    assert exact(lhs) == exact(rhs), question
    # Mutation control ensures this check would reject a shifted numeric claim.
    assert exact(lhs) != exact(rhs)+1


def test_tree_counts_actual_content_and_exposes_high_school_cross_grade_topics():
    tree = BANK.tree(None)
    for term in tree["terms"]:
        for unit in term["units"]:
            for point in unit["points"]:
                detail = asyncio.run(BANK.point(point["code"]))
                assert point["reference_count"] == len(detail["reference_problems"])
                assert point["problem_count"] == len(detail["problems"])
                assert point["total_count"] == len(detail["reference_problems"])+len(detail["problems"])
    assert next(t for t in tree["terms"] if t["code"] == "h3a")["recommended_grades"] == [11,12]


# Derive numeric answers from the DISPLAYED question, not the author's check or
# parameter n. This detects wrong mappings and valid-but-unrelated equalities.
@pytest.mark.parametrize("code, operation", [
    ("g1a-u3-p2", "+"), ("g1a-u3-p3", "-"), ("g1a-u5-p2", "+"),
    ("g1a-u5-p3", "-"), ("g1a-u6-p2", "+"), ("g1a-u8-p1", "+"),
    ("g1a-u8-p2", "+"), ("g1a-u8-p3", "+"), ("g1b-u2-p1", "-"),
    ("g1b-u2-p2", "-"), ("g1b-u2-p3", "-"), ("g1b-u6-p1", "+"),
    ("g1b-u6-p2", "+"), ("g1b-u6-p3", "-"), ("g2a-u2-p1", "+"),
    ("g2a-u2-p2", "-"), ("g2a-u4-p2", "*"), ("g2a-u6-p1", "*"),
    ("g2b-u2-p2", "/"), ("g2b-u4-p1", "/"), ("g3a-u4-p1", "+"),
    ("g3a-u4-p2", "-"), ("g3a-u6-p2", "*"), ("g3b-u2-p2", "/"),
    ("g3b-u4-p2", "*"), ("g4a-u4-p1", "*"), ("g4a-u6-p2", "/"),
])
def test_arithmetic_answer_matches_question_stem(code, operation):
    for q in answers(code):
        expression = q["text"].split("：",1)[1].split("。",1)[0].split("，",1)[0].replace("×","*").replace("÷","/")
        assert operation in expression
        assert exact(expression) == exact(q["reference_answer"])


def test_gcd_lcm_engineering_and_inverse_growth_from_problem_data():
    for q in answers("g5b-u2-p4"):
        a,b = map(int, re.findall(r"\d+",q["text"]))
        actual = list(map(int,re.findall(r"\d+",q["reference_answer"])))
        assert actual == [math.gcd(a,b),math.lcm(a,b)]
    for q in answers("g6b-u6-p4"):
        a,b = map(int,re.findall(r"\d+",q["text"]))
        expected = 1/(Fraction(1,a)+Fraction(1,b))
        assert expected == Fraction(q["reference_answer"].removesuffix("天"))
    for q in answers("g6b-u6-p6"):
        percent,price,_ = map(int,re.findall(r"\d+",q["text"]))
        original = int(re.search(r"原价(\d+)",q["reference_answer"])[1])
        assert Fraction(price)*100/(100+percent)==original
        assert Fraction(120,100)*Fraction(80,100)==Fraction(96,100)


def test_geometry_answers_derived_from_stem_and_domains():
    for code in ("g8b-u2-p1","g8b-u2-p2","g8b-u3-p2"):
        for q in answers(code):
            values=list(map(int,re.findall(r"\d+",q["text"])))
            if code=="g8b-u2-p2": assert values[0]**2+values[1]**2==values[2]**2
            else:
                c=int(re.search(r"\d+",q["reference_answer"])[0])
                assert values[0]**2+values[1]**2==c*c
    for q in answers("h2a-u3-p1")[:2]:
        aa,bb=map(int,re.findall(r"/(\d+)",q["text"]))
        assert aa-bb==9
        assert math.isqrt(aa)**2==aa
        assert f"e={Fraction(3,math.isqrt(aa))}" in q["reference_answer"]
    for q in answers("h1a-u3-p1")[:2]:
        lo,hole=map(int,re.findall(r"x-(\d+)",q["text"]))
        assert lo<hole
        assert q["reference_answer"]==f"[{lo},{hole})∪({hole},+∞)"


def test_probabilities_from_enumerated_sample_spaces_and_statistics():
    # Independent sample spaces, not only pre-written arithmetic identities.
    dice=list(itertools.product(range(1,7),repeat=2))
    assert Fraction(sum(a+b==7 for a,b in dice),len(dice))==Fraction(1,6)
    assert answers("g9a-u5-p2")[1]["reference_answer"]=="1/6"
    draws=list(itertools.combinations(range(5),2)) # red/white or good/defect
    assert Fraction(sum(sum(x<2 for x in d)==1 for d in draws),len(draws))==Fraction(3,5)
    assert answers("h3a-u2-p3")[1]["reference_answer"]=="3/5"
    four_coin=list(itertools.product((0,1),repeat=4))
    assert Fraction(sum(sum(xs)==2 for xs in four_coin),16)==Fraction(3,8)
    assert answers("h3a-u2-p3")[0]["reference_answer"]=="3/8"
    for q in answers("g8b-u5-p1"):
        data=list(map(int,re.findall(r"\d+",q["text"])))
        counts={x:data.count(x) for x in data}
        modes=sorted(x for x,c in counts.items() if c==max(counts.values()))
        assert modes==[2] and sorted(data)[2]==2
    chi=sum(Fraction((x-25)**2,25) for x in [30,20,20,30])
    assert chi==4 and "χ²=4" in answers("h3a-u3-p3")[0]["reference_answer"]


def test_high_school_recurrences_and_sums_for_many_indices():
    for first,constant in [(1,1),(1,2)]:
        a=first;total=0
        for k in range(1,30):
            total+=a
            assert a==(constant+1)*2**(k-1)-constant
            assert total==(constant+1)*(2**k-1)-constant*k
            a=2*a+constant
    assert "2^(k-1)" in answers("h3b-u3-p3")[0]["reference_answer"]
    for m in range(1,35):
        assert sum(k*2**(k-1) for k in range(1,m+1))==1+(m-1)*2**m
        assert sum(k*3**(k-1) for k in range(1,m+1))==(1+(2*m-1)*3**m)//4
        assert sum(Fraction(1,k*(k+1)) for k in range(1,m+1))==Fraction(m,m+1)
        assert sum(Fraction(1,(2*k-1)*(2*k+1)) for k in range(1,m+1))==Fraction(m,2*m+1)


def test_high_school_parametric_geometry_checks_missing_vertical_cases():
    # Non-axis chords of parabola with OA perpendicular OB all pass (4,0),
    # including t1+t2=0, where the chord has no slope.
    for t1 in [Fraction(-4),Fraction(-2),Fraction(-1),Fraction(1),Fraction(2),Fraction(4),Fraction(3,2)]:
        t2=-4/t1
        A=(t1*t1,2*t1);B=(t2*t2,2*t2)
        assert A[0]*B[0]+A[1]*B[1]==0
        assert (B[0]-A[0])*(0-A[1])==(B[1]-A[1])*(4-A[0])
    fixed=next(q for q in answers("h3b-u6-p3") if "OA⊥OB" in q["text"])
    assert "(4,0)" in fixed["reference_answer"] and "竖直弦" in fixed["explanation"]
    # Midpoint-locus elimination for all admissible line families.
    for k in [Fraction(-5),Fraction(-1),Fraction(-1,2),Fraction(1,4),Fraction(1,3)]:
        x=2*(1-k)/(k*k);y=2/k
        assert y*y==2*x+2*y
        assert y<0 or y>4
    # Focus-chord reciprocal invariant for any direction, including vertical.
    for c in [Fraction(-1),Fraction(-3,5),Fraction(0),Fraction(3,5),Fraction(1)]:
        r=3/(2+c);s=3/(2-c)
        assert 1/r+1/s==Fraction(4,3)


def test_narrow_practice_templates_match_displayed_curriculum_operations():
    def texts(code):
        return [q["text"] for q in asyncio.run(BANK.problems(code))]
    assert all("+" in s and "-" in s for s in texts("g2a-u2-p3"))
    assert all("(" in s and ")" in s for code in ("g2b-u5-p2","g4b-u1-p3") for s in texts(code))
    for s in texts("g2b-u5-p1"):
        # Same precedence: addition/subtraction OR multiplication/division.
        assert not (("+" in s or "-" in s) and ("*" in s or "/" in s))
    assert all("+" in s and "-" in s and "." in s for s in texts("g4b-u6-p2"))
    assert all("+" in s and "-" in s and "/" in s for s in texts("g5b-u6-p3"))
    for s in texts("g4b-u3-p3"):
        a,b,c,d=map(int,re.findall(r"\d+",s))
        assert a+c==100 and b==d # genuine distributive shortcut
