"""Real folder/TXT import, edit/export, preflight boundaries and owner isolation."""
import io
import json
import zipfile

from fastapi.testclient import TestClient
import pytest

from test_tutor_p0 import client_at
from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.api.product_state import get_product_state, reset_product_state
from mathtutor.application.community import CATALOG_FORMAT, RESOURCE_FORMAT, canonical_bytes
from mathtutor.application.community_documents import CommunityDocumentService, DocumentUpload
from mathtutor.application.question_packs import MAX_MARKDOWN_BYTES, QUESTION_FORMAT, parse_pack
from mathtutor.extensions.community_plugins import builtin_plugin_packages, package_hash
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope
from mathtutor.security.settings import MathTutorSecuritySettings

BASE = "/api/v2/math-tutor/desktop"
ENDPOINT = BASE + "/community/documents/import"


def upload(client, items, *, operation_id="document-import", headers=None):
    return client.post(ENDPOINT, files=[("files", (path, data, "application/octet-stream")) for path, data in items],
                       data={"operation_id": operation_id}, headers=headers or {})


def archive(items):
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w", compression=zipfile.ZIP_STORED) as bundle:
        for path, data in items:
            bundle.writestr(path, data)
    return result.getvalue()


def question_pack():
    return {"format": QUESTION_FORMAT, "name": "课堂练习", "questions": [
        {"id": "linear", "stem": "求解 2x=4。", "answer": "x=2"}]}


def envelope(payload, type_):
    return {"format": RESOURCE_FORMAT, "resource": {"metadata": {
        **{key: payload[key] for key in ("id", "version", "name", "description", "author", "license", "tags", "grades", "readme", "changelog")},
        "type": type_, "permissions": payload["required_permissions"], "package_sha256": package_hash(payload)},
        "package": {"filename": "plugin.json", "media_type": "application/json", "data": payload}}}


def assert_no_imports(client):
    assert client.get(BASE + "/knowledge/libraries").json() == []
    assert client.get(BASE + "/community/plugins").json()["items"] == []
    assert len(client.get(BASE + "/community/sources").json()["sources"]) == 1


@pytest.mark.parametrize("suffix", ["md", "markdown", "txt"], ids=["markdown", "long-markdown", "plain-text"])
def test_single_text_import_stays_unmounted_and_txt_is_editable_and_exported_as_txt(tmp_path, suffix):
    path = "课堂/定义." + suffix
    with client_at(tmp_path / "text.db") as client:
        response = upload(client, [(path, "# 定义\n请先明确变量的取值范围。".encode())])
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["kind"] == "question-pack" and result["imported_count"] == 1
        sid = result["space_id"]
        note = client.get(BASE + f"/knowledge/libraries/{sid}/notes").json()[0]
        assert note["editable"] and note["provenance"]["relative_path"] == path
        assert client.get(BASE + "/knowledge/conversations/unmounted").json()["space_ids"] == []
        source = client.get(BASE + "/knowledge/sources/" + note["document_id"]).json()
        if suffix == "txt":
            assert source["title"].endswith(".txt") and not source["title"].endswith(".txt.md")
            assert source["provenance"]["source_format"] == "text"
            metadata = client.get(BASE + "/documents/" + note["document_id"]).json()
            assert metadata["mime_type"] == "text/plain" and metadata["filename"].endswith(".txt")
        edited = source["body"] + "\n新增自己的课堂补充。"
        saved = client.post(BASE + f"/knowledge/libraries/{sid}/notes", json={
            "document_id": note["document_id"], "expected_version": source["version"],
            "title": source["title"], "body": edited, "operation_id": "edit-imported-text", "relative_path": path,
        })
        assert saved.status_code == 200, saved.text
        current = client.get(BASE + "/knowledge/sources/" + note["document_id"]).json()
        if suffix == "txt":
            assert current["title"].endswith(".txt") and current["provenance"]["relative_path"] == path
            assert client.get(BASE + "/documents/" + note["document_id"]).json()["mime_type"] == "text/plain"
        exported = client.get(BASE + f"/content/libraries/{sid}/export")
        assert exported.status_code == 200, exported.text
        parsed = parse_pack(exported.content, "exported.zip")
        assert [(n.path, n.body) for n in parsed.notes] == [(path, edited)]


