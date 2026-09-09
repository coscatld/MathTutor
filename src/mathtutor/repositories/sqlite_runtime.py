"""SQLite runtime persistence: sessions, cycles, transitions (Phase 1B).

The database is the authoritative cycle record. Every query is owner-scoped
(``student_id`` always in the WHERE clause — the client never supplies it)
and transitions persist with CAS on ``state_version``.

READ → COMPUTE → COMMIT: the caller loads a snapshot, runs the state machine
in memory, and persists each transition inside a short UoW transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from mathtutor.application.state_machine import VersionConflictError
from mathtutor.domain.tutoring import CycleTransition
from mathtutor.infrastructure.schema import (
    cycle_transitions,
    learning_sessions,
    tutoring_cycles,
)


@dataclass(frozen=True, slots=True)
class CycleSnapshot:
    """Persisted cycle record (authoritative between turns)."""

    cycle_id: UUID
    session_id: UUID
    client_session_id: str
    state: str
    state_version: int
    problem_id: UUID | None
    practice_offer_id: UUID | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_student(
    conn: AsyncConnection, *, student_id: str, username: str = "", role: str = "user"
) -> None:
    """Upsert the identity rows required by the owner FKs (idempotent)."""
    from mathtutor.infrastructure.schema import student_profiles, users

    user_id = student_id  # Phase 0: student_id == user_id (Phase 1 maps profiles)
    existing = (
        await conn.execute(select(users).where(users.c.user_id == user_id))
    ).first()
    if existing is None:
        await conn.execute(
            users.insert().values(
                user_id=user_id,
                username=username or user_id,
                role=role,
                created_at=_now(),
            )
        )
    profile = (
        await conn.execute(
            select(student_profiles).where(student_profiles.c.student_id == student_id)
        )
    ).first()
    if profile is None:
        await conn.execute(
            student_profiles.insert().values(
                student_id=student_id,
                user_id=user_id,
                created_at=_now(),
            )
        )


async def create_cycle(
    conn: AsyncConnection, *, student_id: str, client_session_id: str
) -> CycleSnapshot:
    """Create the session + initial cycle row (problem_received, version 0)."""
    from uuid import uuid4

    session_id = str(uuid4())
    cycle_id = uuid4()
    await conn.execute(
        learning_sessions.insert().values(
            session_id=session_id,
            client_session_id=client_session_id,
            student_id=student_id,
            created_at=_now(),
        )
    )
    await conn.execute(
        tutoring_cycles.insert().values(
            cycle_id=str(cycle_id),
            session_id=session_id,
            student_id=student_id,
            state="problem_received",
            state_version=0,
            problem_id=None,
            practice_offer_id=None,
            created_at=_now(),
            closed_at=None,
        )
    )
    return CycleSnapshot(
        cycle_id=cycle_id,
        session_id=UUID(session_id),
        client_session_id=client_session_id,
        state="problem_received",
        state_version=0,
        problem_id=None,
        practice_offer_id=None,
    )


async def create_successor_cycle(
    conn: AsyncConnection, *, student_id: str, parent: CycleSnapshot
) -> CycleSnapshot:
    """Start a new PROBLEM_RECEIVED cycle on the same learning session.

    ``learning_sessions`` is unique per owner+client session, so a later
    problem in the same conversation cannot insert another session row.
    """
    from uuid import uuid4

    cycle_id = uuid4()
    await conn.execute(
        tutoring_cycles.insert().values(
            cycle_id=str(cycle_id),
            session_id=str(parent.session_id),
            student_id=student_id,
            state="problem_received",
            state_version=0,
            problem_id=None,
            practice_offer_id=None,
            created_at=_now(),
            closed_at=None,
        )
    )
    return CycleSnapshot(
        cycle_id=cycle_id,
        session_id=parent.session_id,
        client_session_id=parent.client_session_id,
        state="problem_received",
        state_version=0,
        problem_id=None,
        practice_offer_id=None,
    )


async def create_practice_child_cycle(
    conn: AsyncConnection,
    *,
    student_id: str,
    session_id: UUID,
    cycle_id: UUID,
    offer_id: UUID,
) -> CycleSnapshot:
    """Insert the child cycle row for an accepted practice offer.

    Phase 5 (§7.8): the child cycle reuses the parent's learning session
    (``learning_sessions`` is unique per owner+client session, so the child
    row shares the parent's session_id — it cannot create a second row).
    ``problem_id`` stays NULL and ``practice_offer_id`` is set: the
    ``ck_cycle_source_xor`` invariant (a cycle is problem-bound XOR
    practice-bound) is preserved, and the problem binding lives in the
    offer → release exact snapshot (resolved by load_verified).
    """
    await conn.execute(
        tutoring_cycles.insert().values(
            cycle_id=str(cycle_id),
            session_id=str(session_id),
            student_id=student_id,
            state="problem_received",
            state_version=0,
            problem_id=None,
            practice_offer_id=str(offer_id),
            created_at=_now(),
            closed_at=None,
        )
    )
    return CycleSnapshot(
        cycle_id=cycle_id,
        session_id=session_id,
        client_session_id="",
        state="problem_received",
        state_version=0,
        problem_id=None,
        practice_offer_id=offer_id,
    )


async def load_cycle_by_offer(
    conn: AsyncConnection, *, student_id: str, offer_id: UUID
) -> CycleSnapshot | None:
    """Owner-scoped: the child cycle created by accepting ``offer_id``."""
    row = (
        await conn.execute(
            select(tutoring_cycles)
            .where(tutoring_cycles.c.practice_offer_id == str(offer_id))
            .where(tutoring_cycles.c.student_id == student_id)
            .order_by(tutoring_cycles.c.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return CycleSnapshot(
        cycle_id=UUID(row.cycle_id),
        session_id=UUID(row.session_id),
        client_session_id="",
        state=row.state,
        state_version=row.state_version,
        problem_id=UUID(row.problem_id) if row.problem_id else None,
        practice_offer_id=UUID(row.practice_offer_id) if row.practice_offer_id else None,
    )


async def load_cycle(
    conn: AsyncConnection, *, student_id: str, client_session_id: str
) -> CycleSnapshot | None:
    """Owner-scoped load: the client session name is namespaced per student."""
    row = (
        await conn.execute(
            select(tutoring_cycles)
            .join(learning_sessions, learning_sessions.c.session_id == tutoring_cycles.c.session_id)
            .where(tutoring_cycles.c.student_id == student_id)
            .where(learning_sessions.c.client_session_id == client_session_id)
            .order_by(tutoring_cycles.c.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    return CycleSnapshot(
        cycle_id=UUID(row.cycle_id),
        session_id=UUID(row.session_id),
        client_session_id=client_session_id,
        state=row.state,
        state_version=row.state_version,
        problem_id=UUID(row.problem_id) if row.problem_id else None,
        practice_offer_id=UUID(row.practice_offer_id) if row.practice_offer_id else None,
    )


async def persist_transition(
    conn: AsyncConnection,
    *,
    student_id: str,
    cycle_id: UUID,
    transition: CycleTransition,
    problem_id: UUID | None = None,
) -> None:
    """CAS transition commit: version AND owner must both match.

    ``rowcount == 0`` → VersionConflictError (stale command, replay, or
    cross-owner attempt). The cycle UPDATE and the append-only transition
    INSERT commit atomically with the caller's transaction. ``problem_id``
    (when given) is bound to the cycle row in the same UPDATE.
    """
    values: dict = {
        "state": transition.to_state,
        "state_version": transition.new_version,
        "closed_at": _now() if transition.to_state == "closed" else None,
    }
    if problem_id is not None:
        values["problem_id"] = str(problem_id)
    result = await conn.execute(
        tutoring_cycles.update()
        .where(tutoring_cycles.c.cycle_id == str(cycle_id))
        .where(tutoring_cycles.c.student_id == student_id)
        .where(tutoring_cycles.c.state_version == transition.prior_version)
        .values(**values)
    )
    if result.rowcount != 1:
        raise VersionConflictError(transition.prior_version, transition.prior_version)

    await conn.execute(
        cycle_transitions.insert().values(
            transition_id=str(transition.transition_id),
            cycle_id=str(cycle_id),
            from_state=transition.from_state,
            to_state=transition.to_state,
            trigger_command=transition.trigger_command,
            chosen_action=(
                transition.chosen_action.model_dump(mode="json")
                if transition.chosen_action is not None
                else None
            ),
            prior_version=transition.prior_version,
            new_version=transition.new_version,
            causation_id=str(transition.causation_id) if transition.causation_id else None,
            correlation_id=str(transition.correlation_id) if transition.correlation_id else None,
            idempotency_key=transition.idempotency_key,
            occurred_at=transition.occurred_at.isoformat(),
        )
    )


async def bind_problem(
    conn: AsyncConnection, *, student_id: str, cycle_id: UUID, problem_id: UUID
) -> None:
    """Bind the verified problem to the cycle (before AWAITING_ATTEMPT).

    Owner-scoped like every other write; failure to match is a programming
    error or a cross-owner attempt, never a silent no-op.
    """
    result = await conn.execute(
        tutoring_cycles.update()
        .where(tutoring_cycles.c.cycle_id == str(cycle_id))
        .where(tutoring_cycles.c.student_id == student_id)
        .values(problem_id=str(problem_id))
    )
    if result.rowcount != 1:
        raise RuntimeError(
            f"bind_problem: cycle {cycle_id} not found for student {student_id}"
        )


async def list_cycles_for_student(
    conn: AsyncConnection, *, student_id: str
) -> list[tuple[str, CycleSnapshot]]:
    rows = (
        await conn.execute(
            select(tutoring_cycles, learning_sessions.c.client_session_id)
            .join(learning_sessions, learning_sessions.c.session_id == tutoring_cycles.c.session_id)
            .where(tutoring_cycles.c.student_id == student_id)
            .order_by(tutoring_cycles.c.created_at.desc())
        )
    ).all()
    return [
        (
            row.client_session_id,
            CycleSnapshot(
                cycle_id=UUID(row.cycle_id),
                session_id=UUID(row.session_id),
                client_session_id=row.client_session_id,
                state=row.state,
                state_version=row.state_version,
                problem_id=UUID(row.problem_id) if row.problem_id else None,
                practice_offer_id=UUID(row.practice_offer_id) if row.practice_offer_id else None,
            ),
        )
        for row in rows
    ]


__all__ = [
    "CycleSnapshot",
    "bind_problem",
    "create_cycle",
    "create_practice_child_cycle",
    "ensure_student",
    "list_cycles_for_student",
    "load_cycle",
    "load_cycle_by_offer",
    "persist_transition",
]
