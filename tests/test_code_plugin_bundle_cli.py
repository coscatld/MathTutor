"""Documented code examples build real importable ZIPs without execution."""
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

from mathtutor.extensions.code_plugins import parse_code_upload

EXAMPLES = Path(__file__).resolve().parents[1] / "examples/code-plugins"
spec = importlib.util.spec_from_file_location("code_bundle_builder", EXAMPLES / "build_bundle.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.mark.parametrize("runtime,entrypoint,alias", [("python", "double.py", "double"), ("typescript", "double-ts.ts", "double-ts")])
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"], ids=["lf", "crlf"])
def test_shipped_examples_build_and_parse_with_exact_sources(tmp_path, runtime, entrypoint, alias, newline):
    source = tmp_path / "source"
    source.mkdir()
    metadata = json.loads((EXAMPLES / "plugin.json").read_text(encoding="utf-8"))
    metadata.update(runtime=runtime, entrypoint=entrypoint, command=alias)
    (source / "plugin.json").write_text(json.dumps(metadata), encoding="utf-8")
    source_bytes = (EXAMPLES / entrypoint).read_bytes().replace(b"\r\n", b"\n").replace(b"\n", newline)
    (source / entrypoint).write_bytes(source_bytes)
    # An unselected file is never swept into an archive by directory traversal.
    (source / "private.json").write_text('{"private":"not selected"}', encoding="utf-8")
    output = tmp_path / "plugin.zip"
    assert builder.main([str(source), "-o", str(output)]) == 0
    package = parse_code_upload(output.read_bytes(), output.name)
    assert package.runtime == runtime and package.command == alias
    assert package.files == {entrypoint: source_bytes.decode("utf-8")}
    with zipfile.ZipFile(output) as archive:
        assert set(archive.namelist()) == {"plugin.json", entrypoint}
    assert builder.main([str(source), "-o", str(output)]) == 2
    assert parse_code_upload(output.read_bytes(), output.name).file_hashes == package.file_hashes


def test_building_does_not_import_or_execute_the_python_module(tmp_path):
    metadata = json.loads((EXAMPLES / "plugin.json").read_text(encoding="utf-8"))
    (tmp_path / "plugin.json").write_text(json.dumps(metadata), encoding="utf-8")
    marker = tmp_path / "executed.txt"
    (tmp_path / "double.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed', encoding='utf-8')\ndef run(request):\n    return {{'text': 'ok'}}\n",
        encoding="utf-8",
    )
    assert builder.main([str(tmp_path), "-o", str(tmp_path / "plugin.zip")]) == 0
    assert not marker.exists()
