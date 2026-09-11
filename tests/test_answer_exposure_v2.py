"""Delivery exposure is based on actual math content, not disclosure numbers."""
import pytest

from mathtutor.pedagogy.output_guard import TutorOutputGuard
from mathtutor.solving import parse_problem, solve_problem
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.tutoring import TutorAction
from mathtutor.pedagogy.tutor_writer import TutorWriterCandidate
from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
from mathtutor.learning.knowledge_tracing.service import StudentStateService


def candidate(text):
    parsed = parse_problem(text).problem
    assert parsed
    problem = MathProblem.canonicalize(parsed.problem_type, parsed.normalized_ast, parsed.display_latex)
    result = solve_problem(problem, parsed).candidate
    assert result
    return result


@pytest.mark.parametrize("problem,text", [
    ("2x+3=7", "两边除以系数后 x=2。"),
    ("2x+3=7", r"答案：\(x = \frac{4}{2}\)。"),
    ("2x+3=7", "答案是2。"),
    ("3/4+1/2", r"结果为 \frac{5}{4}。"),
    ("3/4+1/2", "3/4+1/2=1.25"),
    ("2(x+1)", "合并同类项后：2x+2。"),
    ("2(x+1)", "2(x+1)=2x+2"),
    ("x^2-4=0", "x=2，x=-2"),
    ("x^2-2=0", r"根为\(x=-\sqrt{2}\text{或}x=\sqrt{2}\)。"),
    ("x^2+1=0", "因此无实数解。"),
    ("2x+y=7;x-y=2", "x=3，y=1"),
])
def test_target_answers_detected_across_all_supported_families(problem, text):
    assert TutorOutputGuard()._detect_leak(text, candidate(problem), target_answer_only=True), text


@pytest.mark.parametrize("problem,text", [
    ("2x+3=7", "原题是2x+3=7，请看系数2，需要怎么处理？"),
    ("2x+3=7", "要不要先考虑2这个系数？"),
    ("x^2-4=0", "原题是x^2-4=0，二次项系数和常数项分别是什么？"),
    ("3/4+1/2", r"原题是\(3/4+1/2\)，先考虑分母4。"),
    ("2(x+1)", "仍看原题2(x+1)，括号里的每一项要乘哪个数？"),
    ("2x+y=7;x-y=2", "原题2x+y=7，x-y=2，请观察如何消元。"),
])
def test_source_statement_and_incidental_constants_are_not_answer_exposure(problem, text):
    guard = TutorOutputGuard()
    solved = candidate(problem)
    assert guard._detect_leak(text, solved, target_answer_only=True) is None
    assert guard._detect_leak(text, solved) is None


def test_intermediate_equation_is_help_but_not_the_full_answer():
    guard = TutorOutputGuard()
    solved = candidate("2x+3=7")
    assert guard._detect_leak("现在得到2x=4", solved) == "equivalent_equation"
    assert guard._detect_leak("现在得到2x=4", solved, target_answer_only=True) is None
    assert guard._detect_leak("变形可得2-x=0", solved) == "equivalent_equation"


@pytest.mark.asyncio
async def test_l3_final_step_exposure_cannot_be_independent_evidence():
    service = await StudentStateService.create_memory()
    try:
        solved = candidate("2x+3=7")
        text = "这一小步给出 x=2，请代回检查。"
        # A nominal L3 label cannot erase content that actually exposes x.
        exposed = TutorOutputGuard()._detect_leak(text, solved, target_answer_only=True) is not None
        assert exposed
        context = dict(session_id="s", cycle_id="c", problem_id="p", problem_revision="v",
                       item_family_id="linear", skill_ids=["linear_isolation"])
        await service.record_help("alice", **context, event_id="l3-presented", help_kind="hint",
                                  target_answer_exposed=exposed, delivery_id="l3-message")
        event = await service.record_attempt("alice", **context, assessment_id="assessed", attempt_id="a", correctness="correct")
        assert event.evidence_kind == "post_solution"
        assert not event.independent_target
        guarded = TutorOutputGuard().guard_or_fallback(
            candidate=TutorWriterCandidate(text=text, writer_version="test"), candidate_solution=solved,
            disclosure=DisclosedSolutionContext(assistance_level=3),
            action=TutorAction(action="GIVE_HINT", effective_assistance_level=3, solution_visibility="hint"))
        assert guarded.fallback_used
    finally:
        await service.engine.dispose()
