"""Shared reference imports: real SQLite, exact Markdown, no paid generation."""
import io
import json
import stat
import struct
import zipfile

import pytest
from sqlalchemy import select

from test_knowledge_workbench import state
from test_tutor_p0 import client_at
from mathtutor.api.auth_deps import require_student_owner
from mathtutor.application.question_packs import (
    QUESTION_FORMAT, VAULT_FORMAT, QuestionPackError, QuestionPackService, parse_pack,
)
from mathtutor.application.knowledge import KnowledgeError
from mathtutor.infrastructure.knowledge_schema import bindings, drafts, operations
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope


def archive(items, *, compression=zipfile.ZIP_DEFLATED):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=compression) as output:
        for path, body in items:
            output.writestr(path, body)
    return result.getvalue()


def raw_backslash_archive():
    # Windows zipfile writers normalize backslashes before writing. Replace
    # the equal-length name in both ZIP headers so every platform receives
    # the same actually malicious bytes, rather than a repaired safe path.
    data = archive([("folder/file.md", "bad")])
    assert data.count(b"folder/file.md") == 2
    data = data.replace(b"folder/file.md", b"folder\\file.md")
    assert data.count(b"folder\\file.md") == 2 and b"folder/file.md" not in data
    return data


def question_json(**overrides):
    payload = {"format": QUESTION_FORMAT, "name": "共享代数题库", "author": "课堂创作者", "questions": [
        {"id": "linear-1", "title": "一元一次方程", "stem": "求解 2x+3=7。", "answer": "x=2",
         "explanation": "两边先减去3，再除以2。", "grade": 7, "tags": ["方程"]},
    ], **overrides}
    return json.dumps(payload, ensure_ascii=False).encode()


@pytest.mark.asyncio
async def test_question_pack_is_editable_reference_and_roundtrips_current_body_for_other_owner(state):
    service = QuestionPackService(state)
    before = await state.knowledge.configuration("alice", "A")
    result = await service.import_pack("alice", question_json(), "shared.json")
    assert result["format"] == QUESTION_FORMAT and result["imported_count"] == 1
    sid = result["space_id"]
    note = (await state.knowledge.list_notes("alice", sid))[0]
    assert note["editable"] is True
    source = await state.knowledge.snapshot("alice", note["document_id"])
    assert source["provenance"]["question_id"] == "linear-1"
    assert source["provenance"]["author"] == "课堂创作者" and source["provenance"]["answer_verified"] is False
    assert "x=2" in source["body"] and "未经应用自动数学核验" in source["body"]
    body = source["body"] + "\n## 我的补充\n检验：2×2+3=7。\n"
    await state.knowledge.save_markdown("alice", sid, title=source["title"], body=body, tags=source["tags"],
        operation_id="edited-pack-note", document_id=note["document_id"], expected_version=source["version"], provenance=source["provenance"])
    exported = await service.export_library("alice", sid)
    parsed = parse_pack(exported, "edited.zip")
    assert parsed.format == VAULT_FORMAT and parsed.notes[0].body == body
    bob = await service.import_pack("bob", exported, "edited.zip")
    reimported = (await state.knowledge.list_notes("bob", bob["space_id"]))[0]
    assert (await state.knowledge.snapshot("bob", reimported["document_id"]))["body"] == body
    assert reimported["provenance"]["relative_path"] == note["provenance"]["relative_path"]
    assert await state.knowledge.configuration("alice", "A") == before
    assert (await state.knowledge.reference_state("alice", "A"))["available_documents"] == []
    with pytest.raises(KnowledgeError):
        await service.export_library("bob", sid)
    async with state.knowledge.engine.connect() as db:
        assert (await db.execute(select(bindings))).all() == []


