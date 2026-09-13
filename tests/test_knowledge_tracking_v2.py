"""No API keys or user databases: isolated real persistence/training tests."""
from __future__ import annotations

import json

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from mathtutor.learning.knowledge_tracing import LearningEvent, StudentStateService, evidence_summary
from mathtutor.learning.knowledge_tracing.__main__ import synthetic_events
from mathtutor.learning.knowledge_tracing.dataset import split_events
from mathtutor.learning.knowledge_tracing.evaluation import fit_temperature, metrics
from mathtutor.learning.knowledge_tracing.events import baseline_prediction
from mathtutor.learning.knowledge_tracing.features import FeatureVocabulary
from mathtutor.learning.knowledge_tracing.runtime import LSTMTracker
from mathtutor.learning.knowledge_tracing.schema import learning_predictions, metadata, student_state_snapshots
from mathtutor.learning.knowledge_tracing.training import build_model, export_model, train_pipeline


@pytest.fixture
async def service(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tracking.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield StudentStateService(engine)
    await engine.dispose()


def context(**overrides):
    return {"session_id": "session", "cycle_id": "cycle", "problem_id": "problem", "problem_revision": "revision",
            "item_family_id": "linear", "skill_ids": ["divide_nonzero"], **overrides}


async def attempt(service, identity="a1", *, student_id="alice", **overrides):
    return await service.record_attempt(student_id, **context(), assessment_id=f"assessment-{identity}",
        attempt_id=identity, correctness=overrides.pop("correctness", "correct"), **overrides)


@pytest.mark.asyncio
async def test_prepare_prediction_precedes_label_and_replay_is_idempotent(service):
    before = await service.prepare_prediction("alice", prediction_id="pred-1", **context())
    assert before["history_cutoff_seq"] == 0 and before["prediction_label"] is None
    event = await attempt(service, prediction_id="pred-1")
    assert event.event_seq == 1 and event.evidence_kind == "independent"
    assert (await attempt(service, prediction_id="pred-1")) == event
    after = await service.prepare_prediction("alice", prediction_id="pred-1", **context())
    assert after["history_cutoff_seq"] == 0 and after["prediction_label"] == 1
    assert after["baseline_probability"] == .5
    assert len(await service.events("alice")) == 1
    assert (await service.summary("bob"))["event_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("phase,kind", [("help_requested", "independent"), ("help_committed", "independent"),
    ("help_possibly_exposed", "unknown"), ("help_presented", "assisted")])
async def test_request_and_commit_are_not_actual_exposure(service, phase, kind):
    await service.record_help("alice", event_id="help", event_type=phase, **context())
    event = await attempt(service)
    assert event.evidence_kind == kind
    assert event.independent_target == (kind == "independent")


@pytest.mark.asyncio
async def test_possible_answer_exposure_conservatively_disqualifies_independence(service):
    await service.record_help("alice", event_id="answer-sent", event_type="help_possibly_exposed",
        help_kind="solution", target_answer_exposed=True, delivery_id="message-1", **context())
    event = await attempt(service)
    assert event.evidence_kind == "post_solution" and not event.independent_target
    await service.record_help("alice", event_id="answer-ack", event_type="help_presented",
        help_kind="solution", target_answer_exposed=True, delivery_id="message-1", **context())
    event2 = await attempt(service, "a2")
    assert event2.evidence_kind == "post_solution" and not event2.provenance_uncertain
    # Duplicate answer reopening does not create another actual event.
    await service.record_help("alice", event_id="answer-ack", event_type="help_presented",
        help_kind="solution", target_answer_exposed=True, delivery_id="message-1", **context())
    assert len(await service.events("alice")) == 4


@pytest.mark.asyncio
async def test_new_cycle_does_not_inherit_old_help(service):
    await service.record_help("alice", event_id="old-help", **context(cycle_id="old", problem_revision="different-canonical-task"))
    assert (await attempt(service)).evidence_kind == "independent"


@pytest.mark.asyncio
async def test_same_canonical_problem_in_new_conversation_keeps_answer_exposure(service):
    await service.record_help("alice", event_id="old-answer", **context(session_id="older-conversation", cycle_id="older-cycle"),
                              help_kind="solution", target_answer_exposed=True)
    event = await attempt(service)
    assert event.evidence_kind == "post_solution" and not event.independent_target
    assert event.prior_help_event_ids == ("old-answer",)
    restored_context = await service.exposure_context("alice", "revision")
    assert restored_context["assistance_level"] == 5
    assert restored_context["target_answer_exposed"] and restored_context["help_exposed"]
    assert not (await service.exposure_context("alice", "different-task"))["help_exposed"]
    assert (await attempt(service, "bob-answer", student_id="bob")).evidence_kind == "independent"


