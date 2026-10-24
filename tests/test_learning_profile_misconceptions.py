"""Diagnosed misconceptions reach the public learning profile."""
import pytest

from mathtutor.application.evidence_projection import teaching_evidence
from mathtutor.application.learning_profile import active_misconceptions, profile_projection
from mathtutor.learning.knowledge_tracing.events import LearningEvent, evidence_summary
from test_knowledge_tracking_v2 import service


def assessed(seq, correctness, *, skill="linear_transpose", skills=None, codes=(), revision=None, kind="independent", **changes):
    return LearningEvent(
        event_id=f"e{seq}", student_id="alice", session_id="s", cycle_id=f"c{seq}", event_seq=seq,
        event_type="attempt_assessed", occurred_at=f"2026-10-14T00:00:{seq:02d}+00:00",
        problem_id=f"p{seq}", problem_revision=revision or f"r{seq}", item_family_id="linear",
        skill_ids=tuple(skills or (skill,)), assessment_id=f"a{seq}", attempt_id=f"a{seq}",
        correctness=correctness, evidence_kind=kind, misconception_codes=tuple(codes), **changes)


def test_profile_counts_diagnosed_rules_instead_of_fixed_zero():
    history = [assessed(1, "incorrect", codes=("sign_flip",)),
               assessed(2, "incorrect", codes=("wrong_operation", "sign_flip"))]
    profile = profile_projection(history)
    assert profile["active_misconceptions"] == 2
    assert [m["rule_id"] for m in profile["misconceptions"]] == [
        "miscon-sign-error", "miscon-transposition-error"]
    assert profile["misconceptions"][0]["label"] == "符号错误"
    assert all(row["mastery"] is None for row in profile["skills"])


def test_independent_success_on_the_skill_resolves_its_rules():
    history = [assessed(1, "incorrect", codes=("sign_flip",)),
               assessed(2, "incorrect", skill="quadratic_roots", codes=("missing_root",)),
               assessed(3, "correct")]
    assert [m["rule_id"] for m in active_misconceptions(history)] == ["miscon-missing-root"]


def test_assisted_success_and_unknown_signals_do_not_change_rules():
    history = [assessed(1, "incorrect", codes=("sign_flip", "not_a_rule")),
               assessed(2, "correct", kind="assisted")]
    assert [m["rule_id"] for m in active_misconceptions(history)] == ["miscon-sign-error"]
    assert active_misconceptions([assessed(1, "correct", codes=("sign_flip",))]) == []


@pytest.mark.parametrize("correctness", ["incorrect", "partial"])
def test_unlocalized_multiskill_error_stays_an_item_observation(correctness):
    event = assessed(1, correctness, skills=("linear_transpose", "linear_isolation"), codes=("sign_flip",))
    before = event.model_dump()
    profile = profile_projection([event])
    assert profile["misconceptions"] == []
    assert profile["active_misconceptions"] == 0
    observation = profile["item_error_observations"][0]
    assert observation == {"rule_id": "miscon-sign-error", "label": "符号错误", "event_id": "e1",
        "assessment_id": "a1", "cycle_id": "c1", "related_skill_ids": ["linear_transpose", "linear_isolation"],
        "last_seen_at": event.occurred_at, "status": "unlocalized", "correction_event_id": None}
    assert all(row["joint_task_evidence"] == 1 for row in evidence_summary([event])["skills"])
    assert all(row["independent"]["incorrect"] == 0 for row in evidence_summary([event])["skills"])
    assert event.model_dump() == before


@pytest.mark.parametrize("correctness", ["incorrect", "partial"])
def test_verifier_localization_is_shared_by_profile_and_skill_counts(correctness):
    event = assessed(1, correctness, skills=("linear_transpose", "linear_isolation"), codes=("sign_flip",),
        verified_error_skill_ids=("linear_transpose",))
    profile = profile_projection([event])
    assert profile["misconceptions"][0]["skill_ids"] == ["linear_transpose"]
    assert profile["item_error_observations"] == []
    rows = {row["skill_id"]: row for row in evidence_summary([event])["skills"]}
    category = "diagnostic" if correctness == "partial" else "independent"
    assert rows["linear_transpose"][category]["incorrect"] == 1
    assert rows["linear_isolation"][category]["incorrect"] == 0
    assert rows["linear_transpose"]["step_correct"] == 0


