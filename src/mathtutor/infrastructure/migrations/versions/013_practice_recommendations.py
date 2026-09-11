"""Durable recommendation intent; no fabricated offer on generation failure."""
from alembic import op
from mathtutor.infrastructure.schema import practice_recommendations

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade():
    practice_recommendations.create(op.get_bind(), checkfirst=True)


def downgrade():
    practice_recommendations.drop(op.get_bind(), checkfirst=True)
