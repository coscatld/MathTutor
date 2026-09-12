"""Local image blobs and durable multimodal message references."""
from alembic import op
import sqlalchemy as sa
from mathtutor.infrastructure.schema import image_attachments

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    image_attachments.create(bind, checkfirst=True)
    if "attachments" not in {c["name"] for c in sa.inspect(bind).get_columns("conversation_messages")}:
        op.add_column("conversation_messages", sa.Column("attachments", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    op.drop_column("conversation_messages", "attachments")
    image_attachments.drop(op.get_bind(), checkfirst=True)
