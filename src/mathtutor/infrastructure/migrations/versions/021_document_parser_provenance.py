"""Record which parser produced a document, and what its text layer looked like.

Revision ID: 021
Revises: 020
Create Date: 2026-09-19

Adds ``parser_id`` and ``classification`` to ``user_documents``.

Both are per-document HISTORY, not derivable state:

- ``parser_id`` — the shipped runtime has no PyMuPDF
  (docs/CURRENT_STATE_RAG_AUDIT.md §6.1), so a document imported on a machine
  with the rich parser carries headings/tables/figures while one imported
  without it cannot. Re-reading the bytes later cannot recover which happened.
- ``classification`` — what was observed about the text layer at import time.

Backward compatibility: existing rows get ``parser_id = ''`` (unknown — NOT
retrofitted to a guess) and ``classification`` seeded ONLY where the existing
counters already prove it, i.e. a PDF whose ``empty_page_count`` equals
``page_count`` is ``NO_TEXT_LAYER_PDF`` and one with zero empty pages is
``TEXT_PDF``. Anything else stays ``''`` rather than being invented.
"""

from alembic import op
import sqlalchemy as sa

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


_NEW_COLUMNS = (
    # '' means "imported before this column existed / not recorded".
    ("parser_id", sa.Column("parser_id", sa.String(16), nullable=False, server_default="")),
    ("classification", sa.Column("classification", sa.String(32), nullable=False, server_default="")),
)


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "user_documents")
    for name, column in _NEW_COLUMNS:
        if name not in existing:
            op.add_column("user_documents", column)

    # Seed only what the persisted counters already prove. No page-level data
    # existed before this revision, so TEXT / MIXED are left empty rather than
    # inferred from a ratio that cannot distinguish them.
    op.execute(
        sa.text(
            """
            UPDATE user_documents
               SET classification = 'NO_TEXT_LAYER_PDF'
             WHERE classification = ''
               AND page_count > 0
               AND empty_page_count = page_count
               AND lower(filename) LIKE '%.pdf'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE user_documents
               SET classification = 'TEXT_PDF'
             WHERE classification = ''
               AND page_count > 0
               AND empty_page_count = 0
               AND lower(filename) LIKE '%.pdf'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE user_documents
               SET classification = 'TEXT_FILE'
             WHERE classification = ''
               AND lower(filename) NOT LIKE '%.pdf'
            """
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "user_documents")
    for name, _column in reversed(_NEW_COLUMNS):
        if name in existing:
            op.drop_column("user_documents", name)
