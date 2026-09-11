"""Purpose, bounded candidate selection, provenance and independent offer lifecycle."""
import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from mathtutor.application.adaptive_practice import AdaptivePracticeService, CandidateExercise, practice_context_from_assembled
from mathtutor.application.llm_candidate_generator import PracticeGeneratorChain, TemplateCandidateExerciseGenerator, candidate_is_distinct
from mathtutor.application.practice_policy import resolve_practice_purpose, select_difficulty
from mathtutor.application.practice_release import ExerciseReleaseService, PracticeOfferError, ReleaseDeniedError
from mathtutor.domain.practice_context import AttemptSummaryEntry
from mathtutor.domain.practice_recommendation import PracticeRecommendation
from mathtutor.infrastructure.schema import metadata
from mathtutor.repositories.practice_repository import InMemoryPracticeRepository
from mathtutor.repositories.sqlite_practice import SQLitePracticeRepository
from mathtutor.repositories.sqlite_store import SQLiteSessionStore
from mathtutor.repositories.uow import MathTutorUow
from mathtutor.security.scopes import student_uuid
from test_adaptive_practice import _assembled

OWNER = "student-a"


class Assembler:
    async def assemble(self, **kwargs):
        return _assembled().model_copy(update={"student_id": student_uuid(kwargs["student_id"])})


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def stack(request, tmp_path):
    engine = None
    if request.param == "sqlite":
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'practice.db'}")
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        repo = SQLitePracticeRepository(MathTutorUow(engine))
        parent = (await SQLiteSessionStore(engine).create(str(student_uuid(OWNER)), "practice-v2")).cycle.cycle_id
    else:
        repo, parent = InMemoryPracticeRepository(), uuid4()
    service = AdaptivePracticeService(assembler=Assembler(), generator=PracticeGeneratorChain(),
                                      release_service=ExerciseReleaseService(repository=repo))
    yield repo, service, parent
    if engine:
        await engine.dispose()


@pytest.mark.parametrize("level,expected", [(0, "A1"), (1, "A2"), (4, "A2"), (5, "B")])
def test_completion_purpose_is_based_on_exposure(level, expected):
    assert resolve_practice_purpose("A1", full_task_completed=True, exposure_level=level) == expected


@pytest.mark.parametrize("purpose,kwargs", [("A1", {}), ("A2", {}), ("B", {}), ("C", {}), ("E", {})])
def test_no_fabricated_completion_or_review(purpose, kwargs):
    with pytest.raises(ValueError):
        resolve_practice_purpose(purpose, full_task_completed=False, exposure_level=0, **kwargs)


def test_voluntary_practice_does_not_require_solved_or_assistance():
    assert resolve_practice_purpose("D", full_task_completed=False, exposure_level=0) == "D"


def test_only_cross_problem_independent_success_can_raise_difficulty():
    base = practice_context_from_assembled(_assembled(), target_skill_ids=("LINEAR_EQUATION",))
    def evidence(problem, level=0):
        return AttemptSummaryEntry(skill_id="LINEAR_EQUATION", correctness="correct", effective_assistance_level=level,
                                   attempt_index=1, problem_id=problem)
    for entries in ((evidence("same"),) * 5, tuple(evidence(str(n), 2) for n in range(5)), (evidence(""),) * 5):
        assert select_difficulty(base.model_copy(update={"recent_attempt_summary": entries}), purpose="A1")[0] == 2
    ctx = base.model_copy(update={"recent_attempt_summary": tuple(evidence(str(n)) for n in range(3))})
    assert select_difficulty(ctx, purpose="A1")[0] == 3
    assert select_difficulty(ctx, purpose="A2")[0] == 2
    assert select_difficulty(ctx, purpose="B")[0] == 2


