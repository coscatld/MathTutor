import json
from test_tutor_p0 import client_at, send
from test_image_attachments import bind

BASE = "/api/v2/math-tutor/desktop"
FACT = "总资料专属事实：蓝色灯塔预算为九百七十三。"


def test_global_scope_is_explicit_durable_and_revocable(tmp_path):
    db = tmp_path / "global.db"
    with client_at(db) as client:
        doc = client.post(BASE + "/documents/import?conversation_id=A", files={"file": ("课程手册.txt", FACT.encode(), "text/plain")}).json()
        assert doc["is_global"] is False
        doc_id = doc["document_id"]
        calls = []
        bind(calls)
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            send(ws, "send_message", "private", {"text": "请解释我上传的文档"}, session="B")
        assert FACT not in json.dumps(calls, ensure_ascii=False)
        saved = client.patch(BASE + f"/documents/{doc_id}/scope", json={"is_global": True})
        assert saved.status_code == 200 and saved.json()["is_global"]
    with client_at(db) as client:
        assert client.get(BASE + "/documents").json()[0]["is_global"] is True
        assert len(client.get(BASE + "/documents?conversation_id=B").json()) == 1
        assert client.get(BASE + "/conversations/B/resources").json()["documents"][0]["is_global"]
        calls = []
        bind(calls)
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            send(ws, "send_message", "shared", {"text": "请解释课程手册"}, session="B")
        assert FACT in json.dumps(calls, ensure_ascii=False)
        assert client.patch(BASE + f"/documents/{doc_id}/retrieval", json={"enabled": False}).status_code == 200
        calls.clear()
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            send(ws, "send_message", "disabled", {"text": "请解释课程手册"}, session="C")
        assert FACT not in json.dumps(calls, ensure_ascii=False)
        assert client.patch(BASE + f"/documents/{doc_id}/scope", json={"is_global": False}).status_code == 200
        assert client.get(BASE + "/documents?conversation_id=B").json() == []
        assert client.get(BASE + "/documents?conversation_id=A").json()[0]["document_id"] == doc_id
        assert client.delete(BASE + f"/documents/{doc_id}").status_code in (200, 204)
        assert client.patch(BASE + f"/documents/{doc_id}/scope", json={"is_global": True}).status_code == 404
