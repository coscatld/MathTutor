"""Community directory honesty, isolation, real copies and controlled downloads."""
import base64
from hashlib import sha256
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from test_knowledge_workbench import state
from test_tutor_p0 import client_at
from mathtutor.application.community import (
    ASSETS, CATALOG_FORMAT, RESOURCE_FORMAT, CommunityError, CommunityService, canonical_bytes,
)
from mathtutor.application.question_packs import QUESTION_FORMAT
from mathtutor.application.knowledge import KnowledgeError
from mathtutor.api.auth_deps import require_student_owner
from mathtutor.extensions.community_plugins import CommunityPluginService
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope
from mathtutor.infrastructure.knowledge_schema import drafts, operations


def question_pack(answer="x=2", *, title="社区测试方程"):
    return {"format": QUESTION_FORMAT, "name": title, "author": "测试资源作者", "questions": [
        {"id": "linear-1", "title": "求解方程", "stem": "解方程 2x+3=7。", "answer": answer, "grade": 7}]}


def resource(version="1.0.0", *, package=None, download_url=None, resource_id="test.community-equations"):
    package = question_pack() if package is None else package
    raw = canonical_bytes(package)
    descriptor = {"filename": "equations.json", "media_type": "application/json"}
    descriptor.update({"download_url": download_url} if download_url else {"data": package})
    return {"metadata": {"id": resource_id, "version": version, "type": "question-pack", "name": "社区测试方程",
        "author": "测试资源作者", "license": "CC0-1.0", "description": "测试目录，不含社交统计。", "tags": ["方程"],
        "grades": [7], "readme": "可编辑参考资料。", "changelog": version + "：参考资源更新。",
        "package_sha256": sha256(raw).hexdigest()}, "package": descriptor}


def catalog(*resources):
    return canonical_bytes({"format": CATALOG_FORMAT, "name": "测试用户目录", "resources": list(resources)})


class FakeFetcher:
    def __init__(self):
        self.data, self.calls = {}, []

    async def __call__(self, url, *, max_bytes):
        self.calls.append((url, max_bytes))
        result = self.data[url]
        if isinstance(result, Exception):
            raise result
        return result


def test_packaged_examples_have_real_hashes_and_reuse_original_math_sources():
    bundled = json.loads((ASSETS / "catalog.json").read_bytes())
    assert len(bundled["resources"]) == 2
    reference = json.loads((ASSETS.parent / "question_bank/curriculum_questions_v2.json").read_bytes())["questions"]
    by_id = {q["id"]: q for rows in reference.values() for q in rows}
    for item in bundled["resources"]:
        raw = (ASSETS / item["package"]["bundled_path"]).read_bytes()
        assert sha256(raw).hexdigest() == item["metadata"]["package_sha256"]
        assert item["metadata"]["project_example"] is True and "项目示例" in item["metadata"]["name"]
        pack = json.loads(raw)
        for question in pack["questions"]:
            if question["id"] in by_id:
                original = by_id[question["id"]]
                assert (question["stem"], question["answer"], question["explanation"]) == (
                    original["text"], original["reference_answer"], original["explanation"])
    linear = json.loads((ASSETS / "packs/linear-equations.json").read_bytes())
    assert [(q["stem"], q["answer"]) for q in linear["questions"]] == [
        ("解方程：2x + 3 = 7。", "x = 2。"), ("解方程：3x - 4 = 11。", "x = 5。")]
    assert 2 * 2 + 3 == 7 and 3 * 5 - 4 == 11


