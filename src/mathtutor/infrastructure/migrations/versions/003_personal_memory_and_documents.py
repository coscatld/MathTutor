"""Personal Memory KG + User Document Knowledge (Phase 5/6 foundation).

Revision ID: 003
Revises: 002
Create Date: 2026-08-19

Adds six tables:

- ``personal_memory_nodes`` / ``personal_memory_edges`` — user-controlled,
  non-authoritative preference/goal/note KG. Owner-scoped; soft delete;
  ``retrieval_enabled`` switch. NEVER stores mastery/assessment/
  misconception/verification facts (Student Model stays authoritative).
- ``user_documents`` — imported document metadata (bytes live in
  controlled storage, ``data/uploads/<student_id>/<document_id>/``).
  Unique (student_id, content_hash) → duplicate-import semantics.
- ``document_chunks`` — extracted text chunks (the retrieval fact unit).
- ``document_chunk_vectors`` — embedding vectors as a DERIVED projection
  of chunks, versioned by backend/model/dimension.
- ``document_index_builds`` — index lifecycle row per (student, document):
  current index version + full build signature. Any backend/model/
  chunker/parser version change marks the build stale → rebuild.

Like 001/002, table shapes live in
``mathtutor.infrastructure.schema`` (single source of truth);
this migration applies them via create_all, which only creates tables
that do not exist yet.
"""

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from mathtutor.infrastructure.schema import metadata

    metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from mathtutor.infrastructure.schema import (
        document_chunk_vectors,
        document_chunks,
        document_index_builds,
        personal_memory_edges,
        personal_memory_nodes,
        user_documents,
    )

    # Drop in dependency order (vectors/index before chunks/documents).
    for table in (
        document_chunk_vectors,
        document_index_builds,
        document_chunks,
        user_documents,
        personal_memory_edges,
        personal_memory_nodes,
    ):
        table.drop(bind=op.get_bind())
