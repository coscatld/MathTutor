"""Bounded owner-scoped diagnostic, delayed-review and transfer episodes."""
from alembic import op
import sqlalchemy as sa
from mathtutor.learning.knowledge_tracing.schema import learning_loop_episodes

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "learning_loop_episodes" in inspector.get_table_names():
        columns = inspector.get_columns("learning_loop_episodes")
        primary = inspector.get_pk_constraint("learning_loop_episodes")["constrained_columns"]
        if {c["name"] for c in columns} != {"student_id", "domain", "payload"} or primary != ["student_id", "domain"] or any(c["nullable"] for c in columns):
            raise RuntimeError("Existing learning-loop table does not match the migration contract")
    else:
        learning_loop_episodes.create(bind)


def downgrade():
    learning_loop_episodes.drop(op.get_bind(), checkfirst=True)
