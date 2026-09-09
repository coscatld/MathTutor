"""Persist conversation history and per-conversation document membership.

Revision ID: 009
Revises: 008
Create Date: 2026-09-07
"""

from alembic import op
import sqlalchemy as sa

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    existing = _tables(bind)
    if "conversations" not in existing:
        op.create_table(
            "conversations",
            sa.Column("conversation_id", sa.String(128), primary_key=True),
            sa.Column("student_id", sa.String(64), sa.ForeignKey("student_profiles.student_id"), nullable=False),
            sa.Column("title", sa.String(160), nullable=False, server_default="新对话"),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.Text(), nullable=False),
            sa.UniqueConstraint("student_id", "conversation_id", name="uq_conversation_owner_id"),
        )
    if "conversation_messages" not in existing:
        op.create_table(
            "conversation_messages",
            sa.Column("message_id", sa.String(64), primary_key=True),
            sa.Column("conversation_id", sa.String(128), sa.ForeignKey("conversations.conversation_id"), nullable=False),
            sa.Column("student_id", sa.String(64), sa.ForeignKey("student_profiles.student_id"), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("action", sa.String(48), nullable=False, server_default=""),
            sa.Column("assistance_level", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("event_key", sa.String(160), nullable=False, server_default=""),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.UniqueConstraint("student_id", "conversation_id", "event_key", name="uq_conversation_message_event"),
        )
    if "conversation_documents" not in existing:
        op.create_table(
            "conversation_documents",
            sa.Column("conversation_id", sa.String(128), sa.ForeignKey("conversations.conversation_id"), primary_key=True),
            sa.Column("document_id", sa.String(64), sa.ForeignKey("user_documents.document_id"), primary_key=True),
            sa.Column("student_id", sa.String(64), sa.ForeignKey("student_profiles.student_id"), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
        )


def downgrade() -> None:
    op.drop_table("conversation_documents")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
