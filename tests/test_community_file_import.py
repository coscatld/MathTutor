"""Downloaded files become usable personal resources in one real HTTP action."""
from copy import deepcopy
import io
import zipfile

import pytest

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.application.community import CommunityError, CommunityService, MAX_SHARE_BYTES, RESOURCE_FORMAT, canonical_bytes
from mathtutor.application.question_packs import MAX_UPLOAD_BYTES
from mathtutor.extensions.community_plugins import builtin_plugin_packages
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope
from test_community_resources import catalog, question_pack, resource
from test_knowledge_workbench import state
from test_tutor_p0 import client_at

BASE = "/api/v2/math-tutor/desktop"
PREFIX = BASE + "/community"


def upload(client, raw, filename="下载的学习工具.mathtutor", operation="one-click", **kwargs):
    return client.post(PREFIX + "/import", files={"file": (filename, raw, "application/octet-stream")},
        data={"operation_id": operation} if operation is not None else {}, **kwargs)


def owner(name):
    return StudentOwnerScope(principal=PrincipalScope(user_id=name, username=name, role="student"), student_id=name)


@pytest.mark.parametrize("extension", [".mathtutor", ".mtplugin", ".json"])
def test_exported_plugin_download_imports_directly_without_editing_and_is_disabled(tmp_path, extension):
    with client_at(tmp_path / "plugin-file.db") as client:
        package = builtin_plugin_packages()[0]
        installed = client.post(PREFIX + "/plugins", json={"package": package})
        assert installed.status_code == 200
        exported = client.get(PREFIX + f"/plugins/{package['id']}/export")
        assert exported.status_code == 200
        assert client.delete(PREFIX + f"/plugins/{package['id']}").status_code == 200
        imported = upload(client, exported.content, "插件" + extension)
        assert imported.status_code == 200, imported.text
        result = imported.json()
        assert result["kind"] == "plugin" and result["plugin"]["plugin"] == exported.json()
        assert result["plugin"]["enabled"] is False and result["plugin"]["consented_permissions"] == []
        assert upload(client, exported.content, "插件" + extension).json() == result
        assert len(client.get(PREFIX + "/plugins").json()["items"]) == 1
        assert len(client.get(PREFIX + "/sources").json()["sources"]) == 1
        assert client.get(BASE + "/knowledge/libraries").json() == []


def test_exported_community_resource_imports_immediately_for_another_owner(tmp_path):
    with client_at(tmp_path / "shared-resource.db") as client:
        item = client.get(PREFIX + "/catalog?type=plugin").json()["resources"][0]
        exported = client.get(PREFIX + f"/resources/{item['id']}/export")
        assert exported.status_code == 200
        client.app.dependency_overrides[require_student_owner] = lambda: owner("bob")
        result = upload(client, exported.content, "朋友分享.mtplugin")
        assert result.status_code == 200, result.text
        assert result.json()["kind"] == "plugin" and result.json()["plugin"]["enabled"] is False
        assert result.json()["plugin"]["plugin"]["id"] == item["id"]
        assert len(client.get(PREFIX + "/plugins").json()["items"]) == 1
        assert upload(client, exported.content, "朋友分享.mtplugin").json() == result.json()
        client.app.dependency_overrides.pop(require_student_owner)
        assert client.get(PREFIX + "/plugins").json()["items"] == []
        assert len(client.get(PREFIX + "/sources").json()["sources"]) == 1


def test_plugin_upgrade_is_disabled_preserves_configuration_and_same_hash_is_idempotent(tmp_path):
    with client_at(tmp_path / "plugin-update.db") as client:
        original = builtin_plugin_packages()[0]
        assert upload(client, canonical_bytes(original)).status_code == 200
        plugin_id = original["id"]
        assert client.patch(PREFIX + f"/plugins/{plugin_id}/config", json={"config": {"grade": 12}}).status_code == 200
        assert client.put(PREFIX + f"/plugins/{plugin_id}/enabled", json={
            "enabled": True, "consent_permissions": original["required_permissions"]}).status_code == 200
        repeated = upload(client, canonical_bytes(original), operation="same-package-new-request")
        assert repeated.status_code == 200 and repeated.json()["plugin"]["enabled"] is True
        upgrade = {**original, "version": "1.1.0", "changelog": "新增使用说明。"}
        response = upload(client, canonical_bytes(upgrade), operation="upgrade")
        assert response.status_code == 200, response.text
        assert response.json()["plugin"]["enabled"] is False
        assert response.json()["plugin"]["config"]["grade"] == 12
        reused = upload(client, canonical_bytes(upgrade), operation="one-click")
        assert reused.status_code == 409
        same_version = {**upgrade, "description": "同版本不能更换内容。"}
        assert upload(client, canonical_bytes(same_version), operation="bad-upgrade").status_code == 409


