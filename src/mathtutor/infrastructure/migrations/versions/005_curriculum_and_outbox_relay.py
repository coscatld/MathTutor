"""Phase 6 first round: versioned curriculum catalog + outbox relay ledger.

Revision ID: 005
Revises: 004
Create Date: 2026-08-20

Adds (design doc Phase 6 — curriculum RAG 第一轮, §10):

- ``curriculum_versions`` — one immutable curriculum version per code;
  publishing is the only state path (draft → published → archived), the
  version row itself is never mutated in place.
- ``curriculum_nodes`` / ``curriculum_edges`` — the curriculum graph of
  one version. Nodes are unique by (version_id, code); edges are version-
  bound and may only reference nodes of the SAME version (graph
  validation lives in the service layer — the FKs enforce the hard part).
- ``outbox_dispatch_ledger`` — the outbox relay's idempotency watermark.
  The relay never deletes or mutates ``domain_outbox`` rows (append-only);
  a dispatch is recorded here under the same unique key
  (aggregate_type, aggregate_id, aggregate_version, event_sequence), so
  replays and restarts can never double-publish.

Like 001–004, table shapes live in
``mathtutor.infrastructure.schema`` (single source of truth);
this migration applies them via create_all, which only creates tables
that do not exist yet.
"""

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from mathtutor.infrastructure.schema import metadata

    metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from mathtutor.infrastructure.schema import (
        curriculum_edges,
        curriculum_nodes,
        curriculum_versions,
        outbox_dispatch_ledger,
    )

    # Drop in FK dependency order: edges → nodes → versions; the ledger
    # depends only on domain_outbox (unchanged by this migration).
    for table in (outbox_dispatch_ledger, curriculum_edges, curriculum_nodes, curriculum_versions):
        table.drop(bind=op.get_bind())
