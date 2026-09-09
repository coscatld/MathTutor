"""Persist explicit assistant completion status."""
from alembic import op
import sqlalchemy as sa
revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None


def upgrade():
    existing = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('conversation_messages')}
    for name, size, default in [('status', 16, 'COMPLETED'), ('finish_reason', 32, 'FINAL_ANSWER'), ('turn_id', 160, ''), ('continuation_context', 8192, '')]:
        if name not in existing:
            op.add_column('conversation_messages', sa.Column(name, sa.String(size), nullable=False, server_default=default))


def downgrade():
    with op.batch_alter_table('conversation_messages') as batch:
        for name in ('continuation_context', 'turn_id', 'finish_reason', 'status'):
            batch.drop_column(name)
