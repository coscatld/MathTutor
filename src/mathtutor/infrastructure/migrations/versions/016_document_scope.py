"""Explicit owner-local global document scope; existing files remain private."""
from alembic import op
import sqlalchemy as sa

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade():
    if "is_global" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("user_documents")}:
        op.add_column("user_documents", sa.Column("is_global", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("user_documents", "is_global")
