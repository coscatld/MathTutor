import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from test_tutor_p0 import client_at

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.zhihu import ZhihuClient, ZhihuError
from mathtutor.learning.knowledge_tracing.events import LearningEvent
from mathtutor.learning.knowledge_tracing.schema import learning_events
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope

ROOT = "/api/v2/math-tutor/desktop"
RECOMMENDATIONS = ROOT + "/recommendations"
OWNER = "local-admin"


class DiscoveryClient:
    def __init__(self):
        self.calls = []
        self.release = None
        self.entered = asyncio.Event()
        self.error = None
        self.configuration_reads = 0

    async def configuration(self, owner):
        self.configuration_reads += 1
        return {"configured": True}

    async def search(self, owner, query, *, count):
        self.calls.append((owner, query))
        if self.release is not None:
            self.entered.set()
            await self.release.wait()
        if self.error:
            raise self.error
        return {"SearchHashId": "controlled-discovery", "Items": [{
            "ContentID": "222", "ContentType": "Answer", "Title": "等式与有理数的理解",
            "Url": "https://www.zhihu.com/question/111/answer/222", "AuthorName": "测试资料作者",
            "ContentText": "等式变形需要对两边同时进行相同的合法运算。有理数的加减乘除需要检查符号与运算顺序。" * 3,
        }]}


def owner(client, sid=OWNER):
    client.app.dependency_overrides[require_student_owner] = lambda: StudentOwnerScope(
        principal=PrincipalScope(user_id=sid, username=sid, role="student"), student_id=sid)


async def install():
    service = get_product_state().recommendations
    service.client = DiscoveryClient()
    now = [1735689600.0]
    service.clock = lambda: now[0]
    item = LearningEvent(event_id="verified-equality-observation", student_id=OWNER,
        session_id="observed-session", cycle_id="observed-cycle", event_seq=1,
        event_type="attempt_assessed", problem_id="observed-problem", problem_revision="observed-revision",
        item_family_id="linear", skill_ids=("equality_preservation",), assessment_id="server-assessment",
        attempt_id="student-attempt", correctness="incorrect", evidence_kind="independent")
    async with service.repository.engine.begin() as conn:
        await conn.execute(learning_events.insert().values(student_id=OWNER, event_id=item.event_id,
            event_seq=item.event_seq, event_type=item.event_type, cycle_id=item.cycle_id, payload=item.model_dump(mode="json")))
    return service, now, item.event_id


async def finish(service):
    tasks = list(service.running)
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=2)


async def prepare_slow_refresh(service):
    service.client.release = asyncio.Event()
    service.client.entered.clear()


async def wait_entered(service):
    await asyncio.wait_for(service.client.entered.wait(), timeout=2)


def populate(client, service, *, sid=OWNER, goal="linear_isolation"):
    owner(client, sid)
    response = client.put(RECOMMENDATIONS + "/configuration", json={"enabled": True, "goal": goal})
    assert response.status_code == 200, response.text
    assert client.post(RECOMMENDATIONS + "/start").status_code == 200
    client.portal.call(finish, service)
    response = client.get(RECOMMENDATIONS)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "cached"
    return response.json()