@pytest.mark.asyncio
async def test_catalog_search_stage_favorites_and_restart_are_owner_isolated(state):
    service = CommunityService(state)
    all_ = service.catalog("alice")
    assert len([r for r in all_["resources"] if r["type"] == "question-pack"]) == 2
    assert all(not ({"downloads", "rating", "likes", "stars"} & set(r)) for r in all_["resources"])
    high = service.catalog("alice", type="question-pack", stage="high", q="导数")["resources"]
    assert len(high) == 1
    rid = high[0]["id"]
    assert service.detail("alice", rid)["preview"]["documents"]
    service.favorite("alice", rid, True)
    restarted = CommunityService(state)
    assert [r["id"] for r in restarted.catalog("alice", favorites_only=True)["resources"]] == [rid]
    assert restarted.catalog("bob", favorites_only=True)["resources"] == []
    assert "alice" not in service._path("alice").name
    assert list(service.root.glob(".community-*")) == []


@pytest.mark.asyncio
async def test_import_updates_create_new_copies_preserve_edits_and_have_durable_history(state):
    service = CommunityService(state)
    first = resource()
    service.import_source("alice", catalog(first))
    item = service.detail("alice", first["metadata"]["id"])
    result = await service.import_resource("alice", item["id"], version=item["version"],
        expected_sha256=item["package_sha256"], operation_id="copy-v1")
    assert result == await service.import_resource("alice", item["id"], version=item["version"],
        expected_sha256=item["package_sha256"], operation_id="copy-v1")
    note = (await state.knowledge.list_notes("alice", result["space_id"]))[0]
    original = await state.knowledge.snapshot("alice", note["document_id"])
    body = original["body"] + "\n学生自己编辑的解题记录。"
    await state.knowledge.save_markdown("alice", result["space_id"], title=original["title"], body=body,
        tags=[], operation_id="student-edit", document_id=note["document_id"], expected_version=original["version"], provenance=original["provenance"])
    second = resource("1.1.0", package=question_pack("x=2；代回验证成立。"))
    service.import_source("alice", catalog(second))
    latest = CommunityService(state).detail("alice", item["id"])
    assert latest["version"] == "1.1.0" and latest["update_status"] == "update_available"
    with pytest.raises(CommunityError):
        await service.import_resource("alice", latest["id"], version=latest["version"], expected_sha256=latest["package_sha256"], operation_id="copy-v1")
    updated = await service.import_resource("alice", latest["id"], version=latest["version"],
        expected_sha256=latest["package_sha256"], operation_id="copy-v2")
    assert updated["space_id"] != result["space_id"]
    assert (await state.knowledge.snapshot("alice", note["document_id"]))["body"] == body
    assert len(service.history("alice")["imports"]) == 2
    assert CommunityService(state).detail("alice", item["id"])["update_status"] == "current"
    assert service.history("bob")["imports"] == []
    assert (await state.knowledge.reference_state("alice", "A"))["available_documents"] == []


@pytest.mark.asyncio
async def test_remote_refresh_only_fetches_catalog_and_explicit_import_checks_hash(state):
    fetch = FakeFetcher()
    url, package_url = "https://example.org/catalog.json", "https://example.org/packages/equations.json"
    row = resource(download_url="packages/equations.json")
    fetch.data[url], fetch.data[package_url] = catalog(row), canonical_bytes(question_pack())
    service = CommunityService(state, fetcher=fetch)
    source = service.subscribe("alice", "公开测试目录", url)
    assert fetch.calls == []
    source = await service.refresh("alice", source["id"])
    assert source["error"] is None and source["stale"] is False
    assert [call[0] for call in fetch.calls] == [url]
    detail = service.detail("alice", row["metadata"]["id"])
    assert detail["preview"]["available"] is False
    assert [call[0] for call in fetch.calls] == [url]
    with pytest.raises(CommunityError):
        await service.import_resource("alice", detail["id"], version=detail["version"], expected_sha256="0" * 64)
    assert [call[0] for call in fetch.calls] == [url]
    fetch.data[package_url] = b"tampered"
    with pytest.raises(CommunityError, match="SHA256"):
        await service.import_resource("alice", detail["id"], version=detail["version"], expected_sha256=detail["package_sha256"])
    assert service.history("alice")["imports"] == [] and await state.knowledge.list_spaces("alice") == []
    fetch.data[package_url] = canonical_bytes(question_pack())
    imported = await service.import_resource("alice", detail["id"], version=detail["version"], expected_sha256=detail["package_sha256"])
    assert imported["imported_count"] == 1 and fetch.calls[-1][0] == package_url


