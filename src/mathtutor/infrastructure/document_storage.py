"""Controlled document storage — the only place imported bytes live.

Design contract (§14): after import the ORIGINAL host path is irrelevant.
Documents are addressed by ``document_id`` and stored under the
MathTutor-controlled data directory at:

    <data_root>/uploads/<student_id>/<document_id>/<safe-filename>

- every stored path is derived from the data root — never from caller
  input directly; a resolved path that escapes the root raises;
- filenames are sanitized (basename only, no separators, no control
  chars, no leading dots except the extension) before touching disk;
- storage is byte-preserving: content hashes are computed by the caller
  on the ORIGINAL bytes before store, so store order is irrelevant;
- deletion removes the file and prunes now-empty owner dirs.

Owner scope is structural: two students' files can never collide because
the path embeds both ids (both UUID strings, both validated).
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from uuid import UUID

UPLOADS_DIRNAME = "uploads"

# Filename sanitizer: keep letters/digits plus a safe punctuation set,
# collapse the rest to "_". Length capped at 120 chars, extension kept.
_INVALID_FILENAME_CHARS = re.compile(r'[^A-Za-z0-9._\-一-鿿()（）]+')
_MAX_FILENAME_CHARS = 120


class StoragePathError(ValueError):
    """Raised when a storage ref escapes the controlled root."""


def sanitize_filename(filename: str) -> str:
    """Filesystem-safe name for display + storage (never returns empty)."""
    name = Path(filename.replace("\\", "/")).name  # basename only — kills separators
    name = _INVALID_FILENAME_CHARS.sub("_", name).strip(" .")
    # No bare leading dots (hidden files); keep only the real extension dot.
    name = name.lstrip(".") or "_unnamed"
    if len(name) > _MAX_FILENAME_CHARS:
        stem, dot, extension = name.rpartition(".")
        keep = _MAX_FILENAME_CHARS - len(extension) - (1 if dot else 0)
        name = (stem[:keep] if stem else "_unnamed") + (dot + extension if dot else "")
    return name or "_unnamed"


def storage_ref_for(student_id: UUID, document_id: UUID, safe_filename: str) -> str:
    """Relative ref stored in the DB: ``uploads/<student>/<doc>/<name>``."""
    return f"{UPLOADS_DIRNAME}/{student_id}/{document_id}/{safe_filename}"


class DocumentStorage:
    """Async byte store under one controlled data root.

    The desktop adapter constructs this once per product instance with
    ``data_root = <math_tutor data dir>``; business code only ever sees
    storage REFS (strings), never filesystem paths.
    """

    def __init__(self, data_root: Path) -> None:
        self._data_root = data_root.resolve()
        self._uploads_root = self._data_root / UPLOADS_DIRNAME

    def uploads_root(self) -> Path:
        return self._uploads_root

    def document_dir(self, student_id: UUID, document_id: UUID) -> Path:
        """Directory that holds one document file plus its ``assets/``."""
        placeholder = storage_ref_for(student_id, document_id, "_placeholder")
        return self.resolve(placeholder).parent

    def assets_dir(self, student_id: UUID, document_id: UUID) -> Path:
        return self.document_dir(student_id, document_id) / "assets"

    def assets_ref_prefix(self, student_id: UUID, document_id: UUID) -> str:
        return f"{UPLOADS_DIRNAME}/{student_id}/{document_id}/assets"

    def ref_for(self, student_id: UUID, document_id: UUID, filename: str) -> str:
        safe = sanitize_filename(filename)
        if not safe:
            raise StoragePathError(f"filename unusable after sanitization: {filename!r}")
        return storage_ref_for(student_id, document_id, safe)

    def resolve(self, storage_ref: str) -> Path:
        """Resolve a stored ref to an absolute path — escapes raise.

        The resolved path must sit under ``uploads/``: refs like
        ``../users`` or absolute paths (which override the root in
        pathlib) are rejected before any filesystem access.
        """
        path = (self._uploads_root / storage_ref).resolve()
        if not path.is_relative_to(self._uploads_root):
            raise StoragePathError(f"storage ref escapes uploads root: {storage_ref!r}")
        return path

    async def store_bytes(self, storage_ref: str, data: bytes) -> Path:
        """Write bytes atomically-ish (temp file + replace) and return path."""
        path = self.resolve(storage_ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
        return path

    async def read_bytes(self, storage_ref: str) -> bytes:
        return self.resolve(storage_ref).read_bytes()

    async def remove(self, storage_ref: str) -> bool:
        """Delete the file; prune empty owner dirs. Returns whether it existed."""
        path = self.resolve(storage_ref)
        assets = path.parent / "assets"
        if assets.is_dir():
            shutil.rmtree(assets, ignore_errors=True)
        if not path.exists():
            return False
        path.unlink()
        for parent in (path.parent, path.parent.parent):
            try:
                parent.rmdir()  # only removes when empty
            except OSError:
                break
        return True

    async def exists(self, storage_ref: str) -> bool:
        return self.resolve(storage_ref).exists()


__all__ = [
    "DocumentStorage",
    "StoragePathError",
    "UPLOADS_DIRNAME",
    "sanitize_filename",
    "storage_ref_for",
]