@pytest.mark.parametrize("operation", ["exclude", "educational_history"])
def test_real_evidence_removal_clears_cached_basis_and_rejects_late_discovery(tmp_path, operation):
    database = tmp_path / "lifecycle.db"
    with client_at(database) as client:
        service, now, event_id = client.portal.call(install)
        bob = populate(client, service, sid="bob", goal="probability")
        before = populate(client, service)
        assert before["plan"]["reason_code"] == "prerequisite_difficulty"
        assert before["plan"]["evidence_ids"] == [event_id]
        assert before["discovery"]["resources"]
        now[0] += 6 * 60 * 60 + 1
        client.portal.call(prepare_slow_refresh, service)
        assert client.post(RECOMMENDATIONS + "/start").json()["status"] == "running"
        client.portal.call(wait_entered, service)

        path = (ROOT + f"/student-evidence/{event_id}/exclude" if operation == "exclude"
                else ROOT + "/privacy/educational-history")
        response = client.post(path)
        assert response.status_code == 200, response.text
        if operation == "educational_history":
            assert response.json()["by_table"]["learning_events"] == 1
        after = client.get(RECOMMENDATIONS).json()
        assert after["discovery"] is None and not after["plan"]["evidence_ids"]
        assert after["plan"]["reason_code"] == ("prerequisite_unconfirmed" if operation == "exclude" else "unobserved")
        assert after["enabled"] is (operation == "exclude")
        assert after["goal"] == ("linear_isolation" if operation == "exclude" else "math_foundations")
        row = client.portal.call(service.repository.get, OWNER)
        assert row["payload"] == {} and row["cache_key"] == "" and row["lease_token"] == ""
        assert row["budget_calls"] == 2

        client.portal.call(service.client.release.set)
        client.portal.call(finish, service)
        assert client.get(RECOMMENDATIONS).json() == after
        assert client.portal.call(service.repository.get, OWNER)["payload"] == {}
        history = client.portal.call(service.student_state.events, OWNER)
        assert len(history) == (2 if operation == "exclude" else 0)
        owner(client, "bob")
        other = client.get(RECOMMENDATIONS).json()
        assert other["discovery"] == bob["discovery"]
        assert other["goal"] == "probability" and other["enabled"] is True

    with client_at(database) as client:
        owner(client)
        persisted = client.get(RECOMMENDATIONS).json()
        assert persisted["discovery"] is None and not persisted["plan"]["evidence_ids"]
        assert persisted["enabled"] is (operation == "exclude")


def test_secret_store_failure_returns_local_plan_without_request_or_sensitive_error(tmp_path):
    class UnavailableSecrets:
        async def get(self, key):
            raise OSError("private-keychain-error-must-not-escape")

    calls = []
    def transport(request):
        calls.append(request)
        raise AssertionError("No external request should be made")

    with client_at(tmp_path / "secret-error.db") as client:
        owner(client)
        service = get_product_state().recommendations
        service.client = ZhihuClient(UnavailableSecrets(), transport=httpx.MockTransport(transport))
        assert client.put(RECOMMENDATIONS + "/configuration", json={"enabled": True, "goal": "probability"}).status_code == 200
        response = client.post(RECOMMENDATIONS + "/start")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "failed" and response.json()["plan"]["goal"] == "probability"
        assert response.json()["plan"]["reason_code"] == "outside_assessment_scope"
        assert "private-keychain" not in response.text and not calls
        row = client.portal.call(service.repository.get, OWNER)
        assert row["budget_calls"] == 0 and row["lease_token"] == ""


def test_slow_configuration_is_cancelled_without_search_or_budget_charge(tmp_path):
    with client_at(tmp_path / "configuration-timeout.db") as client:
        service, _, _ = client.portal.call(install)
        service.timeout = 0.01
        cancelled = asyncio.Event()
        async def configuration(owner):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        service.client.configuration = configuration
        owner(client)
        assert client.put(RECOMMENDATIONS + "/configuration", json={"enabled": True, "goal": "probability"}).status_code == 200
        response = client.post(RECOMMENDATIONS + "/start")
        assert response.status_code == 200 and response.json()["status"] == "failed"
        assert cancelled.is_set() and not service.client.calls and not service.running
        assert client.portal.call(service.repository.get, OWNER)["budget_calls"] == 0


def test_expired_cache_survives_failed_refresh_and_daily_budget_limit(tmp_path):
    with client_at(tmp_path / "expired-cache.db") as client:
        service, now, _ = client.portal.call(install)
        first = populate(client, service)
        now[0] += 6 * 60 * 60 + 1
        service.client.error = ZhihuError("unavailable", "controlled outage")
        assert client.post(RECOMMENDATIONS + "/start").status_code == 200
        client.portal.call(finish, service)
        failed = client.get(RECOMMENDATIONS).json()
        assert failed["status"] == "failed" and failed["discovery"] == first["discovery"]
        assert failed["updated_at"] == first["updated_at"] and failed["expires_at"] == first["expires_at"]
        limited = client.post(RECOMMENDATIONS + "/start").json()
        assert limited["status"] == "rate_limited" and limited["discovery"] == first["discovery"]
        assert len(service.client.calls) == 2