@pytest.mark.asyncio
async def test_failed_refresh_preserves_old_cache_marks_stale_and_source_delete_keeps_personal_copy(state):
    fetch = FakeFetcher()
    url = "https://example.org/catalog.json"
    fetch.data[url] = catalog(resource())
    service = CommunityService(state, fetcher=fetch)
    source = service.subscribe("alice", "可失效的源", url)
    fresh = await service.refresh("alice", source["id"])
    row = service.catalog("alice", q="社区测试方程")["resources"][0]
    imported = await service.import_resource("alice", row["id"], version=row["version"], expected_sha256=row["package_sha256"])
    fetch.data[url] = CommunityError("测试网络故障；保留缓存。")
    stale = await service.refresh("alice", source["id"])
    assert stale["stale"] is True and stale["error"] and stale["last_refreshed"] == fresh["last_refreshed"]
    assert service.catalog("alice", q="社区测试方程")["resources"]
    # Rewriting a cached version in-place cannot become a successful refresh.
    fetch.data[url] = catalog(resource(package=question_pack("变化后的同版本答案。")))
    stale = await service.refresh("alice", source["id"])
    assert stale["stale"] and "版本" in stale["error"]
    assert service.detail("alice", row["id"])["package_sha256"] == row["package_sha256"]
    service.remove_source("alice", source["id"])
    assert service.catalog("alice", q="社区测试方程")["resources"] == []
    assert await state.knowledge.require_space("alice", imported["space_id"])
    assert len(service.history("alice")["imports"]) == 1


@pytest.mark.asyncio
async def test_remote_packages_must_share_origin_and_private_subscriptions_are_rejected(state):
    fetch, url = FakeFetcher(), "https://example.org/catalog.json"
    fetch.data[url] = catalog(resource(download_url="https://other.example.net/package.json"))
    service = CommunityService(state, fetcher=fetch)
    for unsafe in ("http://example.org/catalog.json", "https://localhost/catalog.json", "https://127.0.0.1/a", "https://example.org/a?token=secret", "https://user:password@example.org/a"):
        with pytest.raises(CommunityError):
            service.subscribe("alice", "不安全地址", unsafe)
    source = service.subscribe("alice", "同源约束", url)
    response = await service.refresh("alice", source["id"])
    assert response["stale"] and "origin" in response["error"]
    assert response["resource_count"] == 0
    assert [call[0] for call in fetch.calls] == [url]


@pytest.mark.asyncio
async def test_invalid_local_catalogs_do_not_persist_or_read_arbitrary_assets(state):
    service = CommunityService(state)
    invalid = []
    bad = resource(); bad["metadata"]["owner_id"] = "forged"; invalid.append(catalog(bad))
    bad = resource(); bad["metadata"]["package_sha256"] = "0" * 64; invalid.append(catalog(bad))
    bad = resource(); bad["package"] = {"filename": "x.json", "media_type": "application/json", "bundled_path": "../../learner.json"}; invalid.append(catalog(bad))
    bad = resource(download_url="https://example.org/package.json"); invalid.append(catalog(bad))
    invalid.append(b'{"format":"x","format":"y"}')
    for raw in invalid:
        with pytest.raises((CommunityError, ValueError)):
            service.import_source("alice", raw)
    assert not service._path("alice").exists()


