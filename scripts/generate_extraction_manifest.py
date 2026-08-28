#!/usr/bin/env python3
"""Generate a deterministic inventory for the extracted repository."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "standalone" / "STANDALONE_EXTRACTION_MANIFEST.json"
EXCLUDED_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    ".next",
    ".next-mathtutor",
    "__pycache__",
    "data",
    "node_modules",
    "dist",
}


def main() -> None:
    files = []
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if (
            not path.is_file()
            or any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in relative.parts)
            or relative.parts[0] == "build"
        ):
            continue
        if path == OUTPUT or path.suffix in {".pyc", ".pyo", ".tsbuildinfo"}:
            continue
        payload = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest = {
        "schema_version": 1,
        "extraction_stage": "STANDALONE_RC_CANDIDATE",
        "python_namespace": "mathtutor",
        "distribution": "mathtutor",
        "source_repository_dependency": False,
        "file_count": len(files),
        "content_bytes": sum(item["bytes"] for item in files),
        "files": files,
    }
    OUTPUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
