#!/usr/bin/env python3
"""Audit the MathTutor distribution allowlist without mutating the source tree.

The script builds a temporary source-only staging tree, launches a clean
interpreter outside the checkout, runs the production factory (including a
real migration), and reports both static local-import edges and observed
runtime modules.  Pass the final ``.app`` and DMG after MAIN rebuilds to close
the artifact size/count evidence; until then those fields remain explicit
``null`` values rather than estimates presented as measurements.
"""

from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import fnmatch
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Iterable


def _matches(path: str, pattern: str) -> bool:
    """Approximate electron-builder/minimatch's zero-directory ``**/``."""
    candidates = {pattern}
    while "/**/" in pattern:
        pattern = pattern.replace("/**/", "/", 1)
        candidates.add(pattern)
    return any(fnmatch.fnmatchcase(path, candidate) for candidate in candidates)


def _included(relative: str, policy: dict) -> bool:
    includes = policy["python_source"]["include"]
    excludes = policy["python_source"]["exclude"]
    return any(_matches(relative, item) for item in includes) and not any(
        _matches(relative, item) for item in excludes
    )


def _module_name(relative: Path) -> str | None:
    if relative.suffix != ".py":
        return None
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(["mathtutor", *parts]) if parts else "mathtutor"


def _static_edges(files: Iterable[Path], source_root: Path) -> list[list[str]]:
    modules: dict[str, Path] = {}
    for file in files:
        module = _module_name(file.relative_to(source_root))
        if module:
            modules[module] = file

    edges: set[tuple[str, str]] = set()
    for importer, file in modules.items():
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        package = importer if file.name == "__init__.py" else importer.rsplit(".", 1)[0]
        for node in ast.walk(tree):
            candidates: list[str] = []
            if isinstance(node, ast.Import):
                candidates.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split(".")
                    suffix = (node.module or "").split(".") if node.module else []
                    target = ".".join(base[: len(base) - (node.level - 1)] + suffix)
                else:
                    target = node.module or ""
                candidates.append(target)
                candidates.extend(
                    f"{target}.{alias.name}" for alias in node.names if target
                )
            for candidate in candidates:
                if candidate in modules:
                    edges.add((importer, candidate))
    return [list(edge) for edge in sorted(edges)]