def test_active_lease_cache_and_exhausted_budget_skip_credential_reads(tmp_path):
    with client_at(tmp_path / "local-fast-paths.db") as client:
        service, now, _ = client.portal.call(install)
        owner(client)
        assert client.put(RECOMMENDATIONS + "/configuration", json={"enabled": True, "goal": "linear_isolation"}).status_code == 200
        client.portal.call(prepare_slow_refresh, service)
        assert client.post(RECOMMENDATIONS + "/start").json()["status"] == "running"
        client.portal.call(wait_entered, service)
        assert client.post(RECOMMENDATIONS + "/start").json()["status"] == "running"
        assert service.client.configuration_reads == 1
        client.portal.call(service.client.release.set)
        client.portal.call(finish, service)
        assert client.post(RECOMMENDATIONS + "/start").json()["status"] == "cached"
        assert service.client.configuration_reads == 1
        now[0] += 6 * 60 * 60 + 1
        service.client.error = ZhihuError("unavailable", "controlled failure")
        assert client.post(RECOMMENDATIONS + "/start").status_code == 200
        client.portal.call(finish, service)
        assert service.client.configuration_reads == 2
        assert client.post(RECOMMENDATIONS + "/start").json()["status"] == "rate_limited"
        assert client.get(RECOMMENDATIONS).json()["status"] == "rate_limited"
        assert service.client.configuration_reads == 2 and len(service.client.calls) == 2


def test_slow_credentials_release_chat_guard_and_deletion_cancels_old_topic(tmp_path):
    with client_at(tmp_path / "credentials-concurrency.db") as client:
        service, _, _ = client.portal.call(install)
        owner(client)
        assert client.put(RECOMMENDATIONS + "/configuration", json={"enabled": True, "goal": "linear_isolation"}).status_code == 200
        entered, release = asyncio.Event(), asyncio.Event()
        async def configuration(owner):
            entered.set()
            await release.wait()
            return {"configured": True}
        service.client.configuration = configuration
        async def wait_configuration():
            await asyncio.wait_for(entered.wait(), timeout=1)
        async def chat_lock_probe():
            async with get_product_state().turn_requests.conversation(OWNER, "chat-remains-usable"):
                return True
        async def bounded_probe():
            return await asyncio.wait_for(chat_lock_probe(), timeout=0.3)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client.post, RECOMMENDATIONS + "/start")
            try:
                client.portal.call(wait_configuration)
                assert client.portal.call(bounded_probe)
                assert not pending.done()
                deleted = client.post(ROOT + "/privacy/educational-history")
                assert deleted.status_code == 200, deleted.text
                assert deleted.json()["by_table"]["learning_events"] == 1
            finally:
                client.portal.call(release.set)
            response = pending.result(timeout=2)
        assert response.status_code == 200 and response.json()["status"] == "disabled"
        assert not service.client.calls and not service.running
        row = client.portal.call(service.repository.get, OWNER)
        assert row["budget_calls"] == 0 and not row["lease_token"] and not row["payload"]


async def test_close_during_configuration_does_not_schedule_or_charge_new_search(tmp_path):
    from mathtutor.application.recommendations import RecommendationsService
    from mathtutor.infrastructure.db import create_db_engine
    from mathtutor.infrastructure.recommendation_schema import metadata as recommendation_metadata
    from mathtutor.learning.knowledge_tracing.schema import metadata as learning_metadata
    from mathtutor.learning.knowledge_tracing.service import StudentStateService

    engine = create_db_engine(tmp_path / "closing.db")
    async with engine.begin() as conn:
        await conn.run_sync(learning_metadata.create_all)
        await conn.run_sync(recommendation_metadata.create_all)
    client = DiscoveryClient()
    entered, release = asyncio.Event(), asyncio.Event()
    async def configuration(owner):
        entered.set()
        await release.wait()
        return {"configured": True}
    client.configuration = configuration
    service = RecommendationsService(engine, StudentStateService(engine), client)
    pending = None
    try:
        await service.configure(OWNER, enabled=True, goal="math_foundations")
        pending = asyncio.create_task(service.start(OWNER))
        await asyncio.wait_for(entered.wait(), timeout=1)
        await service.close()
        release.set()
        assert (await pending)["status"] == "idle"
        assert not client.calls and not service.running
        assert (await service.repository.get(OWNER))["budget_calls"] == 0
    finally:
        release.set()
        if pending:
            await asyncio.gather(pending, return_exceptions=True)
        await service.close()
        await engine.dispose()
