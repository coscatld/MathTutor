"""The fixed multi-turn evaluation passes the template tutor and catches bad models."""
from mathtutor.application.math_claims import extract_statements
from mathtutor.evaluation.tutor_multiturn import render_markdown, run
from mathtutor.pedagogy.tutor_writer import TutorWriterCandidate


def test_template_tutor_passes_the_release_gate():
    report = run("template")
    assert report["gate"]["passed"], report["gate"]["failures"]
    assert report["scenarios_passed"] == report["scenarios_total"] >= 14
    assert report["human_review"] is False
    assert "没有人工评分" in render_markdown(report)


def test_a_model_that_leaks_answers_and_miscalculates_fails_the_gate():
    class LeakyWriter:
        async def write(self, **kwargs):
            return TutorWriterCandidate(text="直接告诉你：x=5。顺便 $2+2=5$。", writer_version="leaky")

    class WrongChat:
        async def respond(self, text, **kwargs):
            return "通分以后 $\\frac{1}{2}+\\frac{1}{3}=\\frac{2}{5}$。"

    def prepare(state):
        state.controller.writer = LeakyWriter()
        state.controller.chat_responder = WrongChat()

    report = run("template", only=["linear-hint-then-correct", "free-graph-and-chat"], prepare=prepare)
    assert not report["gate"]["passed"]
    details = " ".join(c["detail"] for c in report["critical_failures"])
    assert "算式核验未通过" in details


def test_failed_cancelled_and_missing_terminals_are_hard_failures():
    from mathtutor.evaluation.tutor_multiturn import _delivery_gate, _turn_view, score, ScenarioResult

    failed = _turn_view([
        {"event_type": "assistant_error", "payload": {
            "status": "FAILED", "finish_reason": "INTERNAL_ERROR",
            "error": "这次回答未能生成，请重新同步后再试。"}},
        {"event_type": "turn_end", "payload": {}},
    ])
    failed_checks = _delivery_gate(failed, {}, "第 1 轮 send_message")
    assert any(c.critical and not c.passed for c in failed_checks)

    cancelled = _turn_view([
        {"event_type": "assistant_error", "payload": {
            "status": "CANCELLED", "finish_reason": "USER_CANCELLED", "error": "已停止生成。"}},
        {"event_type": "turn_end", "payload": {}},
    ])
    cancelled_checks = _delivery_gate(cancelled, {}, "第 1 轮 send_message")
    assert any(c.critical and not c.passed for c in cancelled_checks)
    expected_cancel = _delivery_gate(cancelled, {"status": "CANCELLED"}, "第 1 轮 send_message")
    assert all(c.passed for c in expected_cancel)

    missing = _turn_view([
        {"event_type": "assistant_complete", "payload": {"status": "COMPLETED", "final_text": "x=2"}},
    ])
    assert missing["turn_end"] is False
    missing_checks = _delivery_gate(missing, {}, "第 1 轮 send_message")
    assert any(c.critical and not c.passed for c in missing_checks)

    result = ScenarioResult("failed-only", "合成失败")
    result.checks.extend(failed_checks)
    report = score([result])
    assert not report["gate"]["passed"]
    assert report["scenarios_passed"] == 0


def test_controller_exception_without_turn_error_fails_the_gate():
    def prepare(state):
        async def boom(*args, **kwargs):
            raise RuntimeError("eval-synthetic-failure")
        state.controller.run = boom

    report = run("template", only=["linear-independent"], prepare=prepare)
    assert not report["gate"]["passed"]
    details = " ".join(c["detail"] for c in report["critical_failures"])
    assert "终态" in details
    assert "assistant_error" in details or "FAILED" in details
    math_details = " ".join(c["detail"] for s in report["scenarios"] for c in s["checks"] if c["dimension"] == "math")
    assert "算式核验通过" not in math_details


def test_quoted_student_text_and_latex_root_lists_are_not_tutor_claims():
    assert extract_statements("已验证你提交的「x=-2」不满足原方程。") == []
    assert [s.text for s in extract_statements("题目已解析并验证：x^{2} - 5x + 6 = 0")] == ["x^(2) - 5x + 6 = 0"]
    assert [s.text for s in extract_statements("\\[ z = 5 \\text{或} z = 7 \\]")] == ["z = 5 或 z = 7"]
