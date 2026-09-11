"""Clearly labelled teacher-authored error analysis, verified outside student evidence."""
from __future__ import annotations

import re
from typing import Any, Literal, Mapping
from uuid import UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict

from mathtutor.application.adaptive_practice import CandidateExercise
from mathtutor.application.practice_release import ExerciseReleaseService
from mathtutor.application.verification_backend import VerificationBackend
from mathtutor.learning.attempt_parser import parse_student_attempt
from mathtutor.learning.attempt_verifier import AttemptAssessment, Correctness
from mathtutor.solving import nodes as n
from mathtutor.solving.parser import parse_problem, normalize_math_problem_text
from mathtutor.learning.skills import (
    SKILL_ARITHMETIC, SKILL_POLYNOMIAL_BASIC, SKILL_LINEAR_EQUATION,
    SKILL_QUADRATIC_EQUATION, SKILL_LINEAR_SYSTEM, concept_for_skill,
)


class TeacherErrorExampleUnavailable(RuntimeError):
    """Never replace missing verification with a claimed teacher error."""


class TeacherErrorExample(BaseModel):
    model_config = ConfigDict(frozen=True)

    problem_text: str
    wrong_step: str
    expected_repair: str
    skill_ids: tuple[str, ...]
    reference_ids: dict[str, str]
    teacher_authored: Literal[True] = True
    instruction: str = "下面是老师故意写错的一步。请指出问题并修正；这不是你的错误记录。"


_EXAMPLES = {
    SKILL_ARITHMETIC: ("3/4+1/2", "4/6", "5/4"),
    SKILL_POLYNOMIAL_BASIC: ("(z+2)^2", "z^2+4", "z^2+4z+4"),
    SKILL_LINEAR_EQUATION: ("5z+4=39", "5z=43", "5z=35"),
    SKILL_QUADRATIC_EQUATION: ("z^2-7z+12=0", "z=2", "(z-3)*(z-4)=0"),
    SKILL_LINEAR_SYSTEM: ("u+v=8;u-v=2", "2u=6", "2u=10"),
}
_TEACHER_ID = uuid5(UUID(int=0), "mathtutor-teacher-error-example")


def assess_teacher_error_repair(
    *, example: TeacherErrorExample | Mapping[str, Any], raw_text: str,
    assessment: AttemptAssessment,
) -> AttemptAssessment:
    """A valid original-equation restatement is not a repaired teacher step.

    This is a task-completion gate AFTER independent mathematical verification,
    not another correctness authority. Missing the demonstrated operation is
    undetermined (not a fabricated mathematical error or mastery evidence).
    """
    if assessment.correctness not in {Correctness.CORRECT, Correctness.PARTIAL}:
        return assessment
    data = example.model_dump() if isinstance(example, TeacherErrorExample) else example
    skill = next(iter(data.get("skill_ids", ())), "")
    parsed = parse_problem(raw_text)
    ast = parsed.problem.ast if parsed.problem is not None else None
    repaired = False
    if skill == SKILL_ARITHMETIC:
        # A computed number/fraction repairs the mistaken fraction addition;
        # merely repeating its unevaluated expression provides no repair.
        text = re.sub(r"\s+", "", normalize_math_problem_text(raw_text))
        number = r"[+-]?\d+(?:\.\d+)?"
        repaired = bool(re.fullmatch(rf"{number}(?:/{number})?|\\frac\{{{number}\}}\{{{number}\}}", text))
    elif skill == SKILL_POLYNOMIAL_BASIC:
        # The erroneous expansion omitted a cross term. The response must
        # actually expand; repeating the factored problem is not that action.
        repaired = isinstance(ast, n.Add) and all(
            not isinstance(term, n.Pow) or isinstance(term.base, n.Var)
            for term in ast.terms
        )
    elif skill in {SKILL_LINEAR_EQUATION, SKILL_LINEAR_SYSTEM}:
        if isinstance(ast, n.Equation) and len(n.variables(ast)) == 1:
            variable = next(iter(n.variables(ast)))
            for lhs, rhs in ((ast.lhs, ast.rhs), (ast.rhs, ast.lhs)):
                coeffs = n.poly_coeffs(lhs, variable)
                if coeffs and coeffs.get(0, n.ZERO) == n.ZERO and max(coeffs) == 1 and not n.variables(rhs):
                    repaired = True
        # A complete, independently substituted system answer also repairs it.
        repaired = repaired or (skill == SKILL_LINEAR_SYSTEM and assessment.correctness is Correctness.CORRECT)
    elif skill == SKILL_QUADRATIC_EQUATION:
        if isinstance(ast, n.Equation):
            repaired = assessment.correctness is Correctness.CORRECT or any(
                isinstance(side, n.Mul) and sum(bool(n.variables(factor)) for factor in side.factors) >= 2
                for side in (ast.lhs, ast.rhs)
            ) or "missing_root" in assessment.signals
    if repaired:
        return assessment
    return assessment.model_copy(update={
        "correctness": Correctness.UNDETERMINED, "score": None,
        "verified_claims": (), "invalid_claims": (),
        "remaining_requirements": ({"requirement": "repair_teacher_step"},),
        "signals": ("teacher_step_not_repaired",),
        "reason": "当前表达式尚未修正老师标出的错误步骤；仅重述原题不算完成找错。",
    })