def test_naked_question_pack_imports_once_remains_editable_and_receipt_survives_restart(tmp_path):
    db = tmp_path / "question-file.db"
    raw = canonical_bytes(question_pack())
    with client_at(db) as client:
        imported = upload(client, raw)
        assert imported.status_code == 200, imported.text
        receipt = imported.json()
        sid = receipt["space_id"]
        assert receipt["kind"] == "question-pack" and receipt["imported_count"] == 1
        assert upload(client, raw).json() == receipt
        assert len(client.get(BASE + "/knowledge/libraries").json()) == 1
        note = client.get(BASE + f"/knowledge/libraries/{sid}/notes").json()[0]
        snapshot = client.get(BASE + f"/knowledge/sources/{note['document_id']}").json()
        edited = snapshot["body"] + "\n自己的补充笔记。"
        saved = client.post(BASE + f"/knowledge/libraries/{sid}/notes", json={
            "title": snapshot["title"], "body": edited, "tags": [], "document_id": note["document_id"],
            "expected_version": snapshot["version"], "operation_id": "edit-imported"})
        assert saved.status_code == 200, saved.text
        assert client.get(BASE + f"/knowledge/sources/{note['document_id']}").json()["body"] == edited
        scope = client.get(BASE + "/knowledge/conversations/not-created").json()
        assert scope["space_ids"] == [] and scope["effective_document_ids"] == []
        changed = upload(client, canonical_bytes(question_pack("x=3")))
        assert changed.status_code == 409
        client.app.dependency_overrides[require_student_owner] = lambda: owner("bob")
        bob = upload(client, raw)
        assert bob.status_code == 200 and bob.json()["space_id"] != sid
        client.app.dependency_overrides.pop(require_student_owner)
    with client_at(db) as client:
        assert upload(client, raw).json() == receipt
        assert len(client.get(BASE + "/knowledge/libraries").json()) == 1


