import asyncio
import hashlib
import json
import time

import pytest

from mathtutor.application.learning_actions import load_catalog, plan_learning_actions
from mathtutor.application.recommendations import RecommendationsService, _source_time
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.recommendation_schema import metadata as recommendation_metadata
from mathtutor.infrastructure.zhihu import ZhihuError
from mathtutor.learning.knowledge_tracing.events import LearningEvent
from mathtutor.learning.knowledge_tracing.schema import learning_events, metadata as learning_metadata
from mathtutor.learning.knowledge_tracing.service import StudentStateService


def catalog():
    excerpt = "学习等式时，必须对两边同时进行相同的合法运算。"
    return {"version": "test-v1", "resources": [dict(
        resource_id="fixture-equality", title="测试教学片段", author="测试作者",
        url="https://www.zhihu.com/question/100/answer/101", summary=excerpt,
        knowledge_points=["equality_preservation", "math_foundations"], prerequisites=["signed_operations"],
        tags=["等式"], recommendation_reason="解释等式的合法变形", published_at=None, source_time=None,
        source_time_kind="unknown", review={"status": "accepted", "scope": "search_excerpt", "method": "fixture",
            "gates": {str(i): "pass" for i in range(6)}},
        provenance={"excerpt": excerpt, "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
                    "retrieved_at": "2026-11-18T00:00:00+00:00", "request_id": "fixture"})]}


def event(number=1, skill="equality_preservation", correctness="incorrect", kind="independent", **extra):
    return LearningEvent(event_id=f"event-{number}", student_id="alice", session_id=f"session-{number}",
        cycle_id=f"cycle-{number}", event_seq=number, event_type="attempt_assessed", problem_id=f"problem-{number}",
        problem_revision=f"revision-{number}", item_family_id="linear", skill_ids=(skill,), assessment_id=f"assessment-{number}",
        attempt_id=f"attempt-{number}", correctness=correctness, evidence_kind=kind, **extra)


def test_prerequisite_difficulty_is_localized_and_has_real_evidence():
    plan = plan_learning_actions([event(0, skill="signed_operations", correctness="correct"), event()], "linear_isolation", catalog())
    assert (plan["target"], plan["action"], plan["reason_code"]) == (
        "equality_preservation", "review_prerequisite", "prerequisite_difficulty")
    assert plan["evidence_ids"] == ["event-1"]
    assert plan["resources"][0]["resource_id"] == "fixture-equality"


def test_unknown_and_assisted_are_not_failed_or_mastered():
    empty = plan_learning_actions([], "equality_preservation", catalog())
    assisted = plan_learning_actions([event(correctness="correct", kind="assisted")], "equality_preservation", catalog())
    assert empty["reason_code"] == "prerequisite_unconfirmed" and not empty["evidence_ids"]
    assert assisted["action"] == "check" and assisted["reason_code"] == "assisted_observation"
    assert "mastery" not in assisted


def test_independent_success_and_invalidation_replay():
    history = [event(), event(2, correctness="correct")]
    assert plan_learning_actions(history, "equality_preservation", catalog())["action"] == "continue"
    invalidate = history[0].model_copy(update={"event_id": "invalidate", "event_seq": 3,
        "event_type": "evidence_invalidated", "correctness": None, "invalidates_event_id": "event-2"})
    assert plan_learning_actions([*history, invalidate], "equality_preservation", catalog())["reason_code"] == "independent_difficulty"


def test_joint_answer_does_not_diagnose_component_or_outside_scope():
    joint = event().model_copy(update={"skill_ids": ("equality_preservation", "linear_isolation")})
    plan = plan_learning_actions([joint], "linear_isolation", catalog())
    assert plan["reason_code"] == "task_needs_review"
    assert not any(row["observed"] for row in plan["prerequisites"])
    advanced = plan_learning_actions([event(correctness="correct")], "calculus", catalog())
    assert advanced["reason_code"] == "outside_assessment_scope" and advanced["action"] == "explore"


def test_catalog_integrity_and_no_popularity_ranking(tmp_path):
    path = tmp_path / "catalog.json"
    value = catalog()
    path.write_text(json.dumps(value))
    assert load_catalog(path) == value
    value["resources"][0]["votes"] = 999999
    assert plan_learning_actions([], "equality_preservation", value)["resources"] == []
    assert plan_learning_actions([event(skill="signed_operations", correctness="correct")],
                                 "equality_preservation", value)["resources"][0]["selection_reason"]
    value["resources"][0]["provenance"]["excerpt"] += "changed"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="verifiable excerpt"):
        load_catalog(path)