async def build_teacher_error_example(
    *, skill_id: str, verification_backend: VerificationBackend | None,
    release_service: ExerciseReleaseService | None = None,
) -> TeacherErrorExample:
    """One curated example, three bounded authoritative verification calls.

    With the production release service its exact snapshot remains durable.
    The attempts here are teacher-owned transient verification inputs: this
    module has no student repository, LearningCommit or evidence write path.
    """
    if verification_backend is None or skill_id not in _EXAMPLES:
        raise TeacherErrorExampleUnavailable("当前技能没有可独立验证的教师错误示例")
    statement, wrong, repair = _EXAMPLES[skill_id]
    service = release_service or ExerciseReleaseService(verification_backend=verification_backend)
    candidate = CandidateExercise(student_id=_TEACHER_ID, problem_statement=statement,
        skill_ids=(skill_id,), concept_ids=(concept_for_skill(skill_id),), difficulty=2,
        generated_by="mt-template-teacher-error-example-v1")
    try:
        released = await service.release_candidate(candidate, source_type="TEMPLATE")
        assessments = []
        for text in (wrong, repair):
            attempt = parse_student_attempt(attempt_submission_id=uuid4(), student_id=_TEACHER_ID,
                cycle_id=uuid4(), raw_text=text, attempt_index=1)
            assessments.append(await verification_backend.verify_attempt(attempt, released.problem, released.candidate))
        wrong_check, repair_check = assessments
        if wrong_check.correctness is not Correctness.INCORRECT:
            raise TeacherErrorExampleUnavailable("教师示例的错误步骤未获独立确认")
        if repair_check.correctness not in {Correctness.CORRECT, Correctness.PARTIAL}:
            raise TeacherErrorExampleUnavailable("教师示例的修正步骤未通过独立验证")
        return TeacherErrorExample(problem_text=statement, wrong_step=wrong, expected_repair=repair,
            skill_ids=(skill_id,), reference_ids={
                "problem_id": str(released.problem.problem_id),
                "exercise_release_id": str(released.release.release_id),
                "solution_candidate_id": str(released.ref.solution_candidate_id),
                "verification_log_id": str(released.ref.verification_log_id),
                "solution_payload_hash": released.ref.solution_payload_hash,
            })
    except TeacherErrorExampleUnavailable:
        raise
    except Exception as exc:
        raise TeacherErrorExampleUnavailable("教师错误示例验证暂时不可用，请改用普通引导") from exc


__all__ = ["TeacherErrorExample", "TeacherErrorExampleUnavailable", "build_teacher_error_example", "assess_teacher_error_repair"]
