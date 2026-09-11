"""Teaching contexts, approved delivery receipts and explicit cycle focus."""
from alembic import op
from mathtutor.infrastructure.schema import teaching_contexts, teaching_deliveries, cycle_focus, cycle_owner_unique

revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade():
    cycle_owner_unique.create(op.get_bind(), checkfirst=True)
    for table in (teaching_contexts, teaching_deliveries, cycle_focus):
        table.create(op.get_bind(), checkfirst=True)
    # Preserve historical transitions; repair only the live state that never
    # had an actual offer. It is not evidence that the learner reflected.
    op.execute("UPDATE tutoring_cycles SET state='solution_shown' WHERE state IN ('reflection','practice_offered') AND NOT EXISTS (SELECT 1 FROM practice_offers p WHERE p.parent_cycle_id=tutoring_cycles.cycle_id)")


def downgrade():
    for table in (cycle_focus, teaching_deliveries, teaching_contexts):
        table.drop(op.get_bind(), checkfirst=True)
