"""Persist document parse stats and demote zero-text "ready" rows.

Revision ID: 007
Revises: 006
Create Date: 2026-09-07

Adds page/chunk/empty-page counters and ``parse_warning`` on
``user_documents``. Scanned PDFs that previously landed as ``ready`` with
zero chunks are rewritten to ``needs_ocr`` with retrieval disabled.

Migration 001 historically calls the current ``metadata.create_all``.  A
brand-new database can therefore already contain this revision's columns
before Alembic reaches 007.  The inspection guards below make 007 safe
for both that case and a real pre-007 database.
"""

from alembic import op
import sqlalchemy as sa

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


_NEW_COLUMNS = (
    ("page_count", sa.Column("page_count", sa.Integer(), nullable=False, server_default="0")),
    ("chunk_count", sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0")),
    ("image_count", sa.Column("image_count", sa.Integer(), nullable=False, server_default="0")),
    (
        "empty_page_count",
        sa.Column("empty_page_count", sa.Integer(), nullable=False, server_default="0"),
    ),
    ("parse_warning", sa.Column("parse_warning", sa.Text(), nullable=False, server_default="")),
)

_NO_TEXT_PDF = "未提取到文字层，可能是扫描件。当前版本不支持 OCR，无法用于检索。"
_NO_TEXT_FILE = "文件没有可提取的文字，无法用于检索。"


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "user_documents")
    for name, column in _NEW_COLUMNS:
        if name not in existing:
            op.add_column("user_documents", column)

    op.execute(
        sa.text(
            """
            UPDATE user_documents
               SET chunk_count = (
                   SELECT COUNT(*)
                     FROM document_chunks
                    WHERE document_chunks.document_id = user_documents.document_id
                      AND document_chunks.student_id = user_documents.student_id
               )
             WHERE chunk_count = 0
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE user_documents
               SET status = 'needs_ocr',
                   retrieval_enabled = 0,
                   parse_error = :warning,
                   parse_warning = :warning
             WHERE status = 'ready'
               AND chunk_count = 0
               AND lower(filename) LIKE '%.pdf'
            """
        ).bindparams(warning=_NO_TEXT_PDF)
    )
    op.execute(
        sa.text(
            """
            UPDATE user_documents
               SET status = 'failed',
                   retrieval_enabled = 0,
                   parse_error = :warning,
                   parse_warning = :warning
             WHERE status = 'ready'
               AND chunk_count = 0
            """
        ).bindparams(warning=_NO_TEXT_FILE)
    )


def downgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "user_documents")
    for name, _column in reversed(_NEW_COLUMNS):
        if name in existing:
            op.drop_column("user_documents", name)
