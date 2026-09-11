"""Append-only v2 learning events and version-bound tracker snapshots."""
from alembic import op
from mathtutor.learning.knowledge_tracing.schema import metadata

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), checkfirst=True)


def downgrade():
    metadata.drop_all(op.get_bind(), checkfirst=True)
