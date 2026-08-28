"""MathTutor SQLite persistence infrastructure (Phase 1, SQLite-first).

Storage implementation only — the architecture (Repository protocols, UoW,
transactional outbox, CAS, owner isolation) is unchanged from the design
blueprint; see the Phase 1 storage decision for the SQLite adjustment.
"""

from __future__ import annotations

from mathtutor.infrastructure.db import (
    check_db_health,
    create_db_engine,
    resolve_db_path,
)
from mathtutor.infrastructure.schema import metadata

__all__ = [
    "check_db_health",
    "create_db_engine",
    "metadata",
    "resolve_db_path",
]
