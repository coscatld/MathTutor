"""Explicit knowledge mounts and versioned facts; never widen legacy visibility."""
from alembic import op
from mathtutor.infrastructure.knowledge_schema import metadata

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind())
    # Legacy conversation_documents and explicit is_global remain unchanged.


def downgrade():
    metadata.drop_all(op.get_bind())
