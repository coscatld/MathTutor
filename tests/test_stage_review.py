"""Rule reviews use real learning events/outbox and never manufacture mastery."""
import pytest
from sqlalchemy import select
from test_knowledge_workbench import state
from mathtutor.infrastructure.schema import domain_outbox
from mathtutor.learning.knowledge_tracing.events import LearningEvent


async def attempt(state, n, **extra):
    return await state.student_state.record_attempt("alice", session_id="A", cycle_id="c" + str(n),
        problem_id="p" + str(n), problem_revision="r" + str(n), item_family_id="linear",
        skill_ids=("linear_equation",), assessment_id="assessment" + str(n), attempt_id="attempt" + str(n),
        correctness="correct", **extra)


@pytest.mark.asyncio
async def test_incremental_review_real_outbox_and_idempotency(state):
    for n in range(3):
        await attempt(state, n)
    assert (await state.stage_review.read("alice"))["status"] == "pending"
    result = await state.outbox_relay.process_batch()
    assert result["failed"] == 0 and result["dispatched"] == 3  # older queued revisions are safely superseded
    value = await state.stage_review.read("alice")
    assert value["review"]["independent_correct"] == 3
    assert value["dkt_mastery"] is None and value["model_calls"] == 0
    created = value["review"]["created_at"]
    await state.stage_review.request("alice")
    await state.stage_review.request("alice")
    assert (await state.outbox_relay.process_batch())["dispatched"] == 0
    assert (await state.stage_review.read("alice"))["review"]["created_at"] == created
    assert (await state.stage_review.read("bob"))["review"] is None


@pytest.mark.asyncio
async def test_self_report_and_multiple_choice_not_independent_success(state):
    await state.student_state.append_event(LearningEvent(event_id="understood", student_id="alice", session_id="A",
        cycle_id="c", event_type="self_explanation", problem_id="p", problem_revision="r", item_family_id="linear"))
    await attempt(state, 1, response_format="single_choice")
    await state.stage_review.set_preferences("alice", goal="复习方程", style="stepwise")
    await state.outbox_relay.process_batch()
    result = await state.stage_review.read("alice")
    assert result["review"]["independent_correct"] == 0
    assert len(result["review"]["basis"]) == 1
    assert result["review"]["hypotheses"] == []
    assert result["preferences"]["origin"] == "user_explicit"
    assert result["review"]["teaching_style"] == "stepwise"


@pytest.mark.asyncio
async def test_old_job_cannot_restore_deleted_history(state):
    await attempt(state, 1)
    await state.stage_review.request("alice")
    async with state.stage_review.engine.connect() as db:
        event = dict((await db.execute(select(domain_outbox).where(domain_outbox.c.event_type == "stage_review_requested"))).mappings().one())
    await state.data_lifecycle.delete_educational_history("alice")
    await state.stage_review.dispatch(event)
    assert (await state.stage_review.read("alice"))["review"] is None
    assert (await state.stage_review.read("alice"))["facts"] == []


@pytest.mark.asyncio
async def test_invalidation_removes_basis_without_review_loop(state):
    event = await attempt(state, 1)
    await state.stage_review.request("alice")
    await state.outbox_relay.process_batch()
    await state.student_state.invalidate("alice", event_id="correction", invalidates_event_id=event.event_id)
    await state.outbox_relay.process_batch()
    value = await state.stage_review.read("alice")
    assert value["review"]["independent_correct"] == 0
    assert value["review"]["changes"]["removed_observations"] == 1
    assert (await state.outbox_relay.process_batch())["dispatched"] == 0


@pytest.mark.asyncio
async def test_pending_manual_review_coalesces_new_event_instead_of_losing_job(state):
    await state.stage_review.request("alice")
    await state.student_state.record_attempt("alice",session_id="A",cycle_id="c",problem_id="p",problem_revision="r",
        item_family_id="linear",skill_ids=("linear_equation",),assessment_id="a",attempt_id="t",correctness="incorrect")
    assert (await state.stage_review.read("alice"))["status"]=="pending"
    assert (await state.outbox_relay.process_batch())["failed"]==0
    assert (await state.stage_review.read("alice"))["review"]["independent_incorrect"]==1