@pytest.mark.asyncio
async def test_unknown_and_partial_never_become_whole_task_failure(service):
    await attempt(service, correctness="unknown")
    await attempt(service, "a2", correctness="partial", completion_scope="subgoal")
    summary = await service.summary("alice")
    skill = summary["skills"][0]
    assert skill["independent"] == {"correct": 0, "incorrect": 0}
    assert skill["ungradable"] == 1 and skill["step_correct"] == 1
    assert summary["training_data"]["independent_targets"] == 0
    assert "mastery" not in skill


@pytest.mark.asyncio
async def test_diagnostic_has_separate_counts_and_no_independent_main_loss(service):
    event = await attempt(service, task_purpose="diagnostic")
    assert not event.independent_target
    row = (await service.summary("alice"))["skills"][0]
    assert row["diagnostic"] == {"correct": 1, "incorrect": 0}
    assert row["independent"] == {"correct": 0, "incorrect": 0}


@pytest.mark.asyncio
async def test_repeated_same_answer_is_retained_but_not_extra_independent_evidence(service):
    wrong = await attempt(service, "wrong", correctness="incorrect", response_fingerprint="wrong-answer")
    first = await attempt(service, "first", response_fingerprint="correct-answer")
    repeated = await attempt(service, "repeated", response_fingerprint="correct-answer")
    assert wrong.independent_target and not first.independent_target
    assert repeated.duplicate_response and not repeated.independent_target
    rows = await service.events("alice")
    assert len(rows) == 3  # All physical attempts are still auditable.
    summary = await service.summary("alice")
    assert summary["skills"][0]["independent"] == {"correct": 1, "incorrect": 1}
    assert summary["totals"]["duplicate_responses"] == 1
    new_task = await service.record_attempt("alice", **context(problem_revision="new-task"),
        assessment_id="new", attempt_id="new", correctness="correct", response_fingerprint="correct-answer")
    assert new_task.independent_target and not new_task.duplicate_response


@pytest.mark.asyncio
async def test_startup_legacy_import_does_not_duplicate_existing_v2_attempt(service):
    from mathtutor.infrastructure.schema import metadata as product_metadata, attempts, mastery_evidence, tutoring_cycles
    async with service.engine.begin() as conn:
        await conn.run_sync(product_metadata.create_all)
        await conn.execute(tutoring_cycles.insert().values(cycle_id="cycle", session_id="session", student_id="alice",
            state="SOLVED", state_version=1, problem_id="problem", created_at="2026-01-01"))
        await conn.execute(attempts.insert().values(attempt_id="a1", attempt_submission_id="submission", student_id="alice",
            cycle_id="cycle", parsed_steps=[], attempt_index=1, payload_hash="hash", created_at="2026-01-01"))
        await conn.execute(mastery_evidence.insert().values(evidence_id="old-evidence", student_id="alice", attempt_id="a1",
            skill_id="linear_isolation", attempt_assessment_log_id="assessment-a1", correctness="correct", score=1,
            difficulty=1, effective_assistance_level=0, evidence_version="legacy-v1", idempotency_key="legacy-id",
            created_at="2026-01-01"))
    # A custom event_id proves deduplication uses the attempt identity, not a
    # guessed v2 event-id prefix that callers are free not to use.
    await attempt(service, event_id="a-custom-v2-event")
    before = await service.summary("alice")
    restarted = StudentStateService(service.engine)
    assert await restarted.import_legacy("alice") == 0
    assert await restarted.import_legacy("alice") == 0
    assert await restarted.summary("alice") == before


@pytest.mark.asyncio
async def test_atomic_parent_transaction_rollback(service):
    with pytest.raises(RuntimeError):
        async with service.engine.begin() as conn:
            await attempt(service, conn=conn)
            raise RuntimeError("assessment commit failed")
    assert await service.events("alice") == []
    async with service.engine.begin() as conn:
        assert (await conn.execute(select(learning_predictions))).all() == []


@pytest.mark.asyncio
async def test_append_only_correction_rebuilds_evidence_and_owner_isolation(service):
    event = await attempt(service)
    await service.invalidate("alice", event_id="correction", invalidates_event_id=event.event_id)
    assert (await service.summary("alice"))["skills"] == []
    assert len(await service.events("alice")) == 2
    with pytest.raises(ValueError, match="owner"):
        await service.invalidate("bob", event_id="bad", invalidates_event_id=event.event_id)


def test_multiskill_failure_not_copied_to_every_skill():
    event = synthetic_events(students=1, events_per_student=1)[0].model_copy(update={
        "skill_ids": ("eliminate", "arithmetic"), "correctness": "incorrect"})
    summary = evidence_summary([event])
    assert summary["item_level_uncertain"] == 1
    assert all(x["independent"]["incorrect"] == 0 for x in summary["skills"])
    localized = event.model_copy(update={"verified_error_skill_ids": ("arithmetic",)})
    rows = {x["skill_id"]: x for x in evidence_summary([localized])["skills"]}
    assert rows["arithmetic"]["independent"]["incorrect"] == 1
    assert rows["eliminate"]["independent"]["incorrect"] == 0


