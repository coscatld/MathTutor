"""Owner-scoped, restart-safe request deduplication. Existing history is retained."""
from alembic import op
from mathtutor.infrastructure.schema import turn_requests

revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade():
    turn_requests.create(op.get_bind(), checkfirst=True)


def downgrade():
    turn_requests.drop(op.get_bind(), checkfirst=True)
