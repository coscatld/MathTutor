"""Promote attempt and skill identity to first-class evidence columns.

Revision ID: 006
Revises: 005
Create Date: 2026-08-24

Existing rows are deterministically backfilled from the immutable assessment
chain.  The migration changes table shape only; it never rewrites evidence
meaning, idempotency keys, ordering, or estimator inputs.

Migration 001 historically calls the current ``metadata.create_all``.  A
brand-new database can therefore already contain this revision's columns and
constraints before Alembic reaches 006.  The inspection guards below make 006
safe for both that case and a real pre-006 database.
"""

from alembic import op
import sqlalchemy as sa

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


_SKILL_CASE_SQL = """
CASE mp.problem_type
    WHEN 'arithmetic' THEN 'ARITHMETIC'
    WHEN 'polynomial' THEN 'POLYNOMIAL_BASIC'
    WHEN 'linear' THEN 'LINEAR_EQUATION'
    WHEN 'quadratic' THEN 'QUADRATIC_EQUATION'
    ELSE 'UNKNOWN_SKILL'
END
"""


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "mastery_evidence")
    added = False
    if "attempt_id" not in existing:
        op.add_column("mastery_evidence", sa.Column("attempt_id", sa.String(64), nullable=True))
        added = True
    if "skill_id" not in existing:
        op.add_column("mastery_evidence", sa.Column("skill_id", sa.String(64), nullable=True))
        added = True

    if not added:
        # Fresh databases were already created from the current metadata.
        return

    op.execute(
        sa.text(
            """
            UPDATE mastery_evidence
               SET attempt_id = (
                       SELECT aa.attempt_id
                         FROM attempt_assessments AS aa
                        WHERE aa.verification_log_id = mastery_evidence.attempt_assessment_log_id
                   ),
                   skill_id = (
                       SELECT """
            + _SKILL_CASE_SQL
            + """
                         FROM attempt_assessments AS aa
                         JOIN verification_logs AS vl
                           ON vl.log_id = aa.verification_log_id
                         JOIN math_problems AS mp
                           ON mp.problem_id = vl.problem_id
                        WHERE aa.verification_log_id = mastery_evidence.attempt_assessment_log_id
                   )
            """
        )
    )
    missing = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM mastery_evidence "
            "WHERE attempt_id IS NULL OR skill_id IS NULL"
        )
    ).scalar_one()
    if missing:
        raise RuntimeError(
            "migration 006 cannot bind every evidence row to an attempt and skill"
        )

    # SQLite accepts a composite FK target backed by a unique index.  The
    # table recreation below then installs NOT NULL and owner binding without
    # weakening the existing append-only/idempotency constraints.
    op.create_index(
        "uq_attempt_owner_identity",
        "attempts",
        ["attempt_id", "student_id"],
        unique=True,
    )
    with op.batch_alter_table("mastery_evidence", recreate="always") as batch:
        batch.alter_column("attempt_id", existing_type=sa.String(64), nullable=False)
        batch.alter_column("skill_id", existing_type=sa.String(64), nullable=False)
        batch.create_foreign_key(
            "fk_evidence_attempt_owner",
            "attempts",
            ["attempt_id", "student_id"],
            ["attempt_id", "student_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "mastery_evidence")
    if "attempt_id" not in existing and "skill_id" not in existing:
        return
    with op.batch_alter_table("mastery_evidence", recreate="always") as batch:
        batch.drop_constraint("fk_evidence_attempt_owner", type_="foreignkey")
        batch.drop_column("skill_id")
        batch.drop_column("attempt_id")
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("attempts")}
    if "uq_attempt_owner_identity" in indexes:
        op.drop_index("uq_attempt_owner_identity", table_name="attempts")
