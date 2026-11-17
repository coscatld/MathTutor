import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager, closing
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from test_phase5_e2e_offer_flow import _client

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state, reset_product_state
from mathtutor.application.exploration import ExplorationService
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.exploration_schema import metadata
from mathtutor.infrastructure.secret_store import InMemorySecretStore
from mathtutor.infrastructure.zhihu import (
    ENV_SECRET,
    ZhihuClient,
    ZhihuError,
    secret_name,
)
from mathtutor.repositories.exploration_repository import ExplorationConflict
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope

BASE = "/api/v2/math-tutor/desktop"
PREFIX = BASE + "/exploration"
TEST_SECRET = "test-only-zhihu-secret"
ITEM = {"ContentID": "123", "ContentType": "Answer", "Title": "根式的条件",
        "AuthorName": "测试作者", "ContentText": "当 x<0 时，√(x²)=-x。<script>alert(1)</script>",
        "Url": "https://www.zhihu.com/question/99/answer/123?utm_source=test"}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv(ENV_SECRET, raising=False)
    reset_product_state()
    yield
    reset_product_state()


def body(**changes):
    return {"inquiry_id": str(uuid4()), "generation": 0, "question": "√(x²)什么时候等于x？",
            "goal": "compare", **changes}


def install(client):
    calls = []

    def transport(request):
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer " + TEST_SECRET
        assert request.url.host == "developer.zhihu.com"
        if request.method == "GET":
            return httpx.Response(200, json={"Code": 0, "Data": {"Items": [ITEM], "SearchHashId": "trace"}})
        request_json = json.loads(request.content)
        assert set(request_json) == {"model", "stream", "messages"}
        spans = json.loads(request_json["messages"][1]["content"].split("\n")[1])["excerpts"]
        candidate = {"selections": [{"span_id": spans[0]["span_id"], "lens": "conditions"}]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(candidate)}}]})

    get_product_state().exploration.client.transport = httpx.MockTransport(transport)
    response = client.put(PREFIX + "/configuration", json={"api_key": TEST_SECRET})
    assert response.status_code == 200
    assert TEST_SECRET not in response.text
    return calls


def op(view, **changes):
    return {"revision": view["revision"], **changes}


def test_configuration_is_secret_free_owner_scoped_and_validation_never_echoes(tmp_path, monkeypatch):
    with _client(tmp_path / "explore.db") as client:
        assert client.post(PREFIX + "/inquiries", json=body()).status_code == 409
        for invalid in ({"api_key": [TEST_SECRET]}, {"api_key": TEST_SECRET * 400},
                        {"api_key": TEST_SECRET, "unexpected": TEST_SECRET}):
            response = client.put(PREFIX + "/configuration", json=invalid)
            assert response.status_code == 422 and TEST_SECRET not in response.text
        install(client)
        assert client.get(PREFIX + "/configuration").json()["has_saved_secret"]
        client.app.dependency_overrides[require_student_owner] = lambda: StudentOwnerScope(
            principal=PrincipalScope(user_id="bob", username="bob", role="student"), student_id="bob")
        assert not client.get(PREFIX + "/configuration").json()["configured"]
        client.app.dependency_overrides.clear()
        monkeypatch.setenv(ENV_SECRET, "environment-test-secret")
        response = client.delete(PREFIX + "/configuration")
        assert response.json() == {"configured": True, "environment_managed": True,
                                   "persistent": False, "has_saved_secret": False}
        assert "environment-test-secret" not in response.text


