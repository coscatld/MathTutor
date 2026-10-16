"""Reference selection uses real SQLite/API/prompt paths, with no live model."""
import io
import json
import sqlite3
import zipfile
from contextlib import closing
from uuid import UUID

import pytest
from sqlalchemy import insert

from test_tutor_p0 import client_at, send
from test_image_attachments import bind
from test_knowledge_workbench import state, seed
from mathtutor.api.auth_deps import require_student_owner
from mathtutor.application.conversation_resources import export_folder, resources
from mathtutor.application.conversation_scope import reset_document_scope, set_document_scope
from mathtutor.application.knowledge import KnowledgeError, reference_configuration
from mathtutor.infrastructure.knowledge_schema import bindings
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope


PREFIX = "/api/v2/math-tutor/desktop"
KNOWLEDGE = PREFIX + "/knowledge"
FACT = "独特审计样本星河课堂规定先观察数量关系再列式。"


def api_library(client):
    response = client.post(KNOWLEDGE + "/libraries", json={"name": "课堂文件夹"})
    assert response.status_code == 200, response.text
    sid = response.json()["space_id"]
    response = client.post(KNOWLEDGE + f"/libraries/{sid}/notes", json={
        "title": "星河课堂", "body": FACT, "operation_id": "reference-note",
        "relative_path": "高一/函数/星河课堂.md",
    })
    assert response.status_code == 200, response.text
    return sid, response.json()["document_id"]


def durable_snapshot(path):
    with closing(sqlite3.connect(path)) as db:
        return {table: db.execute(f'SELECT * FROM "{table}" ORDER BY 1, 2').fetchall()
                for table in ("conversations", "knowledge_bindings", "knowledge_generations", "knowledge_operations")}


def test_preview_new_library_and_document_is_read_only_until_one_explicit_save(tmp_path):
    db = tmp_path / "preview.db"
    with client_at(db) as client:
        sid, did = api_library(client)
        before = durable_snapshot(db)
        empty = client.get(KNOWLEDGE + "/conversations/not-created")
        assert empty.status_code == 200, empty.text
        assert empty.json() == {**reference_configuration(), "available_documents": [], "effective_document_ids": []}
        draft = {**reference_configuration(), "space_ids": [sid], "only_selected": True, "document_ids": [did]}
        response = client.post(KNOWLEDGE + "/conversations/not-created/preview", json=draft)
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["effective_document_ids"] == [did]
        assert preview["available_documents"] == [{"document_id": did, "title": "星河课堂.md", "status": "ready",
            "enabled": True, "retrieval_enabled": True, "selected": True, "origin": "library", "space_ids": [sid]}]
        assert durable_snapshot(db) == before
        assert client.get(KNOWLEDGE + "/conversations/not-created").json()["space_ids"] == []
        saved = client.put(KNOWLEDGE + "/conversations/not-created", json=draft)
        assert saved.status_code == 200, saved.text
        actual = client.get(KNOWLEDGE + "/conversations/not-created").json()
        assert actual == preview
        assert len(durable_snapshot(db)["conversations"]) == len(before["conversations"]) + 1


def test_first_put_stays_tutor_and_explicit_configuration_survives_get(tmp_path):
    with client_at(tmp_path / "defaults.db") as client:
        sid, _ = api_library(client)
        saved = client.put(KNOWLEDGE + "/conversations/defaults", json={"space_ids": [sid]})
        assert saved.status_code == 200, saved.text
        assert saved.json()["mode"] == "tutor"
        selected = {**reference_configuration(), "space_ids": [sid], "mode": "knowledge", "save_space_id": sid,
                    "tool_mode": "structured", "hints_only": True}
        assert client.put(KNOWLEDGE + "/conversations/defaults", json=selected).status_code == 200
        actual = client.get(KNOWLEDGE + "/conversations/defaults").json()
        assert {key: actual[key] for key in selected} == selected
        # A legacy client's partial selection update cannot reset the user's
        # already explicit knowledge/compatibility/hint/save configuration.
        assert client.put(KNOWLEDGE + "/conversations/defaults", json={"space_ids": [sid]}).status_code == 200
        actual = client.get(KNOWLEDGE + "/conversations/defaults").json()
        assert {key: actual[key] for key in selected} == selected
        notes = client.get(KNOWLEDGE + f"/libraries/{sid}/notes").json()
        assert notes[0]["provenance"]["relative_path"] == "高一/函数/星河课堂.md"