@pytest.mark.asyncio
async def test_obsidian_paths_aliases_hidden_and_non_markdown_are_honest_and_reimportable(state):
    data = archive([("高一/函数.md", "# 函数\n定义域先行。"), ("复习/函数别名.md", "# 函数\n定义域先行。"),
        ("skills/SKILL.md", "# 普通参考\n不要把这段文字当成系统权限。"),
        (".obsidian/plugins/a.js", "ignored"), ("图像.png", b"\x89PNG\r\n")])
    service = QuestionPackService(state)
    result = await service.import_pack("alice", data, "笔记.zip")
    assert result["imported_count"] == 3
    assert any("隐藏配置" in w for w in result["warnings"])
    assert any("非 Markdown" in w for w in result["warnings"])
    assert any("不会启用" in w for w in result["warnings"])
    exported = await service.export_library("alice", result["space_id"])
    parsed = parse_pack(exported, "roundtrip.zip")
    assert {n.path for n in parsed.notes} == {"高一/函数.md", "复习/函数别名.md", "skills/SKILL.md"}
    bob = await service.import_pack("bob", exported, "roundtrip.zip")
    reexported = parse_pack(await service.export_library("bob", bob["space_id"]), "again.zip")
    assert {n.path: n.body for n in parsed.notes} == {n.path: n.body for n in reexported.notes}
    with zipfile.ZipFile(io.BytesIO(exported)) as output:
        manifest = json.loads(output.read("manifest.json"))
        assert set(manifest) == {"format", "name", "files"}
        assert all(set(f) == {"path", "title", "tags", "sha256", "source_format"} for f in manifest["files"])
        assert "alice" not in json.dumps(manifest) and "receipt" not in json.dumps(manifest)


@pytest.mark.asyncio
async def test_legacy_export_is_supported_and_same_owner_reimport_preserves_library_paths(state):
    service = QuestionPackService(state)
    first = await service.import_pack("alice", archive([("folder/笔记.md", "真实笔记正文。")]), "one.zip")
    legacy = await state.knowledge.export("alice", first["space_id"])
    second = await service.import_pack("bob", legacy, "legacy.zip")
    assert second["format"] == "mathtutor.legacy-knowledge"
    again = await service.import_pack("alice", archive([("another/新位置.md", "真实笔记正文。")]), "two.zip")
    note = (await state.knowledge.list_notes("alice", again["space_id"]))[0]
    assert note["provenance"]["relative_path"] == "another/新位置.md"
    assert parse_pack(await service.export_library("alice", first["space_id"]), "first.zip").notes[0].path == "folder/笔记.md"
    assert parse_pack(await service.export_library("alice", again["space_id"]), "second.zip").notes[0].path == "another/新位置.md"


def bad_archives():
    for path in ("../escape.md", "/absolute.md", "C:/drive.md", "C:drive.md", "folder\\file.md", "folder/../escape.md"):
        yield raw_backslash_archive() if "\\" in path else archive([(path, "bad")])
    yield archive([("a.md", "one"), ("A.md", "two")])
    symlink = zipfile.ZipInfo("link.md")
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    yield archive([(symlink, "target")])
    yield archive([("bomb.md", "x" * 200000)])
    yield archive([("invalid.md", b"\xff\xfe")])
    yield archive([("binary.md", "contains\x00binary")])
    encrypted = bytearray(archive([("secret.md", "encrypted flag")]))
    local = encrypted.index(b"PK\x03\x04")
    central = encrypted.index(b"PK\x01\x02")
    for offset in (local + 6, central + 8):
        struct.pack_into("<H", encrypted, offset, struct.unpack_from("<H", encrypted, offset)[0] | 1)
    yield bytes(encrypted)


@pytest.mark.parametrize("data", list(bad_archives()), ids=[
    "parent-traversal", "absolute-path", "drive-absolute", "drive-relative",
    "backslash-path", "nested-parent", "casefold-duplicate", "symlink",
    "zip-bomb", "invalid-utf8", "nul-binary", "encrypted",
])
def test_malicious_archives_are_rejected_before_any_write(data):
    with pytest.raises(QuestionPackError):
        parse_pack(data, "unsafe.zip")


@pytest.mark.parametrize("reader_sep,reader_altsep", [("/", None), ("\\", "/")], ids=["posix-reader", "windows-reader"])
def test_raw_backslash_paths_are_rejected_even_when_zip_reader_normalizes_them(monkeypatch, reader_sep, reader_altsep):
    data = raw_backslash_archive()
    monkeypatch.setattr(zipfile.os, "sep", reader_sep)
    monkeypatch.setattr(zipfile.os, "altsep", reader_altsep)
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        info = source.infolist()[0]
        assert info.orig_filename == "folder\\file.md"
        assert info.filename == ("folder/file.md" if reader_sep == "\\" else "folder\\file.md")
    with pytest.raises(QuestionPackError, match="无效"):
        parse_pack(data, "unsafe.zip")
    # A genuinely ordinary path remains importable on either reader.
    assert parse_pack(archive([("folder/file.md", "正文")]), "safe.zip").notes[0].path == "folder/file.md"