def test_multiskill_final_success_does_not_clear_each_skills_rules():
    history = [assessed(1, "incorrect", codes=("sign_flip",)),
        assessed(2, "incorrect", skill="linear_isolation", codes=("wrong_value",)),
        assessed(3, "correct", skills=("linear_transpose", "linear_isolation"))]
    assert {row["rule_id"] for row in active_misconceptions(history)} == {
        "miscon-sign-error", "miscon-computation-error"}
    assert evidence_summary(history)["skills"][0]["independent"]["correct"] == 0


@pytest.mark.parametrize("changes", [
    {"kind": "assisted"}, {"kind": "post_solution"}, {"provenance_uncertain": True},
    {"target_answer_exposed_before_attempt": True}, {"response_format": "single_choice"},
    {"task_purpose": "diagnostic"}, {"revision": "r1"},
])
def test_clearing_a_skill_rule_requires_new_independent_evidence(changes):
    history = [assessed(1, "incorrect", codes=("sign_flip",)), assessed(2, "correct", **changes)]
    assert [row["rule_id"] for row in active_misconceptions(history)] == ["miscon-sign-error"]


def test_independent_new_single_skill_step_can_resolve_its_rule_without_full_target_credit():
    history = [assessed(1, "incorrect", codes=("sign_flip",)),
        assessed(2, "correct", completion_scope="subgoal", subgoal_id="balance")]
    assert active_misconceptions(history) == []
    row = evidence_summary(history)["skills"][0]
    assert row["independent"]["correct"] == 0 and row["step_correct"] == 1


@pytest.mark.parametrize("changes", [{"provenance_uncertain": True}, {"kind": "unknown"}, {"duplicate_response": True}])
def test_uncertain_or_duplicate_diagnosis_does_not_create_rules_or_item_observations(changes):
    event = assessed(1, "incorrect", skills=("linear_transpose", "linear_isolation"), codes=("sign_flip",), **changes)
    profile = profile_projection([event])
    assert profile["misconceptions"] == [] and profile["item_error_observations"] == []


def test_skill_specific_teaching_context_does_not_borrow_unlocalized_joint_errors():
    event = assessed(1, "incorrect", skills=("linear_transpose", "linear_isolation"), codes=("sign_flip",))
    scoped = teaching_evidence([event], ["linear_transpose"])
    assert scoped["independent_incorrect_items"] == 0 and scoped["verified_error_counts"] == {}
    assert teaching_evidence([event], event.skill_ids)["independent_incorrect_items"] == 1
    localized = event.model_copy(update={"verified_error_skill_ids": ("linear_isolation",)})
    assert teaching_evidence([localized], ["linear_transpose"])["verified_error_counts"] == {}
    assert teaching_evidence([localized], ["linear_isolation"])["verified_error_counts"] == {"sign_flip": 1}


@pytest.mark.parametrize("changes,expected", [
    ({}, "corrected_later"), ({"kind": "assisted"}, "corrected_later"),
    ({"kind": "post_solution"}, "corrected_later"),
    ({"provenance_uncertain": True}, "unlocalized"), ({"kind": "unknown"}, "unlocalized"),
    ({"response_format": "single_choice"}, "unlocalized"),
    ({"completion_scope": "subgoal", "subgoal_id": "balance"}, "unlocalized"),
    ({"task_purpose": "diagnostic"}, "unlocalized"),
    ({"revision": "different"}, "unlocalized"),
])
def test_item_correction_preserves_history_without_claiming_new_independent_success(changes, expected):
    skills = ("linear_transpose", "linear_isolation")
    wrong = assessed(1, "incorrect", skills=skills, codes=("sign_flip",))
    correct = assessed(2, "correct", skills=skills, **{"revision": "r1", **changes})
    history = [wrong, correct]
    before = [event.model_dump() for event in history]
    profile = profile_projection(history)
    observation = profile["item_error_observations"][0]
    assert observation["status"] == expected
    assert observation["correction_event_id"] == ("e2" if expected == "corrected_later" else None)
    assert observation["event_id"] == "e1" and profile["misconceptions"] == []
    assert all(row["independent"]["correct"] == 0 for row in evidence_summary(history)["skills"])
    assert [event.model_dump() for event in history] == before


