"""SQLite FTS5 index over pre-tokenized document chunk text.

The virtual table is NOT part of SQLAlchemy ``metadata`` (it is not a
regular relation and must not change the classified table count). It is
created on demand / by migration 008. Permission filters stay on
``user_documents``; FTS only proposes candidate chunk ids.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

FTS_TABLE = "document_chunks_fts"

_CREATE_FTS = f"""
CREATE VIRTUAL TABLE IF NOT EXISTS {FTS_TABLE} USING fts5(
  chunk_id UNINDEXED,
  student_id UNINDEXED,
  document_id UNINDEXED,
  fts_text,
  tokenize = 'unicode61'
)
"""


async def ensure_document_chunks_fts(conn: AsyncConnection) -> bool:
    """Create the FTS5 table if this SQLite build supports it. False if not."""
    try:
        await conn.execute(text(_CREATE_FTS))
        return True
    except Exception:
        return False


async def sync_document_chunks_fts(
    conn: AsyncConnection, *, document_id: str | None = None
) -> None:
    """Synchronize the FTS5 table from ``document_chunks.fts_text``.

    With ``document_id`` given, only that document's rows are replaced. Every
    chunk write used to rebuild the WHOLE table, so importing one document
    deleted and re-inserted the FTS rows of every other document the student
    owned — write amplification proportional to the whole corpus, on the
    interactive import path.

    Without ``document_id`` the full rebuild is retained for the migration
    backfill path, which genuinely needs to populate a fresh table.
    """
    if not await ensure_document_chunks_fts(conn):
        return

    if document_id is not None:
        await conn.execute(
            text(f"DELETE FROM {FTS_TABLE} WHERE document_id = :document_id"),
            {"document_id": str(document_id)},
        )
        await conn.execute(
            text(
                f"INSERT INTO {FTS_TABLE}(chunk_id, student_id, document_id, fts_text) "
                "SELECT chunk_id, student_id, document_id, COALESCE(fts_text, '') "
                "FROM document_chunks WHERE document_id = :document_id"
            ),
            {"document_id": str(document_id)},
        )
        return

    try:
        await conn.execute(text(f"INSERT INTO {FTS_TABLE}({FTS_TABLE}) VALUES('delete-all')"))
    except Exception:
        await conn.execute(text(f"DROP TABLE IF EXISTS {FTS_TABLE}"))
        await conn.execute(text(_CREATE_FTS))
    await conn.execute(
        text(
            f"INSERT INTO {FTS_TABLE}(chunk_id, student_id, document_id, fts_text) "
            "SELECT chunk_id, student_id, document_id, COALESCE(fts_text, '') "
            "FROM document_chunks"
        )
    )


__all__ = [
    "FTS_TABLE",
    "ensure_document_chunks_fts",
    "sync_document_chunks_fts",
]