@pytest.mark.asyncio
async def test_export_share_preserves_current_markdown_metadata_and_allows_other_owner_copy(state):
    service = CommunityService(state)
    builtin = service.catalog("alice", type="question-pack")["resources"][0]
    copy = await service.import_resource("alice", builtin["id"], version=builtin["version"], expected_sha256=builtin["package_sha256"])
    note = (await state.knowledge.list_notes("alice", copy["space_id"]))[0]
    old = await state.knowledge.snapshot("alice", note["document_id"])
    edited = old["body"] + "\n个人修改，必须出现在分享包。"
    await state.knowledge.save_markdown("alice", copy["space_id"], title=old["title"], body=edited, tags=[],
        operation_id="share-current-body", document_id=note["document_id"], expected_version=old["version"], provenance=old["provenance"])
    share = await service.publish_library("alice", copy["space_id"], {"id": "test.my-learning-vault", "version": "1.0.0",
        "name": "我的整理", "author": "明确填写的作者", "license": "CC0-1.0", "description": "当前版本参考资料。"})
    parsed = json.loads(share)
    assert parsed["format"] == RESOURCE_FORMAT and set(parsed) == {"format", "resource"}
    assert "owner_id" not in share.decode() and str(service.root) not in share.decode()
    service.import_source("bob", share)
    item = service.detail("bob", "test.my-learning-vault")
    assert item["project_example"] is False
    assert any(edited == document["body"] for document in item["preview"]["documents"])
    copied = await service.import_resource("bob", item["id"], version=item["version"], expected_sha256=item["package_sha256"])
    assert copied["space_id"] != copy["space_id"]
    with pytest.raises(KnowledgeError):
        await service.publish_library("bob", copy["space_id"], {})
    exported = await service.export_resource("bob", item["id"], version=item["version"], expected_sha256=item["package_sha256"])
    resource_ = json.loads(exported)["resource"]
    assert sha256(base64.b64decode(resource_["package"]["data_base64"])).hexdigest() == resource_["metadata"]["package_sha256"]


@pytest.mark.asyncio
async def test_builtin_plugin_install_uses_real_plugin_service_and_direct_install_state_is_visible(state, tmp_path):
    state.community_plugins = CommunityPluginService(state=state, storage_root=tmp_path / "plugins")
    service = CommunityService(state)
    plugin = service.catalog("alice", type="plugin")["resources"][0]
    assert plugin["plugin_id"] == plugin["id"] and plugin["permissions"]
    imported = await service.import_resource("alice", plugin["id"], version=plugin["version"], expected_sha256=plugin["package_sha256"])
    assert imported["plugin"]["enabled"] is False
    assert service.detail("alice", plugin["id"])["update_status"] == "current"
    assert service.detail("bob", plugin["id"])["update_status"] == "not_imported"
    state.community_plugins.uninstall("alice", plugin["id"])
    detail = service.detail("alice", plugin["id"])
    assert detail["imported_versions"] == [plugin["version"]]
    assert detail["installed_version"] is None and detail["update_status"] == "not_imported"


@pytest.mark.asyncio
async def test_atomic_state_write_failure_keeps_old_favorites_and_reset_does_not_delete_libraries(state, monkeypatch):
    service = CommunityService(state)
    item = service.catalog("alice", type="question-pack")["resources"][0]
    service.favorite("alice", item["id"], True)
    original = service._path("alice").read_bytes()
    def fail_replace(*args):
        raise OSError("fixture atomic replacement failure")
    with monkeypatch.context() as patch:
        patch.setattr("mathtutor.application.community.os.replace", fail_replace)
        with pytest.raises(OSError):
            service.favorite("alice", item["id"], False)
    assert service._path("alice").read_bytes() == original and list(service.root.glob(".community-*")) == []
    imported = await service.import_resource("alice", item["id"], version=item["version"], expected_sha256=item["package_sha256"])
    service.delete_owner_data("alice")
    assert service.catalog("alice", favorites_only=True)["resources"] == []
    assert await state.knowledge.require_space("alice", imported["space_id"])


