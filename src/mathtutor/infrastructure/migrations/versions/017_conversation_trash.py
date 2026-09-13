"""Recoverable conversation trash; old conversations remain active."""
from alembic import op
import sqlalchemy as sa

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("conversations")}
    for name in ("trashed_at", "purged_at"):
        if name not in columns:
            op.add_column("conversations", sa.Column(name, sa.Text(), nullable=True))


def downgrade():
    op.drop_column("conversations", "purged_at")
    op.drop_column("conversations", "trashed_at")
