"""Ordinary folder saves use real HTTP/SQLite and the shared-vault round trip."""
import asyncio
import sqlite3
from contextlib import closing
import unicodedata

import pytest
from sqlalchemy import select

from test_knowledge_workbench import state
from test_tutor_p0 import client_at
from mathtutor.api.auth_deps import require_student_owner
from mathtutor.application.knowledge import KnowledgeError
from mathtutor.application.question_packs import QuestionPackService, parse_pack
from mathtutor.infrastructure.knowledge_schema import members, operations, versions
from mathtutor.repositories import sqlite_documents as document_sql
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope


BASE = "/api/v2/math-tutor/desktop"
BODY = "# 定义\n同一份可复用的教学笔记。\n"


def owner(client, name):
    scope = StudentOwnerScope(principal=PrincipalScope(user_id=name, username=name, role="student"), student_id=name)
    client.app.dependency_overrides[require_student_owner] = lambda: scope


def library(client, name):
    response = client.post(BASE + "/knowledge/libraries", json={"name": name})
    assert response.status_code == 200, response.text
    return response.json()["space_id"]


def save(client, sid, path, title, tags, operation, body=BODY, **extra):
    return client.post(BASE + f"/knowledge/libraries/{sid}/notes", json={
        "title": title, "body": body, "tags": tags, "operation_id": operation,
        "relative_path": path, **extra})


def notes(client, sid):
    response = client.get(BASE + f"/knowledge/libraries/{sid}/notes")
    assert response.status_code == 200, response.text
    return response.json()


def export(client, sid):
    response = client.get(BASE + f"/content/libraries/{sid}/export")
    assert response.status_code == 200, response.text
    return response.content


def test_http_same_body_preserves_both_locations_metadata_receipts_and_round_trip(tmp_path):
    db_path = tmp_path / "folder-aliases.db"
    with client_at(db_path) as client:
        owner(client, "alice")
        sid = library(client, "普通文件夹")
        first = save(client, sid, "高一/定义.md", "高一的定义", ["高一"], "first")
        second = save(client, sid, "复习/定义.md", "复习的定义", ["复习"], "second")
        assert first.status_code == second.status_code == 200, (first.text, second.text)
        a, b = first.json(), second.json()
        assert a["document_id"] == b["document_id"] and a["version"] == b["version"] == 1
        assert a["created_document_count"] == 1 and b["created_document_count"] == 0
        assert a["deduplicated"] is False and b["deduplicated"] is True
        assert a["path_added"] is b["path_added"] is True
        assert [a["relative_path"], b["relative_path"]] == ["高一/定义.md", "复习/定义.md"]
        for receipt in (a, b):
            assert receipt["input_file_count"] == receipt["unique_body_count"] == receipt["retained_path_count"] == 1
        repeated = save(client, sid, "复习/定义.md", "复习的定义", ["复习"], "second")
        assert repeated.json() == b
        fresh_operation = save(client, sid, "复习/定义.md", "复习的定义", ["复习"], "second-new-operation")
        assert fresh_operation.status_code == 200 and fresh_operation.json()["path_added"] is False
        current, = notes(client, sid)
        assert current["provenance"]["relative_paths"] == ["高一/定义.md", "复习/定义.md"]
        assert current["provenance"]["library_paths"] == [
            {"path": "高一/定义.md", "title": "高一的定义", "tags": ["高一"]},
            {"path": "复习/定义.md", "title": "复习的定义", "tags": ["复习"]},
        ]
        with closing(sqlite3.connect(db_path)) as db:
            assert db.execute("SELECT count(*) FROM user_documents").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM knowledge_versions").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM knowledge_members").fetchone()[0] == 1
        data = export(client, sid)
        parsed = parse_pack(data, "ordinary-folder.zip")
        assert {note.path: (note.title, note.tags, note.body) for note in parsed.notes} == {
            "高一/定义.md": ("高一的定义", ("高一",), BODY),
            "复习/定义.md": ("复习的定义", ("复习",), BODY),
        }
        owner(client, "bob")
        imported = client.post(BASE + "/content/question-packs/import", files={"file": ("ordinary-folder.zip", data, "application/zip")})
        assert imported.status_code == 200, imported.text
        receipt = imported.json()
        assert (receipt["input_file_count"], receipt["unique_body_count"], receipt["retained_path_count"], receipt["created_document_count"]) == (2, 1, 2, 1)
        bob_note, = notes(client, receipt["space_id"])
        assert bob_note["document_id"] != a["document_id"]
        again = parse_pack(export(client, receipt["space_id"]), "again.zip")
        assert again.notes == parsed.notes


