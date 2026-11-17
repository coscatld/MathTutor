"""Owner-scoped inquiry evidence and deletion generations."""

import sqlalchemy as sa
from alembic import op

from mathtutor.infrastructure.exploration_schema import metadata

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = inspector.get_table_names()
    for table in metadata.sorted_tables:
        if table.name not in existing:
            table.create(bind)
            continue
        columns = inspector.get_columns(table.name)
        primary = inspector.get_pk_constraint(table.name)["constrained_columns"]
        if ({column["name"] for column in columns} != set(table.c.keys())
                or primary != [column.name for column in table.primary_key]
                or any(column["nullable"] for column in columns)):
            raise RuntimeError("Existing exploration table does not match its schema")


def downgrade():
    metadata.drop_all(op.get_bind())