def test_folder_mixed_paths_are_preserved_and_order_independent_retries_are_idempotent(tmp_path):
    files = [("数学/高一/函数.md", "函数的定义。".encode()), ("数学/高二/课堂.txt", "数列的观察。".encode()),
             ("数学/高三/回顾.markdown", "复习的要点。".encode())]
    with client_at(tmp_path / "folder.db") as client:
        first = upload(client, files)
        second = upload(client, files[::-1])
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        sid = first.json()["space_id"]
        notes = client.get(BASE + f"/knowledge/libraries/{sid}/notes").json()
        assert {n["provenance"]["relative_path"] for n in notes} == {row[0] for row in files}
        assert len(client.get(BASE + "/knowledge/libraries").json()) == 1
        changed = upload(client, [(files[0][0], b"changed"), *files[1:]])
        assert changed.status_code == 409 and len(client.get(BASE + "/knowledge/libraries").json()) == 1
        prepared = CommunityDocumentService(get_product_state()).prepare([DocumentUpload(*item) for item in files])
        with zipfile.ZipFile(io.BytesIO(prepared.data)) as bundle:
            assert [info.filename for info in bundle.infolist()] == sorted(row[0] for row in files)
            assert all(info.date_time == (1980, 1, 1, 0, 0, 0) and info.compress_type == zipfile.ZIP_STORED for info in bundle.infolist())


def test_uploads_are_owner_isolated_and_other_owner_cannot_edit_or_export(tmp_path):
    with client_at(tmp_path / "owners.db") as client:
        first = upload(client, [("笔记.txt", "自己的参考资料。".encode())]).json()
        sid = first["space_id"]
        note = client.get(BASE + f"/knowledge/libraries/{sid}/notes").json()[0]
        bob = StudentOwnerScope(principal=PrincipalScope(user_id="bob", username="bob", role="student"), student_id="bob")
        client.app.dependency_overrides[require_student_owner] = lambda: bob
        try:
            assert client.get(BASE + "/knowledge/libraries").json() == []
            assert client.get(BASE + f"/knowledge/libraries/{sid}/notes").status_code == 409
            assert client.get(BASE + f"/content/libraries/{sid}/export").status_code == 409
            assert client.post(BASE + f"/knowledge/libraries/{sid}/notes", json={"title": "笔记.txt", "body": "越权更新",
                "document_id": note["document_id"], "expected_version": 1, "operation_id": "cross-owner", "relative_path": "笔记.txt"}).status_code == 409
            other = upload(client, [("笔记.txt", "自己的参考资料。".encode())])
            assert other.status_code == 200 and other.json()["space_id"] != sid
        finally:
            client.app.dependency_overrides.pop(require_student_owner)


@pytest.mark.parametrize("path", ["../escape.txt", "/absolute.md", "C:/drive.txt", "folder\\bad.txt", ".hidden/a.md", "a//b.md", "a/./b.txt", "a/../b.txt"],
                         ids=["parent", "absolute", "drive", "backslash", "hidden", "empty-part", "dot", "parent-in-tree"])
def test_unsafe_paths_fail_before_any_library_or_receipt_write(tmp_path, path):
    with client_at(tmp_path / "unsafe.db") as client:
        result = upload(client, [("safe.md", b"valid"), (path, b"invalid")])
        assert result.status_code == 409, result.text
        assert_no_imports(client)


@pytest.mark.parametrize("items", [
    pytest.param([("A.md", b"first"), ("a.MD", b"second")], id="casefold-collision"),
    pytest.param([("caf\u00e9.txt", b"first"), ("cafe\u0301.txt", b"second")], id="unicode-collision"),
    pytest.param([("a.txt", b"first"), ("a.txt/b.md", b"second")], id="file-directory-collision"),
    pytest.param([("valid.md", b"fine"), ("bad.txt", b"\xff\xfe")], id="not-utf8"),
    pytest.param([("empty.txt", b" \r\n")], id="empty-body"),
    pytest.param([("binary.txt", b"hello\x00world")], id="nul-byte"),
    pytest.param([("ignored.py", b"code")], id="unsupported-file"),
])
def test_whole_batch_validation_rejects_collisions_or_invalid_text_without_partial_import(tmp_path, items):
    with client_at(tmp_path / "invalid.db") as client:
        response = upload(client, items)
        assert response.status_code == 409, response.text
        assert_no_imports(client)