def test_http_new_library_gets_its_own_aliases_and_shared_body_edit_keeps_each_library_metadata(tmp_path):
    with client_at(tmp_path / "library-local.db") as client:
        owner(client, "alice")
        old, new = library(client, "原库"), library(client, "新库")
        first = save(client, old, "原库/定义.md", "原库标题", ["原库标签"], "old").json()
        imported = save(client, new, "新库/自己的位置.md", "新库标题", ["新库标签"], "new")
        assert imported.status_code == 200, imported.text
        assert imported.json()["document_id"] == first["document_id"]
        new_note, = notes(client, new)
        assert new_note["provenance"]["relative_paths"] == ["新库/自己的位置.md"]
        assert new_note["title"] == "新库标题" and new_note["tags"] == ["新库标签"]
        edit = save(client, new, "新库/移动的位置.md", "更新的新库标题", ["新标签"], "edit",
            body="共享正文的新版本。", document_id=first["document_id"], expected_version=1,
            previous_relative_path="新库/自己的位置.md")
        assert edit.status_code == 200, edit.text
        assert edit.json()["version"] == 2 and edit.json()["relative_path"] == "新库/移动的位置.md"
        old_note, = notes(client, old)
        assert (old_note["title"], old_note["tags"], old_note["provenance"]["relative_paths"]) == ("原库标题", ["原库标签"], ["原库/定义.md"])
        for sid, path, title, tags in [(old, "原库/定义.md", "原库标题", ("原库标签",)), (new, "新库/移动的位置.md", "更新的新库标题", ("新标签",))]:
            exported, = parse_pack(export(client, sid), "local.zip").notes
            assert (exported.path, exported.title, exported.tags, exported.body) == (path, title, tags, "共享正文的新版本。")


def test_http_path_conflict_requires_explicit_current_document_and_cas_and_rolls_back(tmp_path):
    db_path = tmp_path / "path-conflicts.db"
    with client_at(db_path) as client:
        owner(client, "alice")
        sid = library(client, "路径冲突")
        first = save(client, sid, "定义.md", "定义", [], "first").json()
        with closing(sqlite3.connect(db_path)) as db:
            before = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                      for table in ("user_documents", "knowledge_versions", "knowledge_members", "knowledge_operations", "document_chunks")}
        conflict = save(client, sid, "定义.md", "定义", [], "conflict", body="另一份不同正文。")
        assert conflict.status_code == 409 and "确认当前版本" in conflict.json()["detail"]
        with closing(sqlite3.connect(db_path)) as db:
            assert {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in before} == before
        changed_metadata = save(client, sid, "定义.md", "不同标题", ["不同标签"], "metadata-conflict")
        assert changed_metadata.status_code == 409 and "确认当前版本" in changed_metadata.json()["detail"]
        updated = save(client, sid, "定义.md", "定义", [], "confirmed", body="另一份不同正文。",
            document_id=first["document_id"], expected_version=1, previous_relative_path="定义.md")
        assert updated.status_code == 200 and updated.json()["version"] == 2, updated.text
        stale = save(client, sid, "定义.md", "定义", [], "stale", body="过期覆盖。",
            document_id=first["document_id"], expected_version=1, previous_relative_path="定义.md")
        assert stale.status_code == 409 and "版本已变化" in stale.json()["detail"]
        source = client.get(BASE + "/knowledge/sources/" + first["document_id"]).json()
        assert source["body"] == "另一份不同正文。" and source["version"] == 2
        confirmed_metadata = save(client, sid, "定义.md", "确认后的标题", ["确认后的标签"], "metadata-confirmed", body=source["body"],
            document_id=first["document_id"], expected_version=2, previous_relative_path="定义.md")
        assert confirmed_metadata.status_code == 200 and confirmed_metadata.json()["version"] == 3
        current, = notes(client, sid)
        assert current["title"] == "确认后的标题" and current["tags"] == ["确认后的标签"]
        stale_metadata = save(client, sid, "定义.md", "过期标题", [], "metadata-stale", body=source["body"],
            document_id=first["document_id"], expected_version=2, previous_relative_path="定义.md")
        assert stale_metadata.status_code == 409


