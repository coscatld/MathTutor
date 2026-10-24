"""SQLite practice catalog (Phase 5): exercises, releases, offers.

Same contract as ``practice_repository.py`` with durability + CAS:

- ``save_release_bundle`` issues the attestation AND the exercise AND the
  release in ONE short transaction (release gate §7.3): upsert problem →
  conn-scoped ``issue_solution_attestation`` → insert exercise (unique by
  content hash) → insert release (exact-snapshot binding) → supersede older
  released releases of the same exercise → REVOKE their ACTIVE offers →
  outbox. Any failure rolls EVERYTHING back — no release without a
  VERIFIED attestation, ever.
- ``accept_offer_cas`` is the CAS inside the session store's accept
  transaction (§7.10): ACTIVE → ACCEPTED only for the owner, only while
  ACTIVE, only before expiry.
- Releases are append-only by convention: only ``status`` flips
  (released → superseded/revoked) ever UPDATE an existing release row.

All reads/writes run inside the caller's UoW transaction (short scope).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncConnection

from mathtutor.domain.practice import Exercise, ExerciseRelease
from mathtutor.domain.practice_recommendation import PracticeRecommendation
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    VerificationDecision,
    VerifiedSolutionRef,
)
from mathtutor.domain.tutoring import PracticeOffer
from mathtutor.infrastructure.schema import (
    exercise_releases,
    exercises,
    practice_offers,
    practice_recommendations,
    math_problems,
    tutoring_cycles,
    learning_events,
)
from mathtutor.repositories.sqlite_math_facts import (
    issue_solution_attestation,
    load_candidate,
    load_problem,
    upsert_math_problem,
)
from mathtutor.repositories.uow import append_outbox_events
from mathtutor.repositories.practice_repository import (
    validate_release_binding,
    SEEN_PROBLEM_EVENT_TYPES,
)
from mathtutor.security.scopes import student_uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def load_seen_problem_revisions(conn: AsyncConnection, student_id: str) -> frozenset[str]:
    """Complete retained owner facts, without raw text, limits or label filtering.

    Learning-result deletion removes its events; explicitly retained cycle/offer
    skeletons still prove prior exposure. Global verified catalog rows alone do not.
    """
    offered = select(exercise_releases.c.problem_hash).select_from(practice_offers.join(
        exercise_releases, practice_offers.c.exercise_release_id == exercise_releases.c.release_id
    )).where(practice_offers.c.student_id == str(student_uuid(student_id)))
    bound = select(math_problems.c.content_hash).select_from(tutoring_cycles.join(
        math_problems, tutoring_cycles.c.problem_id == math_problems.c.problem_id
    )).where(tutoring_cycles.c.student_id == str(student_id))
    events = select(learning_events.c.payload["problem_revision"].as_string()).where(
        learning_events.c.student_id == str(student_id),
        learning_events.c.event_type.in_(SEEN_PROBLEM_EVENT_TYPES))
    revisions = (await conn.execute(union(offered, bound, events))).scalars().all()
    return frozenset(value for value in revisions if isinstance(value, str) and value)


# ------------------------------------------------------------------ mappers


def _exercise_from_row(row: Any) -> Exercise:
    return Exercise(
        exercise_id=UUID(row.exercise_id),
        problem_id=UUID(row.problem_id),
        problem_grounding_id=UUID(row.problem_grounding_id),
        display_latex=row.display_latex,
        difficulty=row.difficulty,
        target_mapping_ids=tuple(UUID(v) for v in (row.target_mapping_ids or [])),
        license_ref=row.license_ref,
        source_type=row.source_type,
        content_hash=row.content_hash,
        problem_statement=row.problem_statement,
        created_at=datetime.fromisoformat(row.created_at),
    )


def _release_from_row(row: Any) -> ExerciseRelease:
    return ExerciseRelease(
        release_id=UUID(row.release_id),
        exercise_id=UUID(row.exercise_id),
        problem_hash=row.problem_hash,
        solution_hash=row.solution_hash,
        verification_policy_hash=row.verification_policy_hash,
        verifier_hash=row.verifier_hash,
        solution_candidate_hash=row.solution_candidate_hash,
        license_hash=row.license_hash,
        provenance_hash=row.provenance_hash,
        status=row.status,
        released_at=(
            datetime.fromisoformat(row.released_at) if row.released_at else None
        ),
        solution_candidate_id=(
            UUID(row.solution_candidate_id) if row.solution_candidate_id else None
        ),
        verification_log_id=(
            UUID(row.verification_log_id) if row.verification_log_id else None
        ),
    )


def _offer_from_row(row: Any) -> PracticeOffer:
    return PracticeOffer(
        offer_id=UUID(row.offer_id),
        student_id=UUID(row.student_id),
        parent_cycle_id=UUID(row.parent_cycle_id),
        exercise_release_id=UUID(row.exercise_release_id),
        target_mapping_ids=tuple(UUID(v) for v in (row.target_mapping_ids or [])),
        stage_policy_version=row.stage_policy_version,
        status=row.status,
        offered_at=datetime.fromisoformat(row.offered_at),
        expires_at=datetime.fromisoformat(row.expires_at),
        consumed_at=(
            datetime.fromisoformat(row.consumed_at) if row.consumed_at else None
        ),
    )


# -------------------------------------------------- conn-scoped loaders


async def load_exercise_by_content_hash(
    conn: AsyncConnection, content_hash: str
) -> Exercise | None:
    row = (
        await conn.execute(
            select(exercises).where(exercises.c.content_hash == content_hash)
        )
    ).first()
    return _exercise_from_row(row) if row is not None else None


async def load_exercise_row(conn: AsyncConnection, exercise_id: UUID) -> Exercise | None:
    row = (
        await conn.execute(
            select(exercises).where(exercises.c.exercise_id == str(exercise_id))
        )
    ).first()
    return _exercise_from_row(row) if row is not None else None


async def load_release_row(conn: AsyncConnection, release_id: UUID) -> ExerciseRelease | None:
    row = (
        await conn.execute(
            select(exercise_releases).where(
                exercise_releases.c.release_id == str(release_id)
            )
        )
    ).first()
    return _release_from_row(row) if row is not None else None


async def load_latest_released_for_exercise(
    conn: AsyncConnection, exercise_id: UUID
) -> ExerciseRelease | None:
    row = (
        await conn.execute(
            select(exercise_releases)
            .where(exercise_releases.c.exercise_id == str(exercise_id))
            .where(exercise_releases.c.status.in_(("released", "superseded", "revoked")))
            .order_by(exercise_releases.c.released_at.desc(), exercise_releases.c.release_id.desc())
            .limit(1)
        )
    ).first()
    return _release_from_row(row) if row is not None else None


async def load_offer_row(conn: AsyncConnection, offer_id: UUID) -> PracticeOffer | None:
    row = (
        await conn.execute(
            select(practice_offers).where(practice_offers.c.offer_id == str(offer_id))
        )
    ).first()
    return _offer_from_row(row) if row is not None else None


async def load_offers_for_student(
    conn: AsyncConnection, student_id: str
) -> list[PracticeOffer]:
    rows = (
        await conn.execute(
            select(practice_offers)
            .where(practice_offers.c.student_id == student_id)
            .order_by(practice_offers.c.offered_at.desc())
        )
    ).all()
    return [_offer_from_row(row) for row in rows]


async def load_offers_with_exercises(
    conn: AsyncConnection, student_id: str
) -> list[tuple[PracticeOffer, Exercise | None]]:
    """Offers + their exercise (for difficulty/skill labels projection)."""
    rows = (
        await conn.execute(
            select(practice_offers, exercises)
            .join(exercise_releases, exercise_releases.c.release_id == practice_offers.c.exercise_release_id)
            .join(exercises, exercises.c.exercise_id == exercise_releases.c.exercise_id)
            .where(practice_offers.c.student_id == student_id)
            .order_by(practice_offers.c.offered_at.desc())
        )
    ).all()
    return [(_offer_from_row(row), _exercise_from_row(row)) for row in rows]


async def load_exact_verified_by_release(
    conn: AsyncConnection, release_id: UUID
) -> tuple[Any, MathSolutionCandidate, VerifiedSolutionRef] | None:
    """Exact-snapshot chain for a release (problem/candidate/ref bound to the
    release's OWN solution_candidate_id + verification_log_id — never
    "the newest attestation of the problem")."""
    from mathtutor.infrastructure.schema import (
        math_problems,
        solution_candidates,
        verification_logs,
    )

    release = await load_release_row(conn, release_id)
    if release is None or release.solution_candidate_id is None or release.verification_log_id is None:
        return None
    exercise = await load_exercise_row(conn, release.exercise_id)
    if exercise is None:
        return None
    problem = await load_problem(conn, exercise.problem_id)
    candidate = await load_candidate(conn, release.solution_candidate_id)
    row = (
        await conn.execute(
            select(
                verification_logs,
                math_problems.c.content_hash,
                solution_candidates.c.payload_hash,
            )
            .join(math_problems, math_problems.c.problem_id == verification_logs.c.problem_id)
            .join(solution_candidates, solution_candidates.c.candidate_id == verification_logs.c.candidate_id)
            .where(verification_logs.c.log_id == str(release.verification_log_id))
        )
    ).first()
    if problem is None or candidate is None or row is None:
        return None
    ref = VerifiedSolutionRef(
        verification_log_id=release.verification_log_id,
        problem_id=problem.problem_id,
        problem_content_hash=row.content_hash,
        solution_candidate_id=release.solution_candidate_id,
        solution_payload_hash=row.payload_hash,
        policy_id="",
        policy_version="",
        attestation_hash=row.attestation_hash,
    )
    from mathtutor.repositories.practice_repository import practice_problem_surface
    return practice_problem_surface(problem, exercise), candidate, ref


# -------------------------------------------------------------- writers

async def _insert_offer(conn: AsyncConnection, offer: PracticeOffer) -> None:
    await conn.execute(practice_offers.insert().values(
        offer_id=str(offer.offer_id), student_id=str(offer.student_id),
        parent_cycle_id=str(offer.parent_cycle_id), exercise_release_id=str(offer.exercise_release_id),
        target_mapping_ids=[str(v) for v in offer.target_mapping_ids],
        stage_policy_version=offer.stage_policy_version, status=offer.status,
        offered_at=offer.offered_at.isoformat(), expires_at=offer.expires_at.isoformat(), consumed_at=None,
    ))


async def accept_offer_cas(
    conn: AsyncConnection, *, student_id: str, offer_id: UUID
) -> bool:
    """Offer accept CAS (owner + ACTIVE + not expired) — the authoritative
    guard inside the session store's accept transaction (§7.7 step 2/5).

    Offer rows are owner-keyed by the session-domain UUID identity; convert
    raw ids at the SQL boundary (idempotent for already-UUID inputs).
    """
    student_id = str(student_uuid(student_id))
    result = await conn.execute(
        practice_offers.update()
        .where(practice_offers.c.offer_id == str(offer_id))
        .where(practice_offers.c.student_id == student_id)
        .where(practice_offers.c.status == "ACTIVE")
        .where(practice_offers.c.expires_at > _now())
        .values(status="ACCEPTED", consumed_at=_now())
    )
    return result.rowcount == 1


async def mark_offer_declined(
    conn: AsyncConnection, *, student_id: str, offer_id: UUID
) -> bool:
    student_id = str(student_uuid(student_id))
    result = await conn.execute(
        practice_offers.update()
        .where(practice_offers.c.offer_id == str(offer_id))
        .where(practice_offers.c.student_id == student_id)
        .where(practice_offers.c.status == "ACTIVE")
        .values(status="DECLINED")
    )
    return result.rowcount == 1


# ------------------------------------------------------------------ repo


class SQLitePracticeRepository:
    """Practice catalog over the product database (short UoW transactions)."""

    def __init__(self, uow: Any) -> None:
        self.uow = uow

    # ------------------------------------------------------- release gate

    async def resolve_problem(self, problem: Any) -> Any:
        """Use the same canonical identity as ordinary tutoring submissions.

        Only the unverified problem is reserved here. Candidate verification,
        attestation and publication still happen through the release gate.
        """
        async with self.uow.transaction() as conn:
            return await upsert_math_problem(conn, problem)

    async def save_release_bundle(
        self,
        *,
        problem: Any,
        candidate: MathSolutionCandidate,
        decision: VerificationDecision,
        exercise: Exercise,
        release: ExerciseRelease,
        outbox_events: list[dict[str, Any]] = (),
    ) -> tuple[VerifiedSolutionRef, ExerciseRelease]:
        """ONE short transaction: attestation + exercise + release + supersede
        + revoke + outbox (release gate §7.3/§7.10)."""
        async with self.uow.transaction() as conn:
            # 1. Re-validate every binding BEFORE any write (fail closed).
            validate_release_binding(problem, candidate, decision)
            # 2. Canonical problem (unique by content hash) + attestation.
            stored_problem = await upsert_math_problem(conn, problem)
            ref = await issue_solution_attestation(conn, stored_problem, candidate, decision)
            # 3. Exercise unique by content_hash (server-owned identity).
            existing = await load_exercise_by_content_hash(conn, exercise.content_hash)
            exercise_id = existing.exercise_id if existing is not None else exercise.exercise_id
            if existing is None:
                await conn.execute(
                    exercises.insert().values(
                        exercise_id=str(exercise.exercise_id),
                        problem_id=str(problem.problem_id),
                        problem_grounding_id=str(exercise.problem_grounding_id),
                        display_latex=exercise.display_latex,
                        difficulty=exercise.difficulty,
                        target_mapping_ids=[str(v) for v in exercise.target_mapping_ids],
                        license_ref=exercise.license_ref,
                        source_type=exercise.source_type,
                        content_hash=exercise.content_hash,
                        problem_statement=exercise.problem_statement,
                        created_at=_now(),
                    )
                )
            # 4. The release row binds the EXACT candidate + log id.
            released_at = _now()
            await conn.execute(
                exercise_releases.insert().values(
                    release_id=str(release.release_id),
                    exercise_id=str(exercise_id),
                    problem_hash=release.problem_hash,
                    solution_hash=release.solution_hash,
                    verification_policy_hash=release.verification_policy_hash,
                    verifier_hash=release.verifier_hash,
                    solution_candidate_hash=release.solution_candidate_hash,
                    license_hash=release.license_hash,
                    provenance_hash=release.provenance_hash,
                    solution_candidate_id=str(candidate.candidate_id),
                    verification_log_id=str(ref.verification_log_id),
                    status="released",
                    released_at=released_at,
                )
            )
            # 5. Any earlier RELEASED version of the same exercise is
            #    superseded; its ACTIVE offers are REVOKED (never leaked).
            superseded_rows = (
                await conn.execute(
                    select(exercise_releases.c.release_id)
                    .where(exercise_releases.c.exercise_id == str(exercise_id))
                    .where(exercise_releases.c.status == "released")
                    .where(exercise_releases.c.release_id != str(release.release_id))
                )
            ).all()
            superseded_ids = [row.release_id for row in superseded_rows]
            if superseded_ids:
                await conn.execute(
                    exercise_releases.update()
                    .where(exercise_releases.c.exercise_id == str(exercise_id))
                    .where(exercise_releases.c.status == "released")
                    .where(exercise_releases.c.release_id != str(release.release_id))
                    .values(status="superseded")
                )
                await conn.execute(
                    practice_offers.update()
                    .where(practice_offers.c.exercise_release_id.in_(superseded_ids))
                    .where(practice_offers.c.status == "ACTIVE")
                    .values(status="REVOKED")
                )
            # 6. Outbox in the SAME transaction.
            if outbox_events:
                await append_outbox_events(conn, list(outbox_events))

        final = release.model_copy(
            update={
                "exercise_id": exercise_id,
                "status": "released",
                "released_at": datetime.fromisoformat(released_at),
                "solution_candidate_id": candidate.candidate_id,
                "verification_log_id": ref.verification_log_id,
            }
        )
        return ref, final

    # ------------------------------------------------------------- offers

    async def recover_preparing_recommendations(self) -> int:
        """Startup-only recovery, before admitting requests; never call mid-generation."""
        async with self.uow.transaction() as conn:
            rows = (await conn.execute(select(practice_recommendations).where(
                practice_recommendations.c.status == "PREPARING"
            ))).all()
            for row in rows:
                record = PracticeRecommendation.model_validate(row.payload).model_copy(update={
                    "status": "FAILED", "failure_reason": "上次生成已中断，可重新请求练习",
                    "updated_at": datetime.now(timezone.utc),
                })
                await conn.execute(practice_recommendations.update().where(
                    practice_recommendations.c.recommendation_id == row.recommendation_id,
                    practice_recommendations.c.status == "PREPARING",
                ).values(status="FAILED", payload=record.model_dump(mode="json"), updated_at=_now()))
            return len(rows)

    async def recommendations_for_student(self, student_id: str, parent_cycle_id: UUID | None = None) -> list[PracticeRecommendation]:
        query = select(practice_recommendations).where(practice_recommendations.c.student_id == str(student_uuid(student_id)))
        if parent_cycle_id is not None:
            query = query.where(practice_recommendations.c.parent_cycle_id == str(parent_cycle_id))
        async with self.uow.transaction() as conn:
            rows = (await conn.execute(query.order_by(practice_recommendations.c.created_at.desc()))).all()
            result = []
            for row in rows:
                record = PracticeRecommendation.model_validate(row.payload).model_copy(update={"status": row.status})
                if record.offer_id and record.status == "ACTIVE":
                    offer = await load_offer_row(conn, record.offer_id)
                    if offer:
                        status = "EXPIRED" if offer.status == "ACTIVE" and offer.expires_at <= datetime.now(timezone.utc) else offer.status
                        record = record.model_copy(update={"status": status})
                result.append(record)
            return result

    async def recommendation_for_offer(self, student_id: str, offer_id: UUID) -> PracticeRecommendation | None:
        return next((item for item in await self.recommendations_for_student(student_id) if item.offer_id == offer_id), None)

    async def begin_recommendation(self, recommendation: PracticeRecommendation) -> tuple[PracticeRecommendation, bool]:
        from sqlalchemy.dialects.sqlite import insert
        from mathtutor.repositories import sqlite_runtime as rt
        # Reconcile expired/consumed offers before the unique active-purpose claim.
        records = await self.recommendations_for_student(str(recommendation.student_id), recommendation.parent_cycle_id)
        async with self.uow.transaction() as conn:
            await rt.ensure_student(conn, student_id=str(recommendation.student_id))
            for record in records:
                if record.status not in {"ACTIVE", "PREPARING"}:
                    await conn.execute(practice_recommendations.update().where(
                        practice_recommendations.c.recommendation_id == str(record.recommendation_id)
                    ).where(practice_recommendations.c.status == "ACTIVE").values(status=record.status))
            result = await conn.execute(insert(practice_recommendations).values(
                recommendation_id=str(recommendation.recommendation_id),
                student_id=str(recommendation.student_id), parent_cycle_id=str(recommendation.parent_cycle_id),
                purpose=recommendation.purpose, target_revision=recommendation.target_revision,
                status="PREPARING", offer_id=None,
                payload=recommendation.model_dump(mode="json"),
                created_at=recommendation.created_at.isoformat(), updated_at=recommendation.updated_at.isoformat(),
            ).on_conflict_do_nothing())
            if result.rowcount == 1:
                return recommendation, True
            row = (await conn.execute(select(practice_recommendations).where(
                practice_recommendations.c.student_id == str(recommendation.student_id),
                practice_recommendations.c.parent_cycle_id == str(recommendation.parent_cycle_id),
                practice_recommendations.c.purpose == recommendation.purpose,
                practice_recommendations.c.target_revision == recommendation.target_revision,
                practice_recommendations.c.status.in_(("PREPARING", "ACTIVE")),
            ))).one()
            return PracticeRecommendation.model_validate(row.payload).model_copy(update={"status": row.status}), False

    async def complete_recommendation(self, recommendation: PracticeRecommendation, offer: PracticeOffer,
        outbox_events: list[dict[str, Any]], *, unseen_for_student: str | None = None) -> None:
        # Offer + recommendation + outbox become visible atomically.
        async with self.uow.transaction() as conn:
            if recommendation.purpose in {"A1", "A2", "B"}:
                # Explicitly reserve the writer before reading current history;
                # this also covers SQLCipher's isolation_level=None connection.
                await conn.exec_driver_sql("BEGIN IMMEDIATE")
            row = (await conn.execute(select(practice_recommendations).where(
                practice_recommendations.c.recommendation_id == str(recommendation.recommendation_id),
                practice_recommendations.c.student_id == str(offer.student_id),
                practice_recommendations.c.parent_cycle_id == str(offer.parent_cycle_id),
                practice_recommendations.c.status == "PREPARING",
            ))).first()
            if row is None:
                raise ValueError("推荐状态已变化，不能发布邀请")
            if row.purpose in {"A1", "A2", "B"}:
                if unseen_for_student is None or student_uuid(unseen_for_student) != offer.student_id:
                    raise ValueError("新题检查缺少学生身份")
                release = await load_release_row(conn, offer.exercise_release_id)
                if release is None or release.problem_hash in await load_seen_problem_revisions(conn, unseen_for_student):
                    raise ValueError("这道题已出现过，请重新请求新题")
            await _insert_offer(conn, offer)
            result = await conn.execute(practice_recommendations.update().where(
                practice_recommendations.c.recommendation_id == str(recommendation.recommendation_id),
                practice_recommendations.c.status == "PREPARING",
            ).values(status="ACTIVE", offer_id=str(offer.offer_id), payload=recommendation.model_dump(mode="json"), updated_at=_now()))
            if result.rowcount != 1:
                raise ValueError("推荐已被另一请求完成")
            await append_outbox_events(conn, outbox_events)

    async def fail_recommendation(self, recommendation: PracticeRecommendation) -> None:
        async with self.uow.transaction() as conn:
            await conn.execute(practice_recommendations.update().where(
                practice_recommendations.c.recommendation_id == str(recommendation.recommendation_id),
                practice_recommendations.c.student_id == str(recommendation.student_id),
                practice_recommendations.c.status == "PREPARING",
            ).values(status="FAILED", payload=recommendation.model_dump(mode="json"), updated_at=_now()))

    async def create_offer(
        self, offer: PracticeOffer, outbox_events: list[dict[str, Any]] = ()
    ) -> None:
        from mathtutor.repositories import sqlite_runtime as rt

        async with self.uow.transaction() as conn:
            # Practice rows are owner-keyed by the session-domain identity
            # (student UUID, same key sessions objects carry); ensure the
            # FK-required profile row exists in this same transaction.
            await rt.ensure_student(conn, student_id=str(offer.student_id))
            await _insert_offer(conn, offer)
            if outbox_events:
                await append_outbox_events(conn, list(outbox_events))

    async def load_offer(self, offer_id: UUID) -> PracticeOffer | None:
        async with self.uow.transaction() as conn:
            return await load_offer_row(conn, offer_id)

    async def offers_for_student(self, student_id: str) -> list[PracticeOffer]:
        owner = str(student_uuid(student_id))
        async with self.uow.transaction() as conn:
            return await load_offers_for_student(conn, owner)

    async def seen_problem_revisions(self, student_id: str) -> frozenset[str]:
        async with self.uow.transaction() as conn:
            return await load_seen_problem_revisions(conn, student_id)

    async def offers_for_student_with_detail(
        self, student_id: str
    ) -> list[tuple[PracticeOffer, Exercise | None]]:
        owner = str(student_uuid(student_id))
        async with self.uow.transaction() as conn:
            return await load_offers_with_exercises(conn, owner)

    async def mark_offer_declined(self, student_id: str, offer_id: UUID) -> bool:
        async with self.uow.transaction() as conn:
            return await mark_offer_declined(
                conn, student_id=str(student_uuid(student_id)), offer_id=offer_id
            )

    async def accept_offer(self, student_id: str, offer_id: UUID) -> bool:
        """CAS-style offer acceptance (in-memory contract parity; the SQLite
        authoritative path is the session store's accept transaction)."""
        async with self.uow.transaction() as conn:
            return await accept_offer_cas(
                conn, student_id=str(student_uuid(student_id)), offer_id=offer_id
            )

    # -------------------------------------------------------------- reads

    async def load_release(self, release_id: UUID) -> ExerciseRelease | None:
        async with self.uow.transaction() as conn:
            return await load_release_row(conn, release_id)

    async def load_exercise(self, exercise_id: UUID) -> Exercise | None:
        async with self.uow.transaction() as conn:
            return await load_exercise_row(conn, exercise_id)

    async def find_exercise_by_content_hash(
        self, content_hash: str
    ) -> Exercise | None:
        async with self.uow.transaction() as conn:
            return await load_exercise_by_content_hash(conn, content_hash)

    async def latest_release_for_exercise(
        self, exercise_id: UUID
    ) -> ExerciseRelease | None:
        async with self.uow.transaction() as conn:
            return await load_latest_released_for_exercise(conn, exercise_id)

    async def load_exact_verified(
        self, release: ExerciseRelease
    ) -> tuple[Any, MathSolutionCandidate, VerifiedSolutionRef] | None:
        async with self.uow.transaction() as conn:
            return await load_exact_verified_by_release(conn, release.release_id)

    async def list_outbox(self) -> list[dict[str, Any]]:
        from mathtutor.infrastructure.schema import domain_outbox

        async with self.uow.transaction() as conn:
            rows = (
                await conn.execute(
                    select(domain_outbox).order_by(domain_outbox.c.created_at)
                )
            ).all()
        return [
            {
                "aggregate_type": row.aggregate_type,
                "aggregate_id": row.aggregate_id,
                "aggregate_version": row.aggregate_version,
                "event_sequence": row.event_sequence,
                "event_type": row.event_type,
                "audience": row.audience,
                "payload": row.payload,
            }
            for row in rows
        ]


__all__ = [
    "SQLitePracticeRepository",
    "accept_offer_cas",
    "load_exact_verified_by_release",
    "load_exercise_by_content_hash",
    "load_offers_for_student",
    "load_offers_with_exercises",
    "load_release_row",
]