@pytest.mark.parametrize("case", ["per-file", "total", "count"], ids=["per-file-limit", "total-limit", "count-limit"])
def test_upload_limits_leave_no_side_effects(tmp_path, case):
    if case == "per-file":
        items = [("large.txt", b"x" * (MAX_MARKDOWN_BYTES + 1))]
    elif case == "total":
        items = [(f"{i}.txt", b"x" * MAX_MARKDOWN_BYTES) for i in range(21)]
    else:
        items = [(f"{i}.txt", b"x") for i in range(1001)]
    with client_at(tmp_path / "limits.db") as client:
        response = upload(client, items)
        assert response.status_code in {400, 413}, response.text
        assert_no_imports(client)


def test_legacy_question_pack_zip_and_resource_envelope_are_still_supported(tmp_path):
    question = question_pack()
    package = {"filename": "questions.json", "media_type": "application/json", "data": question}
    from hashlib import sha256
    metadata = {"id": "example.question-bank", "version": "1.0.0", "name": "课堂练习", "description": "参考题库",
                "author": "作者", "license": "CC0-1.0", "type": "question-pack", "package_sha256": sha256(canonical_bytes(question)).hexdigest()}
    files = [("questions.json", canonical_bytes(question)), ("notes.zip", archive([("课堂/记录.txt", "真实课堂记录。".encode())])),
             ("questions.mathtutor", canonical_bytes({"format": RESOURCE_FORMAT, "resource": {"metadata": metadata, "package": package}}))]
    with client_at(tmp_path / "legacy.db") as client:
        for index, item in enumerate(files):
            result = upload(client, [item], operation_id=f"legacy-{index}")
            assert result.status_code == 200 and result.json()["kind"] == "question-pack", result.text
        assert len(client.get(BASE + "/knowledge/libraries").json()) == 3


@pytest.mark.parametrize("case", ["plugin", "plugin-envelope", "catalog", "forged-kind", "non-object"],
                         ids=["bare-plugin", "plugin-resource", "catalog-resource", "forged-question-resource", "non-object-top-level"])
def test_non_document_packages_are_rejected_during_preflight(tmp_path, case):
    plugin = builtin_plugin_packages()[0]
    if case == "plugin":
        payload = plugin
    elif case == "non-object":
        payload = []
    elif case == "catalog":
        payload = {"format": CATALOG_FORMAT, "name": "目录", "resources": [envelope(plugin, "plugin")["resource"]]}
    else:
        payload = envelope(plugin, "question-pack" if case == "forged-kind" else "plugin")
    with client_at(tmp_path / "kinds.db") as client:
        response = upload(client, [("download.mathtutor", canonical_bytes(payload))])
        assert response.status_code == 409, response.text
        assert_no_imports(client)


def test_failed_receipt_write_rolls_back_only_the_new_text_library(tmp_path, monkeypatch):
    with client_at(tmp_path / "receipt-failure.db") as client:
        def fail_save(*args, **kwargs):
            raise OSError("fixture disk failure")
        monkeypatch.setattr(get_product_state().community, "_save", fail_save)
        response = upload(client, [("课堂/第一份.md", "第一份资料。".encode()), ("课堂/第二份.txt", "第二份资料。".encode())])
        assert response.status_code == 409, response.text
        assert_no_imports(client)
        assert client.get(BASE + "/documents").json() == []


@pytest.mark.parametrize("origin", ["null", "https://evil.example", "http://127.0.0.1.evil.example"],
                         ids=["null-origin", "external-origin", "spoofed-origin"])
def test_external_origins_cannot_import_personal_files(tmp_path, origin):
    with client_at(tmp_path / "origin.db") as client:
        assert upload(client, [("safe.txt", b"valid")], headers={"Origin": origin}).status_code == 403
        assert_no_imports(client)


def test_document_import_requires_existing_owner_authentication():
    reset_product_state()
    try:
        app = create_math_tutor_app(MathTutorSecuritySettings(environment="development", host="127.0.0.1"),
                                   auth_enabled=True, auth_secret="fixture-test-secret-" * 4)
        with TestClient(app) as client:
            assert upload(client, [("safe.txt", b"valid")]).status_code == 401
    finally:
        reset_product_state()
