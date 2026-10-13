"""Closed inequality, word, and geometry checks. Missing numbers stay unsupported."""
from uuid import uuid4

from mathtutor.domain.problem import MathProblem
from mathtutor.learning.attempt_parser import parse_student_attempt
from mathtutor.learning.attempt_verifier import verify_attempt
from mathtutor.solving.parser import parse_problem
from mathtutor.solving.solver import solve_problem
from mathtutor.solving.verifier import verify


def _verified(text):
    parsed = parse_problem(text)
    assert parsed.kind == "parsed" and parsed.problem is not None
    problem = MathProblem.canonicalize(parsed.problem.problem_type, parsed.problem.normalized_ast, parsed.problem.display_latex)
    solved = solve_problem(problem, parsed.problem)
    assert solved.kind == "solved" and solved.candidate is not None
    decision = verify(problem, solved.candidate)
    assert decision.verdict == "VERIFIED", decision
    return problem, solved.candidate


def test_linear_inequality_checks_the_range_and_rejects_the_boundary_equation():
    problem, candidate = _verified("x>3")
    assert candidate.final_answer["relation"] == "gt"
    assert candidate.final_answer["boundary"] == {"n": 3, "d": 1}
    _negative, negative_answer = _verified("-x>2")
    assert negative_answer.final_answer["relation"] == "lt"
    assert negative_answer.final_answer["boundary"] == {"n": -2, "d": 1}
    owner = uuid4()
    cycle = uuid4()

    def attempt(text):
        return parse_student_attempt(attempt_submission_id=uuid4(), student_id=owner, cycle_id=cycle, raw_text=text, attempt_index=1)

    assert verify_attempt(attempt("x>3"), problem, candidate).correctness.value == "correct"
    assert verify_attempt(attempt("3<x"), problem, candidate).correctness.value == "correct"
    wrong = verify_attempt(attempt("x=3"), problem, candidate)
    assert wrong.correctness.value == "incorrect"
    assert "漏变号" not in (wrong.reason or "")
    assert verify_attempt(attempt("x<3"), problem, candidate).correctness.value == "incorrect"


def test_numbered_word_and_geometry_use_existing_verifiers():
    cases = {
        "一个数的2倍加3等于7": "linear",
        "小明买了3支铅笔，每支2元，一共花多少元？": "arithmetic",
        "求三角形两个内角是50度和60度时的第三个角": "arithmetic",
        "长方形长为5宽为3，求周长": "arithmetic",
        "正方形边长为4的面积": "arithmetic",
        "直角三角形两条直角边分别是3和4，求斜边": "arithmetic",
    }
    for text, family in cases.items():
        parsed = parse_problem(text)
        assert parsed.kind == "parsed" and parsed.problem is not None, text
        assert parsed.problem.problem_type == family, text
        _verified(text)
    hypotenuse = parse_problem("直角三角形两条直角边分别是3和4，求斜边").problem
    assert r"\sqrt" in hypotenuse.display_latex
    for text in ("换题：小明买3支铅笔共多少钱？", "求函数y=2x+3的图像", "解含参数方程 ax^2+bx+c=0", "sin(x)=1/2"):
        assert parse_problem(text).kind != "parsed"
