"""Turn traces: a persistent, text-free record of each tutor turn.

Revision ID: 024
Revises: 023
Create Date: 2026-10-14

loop_health() counters lived in process memory and reset on restart, so a
bad answer in production could not be investigated afterwards. Each turn now
leaves one structured row (command, actions, status, finish reason, error
code, latency, tokens, model, formula-check counts). The student's words and
the reply are NOT copied here; they stay in conversation_messages under the
existing owner and conversation scope, and both are removed together when a
conversation is purged.

Additive table only — no existing column changes.
"""

from alembic import op
import sqlalchemy as sa

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "turn_traces" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "turn_traces",
        sa.Column("student_id", sa.String(64), sa.ForeignKey("student_profiles.student_id"), primary_key=True),
        sa.Column("conversation_id", sa.String(128), primary_key=True),
        sa.Column("turn_id", sa.String(160), primary_key=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("command", sa.String(48), nullable=False, server_default=""),
        sa.Column("actions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("finish_reason", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("steps_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("usage_estimated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider", sa.String(64), nullable=False, server_default=""),
        sa.Column("model", sa.String(128), nullable=False, server_default=""),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "turn_traces" in sa.inspect(bind).get_table_names():
        op.drop_table("turn_traces")