def test_http_community_owner_fields_are_not_client_selectable(tmp_path):
    prefix = "/api/v2/math-tutor/desktop/community"
    with client_at(tmp_path / "community.db") as client:
        response = client.get(prefix + "/catalog?type=question-pack")
        assert response.status_code == 200, response.text
        item = response.json()["resources"][0]
        assert client.put(prefix + f"/resources/{item['id']}/favorite", json={"favorite": True, "owner_id": "bob"}).status_code == 422
        assert client.put(prefix + f"/resources/{item['id']}/favorite", json={"favorite": True}).status_code == 200
        copied = client.post(prefix + f"/resources/{item['id']}/import", json={
            "version": item["version"], "expected_sha256": item["package_sha256"], "operation_id": "http-copy"})
        assert copied.status_code == 200, copied.text
        replayed = client.post(prefix + f"/resources/{item['id']}/import", json={
            "version": item["version"], "expected_sha256": item["package_sha256"], "operation_id": "http-copy"})
        assert replayed.status_code == 200 and replayed.json()["space_id"] == copied.json()["space_id"]
        assert len(client.get(prefix + "/history").json()["imports"]) == 1
        bob = StudentOwnerScope(principal=PrincipalScope(user_id="bob", username="bob", role="student"), student_id="bob")
        client.app.dependency_overrides[require_student_owner] = lambda: bob
        try:
            assert client.get(prefix + "/catalog?favorites_only=true").json()["resources"] == []
            assert client.get(prefix + "/history").json()["imports"] == []
        finally:
            client.app.dependency_overrides.pop(require_student_owner)


def test_http_favorites_sources_and_import_history_survive_product_restart(tmp_path):
    prefix = "/api/v2/math-tutor/desktop/community"
    db_path = tmp_path / "community-restart.db"
    with client_at(db_path) as client:
        item = client.get(prefix + "/catalog?type=question-pack").json()["resources"][0]
        assert client.put(prefix + f"/resources/{item['id']}/favorite", json={"favorite": True}).status_code == 200
        source = client.post(prefix + "/sources", json={"name": "手动订阅待刷新", "url": "https://example.org/catalog.json"})
        assert source.status_code == 200, source.text
        imported = client.post(prefix + f"/resources/{item['id']}/import", json={
            "version": item["version"], "expected_sha256": item["package_sha256"], "operation_id": "restart-copy"})
        assert imported.status_code == 200, imported.text
        space_id = imported.json()["space_id"]
    with client_at(db_path) as client:
        assert [r["id"] for r in client.get(prefix + "/catalog?favorites_only=true").json()["resources"]] == [item["id"]]
        assert client.get(prefix + "/history").json()["imports"][0]["space_id"] == space_id
        restored = next(s for s in client.get(prefix + "/sources").json()["sources"] if s["id"] == source.json()["id"])
        assert restored["source_url"] == "https://example.org/catalog.json" and restored["last_refreshed"] is None
        assert client.delete(prefix + "/state").status_code == 200
        assert client.get(prefix + "/history").json()["imports"] == []
        libraries = client.get("/api/v2/math-tutor/desktop/knowledge/libraries").json()
        assert any(library["space_id"] == space_id for library in libraries)