def test_feature_unknown_is_distinct_from_incorrect_and_current_item_has_no_label():
    original = synthetic_events(students=1, events_per_student=1)[0]
    vocab = FeatureVocabulary.fit([original])
    unknown = original.model_copy(update={"correctness": "unknown", "active_response_ms": None})
    incorrect = original.model_copy(update={"correctness": "incorrect", "active_response_ms": 0})
    assert not np.array_equal(vocab.event(unknown), vocab.event(incorrect))
    assert vocab.item(skill_ids=("unmapped",), item_family_id="other")[-2:].tolist() == [1, 1]
    assert not vocab.covered(("unmapped",))


@pytest.mark.parametrize("mode", ["student", "time", "family"])
def test_splits_isolate_identity_and_chronology(mode):
    events = synthetic_events(students=12, events_per_student=18)
    splits = split_events(events, mode=mode)
    folds = [splits[x] for x in ("train", "validation", "test")]
    for i, left in enumerate(folds):
        for right in folds[i + 1:]:
            assert not ({e.problem_revision for e in left} & {e.problem_revision for e in right})
            if mode == "student":
                assert not ({e.student_id for e in left} & {e.student_id for e in right})
            if mode == "family":
                assert not ({e.item_family_id for e in left} & {e.item_family_id for e in right})
            if mode == "time":
                for student in {e.student_id for e in left} & {e.student_id for e in right}:
                    assert max(e.occurred_at for e in left if e.student_id == student) < min(e.occurred_at for e in right if e.student_id == student)


def test_probability_metrics_handle_ties_missing_classes_and_calibration():
    result = metrics([0, 1], [.5, .5])
    assert result["auroc"] == .5 and result["brier"] == .25
    assert result["auprc"] == .5
    assert metrics([1, 1], [.9, .8])["auroc"] is None
    temperature, status = fit_temperature([0, 1, 0, 1], [.99, .99, .99, .99])
    assert temperature > 1 and "validation" in status
    assert metrics([], [])["log_loss"] is None


def test_real_lstm_training_export_and_numpy_state_consistency():
    torch = pytest.importorskip("torch")
    events = synthetic_events(students=8, events_per_student=12)
    vocab = FeatureVocabulary.fit(events)
    model = build_model(vocab, hidden_size=8, embedding_size=8)
    # Export pretraining is explicitly not loadable for serving.
    with pytest.raises(ValueError, match="untrained"):
        LSTMTracker(export_model(model, vocab, seed=1, training_steps=0))
    tracker = LSTMTracker(export_model(model, vocab, seed=1, training_steps=1))
    pt, np_state = model.initialize(), tracker.initialize()
    alternate = events[0].model_copy(update={"correctness": "incorrect" if events[0].correctness == "correct" else "correct"})
    assert model.predict(pt, events[0]).item() == model.predict(pt, alternate).item()
    assert not np.array_equal(tracker.update(np_state, events[0])[0], tracker.update(np_state, alternate)[0])
    for event in events[:6]:
        pt = model.update(pt, event)
        np_state = tracker.update(np_state, event)
        np.testing.assert_allclose(np_state[0], pt[0].detach().numpy().reshape(-1), atol=2e-7)
        np.testing.assert_allclose(np_state[1], pt[1].detach().numpy().reshape(-1), atol=2e-7)
    snapshot = tracker.snapshot(np_state, student_id="alice", last_event_seq=6)
    restored = tracker.restore(snapshot, student_id="alice")
    assert "h" in snapshot and "c" in snapshot
    np.testing.assert_array_equal(restored[0], np_state[0])
    with pytest.raises(ValueError, match="version"):
        tracker.restore({**snapshot, "model_version": "other"}, student_id="alice")
    artifact, report = train_pipeline(events, epochs=2, hidden_size=8, embedding_size=8, synthetic=True)
    assert report["parameters_changed"] and report["training_steps"] > 0
    assert report["dataset_kind"] == "synthetic_pipeline_only" and report["policy_mode"] == "shadow"
    assert report["test"]["count"] > 0 and report["test"]["log_loss"] is not None
    assert LSTMTracker(artifact).mode == "shadow"


