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


def test_quoted_student_text_and_latex_root_lists_are_not_tutor_claims():
    assert extract_statements("已验证你提交的「x=-2」不满足原方程。") == []
    assert [s.text for s in extract_statements("题目已解析并验证：x^{2} - 5x + 6 = 0")] == ["x^(2) - 5x + 6 = 0"]
    assert [s.text for s in extract_statements("\\[ z = 5 \\text{或} z = 7 \\]")] == ["z = 5 或 z = 7"]
