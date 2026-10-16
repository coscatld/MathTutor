"""Owner and Origin checks on the actual community plugin management routes."""
import copy

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.extensions.community_plugins import CommunityPluginService, builtin_plugin_packages
from test_tutor_p0 import client_at

PREFIX = "/api/v2/math-tutor/desktop/community/plugins"


def test_actual_install_config_enable_run_export_and_uninstall(tmp_path):
    with client_at(tmp_path / "plugins.db") as client:
        state = get_product_state()
        assert state.community_plugins is not None
        examples = client.get(PREFIX + "/examples")
        assert examples.status_code == 200
        payload = next(p for p in examples.json()["items"] if p["workflow"] == "exam-builder")
        installed = client.post(PREFIX, json={"package": payload})
        assert installed.status_code == 200 and installed.json()["enabled"] is False
        plugin_id = payload["id"]
        assert client.post(f"{PREFIX}/{plugin_id}/run", json={}).status_code == 409
        assert client.put(f"{PREFIX}/{plugin_id}/enabled", json={"enabled": True}).status_code == 409
        assert client.patch(f"{PREFIX}/{plugin_id}/config", json={"config": {"grade": 12, "question_count": 3, "include_answers": False}}).status_code == 200
        enabled = client.put(f"{PREFIX}/{plugin_id}/enabled", json={"enabled": True, "consent_permissions": ["question_bank"]})
        assert enabled.status_code == 200 and enabled.json()["enabled"]
        result = client.post(f"{PREFIX}/{plugin_id}/run", json={})
        assert result.status_code == 200 and len(result.json()["data"]["questions"]) == 3
        assert result.json()["data"]["answers_included"] is False
        exported = client.get(f"{PREFIX}/{plugin_id}/export")
        assert exported.status_code == 200 and exported.json()["schema_version"] == payload["schema_version"]
        assert "attachment" in exported.headers["content-disposition"]
        assert client.delete(f"{PREFIX}/{plugin_id}").json()["uninstalled"] is True
        assert client.post(f"{PREFIX}/{plugin_id}/run", json={}).status_code == 409


@pytest.mark.parametrize("origin", ["null", "https://evil.example", "http://127.0.0.1.evil.example"])
def test_external_site_cannot_install_enable_configure_run_or_remove(tmp_path, origin):
    with client_at(tmp_path / "origin-plugins.db") as client:
        state = get_product_state()
        assert state.community_plugins is not None
        payload = builtin_plugin_packages()[0]
        state.community_plugins.import_package("local-admin", payload)
        headers = {"Origin": origin}
        plugin_id = payload["id"]
        assert client.post(PREFIX, json={"package": payload}, headers=headers).status_code == 403
        assert client.put(f"{PREFIX}/{plugin_id}/enabled", json={"enabled": True, "consent_permissions": ["question_bank"]}, headers=headers).status_code == 403
        assert client.patch(f"{PREFIX}/{plugin_id}/config", json={"config": {"grade": 1}}, headers=headers).status_code == 403
        assert client.post(f"{PREFIX}/{plugin_id}/run", json={}, headers=headers).status_code == 403
        assert client.delete(f"{PREFIX}/{plugin_id}", headers=headers).status_code == 403
        record = state.community_plugins.list_installed("local-admin")[0]
        assert record["enabled"] is False and record["config"]["grade"] == 10


def test_author_validation_normalizes_without_installing_or_authorizing(tmp_path):
    with client_at(tmp_path / "author-plugins.db") as client:
        before = client.get(PREFIX).json()
        payload = {**builtin_plugin_packages()[0], "id": "example.grade12-weekly", "name": "每周组卷",
                   "author": "示例作者", "defaults": {"grade": 12}}
        response = client.post(PREFIX + "/validate", json={"package": payload})
        assert response.status_code == 200
        normalized = response.json()
        assert normalized["package"]["defaults"]["question_count"] == 8
        assert len(normalized["package_hash"]) == 64 and normalized["package"]["id"] == payload["id"]
        bad = {**payload, "required_permissions": ["filesystem"]}
        assert client.post(PREFIX + "/validate", json={"package": bad}).status_code == 409
        assert client.post(PREFIX + "/validate", json={"package": payload}, headers={"Origin": "null"}).status_code == 403
        assert client.get(PREFIX).json() == before