@pytest.mark.asyncio
async def test_model_snapshot_restart_and_version_change_replay(service, tmp_path):
    pytest.importorskip("torch")
    source = synthetic_events(students=6, events_per_student=8)
    artifact, _ = train_pipeline(source, epochs=1, hidden_size=8, embedding_size=8, synthetic=True)
    path = tmp_path / "trained.json"
    path.write_text(json.dumps(artifact))
    tracked = StudentStateService(service.engine, path)
    for i in range(3):
        await tracked.record_attempt("alice", **context(skill_ids=["linear_isolation"]),
            assessment_id=f"s{i}", attempt_id=f"a{i}", correctness="correct")
    async with service.engine.begin() as conn:
        snapshot = (await conn.execute(select(student_state_snapshots.c.payload))).scalar_one()
    assert snapshot["last_event_seq"] == 3 and len(snapshot["h"]) == 8 and len(snapshot["c"]) == 8
    restarted = StudentStateService(service.engine, path)
    p1 = await tracked.prepare_prediction("alice", prediction_id="next", **context(skill_ids=["linear_isolation"]))
    p2 = await restarted.prepare_prediction("alice", prediction_id="next2", **context(skill_ids=["linear_isolation"]))
    assert p1["shadow_probability"] == p2["shadow_probability"]
    # A new parameter version must replay, not use the stale h/c vectors.
    artifact["model_version"] += "-new"
    path.write_text(json.dumps(artifact))
    changed = StudentStateService(service.engine, path)
    p3 = await changed.prepare_prediction("alice", prediction_id="next3", **context(skill_ids=["linear_isolation"]))
    assert p1["shadow_probability"] == p3["shadow_probability"]
    oov = await changed.prepare_prediction("alice", prediction_id="oov", **context(skill_ids=["unseen_skill"]))
    assert oov["shadow_probability"] is None and oov["policy_source"] == "evidence_tracker_v2"


@pytest.mark.asyncio
async def test_bad_model_does_not_block_assessment_or_claim_trained(service, tmp_path):
    path = tmp_path / "invalid-model.json"
    path.write_text('{"trained":false}')
    fallback = StudentStateService(service.engine, path)
    event = await attempt(fallback)
    assert event.evidence_kind == "independent"
    summary = await fallback.summary("alice")
    assert summary["dkt_mode"] == "unavailable_fallback"
    assert summary["policy_source"] == "evidence_tracker_v2"
    assert not summary["dkt_controls_teaching"]


@pytest.mark.asyncio
async def test_offline_database_source_reads_actual_events_without_mutation(service):
    from mathtutor.learning.knowledge_tracing.__main__ import read_database_events
    await attempt(service)
    before = await service.summary("alice")
    events = read_database_events(service.engine.url.database)
    assert len(events) == 1 and events[0].student_id == "alice"
    assert await service.summary("alice") == before


def test_offline_source_validation_never_echoes_raw_credentials(tmp_path, capsys):
    from mathtutor.learning.knowledge_tracing.__main__ import main
    source = tmp_path / "bad-events.jsonl"
    source.write_text('{"api_key":"secret-must-not-echo"}')
    with pytest.raises(SystemExit):
        main(["--input", str(source), "--output", str(tmp_path / "output")])
    captured = capsys.readouterr()
    assert "secret-must-not-echo" not in captured.err + captured.out


def test_joint_student_item_split_removes_shared_items():
    events = synthetic_events(students=12, events_per_student=12)
    events = [e.model_copy(update={"leakage_group_id": f"near-duplicate-{e.event_seq}"}) for e in events]
    splits = split_events(events, mode="student_item")
    assert splits["audit"]["purged_cross_split_item_events"] > 0
    train = {e.leakage_group_id for e in splits["train"]}
    assert not train & {e.leakage_group_id for e in splits["validation"] + splits["test"]}


def test_d05_future_label_mutation_cannot_change_any_earlier_prediction():
    pytest.importorskip("torch")
    events = synthetic_events(students=8, events_per_student=12)
    artifact, _ = train_pipeline(events, epochs=1, hidden_size=8, embedding_size=8, synthetic=True)
    tracker = LSTMTracker(artifact)
    history = [e for e in events if e.student_id == "synthetic-0"]
    changed_at = 6
    altered = [e.model_copy(update={"correctness": "incorrect" if e.correctness == "correct" else "correct"})
               if i >= changed_at else e for i, e in enumerate(history)]
    def predictions(stream):
        state = tracker.initialize()
        values = []
        for event in stream:
            values.append(tracker.predict(state, {"skill_ids": event.skill_ids,
                "item_family_id": event.item_family_id, "difficulty": event.difficulty}))
            state = tracker.update(state, event)
        return values
    original, mutated = predictions(history), predictions(altered)
    # Including the changed event's OWN pre-label prediction: all identical.
    assert original[:changed_at + 1] == mutated[:changed_at + 1]
    assert any(a != b for a, b in zip(original[changed_at + 1:], mutated[changed_at + 1:]))