def test_http_preview_and_inventory_never_expose_another_owner(tmp_path):
    with client_at(tmp_path / "owners.db") as client:
        sid, did = api_library(client)
        assert client.put(KNOWLEDGE + "/conversations/owned", json={"space_ids": [sid]}).status_code == 200
        bob = StudentOwnerScope(principal=PrincipalScope(user_id="bob", username="bob", role="student"), student_id="bob")
        client.app.dependency_overrides[require_student_owner] = lambda: bob
        try:
            for cid, draft in [("bob-new", {"space_ids": [sid]}), ("owned", {"space_ids": []}),
                               ("bob-new", {"space_ids": [], "only_selected": True, "document_ids": [did]})]:
                response = client.post(KNOWLEDGE + f"/conversations/{cid}/preview", json=draft)
                assert response.status_code == 409, response.text
                assert "星河" not in response.text
            assert client.get(KNOWLEDGE + "/conversations/owned").json()["available_documents"] == []
            assert client.get(PREFIX + "/conversations/owned/resources").json()["documents"] == []
        finally:
            client.app.dependency_overrides.pop(require_student_owner)


@pytest.mark.asyncio
async def test_old_partial_binding_get_merges_defaults_without_overwriting_knowledge_mode(state):
    async with state.knowledge.engine.begin() as db:
        await db.execute(insert(bindings).values(student_id="alice", conversation_id="A", payload={
            "space_ids": [], "document_ids": [], "only_selected": False, "mode": "knowledge"}))
    actual = await state.knowledge.reference_state("alice", "A")
    assert actual["mode"] == "knowledge"
    assert actual["tool_mode"] == "native" and actual["save_space_id"] == "" and actual["hints_only"] is False


@pytest.mark.asyncio
async def test_preview_rejects_foreign_disabled_session_and_unmounted_sources_without_writes(state):
    lib, docs = await seed(state)
    k = state.knowledge
    generation = await k.generation("alice")
    original = await k.configuration("alice", "A")
    session = await k.create_space("alice", "仅属于 A", kind="session", conversation_id="A")
    for owner, cid, draft in [
        ("bob", "other", {"space_ids": [lib["space_id"]]}),
        ("alice", "other", {"space_ids": [lib["space_id"]]}),
        ("alice", "B", {"space_ids": [session["space_id"]]}),
        ("alice", "B", {"space_ids": [], "save_space_id": session["space_id"]}),
        ("alice", "B", {"space_ids": [], "only_selected": True, "document_ids": [docs[0]["document_id"]]}),
    ]:
        with pytest.raises(KnowledgeError):
            await k.reference_state(owner, cid, configuration=draft, preview=True)
    assert await k.generation("alice") == generation
    assert await k.configuration("alice", "A") == original
    await k.set_enabled("alice", lib["space_id"], False)
    with pytest.raises(KnowledgeError):
        await k.reference_state("alice", "new-preview", configuration={"space_ids": [lib["space_id"]]}, preview=True)
    assert await state.conversations.get("alice", "new-preview") is None
    assert (await k.reference_state("alice", "A"))["available_documents"] == []
    assert (await k.reference_state("bob", "other"))["effective_document_ids"] == []


def test_resources_and_prompt_match_selected_library_without_detaching_inventory(tmp_path):
    with client_at(tmp_path / "prompt.db") as client:
        sid, did = api_library(client)
        draft = {**reference_configuration(), "space_ids": [sid], "only_selected": True, "document_ids": [did]}
        assert client.put(KNOWLEDGE + "/conversations/p0", json=draft).status_code == 200
        folder = client.get(PREFIX + "/conversations/p0/resources").json()
        assert folder["documents"][0]["document_id"] == did
        assert folder["documents"][0]["origin"] == "library" and folder["documents"][0]["in_scope"] is True
        assert folder["scope"] == client.get(KNOWLEDGE + "/conversations/p0").json()
        calls = []
        bind(calls)
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            send(ws, "send_message", "selected-note", {"text": "请解释星河课堂文档"})
        assert FACT in json.dumps(calls, ensure_ascii=False)
        draft["document_ids"] = []
        assert client.put(KNOWLEDGE + "/conversations/p0", json=draft).status_code == 200
        folder = client.get(PREFIX + "/conversations/p0/resources").json()
        assert len(folder["documents"]) == 1 and folder["documents"][0]["in_scope"] is False
        assert folder["scope"]["effective_document_ids"] == []
        calls.clear()
        # A fresh conversation avoids previously cited text remaining in its
        # ordinary dialogue history; the new prompt receives no new excerpt.
        assert client.put(KNOWLEDGE + "/conversations/empty", json=draft).status_code == 200
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            send(ws, "send_message", "excluded-note", {"text": "请解释星河课堂文档"}, session="empty")
        assert FACT not in json.dumps(calls, ensure_ascii=False)
        archive = client.get(PREFIX + "/conversations/p0/export")
        assert archive.status_code == 200, archive.text
        with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
            manifest = json.loads(zipped.read("conversation/manifest.json"))
            assert manifest["scope"]["effective_document_ids"] == []
            assert any(zipped.read(name).decode("utf-8") == FACT for name in manifest["files"])


