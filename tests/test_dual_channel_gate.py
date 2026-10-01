"""Dual-channel gate: full merge table + real knowledge-tool integration."""
import itertools
import json

import pytest

from test_knowledge_workbench import state, seed  # noqa: F401  (fixture)
from mathtutor.application.knowledge import KnowledgeError
from mathtutor.application.knowledge_tools import KnowledgeTools
from mathtutor.domain.dual_channel_gate import (
    MathState, SourceState, Treatment, decide, evidence_kind, math_state_from_correctness)

EXPECTED = {
    SourceState.QUOTE_OK: {MathState.CORRECT: Treatment.SHOW, MathState.PARTIAL: Treatment.SHOW,
                           MathState.INCORRECT: Treatment.SHOW_SOURCE_MATH_CONFLICT,
                           MathState.UNDETERMINED: Treatment.SHOW_MATH_UNVERIFIED,
                           MathState.UNSUPPORTED: Treatment.SHOW_MATH_UNVERIFIED, MathState.NONE: Treatment.SHOW},
    SourceState.SUMMARY_OK: {MathState.CORRECT: Treatment.SHOW, MathState.PARTIAL: Treatment.SHOW,
                             MathState.INCORRECT: Treatment.DROP_MATH,
                             MathState.UNDETERMINED: Treatment.SHOW_MATH_UNVERIFIED,
                             MathState.UNSUPPORTED: Treatment.SHOW_MATH_UNVERIFIED, MathState.NONE: Treatment.SHOW},
    SourceState.NONE: {MathState.CORRECT: Treatment.SHOW, MathState.PARTIAL: Treatment.SHOW,
                       MathState.INCORRECT: Treatment.DROP_MATH,
                       MathState.UNDETERMINED: Treatment.SHOW_MATH_UNVERIFIED,
                       MathState.UNSUPPORTED: Treatment.SHOW_MATH_UNVERIFIED, MathState.NONE: Treatment.SHOW},
}


@pytest.mark.parametrize("source,math", list(itertools.product(SourceState, MathState)))
def test_merge_table_is_total_and_matches_policy(source, math):
    decision = decide(source, math)
    if source is SourceState.REJECTED:
        assert decision.treatment is Treatment.WITHHOLD and not decision.visible
    else:
        assert decision.treatment is EXPECTED[source][math]


def test_rejected_source_is_never_rescued_by_correct_math():
    assert decide(SourceState.REJECTED, MathState.CORRECT).treatment is Treatment.WITHHOLD


@pytest.mark.parametrize("verdict", ["correct", "partial", "incorrect", "undetermined"])
@pytest.mark.parametrize("level", range(6))
@pytest.mark.parametrize("diagnostic", [False, True])
def test_evidence_kind_equals_previous_inline_rule(verdict, level, diagnostic):
    legacy = ("diagnostic" if diagnostic else "ungradable" if verdict == "undetermined"
              else "post_solution" if level >= 5 else "assisted" if level else "independent")
    got = evidence_kind(math_state_from_correctness(verdict), max_assistance_level=level, diagnostic=diagnostic)
    assert got == legacy


def test_no_learning_fact_from_qa_rejected_source_or_partial_turn():
    assert evidence_kind(MathState.CORRECT, max_assistance_level=0, channel="knowledge_qa") is None
    assert evidence_kind(MathState.CORRECT, max_assistance_level=0, source=SourceState.REJECTED) is None
    assert evidence_kind(MathState.CORRECT, max_assistance_level=0, turn_status="PARTIAL") is None


async def _read(state, query):
    executor = KnowledgeTools(state, "alice", "A", generation=await state.knowledge.generation("alice"))
    found = await executor.execute("search_knowledge", {"query": query}, "s")
    hit = found["result"]["hits"][0]
    read = await executor.execute("read_source", {k: hit[k] for k in ("document_id", "version", "start", "end")}, "r")
    return executor, read["result"]


async def _seed_erratum(state):
    lib, _ = await seed(state)
    await state.knowledge.save_markdown("alice", lib["space_id"], title="例题勘误",
                                        body="# 例题\n例题：解方程 3x-5=10，得 x=3。\n", operation_id="import:erratum")


@pytest.mark.asyncio
async def test_verbatim_quote_with_wrong_math_is_kept_but_flagged(state):
    await _seed_erratum(state)
    executor, source = await _read(state, "例题")
    quote = "例题：解方程 3x-5=10，得 x=3。"
    assert quote in source["text"]
    final = {"claims": [{"text": quote, "kind": "quote", "evidence": [{"source_id": source["source_id"], "quote": quote}]}],
             "math_assertions": [{"expression": "3x-5=10", "answer": "x=3", "claim_index": 0}]}
    text = await executor.finalize(json.dumps(final, ensure_ascii=False))
    assert "来源支持 ≠ 数学正确" in text
    assert executor.gate_log[0] == {"claim_index": 0, "source": "quote_ok", "math": "incorrect",
                                    "treatment": "show_source_math_conflict"}


