"""Unseen transfer gates use retained owner facts, never the LLM's claim."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio

from mathtutor.application.adaptive_practice import AdaptivePracticeService, CandidateExercise
from mathtutor.application.data_lifecycle import DataLifecycleService
from mathtutor.application.llm_candidate_generator import (PracticeGeneratorChain, TemplateCandidateExerciseGenerator,
    bank_candidates_for, build_llm_prompt)
from mathtutor.application.practice_offer_view import enrich_offer
from mathtutor.application.practice_release import ExerciseReleaseService, PracticeOfferError
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.practice_recommendation import PracticeRecommendation
from mathtutor.domain.tutoring import PracticeOffer
from mathtutor.infrastructure.schema import metadata
from mathtutor.infrastructure import create_db_engine
from mathtutor.learning.knowledge_tracing.events import LearningEvent
from mathtutor.learning.knowledge_tracing.service import StudentStateService
from mathtutor.repositories.sqlite_practice import SQLitePracticeRepository
from mathtutor.repositories.sqlite_store import SQLiteSessionStore
from mathtutor.repositories.uow import MathTutorUow
from mathtutor.security.scopes import student_uuid
from mathtutor.solving.parser import parse_problem
from test_practice_recommendation_v2 import Assembler

OWNER = "student-a"
OLD = "2x+3=7"
FRESH = "x+1=10"


def revision(statement):
    parsed = parse_problem(statement).problem
    return MathProblem.canonicalize(problem_type=parsed.problem_type,
        normalized_ast=parsed.normalized_ast, display_latex=parsed.display_latex).content_hash


class FixedGenerator:
    def __init__(self, *statements):
        self.statements, self.contexts = statements, []

    async def generate(self, context, *, count=1):
        self.contexts.append(context)
        return [CandidateExercise(student_id=context.student_id, problem_statement=statement,
            skill_ids=context.target_skill_ids, difficulty=2, generated_by="test")
            for statement in self.statements[:count]]


@pytest_asyncio.fixture
async def stack(tmp_path, request):
    path = tmp_path / "unseen.db"
    engine = create_db_engine(path)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    if getattr(request, "param", "plaintext") == "encrypted":
        from mathtutor.infrastructure import db_crypto
        if not db_crypto.sqlcipher_available():
            await engine.dispose()
            pytest.skip("SQLCipher is unavailable on this host")
        await engine.dispose()
        db_crypto.request_change(path, True)
        assert db_crypto.apply_pending(path) == "encrypt"
        engine = create_db_engine(path)
    repo = SQLitePracticeRepository(MathTutorUow(engine))
    store = SQLiteSessionStore(engine)
    parent = (await store.create(OWNER, "current")).cycle.cycle_id
    tracking = StudentStateService(engine)
    service = AdaptivePracticeService(assembler=Assembler(),
        generator=FixedGenerator("2*x + 3 = 7", FRESH),
        release_service=ExerciseReleaseService(repository=repo))
    service.student_state = tracking
    yield SimpleNamespace(engine=engine, repo=repo, store=store, parent=parent,
        tracking=tracking, service=service)
    await engine.dispose()


async def fact(stack, statement=OLD, *, owner=OWNER, kind="problem_started"):
    context = dict(session_id="historical", cycle_id=str(uuid4()), problem_id=str(uuid4()),
        problem_revision=revision(statement), item_family_id="linear", skill_ids=("linear_isolation",))
    if kind == "attempt_submitted":
        await stack.tracking.record_submission(owner, **context,
            event_id=str(uuid4()), response_fingerprint="ungraded-submission")
    elif kind == "excluded_assessment":
        event = await stack.tracking.record_attempt(owner, **context,
            assessment_id=str(uuid4()), attempt_id=str(uuid4()), correctness="incorrect")
        await stack.tracking.invalidate(owner, event_id=str(uuid4()), invalidates_event_id=event.event_id)
    elif kind.startswith("help_"):
        await stack.tracking.record_help(owner, **context, event_id=str(uuid4()),
            event_type=kind, help_kind="solution", target_answer_exposed=True)
    else:
        await stack.tracking.append_event(LearningEvent(student_id=owner,
            event_id=str(uuid4()), event_type=kind, **context))


async def prepare(stack, *, purpose="A1", **changes):
    return await stack.service.prepare_offer(OWNER, parent_cycle_id=stack.parent,
        target_skill_ids=("LINEAR_EQUATION",), problem_text="x+1=50",
        purpose=purpose, full_task_completed=True,
        exposure_level={"A1": 0, "A2": 1, "B": 5}.get(purpose, 0), **changes)


async def offered_revision(stack, offer):
    return (await stack.repo.load_release(offer.exercise_release_id)).problem_hash


@pytest.mark.asyncio
@pytest.mark.parametrize("purpose", ["A1", "A2", "B"])
@pytest.mark.parametrize("kind", ["problem_started", "attempt_submitted", "excluded_assessment",
                                  "help_presented", "help_possibly_exposed"])
async def test_transfer_excludes_owner_canonical_history_even_without_a_practice_offer(stack, purpose, kind):
    await fact(stack, kind=kind)
    offer = await prepare(stack, purpose=purpose)
    assert await offered_revision(stack, offer) == revision(FRESH)
    assert len(stack.service._generator.contexts) == 1


async def historical_offer(stack, statement, *, owner=OWNER, days_ago=0):
    parent = stack.parent if owner == OWNER else (await stack.store.create(owner, "other")).cycle.cycle_id
    chain = await stack.service._release_service.release_candidate(CandidateExercise(
        student_id=student_uuid(owner), problem_statement=statement,
        skill_ids=("LINEAR_EQUATION",), difficulty=2, generated_by="test"))
    offer = PracticeOffer(student_id=student_uuid(owner), parent_cycle_id=parent,
        exercise_release_id=chain.release.release_id, target_mapping_ids=chain.exercise.target_mapping_ids,
        stage_policy_version="mt-stage-v2", status="DECLINED",
        offered_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    await stack.repo.create_offer(offer)
    return offer


@pytest.mark.asyncio
async def test_all_offers_are_checked_beyond_the_prompt_window(stack):
    await historical_offer(stack, OLD, days_ago=30)
    for index in range(21):
        await historical_offer(stack, f"x+{index}=100", days_ago=21-index)
    offer = await prepare(stack)
    assert await offered_revision(stack, offer) == revision(FRESH)
    context = stack.service._generator.contexts[0]
    assert len(context.excluded_problem_statements) <= 21
    assert OLD not in context.excluded_problem_statements
    assert revision(OLD) in context.excluded_problem_revisions
    assert "excluded_problem_revisions" not in context.model_dump()
    assert revision(OLD) not in build_llm_prompt(context)


@pytest.mark.asyncio
async def test_other_owner_history_and_global_verified_candidates_are_not_exposure(stack):
    await fact(stack, owner="student-b")
    await historical_offer(stack, OLD, owner="student-b")
    stack.service._generator = FixedGenerator(OLD)
    offer = await prepare(stack)
    assert await offered_revision(stack, offer) == revision(OLD)
    assert await stack.repo.seen_problem_revisions("unrelated-owner") == frozenset()


@pytest.mark.asyncio
async def test_review_can_repeat_a_seen_problem_and_public_projection_explains_it(stack):
    await fact(stack)
    await historical_offer(stack, OLD)
    stack.service._generator = FixedGenerator(OLD)
    offer = await prepare(stack, purpose="E", review_due=True)
    assert await offered_revision(stack, offer) == revision(OLD)
    public = await enrich_offer(SimpleNamespace(), stack.repo, OWNER, offer,
        {"status": "ACTIVE"}, history=await stack.tracking.events(OWNER), feedback={})
    assert public["purpose"] == "E"
    assert "复习" in public["title"] and "旧题" in public["reason"]
    assert "新题" not in public["observation_goal"]


@pytest.mark.asyncio
async def test_finite_local_pool_skips_seen_revisions_without_giving_history_to_llm(stack):
    stack.service._generator = PracticeGeneratorChain()
    first_candidates = await stack.service.generate_candidates(OWNER,
        target_skill_ids=("LINEAR_EQUATION",), count=3)
    for candidate in first_candidates:
        await fact(stack, candidate.problem_statement)
    offer = await prepare(stack)
    assert await offered_revision(stack, offer) not in {revision(c.problem_statement) for c in first_candidates}


@pytest.mark.asyncio
async def test_history_changed_during_generation_is_checked_again(stack):
    original = stack.service._generator.generate
    async def exposing_generator(context, *, count=1):
        await fact(stack, kind="help_presented")
        return await original(context, count=count)
    stack.service._generator.generate = exposing_generator
    assert await offered_revision(stack, await prepare(stack)) == revision(FRESH)


@pytest.mark.asyncio
async def test_last_transaction_refuses_new_exposure_without_publishing_an_offer(stack):
    stack.service._generator = FixedGenerator(OLD)
    complete = stack.repo.complete_recommendation
    async def expose_before_commit(*args, **kwargs):
        await fact(stack, kind="help_presented")
        return await complete(*args, **kwargs)
    stack.repo.complete_recommendation = expose_before_commit
    with pytest.raises(PracticeOfferError):
        await prepare(stack)
    assert await stack.repo.offers_for_student(OWNER) == []
    assert (await stack.repo.recommendations_for_student(OWNER))[0].status == "FAILED"
    stack.repo.complete_recommendation = complete
    stack.service._generator = FixedGenerator(FRESH)
    assert await offered_revision(stack, await prepare(stack)) == revision(FRESH)


@pytest.mark.asyncio
async def test_exhaustion_fails_closed_and_explicit_retry_can_choose_a_fresh_candidate(stack):
    await fact(stack)
    stack.service._generator = FixedGenerator(OLD, OLD, OLD)
    with pytest.raises(PracticeOfferError, match="新题"):
        await prepare(stack, count=100)
    assert len(stack.service._generator.contexts) == 1
    assert await stack.repo.offers_for_student(OWNER) == []
    record = (await stack.repo.recommendations_for_student(OWNER))[0]
    assert record.status == "FAILED" and record.candidate_count <= 3
    assert "重试" in record.failure_reason or "重新" in record.failure_reason
    stack.service._generator = FixedGenerator(FRESH)
    assert (await prepare(stack)).status == "ACTIVE"


@pytest.mark.asyncio
async def test_deletion_removes_event_only_history_but_keeps_retained_offer_history(stack):
    await fact(stack, OLD)
    await historical_offer(stack, FRESH)
    await DataLifecycleService(uow=MathTutorUow(stack.engine)).delete_educational_history(OWNER)
    assert await stack.tracking.events(OWNER) == []
    seen = await stack.repo.seen_problem_revisions(OWNER)
    assert revision(OLD) not in seen
    assert revision(FRESH) in seen


@pytest.mark.asyncio
async def test_legacy_bound_cycle_counts_without_recreating_deleted_learning_facts(stack):
    from mathtutor.repositories.sqlite_runtime import bind_problem
    chain = await stack.service._release_service.release_candidate(CandidateExercise(
        student_id=student_uuid(OWNER), problem_statement=OLD,
        skill_ids=("LINEAR_EQUATION",), difficulty=2, generated_by="test"))
    old_cycle = (await stack.store.create(OWNER, "legacy-task")).cycle.cycle_id
    async with stack.repo.uow.transaction() as conn:
        await bind_problem(conn, student_id=OWNER, cycle_id=old_cycle, problem_id=chain.problem.problem_id)
    assert await stack.tracking.events(OWNER) == []
    assert await offered_revision(stack, await prepare(stack)) == revision(FRESH)
    assert await stack.tracking.events(OWNER) == []


@pytest.mark.asyncio
async def test_exhausted_local_pool_reaches_offline_provider_and_still_rejects_seen_output(stack):
    recorder = FixedGenerator()
    stack.service._generator = recorder
    await stack.service.generate_candidates(OWNER, target_skill_ids=("LINEAR_EQUATION",), count=3)
    context = recorder.contexts[0]
    local = bank_candidates_for(context, count=100) + await TemplateCandidateExerciseGenerator().generate(context, count=100)
    for candidate in local:
        await fact(stack, candidate.problem_statement)
    await fact(stack, OLD)
    calls = []
    class OfflineClient:
        async def complete(self, **kwargs):
            calls.append(kwargs)
            return json.dumps([OLD, FRESH])
    gateway = SimpleNamespace(client_for=lambda role: OfflineClient())
    stack.service._generator = PracticeGeneratorChain(gateway=gateway)
    offer = await prepare(stack)
    assert await offered_revision(stack, offer) == revision(FRESH)
    assert len(calls) == 1 and calls[0]["max_retries"] == 1
    assert all(revision(candidate.problem_statement) not in calls[0]["prompt"] for candidate in local)
    assert "excluded_problem_revisions" not in calls[0]["prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stack", ["plaintext", "encrypted"], indirect=True)
async def test_concurrent_transfer_commits_cannot_offer_the_same_task_twice(stack):
    chain = await stack.service._release_service.release_candidate(CandidateExercise(
        student_id=student_uuid(OWNER), problem_statement=OLD,
        skill_ids=("LINEAR_EQUATION",), difficulty=2, generated_by="test"))
    pairs = []
    for index in range(2):
        parent = (await stack.store.create(OWNER, f"concurrent-{index}")).cycle.cycle_id
        record = PracticeRecommendation(student_id=student_uuid(OWNER), parent_cycle_id=parent,
            purpose="A1", target_revision=f"parent-{index}", target_skill_ids=("LINEAR_EQUATION",))
        record, claimed = await stack.repo.begin_recommendation(record)
        assert claimed
        offer = PracticeOffer(student_id=student_uuid(OWNER), parent_cycle_id=parent,
            exercise_release_id=chain.release.release_id, target_mapping_ids=chain.exercise.target_mapping_ids,
            stage_policy_version="mt-stage-v2", status="ACTIVE", expires_at=datetime.now(timezone.utc)+timedelta(hours=1))
        pairs.append((record.model_copy(update={"status": "ACTIVE", "offer_id": offer.offer_id}), offer))
    results = await asyncio.gather(*(stack.repo.complete_recommendation(record, offer, [], unseen_for_student=OWNER)
        for record, offer in pairs), return_exceptions=True)
    assert sum(result is None for result in results) == 1
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert len(await stack.repo.offers_for_student(OWNER)) == 1


@pytest.mark.asyncio
async def test_history_query_failure_does_not_publish_an_unchecked_task(stack):
    async def unavailable(_):
        raise RuntimeError("history temporarily unavailable")
    stack.repo.seen_problem_revisions = unavailable
    with pytest.raises(PracticeOfferError):
        await prepare(stack)
    assert stack.service._generator.contexts == []
    assert await stack.repo.offers_for_student(OWNER) == []


def test_real_websocket_self_input_is_not_reoffered_as_new_transfer(tmp_path):
    from mathtutor.api.product_state import get_product_state
    from test_tutor_p0 import client_at, send
    with client_at(tmp_path / "api.db") as client:
        runtime = get_product_state()
        runtime.adaptive_practice._generator = FixedGenerator(OLD, FRESH)
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            send(ws, "submit_problem", "history", {"text": OLD}, session="old-input")
            send(ws, "submit_problem", "parent", {"text": "x+1=50"}, session="new-parent")
            frames = send(ws, "submit_attempt", "solve", {"answer": "49"}, session="new-parent")
        offers = client.get("/api/v2/math-tutor/offers")
        assert offers.status_code == 200 and len(offers.json()) == 1
        assert offers.json()[0]["purpose"] == "A1"
        assert any(frame.get("payload", {}).get("action") == "practice_offered" for frame in frames)
        # Only a genuinely fresh second candidate reaches the release gate.
        context = runtime.adaptive_practice._generator.contexts[0]
        assert revision(OLD) in context.excluded_problem_revisions
        assert revision(FRESH) not in context.excluded_problem_revisions
        assert "excluded_problem_revisions" not in json.dumps(offers.json())


@pytest.mark.asyncio
async def test_llm_prompt_remains_bounded_and_never_serializes_the_history_set(stack):
    from mathtutor.domain.practice_context import AttemptSummaryEntry
    await stack.service.generate_candidates(OWNER, target_skill_ids=("LINEAR_EQUATION",))
    context = stack.service._generator.contexts[0].model_copy(update={
        "excluded_problem_statements": tuple(f"x+{n}=1000" for n in range(100)),
        "excluded_problem_revisions": frozenset({"private-history-revision"}),
        "recent_attempt_summary": tuple(AttemptSummaryEntry(skill_id="LINEAR_EQUATION",
            correctness="correct", effective_assistance_level=0, attempt_index=1) for _ in range(100)),
    })
    prompt = build_llm_prompt(context)
    payload = json.loads(prompt)
    assert len(payload["excluded_problem_statements"]) == 21
    assert len(payload["recent_attempt_summary"]) == 20
    assert "private-history-revision" not in prompt
    assert "excluded_problem_revisions" not in context.model_dump(mode="json")
