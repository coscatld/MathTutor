#!/usr/bin/env python3
"""Preview or prune old installers, retaining current README releases and evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
# ZIP files also carry acceptance evidence and CI logs; keep them all.
INSTALLERS = {".dmg", ".exe", ".AppImage"}


def release_tags(readme: str) -> set[str]:
    return set(re.findall(r"/releases/(?:download|tag)/([^/\s)]+)", readme))


def prune_plan(dist: Path, protected: set[str], keep: int = 1) -> list[dict]:
    """Only inspect named MathTutor installers at the top level or one build deep."""
    if keep < 1:
        raise ValueError("keep must be at least one")
    groups: dict[tuple[str, str, str], list[Path]] = {}
    roots = [dist] + sorted(
        p for p in dist.glob("*") if p.is_dir() and not p.is_symlink()
    )
    for directory in roots:
        for path in directory.glob("MathTutor*"):
            if not path.is_file() or path.is_symlink() or path.suffix not in INSTALLERS:
                continue
            # Separate target architectures; no cross-platform pruning.
            arch = next(
                (name for name in ("arm64", "x64", "universal") if name in path.name),
                "unspecified",
            )
            platform = {".dmg": "mac", ".exe": "windows", ".AppImage": "linux"}.get(
                path.suffix
            )
            if platform is None:
                platform = next(
                    (
                        name
                        for name in ("mac", "windows", "win", "linux")
                        if name in path.name.lower()
                    ),
                    "unspecified",
                )
            groups.setdefault((path.suffix, platform, arch), []).append(path)
    candidates = []
    for paths in groups.values():
        newest = set(
            sorted(paths, key=lambda p: (p.stat().st_mtime_ns, str(p)), reverse=True)[
                :keep
            ]
        )
        for path in paths:
            if path in newest or path.relative_to(dist).parts[0] in protected:
                continue
            candidates.append(path)
            blockmap = path.with_name(path.name + ".blockmap")
            if blockmap.is_file() and not blockmap.is_symlink():
                candidates.append(blockmap)
    return [
        dict(
            path=str(p.relative_to(dist)),
            size=p.stat().st_size,
            mtime_ns=p.stat().st_mtime_ns,
        )
        for p in sorted(candidates)
    ]


def apply_plan(dist: Path, plan: list[dict]) -> None:
    # Check the entire plan before the first removal; a changed build is retained.
    root = dist.resolve()
    for item in plan:
        path = dist / item["path"]
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise RuntimeError(f"Artifact path changed: {item['path']}")
        stat = path.stat()
        if (stat.st_size, stat.st_mtime_ns) != (item["size"], item["mtime_ns"]):
            raise RuntimeError(f"Artifact changed: {item['path']}")
    for item in plan:
        (dist / item["path"]).unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=REPO / "desktop/dist")
    parser.add_argument(
        "--keep",
        type=int,
        default=1,
        help="Newest installers to retain per format/architecture",
    )
    parser.add_argument(
        "--protect-build",
        action="append",
        default=[],
        help="Additional build directory to retain",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Remove the reported installers; default is a preview",
    )
    args = parser.parse_args()
    protected = release_tags((REPO / "README.md").read_text(encoding="utf-8")) | set(
        args.protect_build
    )
    plan = prune_plan(args.dist, protected, args.keep)
    print(
        json.dumps(
            {
                "apply": args.apply,
                "protected_builds": sorted(protected),
                "files": plan,
                "bytes": sum(row["size"] for row in plan),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if args.apply:
        apply_plan(args.dist, plan)


if __name__ == "__main__":
    main()
