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


async def sync_document_chunks_fts(conn: AsyncConnection) -> None:
    """Rebuild the whole FTS5 table from ``document_chunks.fts_text``."""
    if not await ensure_document_chunks_fts(conn):
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
