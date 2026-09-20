"""Complete the vector-index signature with normalization + runtime version.

Revision ID: 022
Revises: 021
Create Date: 2026-09-19

``EmbeddingDescriptor`` carries ``normalization`` and ``runtime_version``, and
both change the vectors produced for identical text. The persisted build row
did not record either, so a normalization change could not mark an existing
index stale — the search would keep using vectors built under the old rule and
silently mis-score.

Backward compatibility: existing rows get ``''``. Empty is treated as a
MISMATCH by ``IndexBuildRecord.matches_signature``, so a pre-022 build rebuilds
once on its next check rather than being trusted as current. That is the safe
direction: a spurious rebuild costs CPU, a spurious match costs correctness.
"""

from alembic import op
import sqlalchemy as sa

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


_NEW_COLUMNS = (
    (
        "embedding_normalization",
        sa.Column("embedding_normalization", sa.String(32), nullable=False, server_default=""),
    ),
    (
        "embedding_runtime_version",
        sa.Column("embedding_runtime_version", sa.String(64), nullable=False, server_default=""),
    ),
)


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "document_index_builds")
    for name, column in _NEW_COLUMNS:
        if name not in existing:
            op.add_column("document_index_builds", column)


def downgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "document_index_builds")
    for name, _column in reversed(_NEW_COLUMNS):
        if name in existing:
            op.drop_column("document_index_builds", name)