def test_http_owner_isolation_and_normalized_path_replay(tmp_path):
    with client_at(tmp_path / "owner-paths.db") as client:
        owner(client, "alice")
        alice_sid = library(client, "Alice")
        first = save(client, alice_sid, "e\u0301\\定义.md", "定义", [], "normalized")
        assert first.status_code == 200, first.text
        assert first.json()["relative_path"] == "é/定义.md"
        repeated = save(client, alice_sid, "é/定义.md", "定义", [], "normalized")
        assert repeated.status_code == 200 and repeated.json() == first.json()
        changed = save(client, alice_sid, "不同/定义.md", "定义", [], "normalized")
        assert changed.status_code == 409 and "重复请求" in changed.json()["detail"]
        owner(client, "bob")
        bob_sid = library(client, "Bob")
        other = save(client, bob_sid, "é/定义.md", "定义", [], "normalized")
        assert other.status_code == 200 and other.json()["document_id"] != first.json()["document_id"]
        assert save(client, alice_sid, "偷写.md", "定义", [], "forbidden").status_code == 409
        assert save(client, bob_sid, "偷写.md", "定义", [], "forbidden-edit", document_id=first.json()["document_id"], expected_version=1).status_code == 409
        assert client.get(BASE + "/knowledge/sources/" + first.json()["document_id"]).status_code == 409


def test_http_dedup_against_raw_text_keeps_extracted_identity_and_registers_new_location(tmp_path):
    with client_at(tmp_path / "raw-text.db") as client:
        owner(client, "alice")
        sid = library(client, "普通文字")
        original = client.post(BASE + f"/knowledge/libraries/{sid}/imports", files={"file": ("原件.txt", BODY.encode(), "text/plain")})
        assert original.status_code == 200, original.text
        imported = save(client, sid, "文件夹/定义.md", "文件夹标题", ["别名标签"], "folder")
        assert imported.status_code == 200, imported.text
        assert imported.json()["document_id"] == original.json()["document_id"]
        row, = notes(client, sid)
        assert row["editable"] is False
        assert "文件夹/定义.md" in row["provenance"]["relative_paths"]
        source = client.get(BASE + "/knowledge/sources/" + row["document_id"]).json()
        assert source["provenance"]["format"] == "extracted"


@pytest.mark.asyncio
async def test_concurrent_different_bodies_cannot_occupy_the_same_library_path(state):
    knowledge = state.knowledge
    sid = (await knowledge.create_space("alice", "并发路径"))["space_id"]
    results = await asyncio.gather(*(knowledge.save_markdown("alice", sid, title="定义", body=body,
        operation_id=f"race-{i}", provenance={"relative_path": "同一路径.md"})
        for i, body in enumerate(("正文甲。", "正文乙。"))), return_exceptions=True)
    assert len([row for row in results if isinstance(row, dict)]) == 1
    assert len([row for row in results if isinstance(row, KnowledgeError)]) == 1
    assert len(await knowledge.list_notes("alice", sid)) == 1
    async with knowledge.engine.connect() as db:
        assert len((await db.execute(select(versions))).all()) == 1
        assert len((await db.execute(select(members))).all()) == 1
        assert len((await db.execute(select(operations))).all()) == 1


