#!/usr/bin/env python3
"""Build a validated code-plugin ZIP without executing code or installing it."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from mathtutor.extensions.code_plugins import (
    MAX_CODE_BYTES, export_code_package, safe_path, strict_json, validate_code_package,
)
from mathtutor.extensions.registry import ExtensionError


def build(directory: Path, included: list[str]) -> bytes:
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
    # Hashes are generated from the selected source files on every build.
    # Existing output is never overwritten; version ownership remains explicit.
    package = validate_code_package({**metadata, "files": sources, "file_hashes": {}})
    return export_code_package(package.model_dump())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Directory containing plugin.json and source files")
    parser.add_argument("--include", action="append", default=[], help="Additional relative source/resource path; repeat as needed")
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.suffix.lower() != ".zip":
            raise ValueError("Use .zip output")
        data = build(args.directory, args.include)
        with args.output.open("xb") as stream:
            stream.write(data)
        print(f"Created {args.output.name} ({len(data)} bytes); not installed or executed.")
        return 0
    except (OSError, ValueError, TypeError, ExtensionError):
        print("Cannot build plugin: check the manifest, selected files and output path; existing files are never overwritten.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
