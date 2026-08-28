"""K12 MathTutor — verifiable, traceable, offline-deployable math tutoring.

This package implements the K12 MathTutor vertical slice of the project
design blueprint (``K12_MATHTUTOR_PROJECT_DESIGN.md``):

- :mod:`~mathtutor.domain` — the frozen domain contract (five
  trust domains: candidate solutions, math facts, teaching permissions,
  learning evidence, long-term student state).
- :mod:`~mathtutor.solving` — the deterministic
  parse → solve → verify pipeline for the MVP problem families.
- :mod:`~mathtutor.application` — the tutoring state machine and
  the application service that orchestrates a turn without native tool
  calling.
- :mod:`~mathtutor.repositories` — repository interfaces with
  in-memory implementations; attestations are issued only for verified
  content (fail closed).

The slice is pure Python (stdlib ``fractions`` exact arithmetic) plus
pydantic for the domain contract; no LLM, no PostgreSQL yet. PostgreSQL +
transactional outbox land in Phase 1; pedagogy (L0–L5 disclosure) in
Phase 3.
"""

from __future__ import annotations

__all__ = []