class Client:
    def __init__(self):
        self.calls = []
        self.block = None
        self.error = None
        self.configured = True

    async def configuration(self, owner):
        return {"configured": self.configured}

    async def search(self, owner, query, *, count):
        self.calls.append((owner, query))
        if self.block:
            await self.block.wait()
        if self.error:
            raise self.error
        return {"Items": [{"ContentID": "222", "ContentType": "Answer", "Title": "有理数与等式的学习",
            "AuthorName": "测试作者", "Url": "https://www.zhihu.com/question/111/answer/222",
            "ContentText": "有理数的符号需要结合加减乘除的定义理解。等式变形应对两边进行同样的合法操作。" * 4}],
            "SearchHashId": "test-request"}


@pytest.fixture
async def service(tmp_path):
    engine = create_db_engine(tmp_path / "discovery.db")
    async with engine.begin() as conn:
        await conn.run_sync(learning_metadata.create_all)
        await conn.run_sync(recommendation_metadata.create_all)
    instance = RecommendationsService(engine, StudentStateService(engine), Client(), catalog=catalog())
    yield instance
    await instance.close()
    await engine.dispose()


async def add_event(service, item):
    async with service.repository.engine.begin() as conn:
        await conn.execute(learning_events.insert().values(student_id=item.student_id, event_id=item.event_id,
            event_seq=item.event_seq, event_type=item.event_type, cycle_id=item.cycle_id, payload=item.model_dump(mode="json")))


async def finish_tasks(service):
    tasks = [task for _, task in service.tasks.values()]
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_offline_default_and_shared_plan_do_not_write_evidence(service):
    await add_event(service, event())
    before = await service.student_state.events("alice")
    view = await service.start("alice")
    assert view["status"] == "disabled" and not service.client.calls
    shared = await service.plan_for("alice", "linear_isolation")
    assert shared["target"] == "equality_preservation"
    assert before == await service.student_state.events("alice")


async def test_nonblocking_coalescing_and_durable_cache(service):
    await service.configure("alice", enabled=True, goal="math_foundations")
    service.client.block = asyncio.Event()
    started = time.perf_counter()
    views = await asyncio.gather(*(service.start("alice") for _ in range(5)))
    assert time.perf_counter() - started < 1
    assert all(view["status"] == "running" for view in views)
    assert len(service.client.calls) == 1
    service.client.block.set()
    await finish_tasks(service)
    view = await service.get("alice")
    assert view["status"] == "cached" and view["discovery"]["resources"]
    restarted = RecommendationsService(service.repository.engine, service.student_state, service.client, catalog=catalog())
    try:
        assert (await restarted.start("alice"))["status"] == "cached"
        assert len(service.client.calls) == 1
    finally:
        await restarted.close()


async def test_owner_isolation_and_only_public_topic_leaves(service):
    await add_event(service, event().model_copy(update={"session_id": "PRIVATE_SESSION", "problem_id": "PRIVATE_PROBLEM"}))
    await service.configure("alice", enabled=True, goal="linear_isolation")
    await service.start("alice")
    await finish_tasks(service)
    alice, bob = await service.get("alice"), await service.get("bob")
    assert alice["discovery"] and bob["discovery"] is None and not bob["plan"]["evidence_ids"]
    assert service.client.calls == [("alice", "等式两边同做运算 学习 理解 例子")]
    assert "PRIVATE" not in json.dumps(service.client.calls)


async def test_profile_revision_rejects_old_job_and_cached_reason(service):
    await service.configure("alice", enabled=True, goal="math_foundations")
    service.client.block = asyncio.Event()
    await service.start("alice")
    await asyncio.sleep(0)
    await add_event(service, event())
    service.client.block.set()
    await finish_tasks(service)
    assert (await service.get("alice"))["discovery"] is None


async def test_changed_profile_replaces_pending_lease_within_budget(service):
    await service.configure("alice", enabled=True, goal="math_foundations")
    service.client.block = asyncio.Event()
    await service.start("alice")
    await asyncio.sleep(0)
    old_token, old_task = service.tasks["alice"]
    await add_event(service, event())
    assert (await service.start("alice"))["status"] == "running"
    new_token, _ = service.tasks["alice"]
    assert new_token != old_token
    service.client.block.set()
    await asyncio.gather(old_task, return_exceptions=True)
    await finish_tasks(service)
    view = await service.get("alice")
    assert view["status"] == "cached" and len(service.client.calls) == 2
    assert view["discovery"]["query"] == "等式两边同做运算 学习 理解 例子"
    await service.start("alice")
    await finish_tasks(service)
    assert (await service.get("alice"))["status"] == "cached"
    await add_event(service, event(2, correctness="correct"))
    assert (await service.get("alice"))["discovery"] is None