def test_full_inquiry_round_trip_checks_conflicts_ownership_and_restart(tmp_path):
    db = tmp_path / "explore.db"
    create = body()
    url = PREFIX + "/inquiries/" + create["inquiry_id"]
    with _client(db) as client:
        calls = install(client)
        response = client.post(PREFIX + "/inquiries", json=create)
        assert response.status_code == 200, response.text
        first = response.json()
        assert first["question"] == create["question"]
        assert first["evidence"]["cards"][0]["quote"] == ITEM["ContentText"]
        assert first["evidence"]["cards"][0]["original_url"] == ITEM["Url"]
        assert "answer" not in first["learning"]["check"]
        assert client.post(PREFIX + "/inquiries", json=create).json() == first and len(calls) == 1
        assert client.post(PREFIX + "/inquiries", json={**create, "goal": "apply"}).status_code == 409
        view = client.post(url + "/organize", json=op(first)).json()
        assert view["ai_status"] == "ready" and view["organization_attempts"] == 1
        assert view["evidence"]["cards"][0]["reading_question"] == "这段材料的说法依赖哪些条件？"
        assert client.put(url + "/reflection", json=op(first, reflection="stale")).status_code == 409
        view = client.put(url + "/reflection", json=op(view, reflection="先检查符号条件。 ")).json()
        assert view["reflection"] == "先检查符号条件。 "
        check_id = view["learning"]["check"]["check_id"]
        assert client.post(url + "/response", json=op(view, check_id=check_id, answer="3", correct=True)).status_code == 422
        unknown = client.post(url + "/response", json=op(view, check_id=check_id, answer="3+0")).json()
        assert unknown["last_correctness"] == "unknown" and unknown["learning"]["check"]["check_id"] == check_id
        explained = client.post(url + "/explanation", json=op(unknown, check_id=check_id)).json()
        assert explained["last_correctness"] == "explanation"
        assert explained["last_check"]["check_id"] == check_id
        assert explained["learning"]["independent_successes"] == 0
        assert client.post(url + "/response", json=op(explained, check_id=check_id, answer="3")).status_code == 409
        next_check = explained["learning"]["check"]
        assert next_check["check_id"] == "root.condition"
        view = client.post(url + "/response", json=op(explained, check_id=next_check["check_id"], answer="B")).json()
        assert view["last_correctness"] == "correct" and view["learning"]["independent_successes"] == 1
        assert client.get(BASE + "/student-summary").json()["total_attempts"] == 0
        client.app.dependency_overrides[require_student_owner] = lambda: StudentOwnerScope(
            principal=PrincipalScope(user_id="bob", username="bob", role="student"), student_id="bob")
        assert client.get(url).status_code == 404
        assert not client.get(PREFIX + "/inquiries").json()["items"]
        assert client.delete(url).status_code == 200
        client.app.dependency_overrides.clear()
        assert client.get(url).json()["reflection"] == view["reflection"]
    reset_product_state()
    with _client(db) as client:
        assert client.get(url).json() == view
        english = client.get(url + "?language=en").json()
        assert english["learning"]["check"]["prompt"].startswith("For t")
        assert english["last_check"]["prompt"].startswith("For real x")
        assert english["last_feedback"].startswith("This answer is correct.")
        assert english["evidence"]["cards"][0]["reading_question"] == "Which conditions does this excerpt's statement depend on?"
        assert english["question"] == create["question"]
        assert english["evidence"]["cards"][0]["quote"] == ITEM["ContentText"]
    with closing(sqlite3.connect(db)) as conn:
        assert TEST_SECRET not in conn.execute("SELECT payload FROM exploration_inquiries").fetchone()[0]


def test_failed_organization_is_bounded_and_privacy_delete_prevents_stale_create(tmp_path):
    with _client(tmp_path / "explore.db") as client:
        calls = install(client)
        create = body()
        view = client.post(PREFIX + "/inquiries", json=create).json()
        url = PREFIX + "/inquiries/" + view["inquiry_id"]
        get_product_state().exploration.client.transport = httpx.MockTransport(
            lambda request: httpx.Response(429, text=TEST_SECRET))
        for attempt in (1, 2):
            view = client.post(url + "/organize", json=op(view)).json()
            assert view["ai_status"] == "unavailable" and view["organization_attempts"] == attempt
            assert view["evidence"]["cards"][0]["quote"] == ITEM["ContentText"]
        assert client.post(url + "/organize", json=op(view)).status_code == 409
        deleted = client.post(BASE + "/privacy/educational-history")
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["by_table"]["exploration_inquiries"] == 1
        assert client.get(url).status_code == 404
        assert client.get(PREFIX + "/inquiries").json() == {"generation": 1, "items": []}
        assert client.post(PREFIX + "/inquiries", json=create).status_code == 409
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response,kind", [
    (httpx.Response(401, text=TEST_SECRET), "credential_invalid"),
    (httpx.Response(429, text=TEST_SECRET), "rate_limited"),
    (httpx.Response(302, headers={"Location": "https://elsewhere.invalid"}), "unavailable"),
    (httpx.Response(200, text="{"), "invalid_response"),
    (httpx.Response(200, text='{"a":' * 1500 + '0' + '}' * 1500), "invalid_response"),
    (httpx.Response(200, content=json.dumps({"Code": 0, "Data": {"Items": [{**ITEM, "Title": "\ud800"}]}}).encode()), "invalid_response"),
    (httpx.Response(200, content=b"x" * 2_000_001), "response_too_large"),
    (httpx.Response(200, json={"Code": False, "Data": {"Items": []}}), "unavailable"),
    (httpx.Response(200, json={"Code": 20001, "Message": TEST_SECRET}), "credential_invalid"),
])
async def test_provider_errors_are_bounded_and_never_echo_credentials(response, kind):
    store = InMemorySecretStore()
    await store.put(secret_name("alice"), TEST_SECRET)
    seen = []

    def handle(request):
        seen.append(request)
        return response

    client = ZhihuClient(store, transport=httpx.MockTransport(handle), clock=lambda: 123)
    with pytest.raises(ZhihuError) as error:
        await client.search("alice", "根式的条件")
    assert error.value.kind == kind and TEST_SECRET not in str(error.value)
    assert len(seen) == 1 and seen[0].headers["X-Request-Timestamp"] == "123"


