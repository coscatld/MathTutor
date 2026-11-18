from contextlib import closing
import sqlite3

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application.constraint_layer import ConstraintStatus, evaluate_constraints
from mathtutor.application.input_normalizer import normalize_input
from mathtutor.application.message_intent import ConversationIntent, classify_user_message
from mathtutor.application.network_qa import AnswerDraft, AnswerReview, MathAssertion, NetworkQA
from mathtutor.application.radical_counterexamples import solution_counterexample, source_solution_counterexample
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.application.math_verification import verify_math
from mathtutor.application.bounded_calculus import derivative_question_receipt
from mathtutor.solving.parser import parse_problem
from test_tutor_p0 import client_at, send, summary
from test_network_qa import setup, claim, review


@pytest.mark.parametrize("question,family", [
    ("2-3", "arithmetic"), ("3 加 4 等于几？", "arithmetic"), ("x-1", "polynomial"), ("2x≤4", "linear_inequality"),
    ("x²-5x+6=0", "quadratic"), ("Solve 2x+3=7", "linear"),
    ("x^2-5x+6<0", "quadratic_inequality"), ("x+y=3; x-y=1", "linear_system"),
])
def test_normal_mathematics_reaches_the_complete_supported_family(question, family):
    assert classify_user_message(question).intent is ConversationIntent.MATH_PROBLEM
    result = evaluate_constraints(question)
    assert result.status in {ConstraintStatus.PASS, ConstraintStatus.REPAIRED}
    assert result.parse.problem.problem_type == family


def test_normalization_preserves_exponents_and_does_not_complete_an_equation():
    assert normalize_input("x²-5x+6=0").normalized == "x^(2)-5x+6=0"
    assert normalize_input("(x+1)³").normalized == "(x+1)^(3)"
    assert evaluate_constraints("x₁+1=3").status is ConstraintStatus.SOFT_FAIL
    assert evaluate_constraints("x=").status is ConstraintStatus.SOFT_FAIL
    assert parse_problem("x=").kind == "unparseable"
    assert normalize_input("分数加法为什么要通分？").normalized == "分数加法为什么要通分"
    assert evaluate_constraints("7+5=").parse.problem.problem_type == "arithmetic"


@pytest.mark.parametrize("text", [
    "为什么分数加法要通分？", "什么是导数？", "为什么 x² 有两个方向的变化？", "gpt-4怎么用",
    "> /weekly 仅引用，不执行",
])
def test_open_questions_are_not_invented_as_computation_exercises(text):
    assert classify_user_message(text).intent is ConversationIntent.GENERAL_CHAT


@pytest.mark.parametrize("text", [
    "一个数的2倍加3等于7，但这个数不能为2", "长方形长为5宽为3，求面积再减去2",
    "正方形边长为4的面积，但要扣除阴影", "小明买了3支铅笔，每支2元，一共花多少元，打八折",
    "求三角形两个内角是100度和100度时的第三个角", "长方形长为0宽为3，求面积",
])
def test_word_problem_reductions_do_not_silently_drop_restrictions_or_extra_work(text):
    assert parse_problem(text).kind != "parsed"


class NoInventedAnswer:
    is_configured = True
    async def respond(self, *args, **kwargs):
        pytest.fail("The deterministic task boundary must decide before model explanation")