@pytest.mark.asyncio
async def test_repeated_same_purpose_has_one_actionable_offer(stack):
    repo, service, parent = stack
    kwargs = dict(parent_cycle_id=parent, target_skill_ids=("LINEAR_EQUATION",), problem_text="2x+3=7", target_revision="r1")
    first = await service.prepare_offer(OWNER, **kwargs)
    second = await service.prepare_offer(OWNER, **kwargs)
    assert first.offer_id == second.offer_id
    assert len(await repo.offers_for_student(OWNER)) == 1
    record = (await repo.recommendations_for_student(OWNER, parent))[0]
    assert record.status == "ACTIVE" and record.purpose == "D"
    assert await repo.recommendations_for_student("different-owner") == []
    assert await repo.recommendation_for_offer("different-owner", first.offer_id) is None
    exercise = (await repo.offers_for_student_with_detail(OWNER))[0][1]
    assert candidate_is_distinct(exercise.problem_statement, ["2x+3=7"])


@pytest.mark.asyncio
async def test_generation_failure_has_failed_recommendation_but_no_offer(stack):
    repo, service, parent = stack
    class BadGenerator:
        calls = 0
        async def generate(self, context, *, count=1):
            self.calls += 1
            assert count <= 3
            return [CandidateExercise(student_id=context.student_id, problem_statement="不可解析的题目",
                        skill_ids=context.target_skill_ids, difficulty=2, generated_by="test") for _ in range(9)]
    bad = BadGenerator()
    service._generator = bad
    with pytest.raises(PracticeOfferError):
        await service.prepare_offer(OWNER, parent_cycle_id=parent, target_skill_ids=("LINEAR_EQUATION",), count=100)
    assert bad.calls == 1
    assert await repo.offers_for_student(OWNER) == []
    record = (await repo.recommendations_for_student(OWNER))[0]
    assert record.status == "FAILED" and record.candidate_count == 3
    # FAILED isn't an active-purpose lock; an explicit retry may prepare a valid offer.
    service._generator = PracticeGeneratorChain()
    assert (await service.prepare_offer(OWNER, parent_cycle_id=parent, target_skill_ids=("LINEAR_EQUATION",))).status == "ACTIVE"


@pytest.mark.asyncio
async def test_concurrent_purpose_claim_is_unique(stack):
    repo, _, parent = stack
    records = [PracticeRecommendation(student_id=student_uuid(OWNER), parent_cycle_id=parent,
                    purpose="D", target_revision="same", target_skill_ids=("LINEAR_EQUATION",)) for _ in range(4)]
    results = await asyncio.gather(*(repo.begin_recommendation(record) for record in records))
    assert sum(claimed for _, claimed in results) == 1
    assert len({str(record.recommendation_id) for record, _ in results}) == 1
    assert await repo.recover_preparing_recommendations() == 1
    assert (await repo.recommendations_for_student(OWNER))[0].status == "FAILED"


@pytest.mark.asyncio
async def test_decline_keeps_parent_binding_and_can_request_again(stack):
    repo, service, parent = stack
    first = await service.prepare_offer(OWNER, parent_cycle_id=parent, target_skill_ids=("LINEAR_EQUATION",))
    assert await repo.mark_offer_declined(OWNER, first.offer_id)
    assert (await repo.load_offer(first.offer_id)).status == "DECLINED"
    assert (await repo.recommendation_for_offer(OWNER, first.offer_id)).parent_cycle_id == parent
    second = await service.prepare_offer(OWNER, parent_cycle_id=parent, target_skill_ids=("LINEAR_EQUATION",))
    assert second.offer_id != first.offer_id


