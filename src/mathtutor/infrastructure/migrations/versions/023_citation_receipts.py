"""Citation receipts: historical citation authorization, separate from retrieval.

Revision ID: 023
Revises: 022
Create Date: 2026-09-19

Active retrieval authorization and historical citation authorization are
different questions:

    active retrieval    "may this owner read this document NOW?"
                        owner + conversation scope + binding + retrieval_enabled
                        + not deleted + retrievable status + generation

    historical citation "was this exact range legitimately surfaced before,
                         and is that immutable version still intact?"

The second must survive the document being DISABLED — a citation the student
was already given does not stop being verifiable because retrieval was later
turned off. It must NOT survive DELETION: privacy deletion overrides historical
citation availability, so ``forget_document`` removes receipts and validation
re-reads the immutable version, failing closed when it is gone.

A receipt grants no new authority and cannot widen a range; it records that
authority was already exercised.

Additive table only — no existing column changes.
"""

from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_citation_receipts" in inspector.get_table_names():
        return
    # 001 applies metadata.create_all on a brand-new database, so a fresh DB
    # can already carry this table before Alembic reaches 023. The guard above
    # makes both cases safe, matching migration 007's precedent.
    op.create_table(
        "knowledge_citation_receipts",
        sa.Column("student_id", sa.String(), primary_key=True),
        sa.Column("receipt_id", sa.String(), primary_key=True),
        sa.Column("conversation_id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("document_version", sa.Integer(), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("body_hash", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=False),
        sa.Column("generation_at_issue", sa.Integer(), nullable=False),
        sa.Column("issued_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "knowledge_citation_receipts" in sa.inspect(bind).get_table_names():
        op.drop_table("knowledge_citation_receipts")
