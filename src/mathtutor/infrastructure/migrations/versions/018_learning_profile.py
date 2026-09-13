"""Learning deletion generations and owner-scoped recommendation feedback."""
from alembic import op
from mathtutor.learning.knowledge_tracing.schema import learning_generations, practice_feedback

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade():
    for table in (learning_generations, practice_feedback):
        table.create(op.get_bind(), checkfirst=True)


def downgrade():
    for table in (practice_feedback, learning_generations):
        table.drop(op.get_bind(), checkfirst=True)