@pytest.mark.asyncio
@pytest.mark.parametrize("candidate", [
    {"selections": [{"span_id": "known", "lens": "conditions", "reading_question": "连续不一定可导是错误命题吗？"}]},
    {"selections": [{"span_id": "known", "lens": "verified"}]},
    {"selections": [{"span_id": "known", "lens": "conditions"}], "claims": [{"text": "invented"}]},
    {"selections": []},
])
async def test_model_cannot_publish_freeform_questions_claims_or_truth_labels(candidate):
    store = InMemorySecretStore()
    await store.put(secret_name("alice"), TEST_SECRET)
    client = ZhihuClient(store, transport=httpx.MockTransport(lambda request: httpx.Response(200,
        json={"choices": [{"message": {"content": json.dumps(candidate)}}]})))
    with pytest.raises(ZhihuError, match="原始材料"):
        await client.propose("alice", question="连续和可导", goal="compare", spans=[], language="zh")


@pytest.mark.asyncio
async def test_model_can_select_a_reading_lens_but_questions_are_application_owned():
    store = InMemorySecretStore()
    await store.put(secret_name("alice"), TEST_SECRET)
    candidate = {"selections": [{"span_id": "known", "lens": "reasoning"}],
                 "comparisons": [{"span_ids": ["known", "second"], "lens": "conditions"}]}
    client = ZhihuClient(store, transport=httpx.MockTransport(lambda request: httpx.Response(200,
        json={"choices": [{"message": {"content": json.dumps(candidate)}}]})))
    result = await client.propose("alice", question="连续和可导", goal="compare", spans=[], language="en")
    assert result["selections"][0]["span_id"] == "known"
    assert result["selections"][0]["reading_question"] == "Which reasoning steps are given here, and which need checking?"
    assert result["comparisons"][0]["relation"] == "unresolved"


@pytest.mark.asyncio
async def test_disconnected_search_cancels_network_releases_lock_and_writes_nothing(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from mathtutor.api import exploration_api

    engine = create_db_engine(tmp_path / "cancel.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    store = InMemorySecretStore()
    await store.put(secret_name("alice"), TEST_SECRET)
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def slow(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    service = ExplorationService(engine, store, client=ZhihuClient(store, transport=httpx.MockTransport(slow)))
    lock = asyncio.Lock()

    @asynccontextmanager
    async def owner_lock(owner):
        async with lock:
            yield

    state = SimpleNamespace(exploration=service, turn_requests=SimpleNamespace(owner=owner_lock))
    monkeypatch.setattr(exploration_api, "get_product_state", lambda: state)

    async def disconnected():
        return started.is_set()

    create = body()
    try:
        with pytest.raises(HTTPException) as error:
            await exploration_api.invoke(SimpleNamespace(student_id="alice"),
                lambda state, sid: service.create(sid, **create), SimpleNamespace(is_disconnected=disconnected))
        assert error.value.status_code == 499 and cancelled.is_set() and not lock.locked()
        assert (await service.repository.list("alice"))["items"] == []
        await service.repository.delete("alice", create["inquiry_id"])
        with pytest.raises(ExplorationConflict):
            await service.repository.save("alice", create["inquiry_id"], {"question": "old", "goal": "understand"},
                                          expected_revision=0, expected_generation=0)
    finally:
        await engine.dispose()
