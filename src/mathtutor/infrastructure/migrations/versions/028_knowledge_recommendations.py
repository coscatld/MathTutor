"""Owner-scoped, bounded asynchronous knowledge discovery."""
import sqlalchemy as sa
from alembic import op

from mathtutor.infrastructure.recommendation_schema import metadata

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in metadata.sorted_tables:
        if table.name not in inspector.get_table_names():
            table.create(bind)
        elif (set(column["name"] for column in inspector.get_columns(table.name)) != set(table.c.keys())
              or inspector.get_pk_constraint(table.name)["constrained_columns"] != ["student_id"]
              or any(column["nullable"] for column in inspector.get_columns(table.name))):
            raise RuntimeError("Existing recommendation table does not match its schema")


def downgrade():
    metadata.drop_all(op.get_bind())