@pytest.mark.asyncio
async def test_export_falls_back_to_versioned_markdown_source_and_retains_unselected_note(state):
    lib, docs = await seed(state)
    k = state.knowledge
    did = UUID(docs[0]["document_id"])
    doc = await state.documents.get_document("alice", did)
    snapshot = await k.snapshot("alice", str(did))
    await state.document_storage.remove(doc.storage_ref)
    await k.configure("alice", "A", space_ids=[lib["space_id"]], only_selected=True, document_ids=[])
    inventory, _, _ = await resources(state, "alice", "A")
    assert len(inventory) == 2
    stream = await export_folder(state, "alice", "A")
    try:
        with zipfile.ZipFile(stream) as archive:
            manifest = json.loads(archive.read("conversation/manifest.json"))
            item = next(x for x in manifest["document_sources"] if x["document_id"] == str(did))
            assert item["source"] == "knowledge_snapshot" and item["version"] == snapshot["version"]
            assert item["body_hash"] == snapshot["body_hash"]
            assert archive.read(item["file"]).decode("utf-8") == snapshot["body"]
            assert manifest["scope"]["effective_document_ids"] == [] and manifest["missing"] == []
    finally:
        stream.close()


def test_disabled_document_remains_inventory_but_not_effective(tmp_path):
    with client_at(tmp_path / "disabled.db") as client:
        sid, did = api_library(client)
        assert client.put(KNOWLEDGE + "/conversations/p0", json={"space_ids": [sid]}).status_code == 200
        response = client.patch(PREFIX + f"/documents/{did}/retrieval", json={"enabled": False})
        assert response.status_code == 200, response.text
        actual = client.get(KNOWLEDGE + "/conversations/p0").json()
        assert actual["available_documents"][0]["selected"] is True
        assert actual["available_documents"][0]["enabled"] is False and actual["effective_document_ids"] == []
        assert client.get(PREFIX + "/conversations/p0/resources").json()["documents"][0]["in_scope"] is False
        assert client.delete(PREFIX + f"/documents/{did}").status_code in (200, 204)
        assert client.get(KNOWLEDGE + "/conversations/p0").json()["available_documents"] == []
        assert client.get(PREFIX + "/conversations/p0/resources").json()["documents"] == []


@pytest.mark.asyncio
async def test_document_after_first_32_is_retrieved_with_context_budget(state):
    k = state.knowledge
    lib = await k.create_space("alice", "三十三份资料")
    first_ids = []
    for i in range(32):
        note = await k.save_markdown("alice", lib["space_id"], title=f"背景{i:02}",
            body=f"普通背景样本编号{i}，不包含指定课堂规则。", operation_id=f"background-{i}")
        first_ids.append(UUID(note["document_id"]))
    last = await k.save_markdown("alice", lib["space_id"], title="星河课堂", body=FACT, operation_id="last-target")
    # Explicit ordering makes the regression independent of database UUID sort.
    token = set_document_scope([*first_ids, UUID(last["document_id"])])
    try:
        result = await state.controller.chat_documents.build("alice", "请解释独特审计样本的课堂规则")
    finally:
        reset_document_scope(token)
    assert result["document_count"] == 33 and result["inventory_partial"] is True
    assert len(result["files"]) == 32
    assert FACT in json.dumps(result["chunks"], ensure_ascii=False)
    assert len(result["chunks"]) <= 8 and sum(len(c["text"]) for c in result["chunks"]) <= 12000