def _production_probe(python: Path, package_root: Path, work: Path) -> dict:
    code = r'''
import json, os, pathlib, sys, tempfile
sys.path.insert(0, sys.argv[1])
os.environ.update({
    "AUTH_ENABLED": "0",
    "MATHTUTOR_AUTH_ENABLED": "0",
    "MATHTUTOR_DATA_ROOT": sys.argv[2],
    "MATHTUTOR_ALLOW_LOOPBACK_NO_AUTH": "1",
    "MATHTUTOR_ENVIRONMENT": "test",
})
from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.infrastructure import schema
from mathtutor.infrastructure import verifier_worker
from mathtutor import release_probe
db = pathlib.Path(sys.argv[2]) / "probe.db"
app = create_math_tutor_app(
    db_path=str(db), auth_enabled=False, auth_secret="", password_hash=""
)
root = pathlib.Path(sys.argv[1]).resolve()
observed = {}
for name, module in sorted(sys.modules.items()):
    if name != "mathtutor" and not name.startswith("mathtutor."):
        continue
    filename = getattr(module, "__file__", None)
    if filename:
        resolved = pathlib.Path(filename).resolve()
        if root not in resolved.parents and resolved != root:
            raise SystemExit(f"checkout import leak: {name} -> {resolved}")
        observed[name] = str(resolved.relative_to(root))
print(json.dumps({
    "factory": app.title,
    "migration_db_exists": db.exists(),
    "observed_modules": observed,
}, sort_keys=True))
'''
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "LANG", "LC_ALL", "PATH", "SYSTEMROOT", "TMPDIR"}
    }
    completed = subprocess.run(
        [str(python), "-I", "-c", code, str(package_root), str(work / "data")],
        cwd=work,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _file_measurement(path: Path | None) -> dict | None:
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(path)
    if path.is_file():
        return {"path": str(path.resolve()), "size_bytes": path.stat().st_size}
    entries = list(path.rglob("*"))
    # Match the release manifest's lstat-based vocabulary: a symlink is not a
    # regular file even when its target is a file.  Keeping the counts separate
    # makes the before/after delta comparable across both evidence producers.
    files = [
        item for item in entries if not item.is_symlink() and item.is_file()
    ]
    return {
        "path": str(path.resolve()),
        "file_count": len(files),
        "symlink_count": sum(item.is_symlink() for item in entries),
        "content_bytes": sum(item.stat().st_size for item in files),
    }


@contextmanager
def _exact_artifact_app(
    explicit_app: Path | None, dmg: Path | None
) -> Iterable[Path | None]:
    """Yield the app inside the readonly DMG when no explicit app is given."""

    if explicit_app is not None:
        yield explicit_app
        return
    if dmg is None:
        yield None
        return
    if sys.platform != "darwin":
        raise RuntimeError("automatic DMG mounting requires macOS")
    with tempfile.TemporaryDirectory(prefix="mathtutor-package-dmg-audit-") as raw:
        mountpoint = Path(raw) / "volume"
        mountpoint.mkdir()
        subprocess.run(
            [
                "hdiutil",
                "attach",
                "-nobrowse",
                "-readonly",
                "-mountpoint",
                str(mountpoint),
                str(dmg),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            app = mountpoint / "MathTutor.app"
            if not app.exists():
                raise FileNotFoundError(app)
            yield app
        finally:
            subprocess.run(
                ["hdiutil", "detach", str(mountpoint)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--app", type=Path)
    parser.add_argument("--dmg", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    repo = args.repo.resolve()
    policy_path = repo / "desktop" / "package_allowlist.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    source_root = repo / policy["python_source"]["root"]
    source_files = [item for item in source_root.rglob("*") if item.is_file()]
    selected = sorted(
        item
        for item in source_files
        if _included(item.relative_to(source_root).as_posix(), policy)
    )

    selected_artifact_paths = {
        f"python-app/mathtutor/{item.relative_to(source_root).as_posix()}"
        for item in selected
    }
    violations = sorted(
        selected_path
        for selected_path in selected_artifact_paths
        for forbidden in policy["forbidden_artifact_paths"]
        if selected_path == forbidden or selected_path.startswith(f"{forbidden}/")
    )
    if violations:
        raise SystemExit(f"forbidden source selected: {violations[:10]}")

    with tempfile.TemporaryDirectory(prefix="mathtutor-package-audit-") as raw_temp:
        work = Path(raw_temp)
        package_root = work / "python-app"
        staged_source = package_root / "mathtutor"
        for source in selected:
            target = staged_source / source.relative_to(source_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        # Preserve a virtual-environment launcher symlink. Resolving it to the
        # base interpreter would silently discard the clean venv's site-packages.
        probe = _production_probe(args.python.absolute(), package_root, work)

    with _exact_artifact_app(args.app, args.dmg) as measured_app:
        result = {
            "schema_version": 1,
            "status": "PASS",
            "policy": str(policy_path.relative_to(repo)),
            "entrypoints": policy["production_entrypoints"],
            "selected_source_file_count": len(selected),
            "selected_source_bytes": sum(item.stat().st_size for item in selected),
            "static_local_import_edges": _static_edges(selected, source_root),
            "observed_runtime_module_count": len(probe["observed_modules"]),
            "observed_runtime_modules": probe["observed_modules"],
            "migration_db_exists": probe["migration_db_exists"],
            "forbidden_selected": violations,
            "before": {
                "artifact_size_bytes": 272845178,
                "package_file_count": 21913,
            },
            "after": {
                "artifact": _file_measurement(args.dmg),
                "package_contents": _file_measurement(measured_app),
            },
            "package_contents_source": (
                "explicit_app" if args.app is not None else "readonly_dmg"
            ),
        }
    after_artifact = result["after"]["artifact"]
    after_contents = result["after"]["package_contents"]
    result["delta"] = {
        "artifact_size_bytes": (
            after_artifact["size_bytes"] - result["before"]["artifact_size_bytes"]
            if after_artifact
            else None
        ),
        "package_file_count": (
            after_contents["file_count"] - result["before"]["package_file_count"]
            if after_contents
            else None
        ),
    }
    result["artifact_measurement_status"] = (
        "MEASURED" if after_artifact and after_contents else "PENDING_FINAL_REPACKAGE"
    )

    rendered = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
