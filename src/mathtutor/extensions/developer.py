"""Offline code-plugin authoring: scaffold, build and inspect without execution.

Run ``python -m mathtutor.extensions.developer --help`` from an installed
MathTutor environment. Commands share the import validator; none install a
plugin, grant trust, access student data or run author code.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from mathtutor.extensions.code_plugins import (
    CODE_PERMISSION, CODE_SCHEMA, MAX_CODE_BYTES, MAX_PACKAGE_BYTES,
    export_code_package, parse_code_upload, safe_path, strict_json,
    validate_code_package,
)
from mathtutor.extensions.registry import ExtensionError


_PYTHON_STARTER = '''def run(request: dict) -> dict:
    text = request["text"].strip()
    if not text:
        return {"text": "请在命令后输入文字。"}
    return {"text": text, "data": {"characters": len(text)}}
'''

_TYPESCRIPT_STARTER = '''type Request = { text: string; config: Record<string, unknown> };

export function run(request: Request): Record<string, unknown> {
  const text = request.text.trim();
  if (!text) return { text: "请在命令后输入文字。" };
  return { text, data: { characters: Array.from(text).length } };
}
'''


def scaffold(directory: Path, *, plugin_id: str, name: str, author: str,
             license_id: str, command: str, runtime: str = "python") -> None:
    """Create a validated starter in a new directory; never overwrite a project."""
    entrypoint = "main.py" if runtime == "python" else "main.ts"
    source = _PYTHON_STARTER if runtime == "python" else _TYPESCRIPT_STARTER
    readme = (
        f"# {name}\n\n启用后输入 `/{command} 你好`，返回文字和字符数。\n\n"
        "代码以本机账户权限运行。请审查源码，再在 MathTutor 社区中导入、"
        "确认本地代码执行权限并启用。导入不会自动执行。\n\n"
        "输入只有本次命令文字和插件配置；输出是参考结果，不是数学核验或学习证据。\n"
    )
    payload = {
        "schema_version": CODE_SCHEMA, "kind": "code-plugin", "workflow": "code",
        "id": plugin_id, "version": "1.0.0", "name": name, "author": author,
        "license": license_id, "description": "回显输入并统计字符数的社区插件起点。",
        "readme": readme, "changelog": "1.0.0：首次版本。",
        "runtime": runtime, "command": command, "entrypoint": entrypoint,
        "required_permissions": [CODE_PERMISSION],
        "files": {entrypoint: source, "README.md": readme},
    }
    package = validate_code_package(payload)
    metadata = package.model_dump(exclude={"files", "file_hashes"})
    # Validate before creating anything. mkdir refuses an existing directory,
    # file or symlink, so author projects are never merged or overwritten.
    directory.mkdir()
    for filename, content in {
        "plugin.json": json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        **package.files,
    }.items():
        with (directory / filename).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)


def build(directory: Path, included: list[str]) -> bytes:
    """Package only the entrypoint and explicitly selected files; never run code."""
    directory = directory.resolve(strict=True)
    manifest_path = directory / "plugin.json"
    if manifest_path.is_symlink():
        raise ValueError("Manifest must be a regular file")
    with manifest_path.open("rb") as stream:
        raw = stream.read(MAX_CODE_BYTES + 1)
    if len(raw) > MAX_CODE_BYTES:
        raise ValueError("Manifest exceeds 64 KiB")
    metadata = strict_json(raw)
    if "files" in metadata:
        raise ValueError("Sources must be files in the selected directory")
    names = list(dict.fromkeys([metadata.get("entrypoint", ""), *included]))
    sources = {}
    for name in names:
        safe_path(name)
        path = directory.joinpath(*name.split("/"))
        current = directory
        for part in name.split("/"):
            current = current / part
            if current.is_symlink():
                raise ValueError("Links are not included")
        if not path.is_file() or not path.resolve().is_relative_to(directory):
            raise ValueError("Source is outside the plugin directory")
        with path.open("rb") as stream:
            data = stream.read(MAX_CODE_BYTES + 1)
        if len(data) > MAX_CODE_BYTES:
            raise ValueError("Source exceeds 64 KiB")
        sources[name] = data.decode("utf-8-sig")
    # Recompute source hashes for the author's next package version.
    package = validate_code_package({**metadata, "files": sources, "file_hashes": {}})
    return export_code_package(package.model_dump())


def check(path: Path) -> dict:
    """Validate an upload offline and return metadata, never source or execution."""
    if path.suffix.lower() not in {".zip", ".py", ".ts"}:
        raise ValueError("Check expects a .zip, .py or .ts code plugin")
    with path.open("rb") as stream:
        data = stream.read(MAX_PACKAGE_BYTES + 1)
    package = parse_code_upload(data, path.name)
    return {
        "id": package.id, "version": package.version, "name": package.name,
        "runtime": package.runtime, "command": f"/{package.command}",
        "entrypoint": package.entrypoint,
        "required_permissions": package.required_permissions,
        "files": sorted(package.files), "status": "package_valid",
        "installed": False, "executed": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    init = commands.add_parser("init", help="Create a Python or TypeScript starter in a new directory")
    init.add_argument("directory", type=Path)
    init.add_argument("--id", required=True, dest="plugin_id")
    init.add_argument("--name", required=True)
    init.add_argument("--author", required=True)
    init.add_argument("--license", required=True, dest="license_id")
    init.add_argument("--command", required=True)
    init.add_argument("--runtime", choices=["python", "typescript"], default="python")
    bundle = commands.add_parser("build", help="Build a validated ZIP from explicitly selected files")
    bundle.add_argument("directory", type=Path)
    bundle.add_argument("--include", action="append", default=[])
    bundle.add_argument("-o", "--output", type=Path, required=True)
    inspect = commands.add_parser("check", help="Check a ZIP or source file without installing or executing")
    inspect.add_argument("path", type=Path)
    harness = commands.add_parser("adapt-harness", help="Wrap the apply/tools.register TypeScript subset as a normal code-plugin ZIP")
    harness.add_argument("directory", type=Path)
    harness.add_argument("--tool", required=True, help="Registered tool name to expose through the package command")
    harness.add_argument("--include", action="append", default=[])
    harness.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "init":
            scaffold(args.directory, plugin_id=args.plugin_id, name=args.name,
                     author=args.author, license_id=args.license_id,
                     command=args.command, runtime=args.runtime)
            print(f"Created {args.directory.name}; edit plugin.json and the entrypoint, then build.")
        elif args.action in {"build", "adapt-harness"}:
            if args.output.suffix.lower() != ".zip":
                raise ValueError("Use .zip output")
            if args.action == "adapt-harness":
                from mathtutor.extensions.harness_compat import adapt
                data = adapt(args.directory, args.include, args.tool)
            else:
                data = build(args.directory, args.include)
            with args.output.open("xb") as stream:
                stream.write(data)
            print(f"Created {args.output.name} ({len(data)} bytes); not installed or executed.")
        else:
            print(json.dumps(check(args.path), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, ExtensionError) as error:
        # Report authoring failures without echoing manifest/source content.
        if isinstance(error, FileExistsError):
            message = "Target already exists; choose a new directory or output file."
        elif isinstance(error, FileNotFoundError):
            message = "Input or parent directory does not exist; check the selected paths."
        else:
            message = "Check plugin.json, selected UTF-8 files, package limits and output paths."
        print(f"Cannot {args.action} plugin: {message} No code was executed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
