"""Owner-scoped initial assessment facts; no secrets or DKT state."""
from alembic import op
from mathtutor.learning.knowledge_tracing.schema import initial_assessments

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade():
    initial_assessments.create(op.get_bind(), checkfirst=True)


def downgrade():
    initial_assessments.drop(op.get_bind(), checkfirst=True)
