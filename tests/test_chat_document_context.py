import io
import json
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_tutor_p0 import client_at, send
from test_image_attachments import PNG, bind
from test_image_attachments import provider
from mathtutor.infrastructure.tutor_chat import TutorChatResponder
from mathtutor.infrastructure.generative_gateway import GenerativeModelGateway, ModelRole
from mathtutor.infrastructure.secret_store import InMemorySecretStore
from mathtutor.infrastructure.vision import content_token_estimate
from mathtutor.application.chat_documents import ChatDocumentContext, MAX_CONTEXT_CHARS
from mathtutor.domain.documents import DocumentQueryResult, RetrievedChunk
from mathtutor.application.conversation_scope import set_document_scope, reset_document_scope
from mathtutor.application.knowledge import reference_configuration

PREFIX = "/api/v2/math-tutor/desktop"
FACT = "微网储能每日电价预算为独特样本甲乙丙。"


@pytest.mark.parametrize("with_image", [False, True])
def test_chat_rag_and_folder_survive_restart(tmp_path, with_image):
    db = tmp_path / "rag.db"
    calls = []
    with client_at(db) as client:
        doc = client.post(PREFIX + "/documents/import?conversation_id=p0", files={"file": ("C题.txt", FACT.encode(), "text/plain")})
        assert doc.status_code == 200, doc.text
        doc_id = doc.json()["document_id"]
        attachment = client.post("/api/v2/math-tutor/images", files={"file": ("../图.png", PNG, "image/png")}).json() if with_image else None
        bind(calls)
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            payload = {"text": "我指的是我上传的文档，你看不见吗"}
            if attachment:
                payload["attachment_ids"] = [attachment["id"]]
            frames = send(ws, "send_message", "rag1", payload)
            assert any(f["event_type"] == "assistant_complete" for f in frames)
        assert FACT in json.dumps(calls, ensure_ascii=False)
        assert "不可信参考数据" in json.dumps(calls, ensure_ascii=False)
        if with_image:
            assert calls[-1]["messages"][-1]["content"][1]["type"] == "image_url"
    with client_at(db) as client:
        folder = client.get(PREFIX + "/conversations/p0/resources").json()
        assert len(folder["documents"]) == 1
        assert len(folder["images"]) == int(with_image)
        assert folder["message_count"] >= 2
        assert client.get(PREFIX + "/conversations/other/resources").json() == {
            "documents": [], "images": [], "message_count": 0,
            "scope": {**reference_configuration(), "available_documents": [], "effective_document_ids": []},
        }
        assert client.get(PREFIX + "/conversations/other/export").status_code == 404
        exported = client.get(PREFIX + "/conversations/p0/export")
        assert exported.status_code == 200
        with zipfile.ZipFile(io.BytesIO(exported.content)) as archive:
            assert all(".." not in name for name in archive.namelist())
            assert any(archive.read(name) == FACT.encode() for name in archive.namelist())
            if with_image:
                assert any(archive.read(name) == PNG for name in archive.namelist())
            history = archive.read("conversation/messages.json").decode()
            assert "idempotency_key" not in history and "base64" not in history
        calls.clear()
        bind(calls)
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            send(ws, "send_message", "other", {"text": "请总结我的文档"}, session="other")
        assert FACT not in json.dumps(calls, ensure_ascii=False)
        assert client.delete(PREFIX + f"/documents/{doc_id}").status_code in (200, 204)
        if attachment:
            assert client.delete(attachment["url"]).status_code == 204
        assert client.get(PREFIX + "/conversations/p0/resources").json()["documents"] == []
        assert client.get(PREFIX + "/conversations/p0/resources").json()["images"] == []
        calls.clear()
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            send(ws, "send_message", "deleted", {"text": "我上传的文档，请总结"})
        # Old dialogue can remain; newly injected excerpts must not include deleted data.
        contexts = [m for c in calls for m in c["messages"] if isinstance(m["content"], str) and m["content"].startswith("本轮会话资料")]
        assert FACT not in json.dumps(contexts, ensure_ascii=False)


@pytest.mark.parametrize("eligible", [False, True])
async def test_scope_and_long_file_budget(eligible):
    """D1: retrieval now comes from the orchestrator, so the fake kernel must
    honour the real DocumentQueryResult contract — which is the point of the
    unification: there is no second, chat-specific retrieval shape."""
    doc_id = uuid4()
    doc = SimpleNamespace(document_id=doc_id, filename="长文.txt", deleted_at=None, status="ready", retrieval_enabled=eligible, can_enable_retrieval=lambda: True)
    from mathtutor.domain.documents import DocumentChunk
    from mathtutor.security.scopes import student_uuid

    chunks = [
        DocumentChunk(
            chunk_id=uuid4(), document_id=doc_id, student_id=student_uuid("owner"),
            sequence=i, text=f"{i}:" + "甲" * 3000, content_hash=f"h{i}",
        )
        for i in range(20)
    ]
    documents = SimpleNamespace(get_document=AsyncMock(return_value=doc))
    repo = SimpleNamespace(list_retrievable_chunks=AsyncMock(return_value=chunks))

    hit = RetrievedChunk(
        chunk=chunks[-1], document_id=doc_id, filename=doc.filename,
        score=0.9, lexical_score=0.9,
    )
    search = SimpleNamespace(search=AsyncMock(return_value=DocumentQueryResult(
        query="总结长文", hits=(hit,), vector_used=False, degraded=True,
    )))
    service = ChatDocumentContext(documents, repo, search)
    assert await service.build("owner", "长文") is None
    token = set_document_scope([doc_id])
    try:
        result = await service.build("owner", "总结长文")
        if eligible:
            assert result["chunks"][0]["chunk"] == 20
            assert sum(len(c["text"]) for c in result["chunks"]) <= MAX_CONTEXT_CHARS
        else:
            assert result["chunks"] == []
            search.search.assert_not_awaited()
        documents.get_document.return_value = None  # owner-scoped lookup denied
        assert (await service.build("other-owner", "长文"))["chunks"] == []
    finally:
        reset_document_scope(token)


async def test_long_history_keeps_current_document_and_image_within_budget():
    calls = []
    gateway = GenerativeModelGateway(InMemorySecretStore())
    gateway.register_provider(ModelRole.TUTOR_WRITER, provider(calls))
    context = {"files": [{"filename": "C题.txt"}], "status": "available", "chunks": [{"filename": "C题.txt", "chunk": i + 1, "text": FACT * 100} for i in range(8)]}
    response = await TutorChatResponder(gateway).respond("结合图片解释文档", history=tuple({"role": "student" if i % 2 == 0 else "tutor", "content": "历史内容" * 1000} for i in range(20)), images=[{"data": PNG, "mime_type": "image/png"}], document_context=context)
    assert response and calls
    messages = calls[0]["messages"]
    assert FACT in json.dumps(messages, ensure_ascii=False)
    assert sum(content_token_estimate(m["content"]) + 16 for m in messages) < 16384 - 512
    assert any(isinstance(m["content"], list) for m in messages)
    assert len(context["chunks"][0]["text"]) == len(FACT * 100)  # no shared-state mutation