async def test_config_change_and_delete_reject_old_lease(service):
    await service.configure("alice", enabled=True, goal="math_foundations")
    row = await service.repository.get("alice")
    token = await service.repository.reserve("alice", generation=row["generation"], cache_key="old", now=service.clock())
    await service.configure("alice", enabled=True, goal="calculus")
    assert not await service.repository.finish("alice", token=token, generation=row["generation"], cache_key="old",
        payload={"private": "old"}, expected_stamp=(0, 0), now=service.clock())
    row = await service.repository.get("alice")
    token = await service.repository.reserve("alice", generation=row["generation"], cache_key="delete", now=service.clock())
    await service.delete("alice")
    assert not await service.repository.finish("alice", token=token, generation=row["generation"], cache_key="delete",
        payload={"private": "old"}, expected_stamp=(0, 0), now=service.clock())
    assert (await service.get("alice"))["status"] == "disabled"


async def test_daily_budget_counts_failures_and_survives_delete(service):
    await service.configure("alice", enabled=True, goal="math_foundations")
    service.client.error = ZhihuError("unavailable", "test")
    for _ in range(4):
        await service.start("alice")
        await finish_tasks(service)
    assert len(service.client.calls) == 2
    assert (await service.get("alice"))["status"] == "rate_limited"
    await service.delete("alice")
    await service.configure("alice", enabled=True, goal="calculus")
    assert (await service.start("alice"))["status"] == "rate_limited"
    assert len(service.client.calls) == 2


async def test_timeout_and_missing_key_leave_local_plan_usable(service):
    await service.configure("alice", enabled=True, goal="math_foundations")
    service.client.configured = False
    assert (await service.start("alice"))["status"] == "not_configured"
    assert not service.client.calls
    service.client.configured = True
    service.timeout = 0.01
    service.client.block = asyncio.Event()
    await service.start("alice")
    await finish_tasks(service)
    view = await service.get("alice")
    assert view["status"] == "failed" and view["plan"]["title"]


async def test_two_service_instances_coalesce_without_shared_task_map(service):
    await service.configure("alice", enabled=True, goal="math_foundations")
    service.client.block = asyncio.Event()
    second = RecommendationsService(service.repository.engine, service.student_state, service.client, catalog=catalog())
    try:
        await asyncio.gather(service.start("alice"), second.start("alice"))
        await asyncio.sleep(0)
        assert len(service.client.calls) == 1
        service.client.block.set()
        await finish_tasks(service)
        await finish_tasks(second)
    finally:
        await second.close()


async def test_public_topic_aliases_accept_probability_excerpt(service):
    async def search(owner, query, *, count):
        return {"Items": [{"ContentID": "333", "ContentType": "Answer", "Title": "条件概率的意义",
            "AuthorName": "测试作者", "Url": "https://www.zhihu.com/question/111/answer/333",
            "ContentText": "条件概率讨论获得新信息后事件概率如何改变。先限定条件事件，再比较其中满足目标条件的结果。" * 3}],
            "SearchHashId": "probability-fixture"}
    service.client.search = search
    await service.configure("alice", enabled=True, goal="probability")
    await service.start("alice")
    await finish_tasks(service)
    assert (await service.get("alice"))["discovery"]["resources"][0]["title"] == "条件概率的意义"


@pytest.mark.parametrize("value", [None, 0, -1, True, 1.5, "1710000000", "2024-03-09", 10 ** 100])
def test_malformed_source_time_remains_unknown(value):
    assert _source_time(value) is None


@pytest.mark.parametrize("value,expected", [(1710000000, "2024-03-09T16:00:00+00:00"), ("1710000000", None), (True, None)])
async def test_discovery_converts_documented_epoch_to_utc_and_preserves_date_ambiguity(service, value, expected):
    original = service.client.search
    async def search(owner, query, *, count):
        result = await original(owner, query, count=count)
        result["Items"][0]["EditTime"] = value
        return result
    service.client.search = search
    await service.configure("alice", enabled=True, goal="math_foundations")
    await service.start("alice")
    await finish_tasks(service)
    source = (await service.get("alice"))["discovery"]["resources"][0]
    assert source["source_time"] == expected
    assert source["source_time_kind"] == ("published_or_updated" if expected else "unknown")
    assert "published_at" not in source
