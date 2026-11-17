"""Cleanup may remove old installers, never the current download or release evidence."""

import os
import runpy
from pathlib import Path

import pytest

cleaner = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts/clean-build-artifacts.py")
)


def artifact(root, name, timestamp):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"installer")
    os.utime(path, (timestamp, timestamp))
    return path


def test_keep_latest_each_platform_current_readme_release_and_evidence(tmp_path):
    published = artifact(tmp_path, "published/MathTutor-mac-arm64.dmg", 1)
    old = artifact(tmp_path, "old/MathTutor-mac-arm64.dmg", 2)
    blockmap = artifact(tmp_path, "old/MathTutor-mac-arm64.dmg.blockmap", 2)
    latest = artifact(tmp_path, "new/MathTutor-mac-arm64.dmg", 3)
    windows = artifact(tmp_path, "old/MathTutor-windows-x64.exe", 1)
    receipt = artifact(tmp_path, "old/release.json", 1)
    readme = "[download](https://github.com/owner/repo/releases/download/published/MathTutor-mac-arm64.dmg)"
    plan = cleaner["prune_plan"](tmp_path, cleaner["release_tags"](readme))
    assert {r["path"] for r in plan} == {
        str(p.relative_to(tmp_path)) for p in (old, blockmap)
    }
    assert old.exists()  # Preview has no side effects.
    cleaner["apply_plan"](tmp_path, plan)
    assert not old.exists() and not blockmap.exists()
    assert all(p.exists() for p in (published, latest, windows, receipt))


def test_changed_artifact_aborts_before_any_deletion(tmp_path):
    older = artifact(tmp_path, "MathTutor-old-mac-arm64.dmg", 1)
    artifact(tmp_path, "MathTutor-new-mac-arm64.dmg", 2)
    plan = cleaner["prune_plan"](tmp_path, set())
    older.write_bytes(b"new content")
    with pytest.raises(RuntimeError, match="Artifact changed"):
        cleaner["apply_plan"](tmp_path, plan)
    assert older.exists()


def test_cleanup_does_not_follow_directory_symlinks(tmp_path):
    outside = tmp_path / "outside"
    dist = tmp_path / "dist"
    dist.mkdir()
    linked = artifact(outside, "MathTutor-old-mac-arm64.dmg", 1)
    try:
        (dist / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks require privileges on this Windows host")
    artifact(dist, "MathTutor-new-mac-arm64.dmg", 2)
    assert cleaner["prune_plan"](dist, set()) == []
    assert linked.exists()
