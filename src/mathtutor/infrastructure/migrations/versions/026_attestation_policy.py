"""Retain the policy identity of new immutable solution attestations."""

import sqlalchemy as sa
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade():
    # Fresh 001 databases use current metadata; existing databases need columns.
    columns = {
        c["name"] for c in sa.inspect(op.get_bind()).get_columns("verification_logs")
    }
    for name in ("policy_id", "policy_version"):
        if name not in columns:
            op.add_column(
                "verification_logs",
                sa.Column(name, sa.Text(), nullable=False, server_default=""),
            )
    # Historical policies cannot be reconstructed from a hash: keep them unknown.


def downgrade():
    with op.batch_alter_table("verification_logs") as batch:
        batch.drop_column("policy_version")
        batch.drop_column("policy_id")
