"""Persist policy identity without inventing it for historical attestations."""

import sqlite3
from contextlib import closing

import pytest

from mathtutor.application.math_tutor_service import MathTutorApplicationService
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.migrate import upgrade_db
from mathtutor.repositories.sqlite_math_facts import load_verified_for_problem


@pytest.mark.asyncio
@pytest.mark.parametrize("historical", [False, True])
async def test_attestation_lookup_and_restart_preserve_policy_or_explicit_unknown(
    tmp_path, historical
):
    path = tmp_path / "facts.db"
    upgrade_db(str(path))
    engine = create_db_engine(path)
    try:
        result = await MathTutorApplicationService(engine=engine).submit_problem(
            "2x + 3 = 7"
        )
        reference = result.verified_ref
        assert (
            reference is not None and reference.policy_id and reference.policy_version
        )
    finally:
        await engine.dispose()

    if historical:
        # Reproduce the real 025 layout: fresh migrations use today's metadata.
        with closing(sqlite3.connect(path)) as conn:
            conn.execute("ALTER TABLE verification_logs DROP COLUMN policy_id")
            conn.execute("ALTER TABLE verification_logs DROP COLUMN policy_version")
            conn.execute("UPDATE alembic_version SET version_num='025'")
            conn.commit()
        upgrade_db(str(path))

    engine = create_db_engine(path)
    try:
        service = MathTutorApplicationService(engine=engine)
        by_id = await service.solutions.get_attestation(reference.verification_log_id)
        by_problem = await service.solutions.get_attestation_for_problem(
            reference.problem_id
        )
        async with engine.connect() as conn:
            restored = await load_verified_for_problem(conn, reference.problem_id)
        expected = (
            reference.model_copy(update={"policy_id": "", "policy_version": ""})
            if historical
            else reference
        )
        assert by_id == by_problem == restored[2] == expected
        assert restored[0] == result.problem
        assert restored[1].payload_hash == result.candidate.payload_hash
    finally:
        await engine.dispose()
