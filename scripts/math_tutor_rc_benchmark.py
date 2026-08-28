#!/usr/bin/env python3
"""Lightweight, repeatable MathTutor RC latency baseline.

This is a characterization run, not an SLO gate.  It writes the exact same
measurements as JSON and Markdown so thresholds can be frozen only after a
real baseline exists.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
import platform
from pathlib import Path
import sqlite3
import tempfile
import time
from typing import Awaitable, Callable
from uuid import uuid4

import sqlalchemy as sa

from mathtutor.application.adaptive_practice import CandidateExercise
from mathtutor.application.lexical_reranker import LexicalScoreReranker
from mathtutor.application.practice_release import ExerciseReleaseService
from mathtutor.application.retrieval_router import MetadataFirstRetriever
from mathtutor.domain.problem import MathProblem
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime
from mathtutor.infrastructure.verifier_worker import VerifierWorkerManager
from mathtutor.learning.attempt_parser import parse_student_attempt
from mathtutor.solving import parse_problem, solve_problem
from mathtutor.tests.benchmark_fixtures import (
    BENCHMARK_QUERIES,
    OWNER_A,
    build_corpus,
)


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _summary(values: list[float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "p50_ms": round(_percentile(values, 0.50), 6),
        "p95_ms": round(_percentile(values, 0.95), 6),
        "min_ms": round(min(values), 6),
        "max_ms": round(max(values), 6),
    }


def _measure_sync(fn: Callable[[], object], iterations: int) -> dict[str, float | int]:
    values: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        fn()
        values.append((time.perf_counter_ns() - started) / 1_000_000)
    return _summary(values)


async def _measure_async(
    fn: Callable[[], Awaitable[object]], iterations: int
) -> dict[str, float | int]:
    values: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        await fn()
        values.append((time.perf_counter_ns() - started) / 1_000_000)
    return _summary(values)


async def run(iterations: int, desktop_ms: list[float]) -> dict:
    parsed_outcome = parse_problem("x^2 - 5x + 6 = 0")
    assert parsed_outcome.kind == "parsed" and parsed_outcome.problem is not None
    parsed = parsed_outcome.problem
    problem = MathProblem.canonicalize(
        parsed.problem_type, parsed.normalized_ast, parsed.display_latex
    )

    parser = _measure_sync(lambda: parse_problem("x^2 - 5x + 6 = 0"), iterations)
    solver = _measure_sync(lambda: solve_problem(problem, parsed), iterations)
    solved = solve_problem(problem, parsed)
    assert solved.candidate is not None
    candidate = solved.candidate

    worker = VerifierWorkerManager()
    started = time.perf_counter_ns()
    await worker.start()
    worker_startup = _summary([(time.perf_counter_ns() - started) / 1_000_000])
    worker_verify = await _measure_async(
        lambda: worker.verify(problem, candidate), iterations
    )
    restart_values: list[float] = []
    for _ in range(min(5, iterations)):
        started = time.perf_counter_ns()
        await worker.restart()
        restart_values.append((time.perf_counter_ns() - started) / 1_000_000)
    worker_restart = _summary(restart_values)

    attempt_counter = 0

    async def attempt_roundtrip() -> object:
        nonlocal attempt_counter
        attempt_counter += 1
        attempt = parse_student_attempt(
            attempt_submission_id=uuid4(),
            student_id=uuid4(),
            cycle_id=uuid4(),
            raw_text="x=2 或 x=3",
            attempt_index=attempt_counter,
        )
        return await worker.verify_attempt(attempt, problem, candidate)

    attempt = await _measure_async(attempt_roundtrip, iterations)

    corpus = build_corpus()
    query = BENCHMARK_QUERIES[0]
    retriever = MetadataFirstRetriever(EmbeddingRuntime(), LexicalScoreReranker())

    async def retrieve() -> object:
        return await retriever.retrieve(
            query.query,
            corpus,
            owner_scope=OWNER_A,
            stage=query.stage,
            grade=query.grade,
            skill_codes=query.skill_codes,
            concept_codes=query.concept_codes,
            mapping_ids=query.mapping_ids,
            limit=5,
        )

    retrieval = await _measure_async(retrieve, iterations)

    with tempfile.TemporaryDirectory(prefix="mt-rc-bench-") as tmp:
        engine = create_db_engine(Path(tmp) / "benchmark.db")
        async with engine.begin() as conn:
            await conn.execute(sa.text("CREATE TABLE rc_short_commit (id INTEGER PRIMARY KEY, value TEXT)"))
        sequence = 0

        async def short_commit() -> object:
            nonlocal sequence
            sequence += 1
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text("INSERT INTO rc_short_commit(id, value) VALUES (:id, :value)"),
                    {"id": sequence, "value": "rc"},
                )
            return sequence

        sqlite_commit = await _measure_async(short_commit, iterations)
        await engine.dispose()

    release_service = ExerciseReleaseService(verification_backend=worker)
    release_candidate = CandidateExercise(
        student_id=uuid4(),
        problem_statement="2x + 3 = 7",
        skill_ids=("linear_equation.solve",),
        concept_ids=("linear_equations",),
        difficulty=2,
        generated_by="rc-benchmark",
    )
    practice_release = await _measure_async(
        lambda: release_service.release_candidate(release_candidate), iterations
    )
    await worker.shutdown()

    if desktop_ms:
        desktop_cold_startup: dict[str, object] = _summary(desktop_ms)
    else:
        desktop_cold_startup = {
            "status": "NOT_MEASURED",
            "reason": "Pass --desktop-cold-startup-ms from packaged smoke evidence.",
        }

    return {
        "kind": "math_tutor_rc_performance_baseline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "threshold_status": "CHARACTERIZATION_ONLY_NOT_FROZEN",
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
        },
        "measurements": {
            "parser": parser,
            "solver": solver,
            "worker_verifier": worker_verify,
            "worker_startup": worker_startup,
            "worker_restart": worker_restart,
            "attempt_roundtrip": attempt,
            "retrieval": retrieval,
            "sqlite_short_commit": sqlite_commit,
            "practice_release": practice_release,
            "desktop_cold_startup": desktop_cold_startup,
        },
    }


def _markdown(result: dict) -> str:
    env = result["environment"]
    lines = [
        "# MathTutor RC Performance Baseline",
        "",
        f"- Generated: {result['generated_at']}",
        f"- Environment: {env['platform']} / {env['machine']} / Python {env['python']} / SQLite {env['sqlite']}",
        "- Thresholds: characterization only; no SLO is frozen by this run.",
        "",
        "| Measurement | n | p50 ms | p95 ms | Status |",
        "|---|---:|---:|---:|---|",
    ]
    for name, value in result["measurements"].items():
        if "p50_ms" in value:
            lines.append(
                f"| {name} | {value['n']} | {value['p50_ms']} | {value['p95_ms']} | MEASURED |"
            )
        else:
            lines.append(
                f"| {name} | — | — | — | {value.get('status', 'NOT_MEASURED')} |"
            )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument(
        "--desktop-cold-startup-ms", type=float, action="append", default=[]
    )
    parser.add_argument("--output-dir", type=Path, default=Path("docs/rc"))
    args = parser.parse_args()
    if args.iterations < 5:
        parser.error("--iterations must be >= 5")
    result = asyncio.run(run(args.iterations, args.desktop_cold_startup_ms))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "RC_PERFORMANCE_BASELINE.json"
    md_path = args.output_dir / "RC_PERFORMANCE_BASELINE.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_markdown(result), encoding="utf-8")
    print(json_path)
    print(md_path)


if __name__ == "__main__":
    main()
