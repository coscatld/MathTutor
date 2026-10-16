"""The documented offline developer packer interoperates with real imports."""
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from mathtutor.application.community import CommunityError, CommunityService, canonical_bytes
from mathtutor.extensions.community_plugins import CommunityPluginService, builtin_plugin_packages, package_hash


EXAMPLES = Path(__file__).resolve().parents[1] / "examples/community-plugins"
spec = importlib.util.spec_from_file_location("plugin_bundle_builder", EXAMPLES / "build_bundle.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.mark.parametrize("workflow", ["exam-builder", "mistake-review", "learning-report"])
@pytest.mark.asyncio
async def test_documented_cli_bundles_install_through_real_community_import(tmp_path, workflow, capsys):
    # Authors copy a template and use their own ID; bundled MathTutor IDs are
    # reserved by the already-present project-example catalog metadata.
    expected = json.loads((EXAMPLES / (workflow + ".plugin.json")).read_bytes())
    assert expected == next(row for row in builtin_plugin_packages() if row["workflow"] == workflow)
    payload = {**expected, "id": "example." + workflow, "author": "示例开发者"}
    manifest = tmp_path / (workflow + ".json")
    manifest.write_bytes(canonical_bytes(payload))
    destination = tmp_path / (workflow + ".mathtutor")
    assert builder.main([str(manifest), "-o", str(destination)]) == 0
    raw = destination.read_bytes()
    envelope = json.loads(raw)
    payload = envelope["resource"]["package"]["data"]
    assert envelope["resource"]["metadata"]["package_sha256"] == package_hash(payload)
    assert sha256(canonical_bytes(payload)).hexdigest() == package_hash(payload)
    output = capsys.readouterr().out
    assert sha256(raw).hexdigest() in output
    assert payload["defaults"] == expected["defaults"] and payload["workflow"] == expected["workflow"]

    state = SimpleNamespace()
    state.community_plugins = CommunityPluginService(state=state, storage_root=tmp_path / "plugins")
    async def no_fetch(*args, **kwargs):
        raise AssertionError("Offline bundle must not use the network")
    service = CommunityService(state, data_dir=tmp_path, fetcher=no_fetch)
    assert state.community_plugins.list_installed("alice") == []
    result = await service.import_file("alice", raw, destination.name, operation_id="builder-test")
    assert result["kind"] == "plugin"
    assert result["plugin"]["package_hash"] == package_hash(payload)
    assert service._load("alice")["sources"] == []
    assert result["plugin"]["enabled"] is False
    assert result["plugin"]["consented_permissions"] == []
    assert state.community_plugins.list_installed("bob") == []

    envelope["resource"]["package"]["data"]["name"] += "changed without hash"
    with pytest.raises(CommunityError, match="SHA256"):
        await CommunityService(state, data_dir=tmp_path / "tampered").import_file(
            "alice", canonical_bytes(envelope), "tampered.mtplugin")


def test_cli_never_overwrites_existing_output_or_follows_its_symlink(tmp_path, capsys):
    existing = tmp_path / "keep.mathtutor"
    existing.write_text("keep", encoding="utf-8")
    manifest = EXAMPLES / "exam-builder.plugin.json"
    assert builder.main([str(manifest), "-o", str(existing)]) == 2
    assert existing.read_text() == "keep"
    link = tmp_path / "linked.mtplugin"
    link.symlink_to(existing)
    assert builder.main([str(manifest), "-o", str(link)]) == 2
    assert existing.read_text() == "keep"
    assert "Nothing was overwritten" in capsys.readouterr().err


@pytest.mark.parametrize("workflow", ["exam-builder", "mistake-review", "learning-report"])
@pytest.mark.asyncio
async def test_exact_project_templates_keep_catalog_metadata_compatible(tmp_path, workflow):
    state = SimpleNamespace()
    state.community_plugins = CommunityPluginService(state=state, storage_root=tmp_path / "plugins")
    payload = json.loads((EXAMPLES / (workflow + ".plugin.json")).read_bytes())
    raw = builder.build_bundle(payload)
    result = await CommunityService(state, data_dir=tmp_path).import_file("alice", raw, workflow + ".mtplugin")
    assert result["kind"] == "plugin" and result["plugin"]["enabled"] is False
    assert result["plugin"]["package_hash"] == package_hash(payload)


@pytest.mark.parametrize("invalid", [
    b'{"schema_version":"mathtutor.community-plugin.v1","schema_version":"other"}',
    b'{"value":NaN}', b'[]', b'x' * 65537,
], ids=["duplicate-fields", "nonfinite-number", "non-object", "over-64k"])
def test_invalid_manifests_do_not_create_output(tmp_path, invalid):
    manifest, output = tmp_path / "invalid.json", tmp_path / "invalid.mtplugin"
    manifest.write_bytes(invalid)
    assert builder.main([str(manifest), "-o", str(output)]) == 2
    assert not output.exists()
