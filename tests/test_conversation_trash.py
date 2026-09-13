import sqlite3
import pytest
from test_tutor_p0 import client_at, send
from mathtutor.api.product_state import get_product_state
from mathtutor.repositories.conversation_repository import InMemoryConversationRepository

BASE = "/api/v2/math-tutor"


def seed(client, cid, owner="local-admin", attachments=None):
    async def write():
        await get_product_state().conversations.append_message(
            owner, cid, role="student", content="保留的对话 " + cid, attachments=attachments)
    client.portal.call(write)


def test_trash_retains_messages_restart_restore_and_blocks_stale_urls(tmp_path):
    db = tmp_path / "trash.db"
    with client_at(db) as client:
        seed(client, "A")
        seed(client, "B")
        assert client.delete(BASE + "/sessions/A").status_code == 200
        assert [r["conversation_id"] for r in client.get(BASE + "/sessions").json()] == ["B"]
        assert client.get(BASE + "/sessions/A").status_code == 410
        assert client.post(BASE + "/sessions", json={"conversation_id": "A"}).status_code == 410
        with client.websocket_connect(BASE + "/ws") as ws:
            frames = send(ws, "send_message", "stale", {"text": "不得写入"}, session="A")
        assert any(f["payload"].get("error_code") == "CONVERSATION_DELETED" for f in frames)
        with sqlite3.connect(db) as conn:
            assert conn.execute("select count(*) from conversation_messages where conversation_id='A'").fetchone()[0] == 1
    with client_at(db) as client:
        assert [r["conversation_id"] for r in client.get(BASE + "/trash").json()] == ["A"]
        assert client.post(BASE + "/trash/A/restore").status_code == 200
        assert len(client.get(BASE + "/sessions").json()) == 2
        assert client.get(BASE + "/sessions/A").json()["messages"][0]["content"] == "保留的对话 A"


def test_permanent_delete_exclusive_attachments_but_retain_shared_and_global(tmp_path):
    db = tmp_path / "purge.db"
    with client_at(db) as client:
        async def image():
            return await get_product_state().images.put("local-admin", b"\x89PNG\r\n\x1a\nTEST", "image/png", "test.png")
        exclusive = client.portal.call(image)
        shared = client.portal.call(image)
        seed(client, "A", attachments=[exclusive, shared])
        seed(client, "B", attachments=[shared])
        docs = []
        for name in ["exclusive", "shared", "global"]:
            response = client.post(BASE + "/desktop/documents/import?conversation_id=A",
                files={"file": (name + ".txt", (name + " Meaningful math learning notes.").encode(), "text/plain")})
            assert response.status_code == 200
            docs.append(response.json()["document_id"])
        client.post(BASE + f"/desktop/conversations/B/documents/{docs[1]}")
        client.patch(BASE + f"/desktop/documents/{docs[2]}/scope", json={"is_global": True})
        assert client.delete(BASE + "/trash/A").status_code == 409
        assert client.delete(BASE + "/sessions/A").status_code == 200
        visible = client.get(BASE + "/desktop/documents").json()
        assert docs[0] not in [d["document_id"] for d in visible]
        assert client.get(BASE + "/desktop/conversations/A/resources").status_code == 410
        assert client.delete(BASE + "/trash/A").status_code == 200
        assert client.get(BASE + "/trash").json() == []
        assert client.post(BASE + "/trash/A/restore").status_code == 404
        assert client.get(BASE + "/sessions/A").status_code == 410
        assert client.get(BASE + f"/images/{exclusive['id']}").status_code == 404
        assert client.get(BASE + f"/images/{shared['id']}").status_code == 200
        assert client.get(BASE + f"/desktop/documents/{docs[0]}").status_code == 404
        for doc in docs[1:]:
            assert client.get(BASE + f"/desktop/documents/{doc}").status_code == 200
        with sqlite3.connect(db) as conn:
            assert conn.execute("select count(*) from conversation_messages where conversation_id='A'").fetchone()[0] == 0
            assert conn.execute("select count(*) from conversation_documents where conversation_id='A'").fetchone()[0] == 0
            assert conn.execute("select count(*) from document_chunks where document_id=?", (docs[0],)).fetchone()[0] == 0
    with client_at(db) as client:
        assert client.get(BASE + "/trash").json() == []
        assert client.post(BASE + "/sessions", json={"conversation_id": "A"}).status_code == 410


def test_trash_owner_isolation(tmp_path):
    with client_at(tmp_path / "owners.db") as client:
        seed(client, "foreign", owner="other-student")
        for method, path in [("delete", "/sessions/foreign"), ("delete", "/trash/foreign"), ("post", "/trash/foreign/restore")]:
            assert getattr(client, method)(BASE + path).status_code == 404
        assert client.get(BASE + "/trash").json() == []


def test_busy_conversation_cannot_be_deleted(tmp_path):
    with client_at(tmp_path / "busy.db") as client:
        seed(client, "A")
        state = get_product_state()
        # Exercise the actual lock used by WebSocket generation.
        manager = state.turn_requests.conversation("local-admin", "A")
        client.portal.call(manager.__aenter__)
        try:
            response = client.delete(BASE + "/sessions/A")
            assert response.status_code == 409
        finally:
            client.portal.call(manager.__aexit__, None, None, None)
        assert len(client.get(BASE + "/sessions").json()) == 1


@pytest.mark.asyncio
async def test_memory_repository_matches_durable_trash_contract():
    repo = InMemoryConversationRepository()
    await repo.append_message("s", "c", role="student", content="test")
    await repo.set_trash("s", "c", True)
    assert not await repo.list("s")
    assert len(await repo.list("s", trashed=True)) == 1
    assert len(await repo.messages("s", "c")) == 1
    await repo.set_trash("s", "c", False)
    assert len(await repo.list("s")) == 1
    await repo.set_trash("s", "c", True)
    await repo.purge("s", "c")
    assert not await repo.list("s", trashed=True)
    assert not await repo.messages("s", "c")
