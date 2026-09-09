"""Add chunk fts_text and the FTS5 virtual table.

Revision ID: 008
Revises: 007
Create Date: 2026-09-07

``fts_text`` is a pre-tokenized copy of the chunk (CJK bigrams, full
runs, latex-plain, skill aliases). The FTS5 virtual table
``document_chunks_fts`` is the lexical candidate source; LIKE is no
longer the primary path. Embedding remains optional and DEFERRED.
"""

from alembic import op
import sqlalchemy as sa

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
  chunk_id UNINDEXED,
  student_id UNINDEXED,
  document_id UNINDEXED,
  fts_text,
  tokenize = 'unicode61'
)
"""


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "document_chunks")
    if "fts_text" not in existing:
        op.add_column(
            "document_chunks",
            sa.Column("fts_text", sa.Text(), nullable=False, server_default=""),
        )

    from mathtutor.infrastructure.lexical import build_fts_text
    import json

    rows = bind.execute(
        sa.text(
            "SELECT chunk_id, text, section, metadata_json FROM document_chunks"
        )
    ).fetchall()
    for row in rows:
        chunk_id, body, section, raw_meta = row[0], row[1], row[2], row[3]
        metadata = raw_meta
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except json.JSONDecodeError:
                metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        heading = metadata.get("heading_path") or []
        fts = build_fts_text(
            body or "",
            heading_path=heading if isinstance(heading, list) else (),
            section=section or "",
            metadata=metadata,
        )
        bind.execute(
            sa.text("UPDATE document_chunks SET fts_text = :fts WHERE chunk_id = :cid").bindparams(
                fts=fts, cid=chunk_id
            )
        )

    bind.execute(sa.text(_FTS_SQL))
    try:
        bind.execute(
            sa.text("INSERT INTO document_chunks_fts(document_chunks_fts) VALUES('delete-all')")
        )
    except Exception:
        pass
    bind.execute(
        sa.text(
            "INSERT INTO document_chunks_fts(chunk_id, student_id, document_id, fts_text) "
            "SELECT chunk_id, student_id, document_id, fts_text FROM document_chunks"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DROP TABLE IF EXISTS document_chunks_fts"))
    existing = _columns(bind, "document_chunks")
    if "fts_text" in existing:
        op.drop_column("document_chunks", "fts_text")