@pytest.mark.asyncio
async def test_history_write_failure_rolls_back_only_new_question_copy_and_preserves_existing_shared_body(state, monkeypatch):
    service = CommunityService(state)
    row = resource()
    service.import_source("alice", catalog(row))
    first = await service.import_resource("alice", row["metadata"]["id"], version="1.0.0",
        expected_sha256=row["metadata"]["package_sha256"], operation_id="old-copy")
    notes = await state.knowledge.list_notes("alice", first["space_id"])
    original = await state.knowledge.snapshot("alice", notes[0]["document_id"])
    original_spaces = await state.knowledge.list_spaces("alice")
    previous_state = service._path("alice").read_bytes()
    async with state.knowledge.engine.begin() as db:
        await db.execute(drafts.insert().values(student_id="alice", draft_id="keep-old-draft", generation=0, payload={"keep": True}))
    async with state.knowledge.engine.connect() as db:
        previous_ops = (await db.execute(select(operations))).all()
    def fail_save(*args):
        raise OSError("fixture history file failure")
    monkeypatch.setattr(service, "_save", fail_save)
    with pytest.raises(CommunityError, match="已撤回"):
        await service.import_resource("alice", row["metadata"]["id"], version="1.0.0",
            expected_sha256=row["metadata"]["package_sha256"], operation_id="failed-new-copy")
    assert await state.knowledge.list_spaces("alice") == original_spaces
    assert await state.knowledge.snapshot("alice", notes[0]["document_id"]) == original
    assert len(await state.documents.list_documents("alice")) == 1
    assert service._path("alice").read_bytes() == previous_state
    async with state.knowledge.engine.connect() as db:
        assert (await db.execute(select(operations))).all() == previous_ops
        assert (await db.execute(select(drafts.c.payload))).scalar_one() == {"keep": True}


@pytest.mark.asyncio
async def test_plugin_history_failure_reports_actual_installed_state_instead_of_false_failure(state, tmp_path, monkeypatch):
    state.community_plugins = CommunityPluginService(state=state, storage_root=tmp_path / "plugins")
    service = CommunityService(state)
    item = service.catalog("alice", type="plugin")["resources"][0]
    def fail_save(*args):
        raise OSError("fixture history save failed")
    monkeypatch.setattr(service, "_save", fail_save)
    result = await service.import_resource("alice", item["id"], version=item["version"], expected_sha256=item["package_sha256"])
    assert result["history_recorded"] is False and any("安装成功" in warning for warning in result["warnings"])
    assert result["plugin"]["enabled"] is False
    assert len(state.community_plugins.list_installed("alice")) == 1
    assert service.detail("alice", item["id"])["update_status"] == "current"
    assert service.history("alice")["imports"] == []


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "file:///"])
def test_community_mutations_reject_foreign_null_and_file_origin_before_changes(tmp_path, origin, monkeypatch):
    monkeypatch.setenv("MATHTUTOR_ALLOWED_ORIGINS", "http://127.0.0.1:3199")
    prefix = "/api/v2/math-tutor/desktop/community"
    with client_at(tmp_path / "origin.db") as client:
        item = client.get(prefix + "/catalog?type=question-pack").json()["resources"][0]
        headers = {"Origin": origin}
        assert client.post(prefix + "/sources/import", headers=headers,
            files={"file": ("directory.json", catalog(resource()), "application/json")}).status_code == 403
        actions = [
            ("POST", "/sources", {"name": "不得添加", "url": "https://example.org/catalog.json"}),
            ("PUT", f"/resources/{item['id']}/favorite", {"favorite": True}),
            ("POST", f"/resources/{item['id']}/import", {"version": item["version"], "expected_sha256": item["package_sha256"]}),
            ("POST", "/sources/missing/refresh", None),
            ("DELETE", "/sources/missing", None),
            ("DELETE", "/state", None),
            ("POST", "/libraries/missing/publish", {"id": "test.no-foreign-share", "version": "1.0.0", "name": "不得导出",
                "author": "作者", "license": "CC0-1.0", "description": "拒绝跨源操作。"}),
        ]
        for method, path, body in actions:
            response = client.request(method, prefix + path, json=body, headers=headers)
            assert response.status_code == 403, (method, path, response.text)
        assert len(client.get(prefix + "/sources").json()["sources"]) == 1
        assert client.get(prefix + "/history").json()["imports"] == []
        assert client.get(prefix + "/catalog?favorites_only=true").json()["resources"] == []
        allowed = client.put(prefix + f"/resources/{item['id']}/favorite", json={"favorite": True},
            headers={"Origin": "http://127.0.0.1:3199"})
        assert allowed.status_code == 200, allowed.text