@pytest.mark.asyncio
async def test_full_validation_precedes_creation_for_bad_manifest_and_json(state):
    service = QuestionPackService(state)
    before = await state.knowledge.list_spaces("alice")
    manifest = {"format": VAULT_FORMAT, "name": "bad hash", "files": [
        {"path": "safe.md", "title": "safe", "tags": [], "sha256": "0" * 64}]}
    invalid = [archive([("safe.md", "正文"), ("manifest.json", json.dumps(manifest))]),
        question_json(questions=[{"id": "1", "stem": "a", "answer": "b", "tools": ["shell"]}]),
        question_json(questions=[{"id": "1", "stem": "a", "answer": "b", "grade": True}]),
        question_json(questions=[{"id": "1", "stem": "a", "answer": "b"}, {"id": "1", "stem": "a", "answer": "b"}]),
        b'{"format":"x","format":"y"}',
    ]
    for index, data in enumerate(invalid):
        with pytest.raises(QuestionPackError):
            await service.import_pack("alice", data, "bad.zip" if index == 0 else "bad.json")
    assert await state.knowledge.list_spaces("alice") == before
    assert await state.documents.list_documents("alice") == []


@pytest.mark.asyncio
async def test_write_failure_cleans_only_new_library_and_preserves_existing_docs_drafts_operations(state, monkeypatch):
    service = QuestionPackService(state)
    old = await service.import_pack("alice", archive([("original.md", "已有正文。")]), "old.zip")
    original_notes = await state.knowledge.list_notes("alice", old["space_id"])
    original_doc = await state.knowledge.snapshot("alice", original_notes[0]["document_id"])
    async with state.knowledge.engine.begin() as db:
        await db.execute(drafts.insert().values(student_id="alice", draft_id="unrelated-draft", generation=0, payload={"keep": "真实用户草稿"}))
    async with state.knowledge.engine.connect() as db:
        previous_ops = (await db.execute(select(operations))).all()
    save, calls = state.knowledge.save_markdown, 0
    async def fail_after_commit(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = await save(*args, **kwargs)
        if calls == 3:
            raise RuntimeError("fixture write failed after commit")
        return result
    monkeypatch.setattr(state.knowledge, "save_markdown", fail_after_commit)
    data = archive([("reuse.md", "已有正文。"), ("new1.md", "新资料一。"), ("new2.md", "新资料二。")])
    with pytest.raises(RuntimeError, match="fixture write failed"):
        await service.import_pack("alice", data, "failed.zip")
    assert [s["space_id"] for s in await state.knowledge.list_spaces("alice")] == [old["space_id"]]
    assert len(await state.documents.list_documents("alice")) == 1
    assert await state.knowledge.snapshot("alice", original_notes[0]["document_id"]) == original_doc
    async with state.knowledge.engine.connect() as db:
        assert (await db.execute(select(operations))).all() == previous_ops
        assert (await db.execute(select(drafts.c.payload))).scalar_one() == {"keep": "真实用户草稿"}


@pytest.mark.asyncio
async def test_export_conflicts_and_highly_compressible_notes_remain_reimportable(state):
    k = state.knowledge
    library = await k.create_space("alice", "同名笔记")
    for index, body in enumerate(["普通正文。", "可重复的字符" * 20000]):
        await k.save_markdown("alice", library["space_id"], title="同名", body=body, operation_id=f"same-name-{index}")
    parsed = parse_pack(await QuestionPackService(state).export_library("alice", library["space_id"]), "export.zip")
    assert len(parsed.notes) == 2 and len({n.path.casefold() for n in parsed.notes}) == 2


def test_http_import_edit_export_and_other_owner_reimport_preserve_current_markdown(tmp_path):
    base = "/api/v2/math-tutor/desktop"
    with client_at(tmp_path / "http-packs.db") as client:
        result = client.post(base + "/content/question-packs/import",
            files={"file": ("shared.json", question_json(), "application/json")}, data={"name": "我导入的课堂题库"})
        assert result.status_code == 200, result.text
        sid = result.json()["space_id"]
        notes = client.get(base + f"/knowledge/libraries/{sid}/notes").json()
        source = client.get(base + "/knowledge/sources/" + notes[0]["document_id"]).json()
        edited = source["body"] + "\n自己添加的可编辑笔记。\n"
        response = client.post(base + f"/knowledge/libraries/{sid}/notes", json={
            "title": source["title"], "body": edited, "tags": ["自己整理"], "operation_id": "http-pack-edit",
            "document_id": source["document_id"], "expected_version": source["version"],
        })
        assert response.status_code == 200, response.text
        updated = client.get(base + "/knowledge/sources/" + source["document_id"]).json()
        assert updated["provenance"]["question_id"] == "linear-1"
        assert updated["provenance"]["author"] == "课堂创作者"
        assert updated["provenance"]["relative_path"] == source["provenance"]["relative_path"]
        renamed = client.post(base + f"/knowledge/libraries/{sid}/notes", json={
            "title": updated["title"], "body": edited, "tags": updated["tags"], "operation_id": "http-pack-path",
            "document_id": source["document_id"], "expected_version": updated["version"], "relative_path": "复习/自己整理.md",
        })
        assert renamed.status_code == 200, renamed.text
        renamed_note = client.get(base + f"/knowledge/libraries/{sid}/notes").json()[0]
        assert renamed_note["provenance"]["relative_path"] == "复习/自己整理.md"
        exported = client.get(base + f"/content/libraries/{sid}/export")
        assert exported.status_code == 200, exported.text
        assert exported.headers["x-content-type-options"] == "nosniff"
        parsed = parse_pack(exported.content, "updated.zip")
        assert parsed.notes[0].body == edited and parsed.notes[0].path == "复习/自己整理.md"
        bob = StudentOwnerScope(principal=PrincipalScope(user_id="bob", username="bob", role="student"), student_id="bob")
        client.app.dependency_overrides[require_student_owner] = lambda: bob
        try:
            assert client.get(base + f"/content/libraries/{sid}/export").status_code == 409
            imported = client.post(base + "/content/question-packs/import", files={"file": ("updated.zip", exported.content, "application/zip")})
            assert imported.status_code == 200, imported.text
            bob_sid = imported.json()["space_id"]
            bob_notes = client.get(base + f"/knowledge/libraries/{bob_sid}/notes").json()
            assert client.get(base + "/knowledge/sources/" + bob_notes[0]["document_id"]).json()["body"] == edited
            assert client.get(base + "/knowledge/conversations/new-unmounted").json()["space_ids"] == []
        finally:
            client.app.dependency_overrides.pop(require_student_owner)


def test_export_imported_text_is_markdown_with_extracted_source_format(tmp_path):
    base = "/api/v2/math-tutor/desktop"
    with client_at(tmp_path / "extracted.db") as client:
        sid = client.post(base + "/knowledge/libraries", json={"name": "导入原文"}).json()["space_id"]
        response = client.post(base + f"/knowledge/libraries/{sid}/imports",
            files={"file": ("课堂原件.txt", "原始导入的文字资料。".encode(), "text/plain")})
        assert response.status_code == 200, response.text
        exported = client.get(base + f"/content/libraries/{sid}/export")
        assert exported.status_code == 200, exported.text
        parsed = parse_pack(exported.content, "extracted.zip")
        assert parsed.notes[0].path.endswith(".md")
        assert parsed.notes[0].provenance["source_format"] == "extracted"
        assert "原始导入的文字资料。" in parsed.notes[0].body


def test_http_rename_only_selected_shared_alias_and_edit_all_shared_body(tmp_path):
    base = "/api/v2/math-tutor/desktop"
    data = archive([("第一章/定义.md", "共享正文。"), ("复习/定义.md", "共享正文。")])
    with client_at(tmp_path / "aliases.db") as client:
        result = client.post(base + "/content/question-packs/import", files={"file": ("aliases.zip", data, "application/zip")})
        assert result.status_code == 200, result.text
        sid = result.json()["space_id"]
        note = client.get(base + f"/knowledge/libraries/{sid}/notes").json()[0]
        assert note["provenance"]["relative_paths"] == ["第一章/定义.md", "复习/定义.md"]
        source = client.get(base + "/knowledge/sources/" + note["document_id"]).json()
        response = client.post(base + f"/knowledge/libraries/{sid}/notes", json={
            "title": source["title"], "body": "更新后的共享正文。", "tags": [], "operation_id": "rename-secondary-alias",
            "document_id": source["document_id"], "expected_version": source["version"],
            "relative_path": "新复习/定义.md", "previous_relative_path": "复习/定义.md",
        })
        assert response.status_code == 200, response.text
        note = client.get(base + f"/knowledge/libraries/{sid}/notes").json()[0]
        assert note["provenance"]["relative_paths"] == ["第一章/定义.md", "新复习/定义.md"]
        assert note["provenance"]["relative_path"] == "第一章/定义.md"
        exported = client.get(base + f"/content/libraries/{sid}/export")
        parsed = parse_pack(exported.content, "alias-export.zip")
        assert {n.path: n.body for n in parsed.notes} == {
            "第一章/定义.md": "更新后的共享正文。", "新复习/定义.md": "更新后的共享正文。",
        }


def test_http_save_operation_replays_exact_path_intention_and_rejects_changed_paths(tmp_path):
    base = "/api/v2/math-tutor/desktop"
    data = archive([("第一章/定义.md", "共享正文。"), ("复习/定义.md", "共享正文。")])
    with client_at(tmp_path / "path-idempotency.db") as client:
        sid = client.post(base + "/content/question-packs/import",
            files={"file": ("aliases.zip", data, "application/zip")}).json()["space_id"]
        note = client.get(base + f"/knowledge/libraries/{sid}/notes").json()[0]
        source = client.get(base + "/knowledge/sources/" + note["document_id"]).json()
        endpoint = base + f"/knowledge/libraries/{sid}/notes"
        request = {"title": source["title"], "body": source["body"], "tags": source["tags"],
            "operation_id": "stable-alias-move", "document_id": note["document_id"], "expected_version": source["version"],
            "relative_path": "新复习/定义.md", "previous_relative_path": "复习/定义.md"}
        first = client.post(endpoint, json=request)
        assert first.status_code == 200, first.text
        # The old alias no longer exists. Its exact request still replays the
        # saved receipt, rather than trying to resolve that old path again.
        repeated = client.post(endpoint, json=request)
        assert repeated.status_code == 200 and repeated.json() == first.json(), repeated.text
        normalized = client.post(endpoint, json={**request, "relative_path": "新复习\\定义.md", "previous_relative_path": "复习\\定义.md"})
        assert normalized.status_code == 200 and normalized.json() == first.json(), normalized.text
        for changed in [{"relative_path": "另一个目录/定义.md"}, {"previous_relative_path": "第一章/定义.md"}]:
            conflict = client.post(endpoint, json={**request, **changed})
            assert conflict.status_code == 409 and "重复请求" in conflict.json()["detail"]
        current = client.get(base + "/knowledge/sources/" + note["document_id"]).json()
        assert current["version"] == source["version"] + 1
        assert client.get(base + f"/knowledge/libraries/{sid}/notes").json()[0]["provenance"]["relative_paths"] == [
            "第一章/定义.md", "新复习/定义.md"]


def test_http_create_operation_does_not_ignore_a_changed_relative_path(tmp_path):
    base = "/api/v2/math-tutor/desktop"
    with client_at(tmp_path / "create-path-idempotency.db") as client:
        sid = client.post(base + "/knowledge/libraries", json={"name": "路径幂等"}).json()["space_id"]
        endpoint = base + f"/knowledge/libraries/{sid}/notes"
        request = {"title": "定义", "body": "同一份正文。", "operation_id": "create-with-path", "relative_path": "一章/定义.md"}
        first = client.post(endpoint, json=request)
        assert first.status_code == 200, first.text
        repeated = client.post(endpoint, json=request)
        assert repeated.status_code == 200 and repeated.json() == first.json()
        conflict = client.post(endpoint, json={**request, "relative_path": "二章/定义.md"})
        assert conflict.status_code == 409 and "重复请求" in conflict.json()["detail"]
        notes = client.get(base + f"/knowledge/libraries/{sid}/notes").json()
        assert len(notes) == 1 and notes[0]["provenance"]["relative_path"] == "一章/定义.md"


def test_no_text_pdf_is_not_exported_as_a_fabricated_markdown_document(tmp_path):
    from test_pdf_classification import _pdf_with_pages
    base = "/api/v2/math-tutor/desktop"
    with client_at(tmp_path / "no-text.db") as client:
        sid = client.post(base + "/knowledge/libraries", json={"name": "尚无文字"}).json()["space_id"]
        response = client.post(base + f"/knowledge/libraries/{sid}/imports",
            files={"file": ("empty.pdf", _pdf_with_pages([""]), "application/pdf")})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "needs_ocr"
        exported = client.get(base + f"/content/libraries/{sid}/export")
        assert exported.status_code == 422 and "尚未提取到文字" in exported.json()["detail"]
