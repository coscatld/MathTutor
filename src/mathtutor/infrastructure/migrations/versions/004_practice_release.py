"""Verified Adaptive Practice: exercises / exercise_releases / practice_offers.

Revision ID: 004
Revises: 003
Create Date: 2026-08-20

Adds the Phase 5 practice catalog (design doc §11.3 / §24):

- ``exercises`` — one catalogued exercise per content identity (unique by
  ``content_hash`` bound to problem statement + problem_id + difficulty +
  source_type). ``source_type`` is a CLAIM (BANK/TEMPLATE/LLM), never a
  trust grant — every candidate passes the identical release gate.
- ``exercise_releases`` — immutable release attestations. Problem/solution/
  verifier/policy/license/provenance hashes plus the exact
  ``solution_candidate_id`` and ``verification_log_id`` the release was
  issued against (exact-snapshot judging). Any bound-byte change yields a
  NEW release (old → SUPERSEDED); status flips (released→revoked/
  superseded) are the only UPDATE path.
- ``practice_offers`` — one offer per (student, parent cycle, release).
  Status lifecycle ACTIVE → ACCEPTED / REVOKED / EXPIRED; owner-scoped.

Like 001–003, table shapes live in
``mathtutor.infrastructure.schema`` (single source of truth);
this migration applies them via create_all, which only creates tables
that do not exist yet.
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from mathtutor.infrastructure.schema import metadata

    metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from mathtutor.infrastructure.schema import (
        exercise_releases,
        exercises,
        practice_offers,
    )

    # Drop in FK dependency order: offers → releases → exercises.
    for table in (practice_offers, exercise_releases, exercises):
        table.drop(bind=op.get_bind())