def test_markdown_archive_detected_by_bytes_and_catalog_only_adds_a_source(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("高中/函数.md", "# 函数\n先检查定义域。")
    with client_at(tmp_path / "vault-file.db") as client:
        imported = upload(client, stream.getvalue(), "函数资料.mathtutor")
        assert imported.status_code == 200, imported.text
        assert imported.json()["kind"] == "question-pack" and imported.json()["imported_count"] == 1
        sid = imported.json()["space_id"]
        note = client.get(BASE + f"/knowledge/libraries/{sid}/notes").json()[0]
        assert note["provenance"]["relative_path"] == "高中/函数.md"
        source = upload(client, catalog(resource()), "资源来源.mathtutor", operation="catalog-only")
        assert source.status_code == 200 and source.json()["kind"] == "source"
        assert source.json()["source"]["resource_count"] == 1
        assert len(client.get(BASE + "/knowledge/libraries").json()) == 1
        assert client.get(PREFIX + "/plugins").json()["items"] == []


def test_downloaded_question_resource_imports_in_one_action_and_operation_conflicts_do_not_add_sources(tmp_path):
    with client_at(tmp_path / "shared-question-file.db") as client:
        row = resource()
        raw = canonical_bytes({"format": RESOURCE_FORMAT, "resource": row})
        imported = upload(client, raw)
        assert imported.status_code == 200, imported.text
        assert imported.json()["kind"] == "question-pack" and imported.json()["imported_count"] == 1
        assert upload(client, raw).json() == imported.json()
        source_count = len(client.get(PREFIX + "/sources").json()["sources"])
        assert len(client.get(BASE + "/knowledge/libraries").json()) == 1
        changed = canonical_bytes({"format": RESOURCE_FORMAT,
            "resource": resource(resource_id="test.different-package")})
        assert upload(client, changed).status_code == 409
        # Reusing an operation across the raw-file and resource-envelope paths
        # must not bypass their separate durable receipt stores.
        assert upload(client, canonical_bytes(question_pack())).status_code == 409
        assert len(client.get(PREFIX + "/sources").json()["sources"]) == source_count
        assert len(client.get(BASE + "/knowledge/libraries").json()) == 1
        plain = upload(client, canonical_bytes(question_pack()), operation="plain-first")
        assert plain.status_code == 200
        assert upload(client, raw, operation="plain-first").status_code == 409
        assert len(client.get(PREFIX + "/sources").json()["sources"]) == source_count


def test_modified_hash_private_references_and_foreign_owner_sources_cannot_be_imported(tmp_path):
    with client_at(tmp_path / "invalid-file.db") as client:
        row = resource()
        assert client.post(PREFIX + "/sources/import", files={"file": ("owner-source.json", catalog(row))}).status_code == 200
        client.app.dependency_overrides[require_student_owner] = lambda: owner("bob")
        tampered = deepcopy(row)
        tampered["metadata"]["package_sha256"] = "0" * 64
        borrowed = deepcopy(row)
        borrowed["package"] = {"filename": "questions.json", "media_type": "application/json", "download_url": "https://example.org/private.json"}
        owner_field = deepcopy(row)
        owner_field["metadata"]["owner_id"] = "local-admin"
        invalid = [canonical_bytes({"format": RESOURCE_FORMAT, "resource": item}) for item in (tampered, borrowed, owner_field)]
        invalid.append(canonical_bytes({"resource_id": row["metadata"]["id"], "source_id": "alice-source"}))
        invalid.extend([b"print('do not execute')", b"\x89PNG\r\n\x1a\n", b'{"format":"x","format":"y"}'])
        for raw in invalid:
            response = upload(client, raw, operation="invalid-attempt")
            assert response.status_code == 409, response.text
            assert "JSON" not in response.text and "SHA256" not in response.text
        assert client.get(BASE + "/knowledge/libraries").json() == []
        assert len(client.get(PREFIX + "/sources").json()["sources"]) == 1
        assert client.get(PREFIX + "/plugins").json()["items"] == []
        assert client.get(PREFIX + "/history").json()["imports"] == []


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "file:///"])
def test_one_click_import_rejects_cross_origin_before_any_install(tmp_path, origin):
    with client_at(tmp_path / "origin-file.db") as client:
        result = upload(client, canonical_bytes(builtin_plugin_packages()[0]), headers={"Origin": origin})
        assert result.status_code == 403
        assert client.get(PREFIX + "/plugins").json()["items"] == []


def test_one_click_file_and_original_question_archive_size_limits(tmp_path):
    with client_at(tmp_path / "size-file.db") as client:
        too_large = upload(client, b"x" * (MAX_SHARE_BYTES + 1))
        assert too_large.status_code == 413
        question_too_large = upload(client, b"PK\x03\x04" + b"x" * MAX_UPLOAD_BYTES)
        assert question_too_large.status_code == 409 and "20 MiB" in question_too_large.text
        assert client.get(BASE + "/knowledge/libraries").json() == []


@pytest.mark.asyncio
async def test_file_receipt_failure_compensates_only_new_question_library(state, monkeypatch):
    service = CommunityService(state)
    old = await service.import_file("alice", canonical_bytes(question_pack()), "旧题库.mathtutor", operation_id="old-file")
    spaces = await state.knowledge.list_spaces("alice")
    notes = await state.knowledge.list_notes("alice", old["space_id"])
    before = await state.knowledge.snapshot("alice", notes[0]["document_id"])
    def fail(*args):
        raise OSError("fixture receipt save failed")
    monkeypatch.setattr(service, "_save", fail)
    with pytest.raises(CommunityError, match="已撤回"):
        await service.import_file("alice", canonical_bytes(question_pack()), "再次下载.mathtutor", operation_id="new-file")
    assert await state.knowledge.list_spaces("alice") == spaces
    assert await state.knowledge.snapshot("alice", notes[0]["document_id"]) == before


def test_file_plugin_receipt_failure_reports_actual_install_and_same_package_retry_is_safe(tmp_path, monkeypatch):
    with client_at(tmp_path / "plugin-write-file.db") as client:
        service = get_product_state().community
        def fail(*args):
            raise OSError("fixture receipt save failed")
        monkeypatch.setattr(service, "_save", fail)
        raw = canonical_bytes(builtin_plugin_packages()[0])
        result = upload(client, raw)
        assert result.status_code == 200, result.text
        assert result.json()["history_recorded"] is False and result.json()["warnings"]
        assert result.json()["plugin"]["enabled"] is False
        assert upload(client, raw).status_code == 200
        assert len(client.get(PREFIX + "/plugins").json()["items"]) == 1