@pytest.mark.parametrize("question", ["2-3", "3 加 4 等于几？", "2x≤4", "x²-5x+6=0", "Solve 2x+3=7", "x+y=3; x-y=1"])
def test_real_chat_starts_verified_practice_including_high_school_stage(tmp_path, question):
    with client_at(tmp_path / "supported.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        state.learner_settings.update("high", 10)
        state.controller.chat_responder = NoInventedAnswer()
        state.controller.network_qa = NoInventedAnswer()
        send(ws, "send_message", "question", {"text": question, "network_search": True})
        current = summary(client)
        assert current["state"] == "awaiting_attempt"
        assert current["problem_context"]["lifecycle"] != "discussion"


@pytest.mark.parametrize("question,expected", [
    ("x=", "不能可靠地解析"), ("2+", "不能可靠地解析"), ("求三角形的面积", "已知条件"),
    ("x等于多少", "已知条件"), ("求x的值", "已知条件"), ("三角形的面积是多少", "已知条件"),
    ("把那道题算一下", "已知条件"),
    ("猜猜x等于多少", "不会猜测"), ("解x+y=3", "超出当前可逐步核验"),
    ("已知x>0，解x^2=9", "超出当前可逐步核验"),
    ("求∫sin(x)dx", "超出当前可逐步核验"),
    ("长方形长为5宽为3，求面积再减去2", "不能可靠地解析"),
])
def test_real_chat_does_not_guess_a_result_for_an_incomplete_or_unsupported_task(tmp_path, question, expected):
    with client_at(tmp_path / "boundary.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        state.learner_settings.update("high", 10)
        state.controller.chat_responder = NoInventedAnswer()
        frames = send(ws, "send_message", "question", {"text": question, "network_search": True})
        shown = [frame["payload"]["final_text"] for frame in frames if frame["event_type"] == "assistant_complete"]
        assert shown and expected in shown[-1]
        with closing(sqlite3.connect(tmp_path / "boundary.db")) as conn:
            assert conn.execute("SELECT count(*) FROM learning_events").fetchone()[0] == 0


@pytest.mark.parametrize("expression,answer,witness", [
    ("√x ≥ x−2", "0<x≤4", "0"), ("√(x-1) ≥ x-3", "1<x≤5", "1"),
    ("sqrt(x+2) >= x", "-2<x≤2", "-2"), ("\\sqrt{x} < x-2", "0≤x≤4", "0"),
])
async def test_radical_solution_endpoints_are_refuted_by_an_exact_counterexample(expression, answer, witness):
    result = solution_counterexample(expression, answer)
    assert result and result["witness"] == witness
    assert result["original_satisfied"] != result["answer_contains"]
    assert (await verify_math(InProcessVerificationBackend(), expression, answer)).status == "refuted"


@pytest.mark.parametrize("expression,answer,conditions", [
    ("√x ≥ x−2", "0≤x≤4", ""), ("√x ≥ x−2", "0<x≤4", "已知 x>0"),
    ("√x ≥ x−2", "0<x≤4", "只考虑整数解"), ("√x ≥ x−2", "0<x≤4", "仅考虑正数"),
    ("√x ≥ x−2", "0<x≤4", "Only positive x"), ("√x ≥ x−2", "0<x≤4", "x≠0"),
    ("√(x+a) ≥ x−2", "0<x≤4", "a>0"), ("sqrt(__import__('os'))>x", "x<4", ""),
])
def test_no_counterexample_does_not_become_a_correctness_certificate(expression, answer, conditions):
    assert solution_counterexample(expression, answer, conditions) is None


async def test_source_endpoint_failure_overrides_model_consistency_and_invalidates_dependencies():
    source = "在不等式 √x ≥ x−2 的处理中，最终 0<x≤4。"
    _, _, _, spans, refs = setup(source)
    original = claim(spans[0], text=source, conditions="定义域要求 x≥0；平方步骤只在 x−2>0 时使用。")
    consequence = claim(spans[0], claim_id="b", text="根据上一个结论继续推导。", depends_on=["a"])
    service = NetworkQA(None, InProcessVerificationBackend())
    shown, audit = await service.gate(AnswerDraft(claims=[original, consequence]),
        AnswerReview(claims=[review(), review("b")]), spans, refs)
    assert not shown and audit[0]["math"] == "incorrect"
    assert audit[0]["solution_counterexample"]["witness"] == "0"
    assert audit[0]["text"] == source and audit[0]["evidence"][0]["quote"] == spans[0].text
    assert "invalid_dependency" in audit[1]["reasons"]


async def test_declared_radical_math_keeps_the_same_explicit_domain_as_its_claim():
    source = "已知 x>0，不等式 √x ≥ x−2 最终 0<x≤4。"
    _, _, _, spans, refs = setup(source)
    proposed = claim(spans[0], text=source, conditions="已知 x>0",
                     math=[MathAssertion(expression="√x ≥ x−2", answer="0<x≤4")])
    shown, audit = await NetworkQA(None, InProcessVerificationBackend()).gate(
        AnswerDraft(claims=[proposed]), AnswerReview(claims=[review()]), spans, refs)
    assert shown and audit[0]["math_checks"][0]["status"] == "unchecked"
    assert audit[0]["math"] == "unsupported" and not audit[0]["solution_counterexample"]


def test_scoped_branch_intervals_are_not_misread_as_a_global_solution_set():
    assert source_solution_counterexample("当 x>2 时，√x ≥ x−2 这一分支解得 2<x≤4。") is None
    assert source_solution_counterexample("已知 x>0，不等式 √x ≥ x−2 最终 0<x≤4。") is None
    assert source_solution_counterexample("不等式 √x ≥ x−2，错误地说最终 0<x≤4。") is None
    assert source_solution_counterexample("不等式 √x ≥ x−2，最终 0<x≤4 是错误的。") is None
    assert source_solution_counterexample("For inequality sqrt(x)>=x-2, the incorrect solution set is 0<x≤4.") is None
    assert source_solution_counterexample("For inequality sqrt(x)>=x-2, the solution set is 0<x≤4 is wrong.") is None


@pytest.mark.parametrize("text,answer", [
    ("对 (x+1)³ 求导", "(3)+(6)*x^1+(3)*x^2"),
    ("Find the derivative of 3*x^4-x/2.", "(-1/2)+(12)*x^3"),
    ("derivative(3,t)", "0"),
])
def test_existing_polynomial_derivative_capability_is_available_without_model_selection(text, answer):
    receipt = derivative_question_receipt(text)
    assert receipt and receipt["answer"] == answer and receipt["scope"] == "polynomial_derivative"


@pytest.mark.parametrize("text", [
    "Find the derivative of sin(x).", "对 x^13 求导", "对 1/x 求导", "对 a*x 求导",
    "对 x^2 求导并找出最小值", "derivative(__import__('os'),x)",
])
def test_derivative_receipts_do_not_certify_a_larger_or_unsupported_request(text):
    assert derivative_question_receipt(text) is None


def test_unsupported_notebook_cannot_bypass_the_boundary_by_requesting_a_complete_solution(tmp_path):
    with client_at(tmp_path / "unsupported-notebook.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().controller.chat_responder = NoInventedAnswer()
        send(ws, "send_message", "original", {"text": "求∫sin(x)dx"})
        current = summary(client)
        assert current["problem_context"]["display_text"] == "求∫sin(x)dx"
        assert not next(action for action in current["allowed_actions"] if action["command"] == "request_solution")["enabled"]
        for command, payload in (("request_solution", {}), ("send_message", {"text": "请给出完整答案"})):
            frames = send(ws, command, command, payload)
            text = next(frame["payload"]["final_text"] for frame in frames if frame["event_type"] == "assistant_complete")
            assert "尚无可核验的完整解答" in text