@pytest.mark.asyncio
async def test_generated_collision_paths_are_normalized_bounded_and_explicit_invalid_paths_roll_back(state):
    knowledge = state.knowledge
    sid = (await knowledge.create_space("alice", "自动路径"))["space_id"]
    title = "e\u0301" * 50
    receipts = [await knowledge.save_markdown("alice", sid, title=title, body=body, operation_id=f"generated-{i}")
                for i, body in enumerate(("自动路径甲。", "自动路径乙。"))]
    assert receipts[0]["relative_path"] != receipts[1]["relative_path"]
    for row in receipts:
        path = row["relative_path"]
        assert len(path) <= 512 and path == unicodedata.normalize("NFC", path) and path.endswith(".md")
    with pytest.raises(KnowledgeError):
        await knowledge.save_markdown("alice", sid, title="越界路径", body="不得残留。", operation_id="too-long",
            provenance={"relative_path": "目录/" + "长" * 510 + ".md"})
    assert len(await knowledge.list_notes("alice", sid)) == 2


@pytest.mark.asyncio
async def test_extracted_snapshot_refresh_preserves_library_locations(state):
    from mathtutor.application.desktop_files import PickedFile
    sid = (await state.knowledge.create_space("alice", "原始文字"))["space_id"]
    document = await state.documents.ingest("alice", PickedFile(filename="原件.txt", mime_type="text/plain", data=BODY.encode()))
    await state.knowledge.attach("alice", sid, str(document.document_id), expected_generation=await state.knowledge.generation("alice"))
    await state.knowledge.save_markdown("alice", sid, title="另一个位置", body=BODY, tags=["本库标签"],
        operation_id="text-alias", provenance={"relative_path": "文件夹/定义.md"})
    before = await state.knowledge.snapshot("alice", str(document.document_id))
    chunks = await state.document_repository.list_chunks("alice", document.document_id)
    refreshed = [chunks[0].model_copy(update={"text": "重解析得到的正文。"})]
    async with state.knowledge.engine.begin() as db:
        await document_sql.replace_document_chunks(db, student_id="alice", document_id=document.document_id, chunks=refreshed)
    after = await state.knowledge.snapshot("alice", str(document.document_id))
    assert after["version"] == before["version"] + 1 and after["body"] == "重解析得到的正文。"
    assert after["provenance"]["format"] == "extracted"
    assert after["provenance"]["vault_paths"] == before["provenance"]["vault_paths"]
    note, = await state.knowledge.list_notes("alice", sid)
    assert "文件夹/定义.md" in note["provenance"]["relative_paths"]


@pytest.mark.asyncio
async def test_failed_pack_does_not_leave_its_default_path_on_legacy_document(state, monkeypatch):
    from test_question_packs import archive
    knowledge = state.knowledge
    sid = (await knowledge.create_space("alice", "旧版笔记"))["space_id"]
    result = await knowledge.save_markdown("alice", sid, title="原名", body=BODY, operation_id="legacy")
    async with knowledge.engine.begin() as db:
        await db.execute(versions.update().where(versions.c.student_id == "alice",
            versions.c.document_id == result["document_id"]).values(provenance={"format": "markdown", "origin": "user"}))
    original = await knowledge.snapshot("alice", result["document_id"])
    save_original, calls = knowledge.save_markdown, 0
    async def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        receipt = await save_original(*args, **kwargs)
        if calls == 2:
            raise RuntimeError("second imported file failed after commit")
        return receipt
    monkeypatch.setattr(knowledge, "save_markdown", fail_second)
    with pytest.raises(RuntimeError):
        await QuestionPackService(state).import_pack("alice", archive([("新库/新路径.md", BODY), ("新正文.md", "不同正文。")]), "failed.zip")
    assert await knowledge.snapshot("alice", result["document_id"]) == original
    assert [row["space_id"] for row in await knowledge.list_spaces("alice")] == [sid]
