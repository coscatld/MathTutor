"""The fixed multi-turn evaluation passes the template tutor and catches bad models."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mathtutor.application.math_claims import extract_statements
from mathtutor.evaluation.tutor_multiturn import ScenarioResult, render_markdown, run, score
from mathtutor.pedagogy.tutor_writer import TutorWriterCandidate


def test_template_tutor_passes_the_release_gate():
    report = run("template")
    assert report["gate"]["passed"], report["gate"]["failures"]
    assert report["scenarios_passed"] == report["scenarios_total"] >= 14
    assert report["human_review"] is False
    assert report["coverage"]["scope"] == "full_suite"
    assert report["coverage"]["executed"] == report["coverage"]["available"]
    assert report["release_gate"]["passed"] is True
    assert "没有人工评分" in render_markdown(report)


def test_empty_or_unscored_results_cannot_pass_the_gate():
    empty = score([])
    assert empty["scenarios_total"] == 0
    assert not empty["gate"]["passed"]
    assert empty["gate"]["failures"]
    unscored = score([ScenarioResult("unscored", "没有执行检查")])
    assert not unscored["gate"]["passed"]
    assert unscored["scenarios_passed"] == 0


@pytest.mark.parametrize("selection", [["typo"], ["linear-independent", "typo"], []])
def test_invalid_selection_fails_before_starting_any_product_session(selection):
    def prepare(_state):
        pytest.fail("invalid selection must not create an app or invoke a model")

    with pytest.raises(ValueError, match="scenario|场景"):
        run(only=selection, prepare=prepare)


def test_a_valid_subset_records_coverage_without_passing_the_full_release_gate():
    report = run(only=["linear-independent"])
    assert report["gate"]["passed"], report["gate"]["failures"]
    assert report["coverage"]["scope"] == "subset"
    assert report["coverage"]["executed"] == report["scenarios_total"] == 1
    assert report["coverage"]["available"] >= 14
    assert report["coverage"]["selected_ids"] == ["linear-independent"]
    assert "linear-hint-then-correct" in report["coverage"]["missing_ids"]
    assert not report["release_gate"]["passed"]
    markdown = render_markdown(report)
    assert "子集回归：**通过**" in markdown
    assert "全套发布门：**未验收**" in markdown
    legacy = {key: value for key, value in report.items() if key not in {"coverage", "release_gate"}}
    legacy_markdown = render_markdown(legacy)
    assert "历史检查结果：**通过**" in legacy_markdown
    assert "全套发布门：**未验收**" in legacy_markdown


@pytest.mark.parametrize("selection", [["typo"], ["linear-independent", "typo"], []])
def test_cli_rejects_unknown_or_empty_selection_without_writing_a_green_report(tmp_path, selection):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "report"
    result = subprocess.run(
        [sys.executable, "scripts/tutor_multiturn_eval.py", "--output", str(output), "--only", *selection],
        cwd=root, env=dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(root / "src"), os.environ.get("PYTHONPATH")]))),
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 2, result.stderr
    assert ("Unknown scenario IDs" if selection else "--only: expected at least one argument") in result.stderr
    assert not output.exists()


@pytest.mark.parametrize("stdio_encoding", ["utf-8", "cp1252", "ascii"])
def test_cli_valid_subset_succeeds_and_writes_explicit_subset_coverage(tmp_path, stdio_encoding):
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/tutor_multiturn_eval.py", "--output", str(tmp_path),
         "--only", "linear-independent"],
        cwd=root, env=dict(os.environ, PYTHONIOENCODING=stdio_encoding,
                          PYTHONPATH=os.pathsep.join(filter(None, [str(root / "src"), os.environ.get("PYTHONPATH")]))),
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads((tmp_path / "tutor-multiturn-template.json").read_text(encoding="utf-8"))
    assert report["coverage"]["scope"] == "subset"
    assert report["gate"]["passed"] is True
    assert report["release_gate"]["passed"] is False
    assert "子集回归：**通过**" in result.stdout


def test_cli_unknown_chinese_id_uses_utf8_diagnostics_with_legacy_stdio(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "invalid-report"
    result = subprocess.run(
        [sys.executable, "scripts/tutor_multiturn_eval.py", "--output", str(output), "--only", "不存在"],
        cwd=root, env=dict(os.environ, PYTHONIOENCODING="cp1252",
                          PYTHONPATH=os.pathsep.join(filter(None, [str(root / "src"), os.environ.get("PYTHONPATH")]))),
        capture_output=True, timeout=30,
    )
    assert result.returncode == 2
    assert "Unknown scenario IDs: 不存在" in result.stderr.decode("utf-8")
    assert not output.exists()


@pytest.mark.parametrize("invalid", ["skill_diagnosis", "missing", "false_correction", "wrong_skills"])
def test_profile_grader_rejects_wrong_attribution_and_untraceable_corrections(invalid):
    from mathtutor.evaluation.tutor_multiturn import _profile_gate

    expected = {"misconceptions": [], "item_error_observations": [{
        "rule_id": "miscon-sign-error", "status": "corrected_later", "related_skill_ids": ["a", "b"]}]}
    profile = {"misconceptions": [], "item_error_observations": [{
        **expected["item_error_observations"][0], "event_id": "e1", "assessment_id": "a1", "cycle_id": "c1",
        "correction_event_id": "e2"}]}
    assert all(c.passed for c in _profile_gate(profile, expected))
    if invalid == "skill_diagnosis":
        profile["misconceptions"] = [{"rule_id": "miscon-sign-error", "skill_ids": ["a", "b"]}]
    elif invalid == "missing":
        profile["item_error_observations"] = []
    elif invalid == "false_correction":
        profile["item_error_observations"][0]["correction_event_id"] = None
    else:
        profile["item_error_observations"][0]["related_skill_ids"] = ["a"]
    result = ScenarioResult("profile-regression", "错误归因")
    result.checks = _profile_gate(profile, expected)
    assert result.critical_failures
    assert not score([result])["gate"]["passed"]


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
