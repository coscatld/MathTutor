"""T06: intentional examples are labelled teacher-authored, never student mistakes."""
from uuid import uuid4

import pytest

from mathtutor.application.practice_release import ExerciseReleaseService
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.learning.attempt_parser import parse_student_attempt
from mathtutor.learning.attempt_verifier import Correctness
from mathtutor.learning.skills import all_skill_ids
from mathtutor.pedagogy.error_example import build_teacher_error_example, TeacherErrorExampleUnavailable, assess_teacher_error_repair


@pytest.mark.asyncio
@pytest.mark.parametrize("skill", all_skill_ids())
async def test_teacher_error_and_repair_are_independently_verified(skill):
    backend = InProcessVerificationBackend()
    service = ExerciseReleaseService(verification_backend=backend)
    example = await build_teacher_error_example(skill_id=skill, verification_backend=backend, release_service=service)
    assert example.teacher_authored and "故意" in example.instruction and "不是你的错误" in example.instruction
    release = await service.repository.load_release(example.reference_ids["exercise_release_id"])
    assert release is not None
    problem, candidate, ref = await service.repository.load_exact_verified(release)
    assert str(ref.verification_log_id) == example.reference_ids["verification_log_id"]
    for text, allowed in [(example.wrong_step, {Correctness.INCORRECT}),
                          (example.expected_repair, {Correctness.CORRECT, Correctness.PARTIAL})]:
        attempt = parse_student_attempt(attempt_submission_id=uuid4(), student_id=uuid4(), cycle_id=uuid4(), raw_text=text, attempt_index=1)
        assert (await backend.verify_attempt(attempt, problem, candidate)).correctness in allowed
    assert await service.repository.offers_for_student("student-a") == []
    assert not any("assessment" in event["event_type"] or "evidence" in event["event_type"] for event in await service.repository.list_outbox())


@pytest.mark.asyncio
async def test_no_verifier_means_no_error_example():
    with pytest.raises(TeacherErrorExampleUnavailable):
        await build_teacher_error_example(skill_id="LINEAR_EQUATION", verification_backend=None)


@pytest.mark.asyncio
async def test_unsupported_skill_means_no_error_example():
    with pytest.raises(TeacherErrorExampleUnavailable):
        await build_teacher_error_example(skill_id="UNSUPPORTED", verification_backend=InProcessVerificationBackend())


@pytest.mark.asyncio
async def test_unconfirmed_wrong_or_unverified_repair_is_rejected():
    class WrongAuthority(InProcessVerificationBackend):
        async def verify_attempt(self, *args):
            result = await super().verify_attempt(*args)
            return result.model_copy(update={"correctness": Correctness.UNDETERMINED})
    with pytest.raises(TeacherErrorExampleUnavailable):
        await build_teacher_error_example(skill_id="LINEAR_EQUATION", verification_backend=WrongAuthority())


@pytest.mark.asyncio
@pytest.mark.parametrize("skill", all_skill_ids())
async def test_restating_original_task_is_not_repair_but_verified_repair_is(skill):
    backend = InProcessVerificationBackend()
    service = ExerciseReleaseService(verification_backend=backend)
    example = await build_teacher_error_example(skill_id=skill, verification_backend=backend, release_service=service)
    release = await service.repository.load_release(example.reference_ids["exercise_release_id"])
    problem, candidate, _ = await service.repository.load_exact_verified(release)
    for raw_text, expected in ((example.problem_text, False), (example.expected_repair, True)):
        attempt = parse_student_attempt(attempt_submission_id=uuid4(), student_id=uuid4(), cycle_id=uuid4(), raw_text=raw_text, attempt_index=1)
        math_result = await backend.verify_attempt(attempt, problem, candidate)
        checked = assess_teacher_error_repair(example=example, raw_text=raw_text, assessment=math_result)
        assert (checked.correctness in {Correctness.CORRECT, Correctness.PARTIAL}) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("text,expected", [("39=4+5z", False), ("10z+8=78", False),
    ("35=5z", True), ("z=7", True), ("10z=70", True), ("5z=43", False)])
async def test_linear_error_repair_requires_the_transposition_operation(text, expected):
    backend = InProcessVerificationBackend()
    service = ExerciseReleaseService(verification_backend=backend)
    example = await build_teacher_error_example(skill_id="LINEAR_EQUATION", verification_backend=backend, release_service=service)
    release = await service.repository.load_release(example.reference_ids["exercise_release_id"])
    problem, candidate, _ = await service.repository.load_exact_verified(release)
    attempt = parse_student_attempt(attempt_submission_id=uuid4(), student_id=uuid4(), cycle_id=uuid4(), raw_text=text, attempt_index=1)
    checked = assess_teacher_error_repair(example=example, raw_text=text, assessment=await backend.verify_attempt(attempt, problem, candidate))
    assert (checked.correctness in {Correctness.CORRECT, Correctness.PARTIAL}) is expected


def test_error_example_works_with_production_sqlite_and_worker(tmp_path):
    from functools import partial
    from test_tutor_p0 import client_at
    from mathtutor.api.product_state import get_product_state
    with client_at(tmp_path / "teacher-example.db") as client:
        state = get_product_state()
        # The controller first builds its ordinary analogy using this same
        # statement. Releasing it must reuse that canonical problem UUID.
        first = client.portal.call(state.controller.service.submit_problem, "5z+4=39")
        example = client.portal.call(partial(build_teacher_error_example,
            skill_id="LINEAR_EQUATION", verification_backend=state.exercise_release.verification_backend,
            release_service=state.exercise_release))
        assert example.teacher_authored
        assert example.reference_ids["problem_id"] == str(first.problem.problem_id)