@pytest.mark.asyncio
async def test_prerequisite_offer_carries_resume_parent(stack):
    repo, service, parent = stack
    offer = await service.prepare_offer(OWNER, parent_cycle_id=parent, target_skill_ids=("LINEAR_EQUATION",),
        purpose="C", prerequisite_skill_ids=("ARITHMETIC",))
    record = await repo.recommendation_for_offer(OWNER, offer.offer_id)
    assert record.purpose == "C" and record.resume_parent_cycle_id == parent
    assert record.target_skill_ids == ("ARITHMETIC",)
    exercise = (await repo.offers_for_student_with_detail(OWNER))[0][1]
    assert "- (-" in exercise.problem_statement and "/" not in exercise.problem_statement
    release = await repo.load_release(offer.exercise_release_id)
    problem, candidate, ref = await repo.load_exact_verified(release)
    assert "-" in problem.display_latex and "(" in problem.display_latex
    assert candidate.problem_id == ref.problem_id == problem.problem_id


@pytest.mark.asyncio
async def test_specific_fraction_gap_uses_fraction_foundation(stack):
    repo, service, parent = stack
    offer = await service.prepare_offer(OWNER, parent_cycle_id=parent, target_skill_ids=("ARITHMETIC",),
        purpose="C", prerequisite_skill_ids=("ARITHMETIC",), foundation_focus="fraction_operations")
    release = await repo.load_release(offer.exercise_release_id)
    exercise = await repo.load_exercise(release.exercise_id)
    assert "/" in exercise.problem_statement and "+" in exercise.problem_statement


@pytest.mark.asyncio
async def test_arithmetic_task_surface_survives_existing_folded_canonical_fact(stack):
    repo, service, _ = stack
    release_service = service._release_service
    first = await release_service.release_candidate(CandidateExercise(student_id=student_uuid(OWNER),
        problem_statement="5/4", skill_ids=("ARITHMETIC",), difficulty=1, generated_by="test"))
    second = await release_service.release_candidate(CandidateExercise(student_id=student_uuid(OWNER),
        problem_statement="3/4 + 1/2", skill_ids=("ARITHMETIC",), difficulty=1, generated_by="test"))
    assert first.problem.problem_id == second.problem.problem_id
    assert "+" in second.exercise.display_latex
    replayed, candidate, ref = await repo.load_exact_verified(second.release)
    assert "+" in replayed.display_latex
    assert replayed.content_hash == first.problem.content_hash
    assert candidate.payload_hash == ref.solution_payload_hash == second.candidate.payload_hash


@pytest.mark.asyncio
async def test_retrieval_hit_alone_is_not_grounding_and_difficulty_changes_structure():
    assembled = _assembled(with_documents=True)
    selection = assembled.user_documents[0]
    context = practice_context_from_assembled(assembled, target_skill_ids=("LINEAR_EQUATION",))
    unrelated = selection.model_copy(update={"chunks": tuple(chunk.model_copy(update={"text": "课程通知：周五放假"}) for chunk in selection.chunks)})
    generator = TemplateCandidateExerciseGenerator()
    ungrounded = (await generator.generate(context.model_copy(update={"document_context": unrelated})))[0]
    assert "grounded" not in ungrounded.generated_by and not ungrounded.material_basis
    grounded = (await generator.generate(context))[0]
    citation = grounded.material_basis[0]
    chunk = next(chunk for chunk in selection.chunks if chunk.chunk_id == citation.source_chunk_id)
    assert chunk.text[citation.quote_start:citation.quote_end] == citation.quote
    assert "-" in grounded.problem_statement and "移项" in citation.design_influence
    easy = (await generator.generate(context.model_copy(update={"desired_difficulty": 1})))[0]
    hard = (await generator.generate(context.model_copy(update={"desired_difficulty": 4})))[0]
    assert "/" not in easy.problem_statement and "/" in hard.problem_statement


@pytest.mark.asyncio
async def test_release_rejects_mathematically_valid_but_wrong_skill():
    candidate = CandidateExercise(student_id=student_uuid(OWNER), problem_statement="1/2+1/3",
                                  skill_ids=("LINEAR_EQUATION",), difficulty=2, generated_by="mt-bank-test")
    with pytest.raises(ReleaseDeniedError, match="技能"):
        await ExerciseReleaseService().release_candidate(candidate)
