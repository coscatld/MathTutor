"""Misconception observations (Phase 4 learning loop).

Revision ID: 002
Revises: 001
Create Date: 2026-08-18

Adds ``misconception_observations`` — the append-only fact table written by
the Phase 4 diagnosis step. The student-level misconception *projection* is
derived state and stays inside the existing
``student_state_projections.active_misconceptions`` JSON column (no new
state table).

Like 001, table shapes live in ``mathtutor.infrastructure.schema``
(single source of truth); this migration applies them via create_all, which
only creates tables that do not exist yet.
"""

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from mathtutor.infrastructure.schema import metadata

    metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from mathtutor.infrastructure.schema import misconception_observations

    misconception_observations.drop(bind=op.get_bind())