def test_profile_export_exclusion_and_deletion_share_real_item_observations(tmp_path):
    from urllib.parse import quote
    from test_tutor_p0 import client_at, send
    prefix = "/api/v2/math-tutor/desktop"
    with client_at(tmp_path / "export.db") as client:
        def shared_observations():
            response = client.get(prefix + "/student-summary")
            assert response.status_code == 200
            profile = response.json()
            export_response = client.get(prefix + "/privacy/export")
            assert export_response.status_code == 200
            exported = export_response.json()["student_summary"]
            assert profile["active_misconceptions"] == 0 and profile["misconceptions"] == []
            assert exported["active_misconceptions"] == []
            assert exported["item_error_observations"] == profile["item_error_observations"]
            assert all(row["evidence_summary"]["independent"]["incorrect"] == 0 for row in exported["skills"])
            return profile["item_error_observations"]

        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            send(ws, "submit_problem", "p", {"text": "2x+3=7"})
            send(ws, "submit_attempt", "wrong", {"answer": "x=-2"})
            observations = shared_observations()
            assert len(observations) == 1
            wrong = observations[0]
            assert wrong["rule_id"] == "miscon-sign-error" and wrong["label"] == "符号错误"
            assert wrong["status"] == "unlocalized" and wrong["correction_event_id"] is None
            assert len(wrong["related_skill_ids"]) > 1
            evidence = client.get(prefix + "/student-evidence").json()["items"]
            assert len(evidence) == 1 and evidence[0]["event_id"] == wrong["event_id"]
            assert evidence[0]["correctness"] == "incorrect" and evidence[0]["student_response"] == "x=-2"
            send(ws, "submit_attempt", "right", {"answer": "x=2"})
        corrected = shared_observations()[0]
        assert corrected["status"] == "corrected_later"
        assert corrected["event_id"] == wrong["event_id"] and corrected["correction_event_id"]
        evidence = client.get(prefix + "/student-evidence").json()["items"]
        assert len(evidence) == 2
        correct = next(row for row in evidence if row["event_id"] == corrected["correction_event_id"])
        assert correct["correctness"] == "correct" and not correct["first_target"]
        exclude = prefix + "/student-evidence/" + quote(correct["event_id"], safe="") + "/exclude"
        assert client.post(exclude).status_code == 200
        assert shared_observations() == observations  # removing the correction reopens the item observation
        exclude = prefix + "/student-evidence/" + quote(wrong["event_id"], safe="") + "/exclude"
        assert client.post(exclude).status_code == 200
        assert shared_observations() == []
        evidence = client.get(prefix + "/student-evidence").json()["items"]
        assert len(evidence) == 2 and all(row["excluded"] for row in evidence)
        assert client.post(prefix + "/privacy/educational-history").status_code == 200
        assert client.get(prefix + "/student-evidence").json()["items"] == []
        assert shared_observations() == []


async def test_persisted_localization_exports_only_verified_skill_and_respects_owner(service):
    from mathtutor.application.data_export import export_evidence_summary
    from test_knowledge_tracking_v2 import context
    await service.record_attempt("alice", **context(skill_ids=["linear_transpose", "linear_isolation"]),
        assessment_id="wrong", attempt_id="wrong", correctness="incorrect", misconception_codes=["sign_flip"],
        verified_error_skill_ids=["linear_transpose"])
    history = await service.events("alice")
    profile = profile_projection(history)
    exported = await export_evidence_summary("alice", student_state=service)
    rule = exported["active_misconceptions"][0]
    assert rule["skill_ids"] == profile["misconceptions"][0]["skill_ids"] == ["linear_transpose"]
    assert rule["rule_id"] == "miscon-sign-error" and rule["status"] == "active" and rule["confidence"] is None
    assert exported["item_error_observations"] == []
    await service.record_attempt("alice", **context(skill_ids=["linear_transpose", "linear_isolation"],
        cycle_id="new-cycle", problem_revision="new-item"), assessment_id="unlocalized", attempt_id="unlocalized",
        correctness="incorrect", misconception_codes=["sign_flip"])
    assert len((await export_evidence_summary("alice", student_state=service))["item_error_observations"]) == 1
    assert (await export_evidence_summary("bob", student_state=service))["active_misconceptions"] == []
    assert (await export_evidence_summary("bob", student_state=service))["item_error_observations"] == []
    await service.invalidate("alice", event_id="exclude-wrong", invalidates_event_id=history[0].event_id)
    assert (await export_evidence_summary("alice", student_state=service))["active_misconceptions"] == []
