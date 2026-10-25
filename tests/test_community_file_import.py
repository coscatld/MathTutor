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


def plugin_upload(client, raw, filename="下载的插件.mtplugin", operation="plugin-upload", **kwargs):
    return client.post(PREFIX + "/plugins/import", files={"file": (filename, raw, "application/octet-stream")},
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


@pytest.mark.asyncio
async def test_thirty_three_real_share_imports_work_with_all_source_slots_full_and_do_not_cache_packages(state):
    service = CommunityService(state)
    for index in range(32):
        service.subscribe("alice", f"已有来源 {index}", f"https://example.org/catalog-{index}.json")
    previous_sources = deepcopy(service._load("alice")["sources"])
    for index in range(33):
        pack = question_pack()
        pack["questions"][0].update(title=f"方程 {index}", stem=f"解方程 x+{index}={index + 2}。")
        row = resource(package=pack, resource_id=f"test.shared-file-{index:02d}")
        raw = canonical_bytes({"format": RESOURCE_FORMAT, "resource": row})
        imported = await service.import_file("alice", raw, f"分享题库{index}.mathtutor", operation_id=f"copy-{index}")
        assert imported["kind"] == "question-pack" and imported["imported_count"] == 1
    assert len(await state.knowledge.list_spaces("alice")) == 33
    assert len(await state.documents.list_documents("alice")) == 33
    restarted = CommunityService(state)
    current = restarted._load("alice")
    assert current["sources"] == previous_sources
    assert len(current["history"]) == 33 and restarted.history("bob")["imports"] == []
    assert all(record["source_id"] == "" and record["source_name"] == "分享文件" for record in current["history"])
    assert all("metadata" in record and "package" not in record for record in current["history"])
    assert all("metadata" not in record for record in restarted.history("alice")["imports"])
    saved = restarted._path("alice").read_bytes()
    assert b'"data_base64"' not in saved and b'"stem"' not in saved
    assert await state.knowledge.list_spaces("bob") == []


@pytest.mark.asyncio
async def test_direct_share_receipts_enforce_version_hash_metadata_and_preserve_personal_edits(state):
    service = CommunityService(state)
    row = resource()
    raw = canonical_bytes({"format": RESOURCE_FORMAT, "resource": row})
    first = await service.import_file("alice", raw, "题库.mathtutor", operation_id="direct-first")
    assert service._load("alice")["sources"] == []
    note = (await state.knowledge.list_notes("alice", first["space_id"]))[0]
    old = await state.knowledge.snapshot("alice", note["document_id"])
    edited = old["body"] + "\n个人编辑必须保留。"
    await state.knowledge.save_markdown("alice", first["space_id"], title=old["title"], body=edited,
        operation_id="edit-personal-copy", document_id=note["document_id"], expected_version=old["version"])
    same_version_changes = [resource(package=question_pack("x=2；代回检验成立。")),
        {**row, "metadata": {**row["metadata"], "author": "另一位作者"}},
        {**row, "metadata": {**row["metadata"], "tags": ["修改后的标签"]}}]
    before = service._path("alice").read_bytes()
    for changed in same_version_changes:
        with pytest.raises(CommunityError, match="同一资源版本"):
            await service.import_file("alice", canonical_bytes({"format": RESOURCE_FORMAT, "resource": changed}),
                "同版本修改.mathtutor", operation_id="rejected-change")
        assert service._path("alice").read_bytes() == before
    assert await service.import_file("alice", raw, "再次下载.mathtutor", operation_id="direct-first") == first
    updated = resource("1.1.0", package=question_pack("x=2；代回检验成立。"))
    next_copy = await service.import_file("alice", canonical_bytes({"format": RESOURCE_FORMAT, "resource": updated}),
        "更新版.mathtutor", operation_id="direct-upgrade")
    assert next_copy["space_id"] != first["space_id"]
    assert (await state.knowledge.snapshot("alice", note["document_id"]))["body"] == edited
    assert service._load("alice")["sources"] == []


@pytest.mark.asyncio
async def test_preexisting_source_based_receipt_replays_without_new_source_or_library(state):
    service = CommunityService(state)
    row = resource()
    raw = canonical_bytes({"format": RESOURCE_FORMAT, "resource": row})
    source = service.import_source("alice", raw)
    original = await service.import_resource("alice", row["metadata"]["id"], version="1.0.0",
        expected_sha256=row["metadata"]["package_sha256"], operation_id="legacy-operation")
    legacy = service._load("alice")
    legacy["history"][0].pop("metadata")  # State produced before direct-file imports.
    service._save("alice", legacy)
    before = service._path("alice").read_bytes()
    replay = await CommunityService(state).import_file("alice", raw, "旧分享包.mtplugin", operation_id="legacy-operation")
    assert replay == {"kind": "question-pack", **original}
    assert service._path("alice").read_bytes() == before
    assert len(await state.knowledge.list_spaces("alice")) == 1
    assert service._load("alice")["sources"][0]["id"] == source["id"]
    # An explicitly removed legacy source must not make its durable receipt
    # unusable; the original package supplied by the user is still validated.
    service.remove_source("alice", source["id"])
    replay = await service.import_file("alice", raw, "旧分享包.mathtutor", operation_id="legacy-operation")
    assert replay["space_id"] == original["space_id"] and service._load("alice")["sources"] == []


@pytest.mark.asyncio
async def test_direct_resource_history_failure_rolls_back_only_new_library_without_creating_a_source(state, monkeypatch):
    service = CommunityService(state)
    row = resource()
    raw = canonical_bytes({"format": RESOURCE_FORMAT, "resource": row})
    first = await service.import_file("alice", raw, "题库.mathtutor", operation_id="first-success")
    previous_spaces = await state.knowledge.list_spaces("alice")
    before = service._path("alice").read_bytes()
    def fail(*args):
        raise OSError("fixture direct history failure")
    monkeypatch.setattr(service, "_save", fail)
    with pytest.raises(CommunityError, match="已撤回"):
        await service.import_file("alice", raw, "再次导入.mathtutor", operation_id="failed-copy")
    assert await state.knowledge.list_spaces("alice") == previous_spaces
    assert await state.knowledge.require_space("alice", first["space_id"])
    assert service._path("alice").read_bytes() == before
    assert service._load("alice")["sources"] == []


def test_direct_plugin_envelope_history_failure_reports_installed_plugin_without_source_cache(tmp_path, monkeypatch):
    with client_at(tmp_path / "direct-plugin-history.db") as client:
        service = get_product_state().community
        item = service.catalog("local-admin", type="plugin")["resources"][0]
        exported = client.get(PREFIX + f"/resources/{item['id']}/export")
        assert exported.status_code == 200
        def fail(*args):
            raise OSError("fixture direct plugin history failure")
        monkeypatch.setattr(service, "_save", fail)
        result = upload(client, exported.content)
        assert result.status_code == 200, result.text
        assert result.json()["kind"] == "plugin" and result.json()["history_recorded"] is False
        assert result.json()["plugin"]["enabled"] is False
        assert any("安装成功" in warning for warning in result.json()["warnings"])
        assert len(client.get(PREFIX + "/plugins").json()["items"]) == 1
        assert len(client.get(PREFIX + "/sources").json()["sources"]) == 1
        assert upload(client, exported.content).status_code == 200
        assert len(client.get(PREFIX + "/plugins").json()["items"]) == 1


@pytest.mark.parametrize("wrapped", [False, True], ids=["bare-plugin", "shared-plugin"])
def test_plugin_only_upload_installs_disabled_retries_and_is_owner_isolated(tmp_path, wrapped, monkeypatch):
    monkeypatch.setenv("MATHTUTOR_ALLOWED_ORIGINS", "http://127.0.0.1:3199")
    with client_at(tmp_path / "plugin-only.db") as client:
        package = builtin_plugin_packages()[0]
        if wrapped:
            exported = client.get(PREFIX + f"/resources/{package['id']}/export")
            assert exported.status_code == 200
            raw = exported.content
        else:
            raw = canonical_bytes(package)
        first = plugin_upload(client, raw, headers={"Origin": "http://127.0.0.1:3199"})
        assert first.status_code == 200, first.text
        result = first.json()
        assert result["kind"] == "plugin" and result["plugin"]["plugin"] == package
        assert result["plugin"]["enabled"] is False and result["plugin"]["consented_permissions"] == []
        assert plugin_upload(client, raw).json() == result
        assert len(client.get(PREFIX + "/plugins").json()["items"]) == 1
        assert client.get(BASE + "/knowledge/libraries").json() == []
        assert get_product_state().community._load("local-admin")["sources"] == []
        client.app.dependency_overrides[require_student_owner] = lambda: owner("bob")
        assert client.get(PREFIX + "/plugins").json()["items"] == []
        second = plugin_upload(client, raw)
        assert second.status_code == 200 and second.json()["plugin"]["enabled"] is False
        assert len(client.get(PREFIX + "/plugins").json()["items"]) == 1
        assert get_product_state().community._load("bob")["sources"] == []
        client.app.dependency_overrides.pop(require_student_owner)
        assert len(client.get(PREFIX + "/plugins").json()["items"]) == 1


def test_plugin_only_upgrade_preserves_config_disables_and_does_not_grant_new_permission(tmp_path):
    with client_at(tmp_path / "plugin-only-upgrade.db") as client:
        package = builtin_plugin_packages()[0]
        raw = canonical_bytes(package)
        assert plugin_upload(client, raw).status_code == 200
        plugin_id = package["id"]
        assert client.patch(PREFIX + f"/plugins/{plugin_id}/config", json={"config": {"grade": 12}}).status_code == 200
        assert client.put(PREFIX + f"/plugins/{plugin_id}/enabled", json={"enabled": True,
            "consent_permissions": ["question_bank"]}).status_code == 200
        same = plugin_upload(client, raw, operation="same-package")
        assert same.status_code == 200 and same.json()["plugin"]["enabled"] is True
        update = {**package, "version": "1.1.0", "required_permissions": ["question_bank", "read_learning_records"]}
        upgraded = plugin_upload(client, canonical_bytes(update), operation="new-version")
        assert upgraded.status_code == 200, upgraded.text
        installed = upgraded.json()["plugin"]
        assert installed["enabled"] is False and installed["config"]["grade"] == 12
        assert installed["consented_permissions"] == ["question_bank"]
        assert client.post(PREFIX + f"/plugins/{plugin_id}/run", json={}).status_code == 409
        assert plugin_upload(client, canonical_bytes(update), operation="plugin-upload").status_code == 409


def test_plugin_only_wrong_files_or_hashes_are_rejected_before_any_writes(tmp_path):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("笔记/函数.md", "# 定义域\n先写出定义域。")
    wrong = [(canonical_bytes(question_pack()), "题库.mathtutor"),
        (canonical_bytes({"format": RESOURCE_FORMAT, "resource": resource()}), "题库分享.mtplugin"),
        (catalog(resource()), "资源目录.mathtutor"), (stream.getvalue(), "笔记.zip"),
        ("# 普通笔记\n不能安装为插件。".encode(), "文件夹/笔记.md"),
        (b"print('never execute')", "插件.py")]
    with client_at(tmp_path / "plugin-only-rejection.db") as client:
        package = builtin_plugin_packages()[0]
        exported = client.get(PREFIX + f"/resources/{package['id']}/export")
        import json
        invalid_hash = json.loads(exported.content)
        invalid_hash["resource"]["metadata"]["package_sha256"] = "0" * 64
        wrong.append((canonical_bytes(invalid_hash), "损坏插件.mtplugin"))
        invalid_owner = deepcopy(invalid_hash)
        invalid_owner["resource"]["metadata"]["owner_id"] = "other"
        wrong.append((canonical_bytes(invalid_owner), "伪造所有者.mtplugin"))
        for raw, name in wrong:
            result = plugin_upload(client, raw, name)
            assert result.status_code == 422, (name, result.text)
            assert "JSON" not in result.text and "SHA256" not in result.text
            assert client.get(PREFIX + "/plugins").json()["items"] == []
            assert client.get(BASE + "/knowledge/libraries").json() == []
            assert get_product_state().community._load("local-admin")["sources"] == []
            assert not get_product_state().community._path("local-admin").exists()


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "file:///"])
def test_plugin_only_upload_rejects_foreign_origins_before_changes(tmp_path, origin):
    with client_at(tmp_path / "plugin-only-origin.db") as client:
        result = plugin_upload(client, canonical_bytes(builtin_plugin_packages()[0]), headers={"Origin": origin})
        assert result.status_code == 403
        assert client.get(PREFIX + "/plugins").json()["items"] == []
        assert not get_product_state().community._path("local-admin").exists()
