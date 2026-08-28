"""Initial MathTutor schema (runtime + math facts + education + outbox).

Revision ID: 001
Revises:
Create Date: 2026-08-16

Table shapes live in ``mathtutor.infrastructure.schema``
(single source of truth); this migration applies them via create_all.
"""

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from mathtutor.infrastructure.schema import metadata

    metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from mathtutor.infrastructure.schema import metadata

    metadata.drop_all(bind=op.get_bind())