@pytest.mark.asyncio
async def test_summary_with_wrong_math_is_dropped_and_correct_math_labelled(state):
    await _seed_erratum(state)
    executor, source = await _read(state, "例题")

    async def supports(_):
        return True
    executor.support_checker = supports
    final = {"claims": [
        {"text": "按例题方法求得 x=3", "kind": "summary", "evidence": [{"source_id": source["source_id"], "quote": "解方程 3x-5=10"}]},
        {"text": "按例题方法求得 x=5", "kind": "summary", "evidence": [{"source_id": source["source_id"], "quote": "解方程 3x-5=10"}]}],
        "math_assertions": [{"expression": "3x-5=10", "answer": "x=3", "claim_index": 0},
                            {"expression": "3x-5=10", "answer": "x=5", "claim_index": 1}]}
    text = await executor.finalize(json.dumps(final, ensure_ascii=False))
    assert "x=3" not in text and "已移除 1 条未通过数学验证的结论" in text
    assert "数学结论已验证" in text
    assert [row["treatment"] for row in executor.gate_log] == ["drop_math", "show"]


@pytest.mark.asyncio
async def test_forged_quote_is_withheld_even_with_correct_math(state):
    await _seed_erratum(state)
    executor, source = await _read(state, "例题")
    final = {"claims": [{"text": "x=5", "kind": "quote", "evidence": [{"source_id": source["source_id"], "quote": "x=5"}]}],
             "math_assertions": [{"expression": "3x-5=10", "answer": "x=5", "claim_index": 0}]}
    with pytest.raises(KnowledgeError):
        await executor.finalize(json.dumps(final, ensure_ascii=False))
    assert executor.gate_log[0]["treatment"] == "withhold"


@pytest.mark.asyncio
async def test_standalone_math_and_unsupported_problem(state):
    await seed(state)
    executor = KnowledgeTools(state, "alice", "A", generation=await state.knowledge.generation("alice"))
    final = {"claims": [], "math_assertions": [
        {"expression": "2x+3=7", "answer": "x=2"},
        {"expression": "2x+3=7", "answer": "x=3"},
        {"expression": "sin(x)=1/2", "answer": "x=pi/6"}]}
    text = await executor.finalize(json.dumps(final, ensure_ascii=False))
    assert "2x+3=7：x=2（数学结论已验证）" in text
    assert "x=3" not in text
    assert "超出确定性验证范围" in text
    assert [row["math"] for row in executor.gate_log] == ["correct", "incorrect", "unsupported"]


# --- attempt parser: two roots written the way students write them ----------

@pytest.mark.asyncio
@pytest.mark.parametrize("answer,expected", [
    ("x=2或x=3", "correct"), ("x1=2, x2=3", "correct"), ("x=2,3", "correct"), ("x=2 or x=3", "correct"),
    ("x=2,x=4", "incorrect"), ("x=2", "partial")])
async def test_quadratic_root_forms(state, answer, expected):
    executor = KnowledgeTools(state, "alice", "A", generation=await state.knowledge.generation("alice"))
    assert (await executor.math_state("x^2-5x+6=0", answer)).value == expected


@pytest.mark.asyncio
async def test_system_answer_is_not_read_as_two_roots(state):
    executor = KnowledgeTools(state, "alice", "A", generation=await state.knowledge.generation("alice"))
    assert (await executor.math_state("x+y=5, x-y=1", "x=3, y=2")).value == "correct"


# --- output guard: phrasing-independent answer detection ---------------------

def _guarded(problem_text, utterance, level=2):
    from mathtutor.domain.problem import MathProblem
    from mathtutor.domain.tutoring import TutorAction
    from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
    from mathtutor.pedagogy.output_guard import TutorOutputGuard
    from mathtutor.pedagogy.tutor_writer import TutorWriterCandidate
    from mathtutor.solving import parse_problem, solve_problem
    parsed = parse_problem(problem_text).problem
    problem = MathProblem.canonicalize(problem_type=parsed.problem_type, normalized_ast=parsed.normalized_ast,
                                       display_latex=parsed.display_latex)
    candidate = solve_problem(problem, parsed).candidate
    return TutorOutputGuard().guard_or_fallback(
        candidate=TutorWriterCandidate(text=utterance, writer_version="test"), candidate_solution=candidate,
        disclosure=DisclosedSolutionContext(assistance_level=level),
        action=TutorAction(action="GIVE_HINT", effective_assistance_level=level, solution_visibility="hint"))


@pytest.mark.parametrize("problem,utterance", [
    ("3x-4=11", "x 应该填 5。"), ("3x-5=10", "解得x＝5。"), ("3x-4=11", "答：5"), ("3x-5=10", "未知数等于 10/2。"),
    ("x^2-5x+6=0", "x1=2，x2=3。"), ("x^2-5x+6=0", "可以写成 (x-2)(x-3)=0。"), ("x^2-5x+6=0", "两个解分别为 2、3。"),
    ("x+y=5; x-y=1", "x 与 y 分别是 3 和 2。")])
def test_guard_blocks_answer_in_any_phrasing(problem, utterance):
    assert _guarded(problem, utterance).fallback_used, utterance


@pytest.mark.parametrize("problem,utterance", [
    ("3x-5=10", "先把常数项 -5 移到等号另一边。"), ("3x-5=10", "注意 10 在等号右边。"),
    ("3x-5=10", "检查一下 x=8 是不是解？"), ("3x=15", "原方程是 3x=15，先观察系数。"),
    ("x^2-5x+6=0", "常数项是 6，想想它能分解成哪两个数的积。")])
def test_guard_keeps_clean_hints(problem, utterance):
    assert not _guarded(problem, utterance).fallback_used, utterance


def test_coverage_rule_stays_out_when_answer_equals_a_statement_constant():
    """3x-5=10 has root 5 and constant 5: a bare "5" may be the constant, so coverage abstains."""
    assert not _guarded("3x-5=10", "x 应该填 5。").fallback_used
