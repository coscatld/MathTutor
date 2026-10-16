#!/usr/bin/env python3
"""Validate a teaching-plugin manifest and create an offline community bundle.

For developers, from the repository root after ``pip install -e .``:
    python examples/community-plugins/build_bundle.py manifest.json -o lesson.mathtutor
The output is UTF-8 JSON data, not a ZIP or executable; nothing is installed.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

from mathtutor.application.community import RESOURCE_FORMAT, Resource, canonical_bytes
from mathtutor.extensions.community_plugins import MAX_PACKAGE_BYTES, builtin_plugin_packages, package_hash, validate_package
from mathtutor.extensions.registry import ExtensionError


def read_manifest(path: Path) -> dict:
    """Reject duplicate fields and non-finite JSON before strict validation."""
    with path.open("rb") as stream:
        data = stream.read(MAX_PACKAGE_BYTES + 1)
    if not data or len(data) > MAX_PACKAGE_BYTES:
        raise ValueError("Manifest must be between 1 byte and 64 KiB.")

    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Manifest contains duplicate JSON fields.")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("Manifest cannot contain NaN or Infinity.")

    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique_fields,
                      parse_constant=nonfinite)


def build_bundle(payload: dict) -> bytes:
    """Use the same manifest, hash and resource contracts as the application."""
    plugin = validate_package(payload).model_dump()
    metadata = {key: plugin[key] for key in (
        "id", "version", "name", "description", "author", "license", "tags", "grades", "readme", "changelog",
    )}
    # Preserve the immutable catalog metadata of an exact project template.
    # Modified/third-party packages do not inherit that marker. At display time
    # the app independently derives the badge from its own source provenance.
    project_example = any(plugin == example for example in builtin_plugin_packages())
    metadata.update(type="plugin", permissions=plugin["required_permissions"],
                    package_sha256=package_hash(plugin), project_example=project_example)
    resource = Resource.model_validate({
        "metadata": metadata,
        "package": {"filename": plugin["id"] + ".json", "media_type": "application/json", "data": plugin},
    }).model_dump(exclude_none=True)
    return canonical_bytes({"format": RESOURCE_FORMAT, "resource": resource})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate and bundle a MathTutor declarative teaching plugin offline.")
    parser.add_argument("manifest", type=Path, help="Developer manifest (.json), at most 64 KiB")
    parser.add_argument("-o", "--output", type=Path, required=True,
                        help="New .mathtutor or .mtplugin file; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        if args.output.suffix.lower() not in {".mathtutor", ".mtplugin"}:
            raise ValueError("Output filename must end in .mathtutor or .mtplugin.")
        bundle = build_bundle(read_manifest(args.manifest))
        # Exclusive creation also rejects an existing symlink. No overwrite flag:
        # a developer must choose a new output or deliberately remove the old one.
        with args.output.open("xb") as stream:
            stream.write(bundle)
        print(f"Created {args.output.name}")
        print(f"Bundle SHA-256: {sha256(bundle).hexdigest()}")
        print(f"Plugin SHA-256: {json.loads(bundle)['resource']['metadata']['package_sha256']}")
        return 0
    except (OSError, ValueError, TypeError, RecursionError, ExtensionError) as exc:
        # Do not echo invalid manifest values: they can contain accidental secrets.
        if isinstance(exc, FileExistsError):
            message = "Output already exists; choose a new filename. Nothing was overwritten."
        elif isinstance(exc, ExtensionError):
            message = str(exc)
        else:
            message = "Cannot build bundle: check input format, supported fields, output suffix and writable destination."
        print(message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
