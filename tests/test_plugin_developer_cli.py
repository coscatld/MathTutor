"""Offline authoring reaches the real plugin importer, consent and interpreter."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from mathtutor.extensions import developer
from mathtutor.extensions.code_plugins import CODE_PERMISSION, parse_code_upload
from mathtutor.extensions.community_plugins import CommunityPluginService
from mathtutor.extensions.registry import ExtensionError
from test_code_plugins import native_node


def init_args(directory, runtime="python"):
    return ["init", str(directory), "--id", "community.echo", "--name", "社区回显",
            "--author", "示例作者", "--license", "MIT", "--command", "echo",
            "--runtime", runtime]


@pytest.mark.parametrize("runtime,suffix", [("python", "py"), ("typescript", "ts")])
def test_starters_build_exact_importable_packages_without_collecting_private_files(
    tmp_path, capsys, runtime, suffix
):
    directory = tmp_path / "plugin"
    assert developer.main(init_args(directory, runtime)) == 0
    (directory / "private.json").write_text('{"secret":"must not ship"}', encoding="utf-8")
    output = tmp_path / "echo.zip"
    assert developer.main(["build", str(directory), "--include", "README.md", "-o", str(output)]) == 0
    capsys.readouterr()
    assert developer.main(["check", str(output)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["files"] == ["README.md", f"main.{suffix}"]
    assert report["runtime"] == runtime and report["command"] == "/echo"
    assert report["installed"] is False and report["executed"] is False
    assert report["required_permissions"] == [CODE_PERMISSION]
    package = parse_code_upload(output.read_bytes(), output.name)
    assert package.id == "community.echo" and package.version == "1.0.0"
    assert package.files[f"main.{suffix}"] == (directory / f"main.{suffix}").read_text(encoding="utf-8")
    assert "private.json" not in package.files


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["python", "typescript"])
async def test_generated_plugin_requires_consent_then_runs_in_real_interpreter(tmp_path, request, runtime):
    if runtime == "typescript":
        request.getfixturevalue("native_node")
    directory = tmp_path / "plugin"
    assert developer.main(init_args(directory, runtime)) == 0
    package = parse_code_upload(developer.build(directory, []), "echo.zip")
    service = CommunityPluginService(state=SimpleNamespace(), storage_root=tmp_path / "installed")
    row = service.import_package("alice", package.model_dump())
    assert row["enabled"] is False
    assert service.commands("alice")[0]["enabled"] is False
    with pytest.raises(ExtensionError):
        await service.run_slash("alice", "echo", "你好🙂", operation_id="disabled")
    with pytest.raises(ExtensionError):
        service.set_enabled("alice", package.id, enabled=True, consent_permissions=[])
    service.set_enabled("alice", package.id, enabled=True, consent_permissions=[CODE_PERMISSION])
    result = await service.run_slash("alice", "echo", "你好🙂", operation_id="first-run")
    assert result["data"] == {"text": "你好🙂", "data": {"characters": 3}}
    assert result["authority"] == "reference_only" and result["sandboxed"] is False
    assert service.commands("bob") == []


def test_init_and_build_never_overwrite_existing_targets(tmp_path):
    directory = tmp_path / "plugin"
    assert developer.main(init_args(directory)) == 0
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    assert developer.main(init_args(directory, "typescript")) == 2
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before
    output = tmp_path / "existing.zip"
    output.write_bytes(b"existing-user-output")
    assert developer.main(["build", str(directory), "-o", str(output)]) == 2
    assert output.read_bytes() == b"existing-user-output"


@pytest.mark.parametrize("field,value", [("--id", "../outside"), ("--command", "x"), ("--license", "bad license")])
def test_init_rejects_invalid_metadata_before_creating_files(tmp_path, field, value):
    directory = tmp_path / "plugin"
    args = init_args(directory)
    args[args.index(field) + 1] = value
    assert developer.main(args) == 2
    assert not directory.exists()


def test_build_and_check_do_not_execute_module_and_reject_tampered_hashes(tmp_path):
    directory = tmp_path / "plugin"
    assert developer.main(init_args(directory)) == 0
    marker = tmp_path / "must-not-execute.txt"
    source = directory / "main.py"
    source.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
        "def run(request):\n    return {'text': 'ok'}\n", encoding="utf-8",
    )
    assert developer.main(["check", str(source)]) == 0
    archive = developer.build(directory, [])
    output = tmp_path / "package.zip"
    output.write_bytes(archive)
    assert developer.main(["check", str(output)]) == 0
    assert not marker.exists()
    with zipfile.ZipFile(io.BytesIO(archive)) as original:
        files = {name: original.read(name) for name in original.namelist()}
    files["main.py"] += b"\n# changed after build\n"
    with zipfile.ZipFile(output, "w") as changed:
        for name, contents in files.items():
            changed.writestr(name, contents)
    assert developer.main(["check", str(output)]) == 2
    assert not marker.exists()


@pytest.mark.parametrize("included", ["../outside.py", "linked.py"])
def test_build_rejects_unscoped_and_symlink_sources(tmp_path, included):
    directory = tmp_path / "plugin"
    assert developer.main(init_args(directory)) == 0
    outside = tmp_path / "outside.py"
    outside.write_text("PRIVATE = True\n", encoding="utf-8")
    if included == "linked.py":
        try:
            (directory / "linked.py").symlink_to(outside)
        except OSError:
            pytest.skip("Creating file symlinks is unavailable on this host")
    output = tmp_path / "invalid.zip"
    assert developer.main(["build", str(directory), "--include", included, "-o", str(output)]) == 2
    assert not output.exists()


def test_module_cli_works_outside_the_repository_without_examples_directory(tmp_path):
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    result = subprocess.run(
        [sys.executable, "-m", "mathtutor.extensions.developer", *init_args(tmp_path / "plugin")],
        cwd=tmp_path, env={**os.environ, "PYTHONPATH": source_root},
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "plugin/plugin.json").is_file()
