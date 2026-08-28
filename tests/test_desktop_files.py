"""Desktop file picking + controlled storage tests (§37 DESKTOP group).

Only EXPLICITLY picked files may enter the system; the business layer
never scans host directories, and storage paths are always derived from
the controlled root — path escapes fail closed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mathtutor.application.desktop_files import (
    InMemoryPickedFilePicker,
    PickedFile,
)
from mathtutor.infrastructure.document_storage import (
    DocumentStorage,
    StoragePathError,
    sanitize_filename,
    storage_ref_for,
)

pytestmark = pytest.mark.asyncio


def test_picked_file_is_immutable():
    picked = PickedFile(filename="a.md", data=b"x", original_path="/tmp/a.md")
    with pytest.raises(Exception):
        picked.filename = "b.md"  # type: ignore[misc]


async def test_picker_queue_fifo_and_cancel():
    picker = InMemoryPickedFilePicker()
    assert await picker.pick_document_file("student-a") is None  # cancel: empty queue
    first = PickedFile(filename="one.txt", data=b"1")
    second = PickedFile(filename="two.md", data=b"2")
    picker.enqueue(first)
    picker.enqueue(second)
    assert await picker.pick_document_file("student-a") == first
    assert await picker.pick_document_file("student-a") == second
    assert await picker.pick_document_file("student-a") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("notes.md", "notes.md"),
        ("../../evil.sh", "evil.sh"),  # separators stripped — basename only
        ("..\\..\\evil.sh", "evil.sh"),  # windows-style separators
        ("名字 有 空格.md", "名字_有_空格.md"),
        ("tab\tname.txt", "tab_name.txt"),
        (".hidden", "hidden"),  # leading dots stripped — no hidden files
        ("....", "_unnamed"),
        ("a" * 300 + ".txt", None),  # length-capped (checked below)
    ],
)
def test_sanitize_filename(raw, expected):
    if expected is None:
        assert len(sanitize_filename(raw)) <= 120
    else:
        assert sanitize_filename(raw) == expected


def test_storage_ref_shape():
    ref = storage_ref_for(
        __import__("uuid").UUID(int=1), __import__("uuid").UUID(int=2), "doc.pdf"
    )
    parts = ref.split("/")
    assert parts[0] == "uploads"
    assert len(parts) == 4


async def test_storage_roundtrip_and_remove(tmp_path: Path):
    storage = DocumentStorage(tmp_path / "data")
    ref = storage.ref_for(
        __import__("uuid").UUID(int=3), __import__("uuid").UUID(int=4), "note.txt"
    )
    path = await storage.store_bytes(ref, "二次方程内容".encode("utf-8"))
    assert path.exists()
    assert await storage.exists(ref)
    assert await storage.read_bytes(ref) == "二次方程内容".encode("utf-8")
    # Stored under <data_root>/uploads/<student>/<document>/<name>.
    assert storage.uploads_root() in path.parents

    assert await storage.remove(ref) is True
    assert await storage.exists(ref) is False
    assert await storage.remove(ref) is False  # already gone
    # Empty owner dirs pruned after removal.
    assert not path.parent.exists()
    assert not path.parent.parent.exists()


async def test_storage_rejects_path_escape(tmp_path: Path):
    storage = DocumentStorage(tmp_path / "data")
    with pytest.raises(StoragePathError):
        storage.resolve("../users/evil.txt")
    with pytest.raises(StoragePathError):
        storage.resolve("uploads/../../secret.txt")  # escapes the uploads root
    with pytest.raises(StoragePathError):
        await storage.store_bytes("/etc/passwd", b"x")
    with pytest.raises(StoragePathError):
        await storage.read_bytes("../../etc/passwd")


async def test_storage_degenerate_filename_becomes_safe(tmp_path: Path):
    storage = DocumentStorage(tmp_path / "data")
    ref = storage.ref_for(
        __import__("uuid").UUID(int=5), __import__("uuid").UUID(int=6), "...."
    )
    # Degenerate names never raise — they sanitize to a safe placeholder.
    assert ref.endswith("/_unnamed")
