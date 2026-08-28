#!/usr/bin/env python3
"""Evaluation-only full-cosine vs sqlite-vec benchmark.

This script does not configure MathTutor, download a model, or change the
production retrieval path. It compares the two post-metadata-filter search
kernels over deterministic, synthetic, L2-normalized vectors:

* the current Python cosine_similarity full scan;
* the existing optional SqliteVecVectorIndex adapter, when an explicit
  extension artifact is already present.

Each size/dimension case runs in a fresh child process so max RSS is
case-local. JSON is written to stdout for reproducible capture.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import heapq
import json
import math
import os
import platform
from pathlib import Path
import random
import resource
import sqlite3
import statistics
import subprocess
import sys
import time
from typing import Sequence

from mathtutor.infrastructure.sqlite_vec_index import (
    SqliteVecVectorIndex,
)
from mathtutor.repositories.document_repository import cosine_similarity

DEFAULT_EXTENSION = Path("/tmp/sqlite_vec_probe/extracted/sqlite_vec/vec0.dylib")


def _percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _summary(values: Sequence[float]) -> dict[str, float | int]:
    return {
        "n": len(values),
        "p50_ms": round(statistics.median(values), 6),
        "p95_ms": round(_percentile(values, 0.95), 6),
        "min_ms": round(min(values), 6),
        "max_ms": round(max(values), 6),
    }


def _max_rss_bytes() -> int:
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports bytes; Linux reports KiB.
    return int(value if sys.platform == "darwin" else value * 1024)


def _vector(seed: int, dimension: int) -> tuple[float, ...]:
    generator = random.Random(seed)
    values = [generator.uniform(-1.0, 1.0) for _ in range(dimension)]
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return tuple(value / norm for value in values)


def _full_scan(
    entries: Sequence[tuple[str, tuple[float, ...]]],
    query: tuple[float, ...],
    k: int,
) -> list[tuple[str, float]]:
    return heapq.nlargest(
        k,
        (
            (entry_id, cosine_similarity(query, vector))
            for entry_id, vector in entries
        ),
        key=lambda row: row[1],
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


async def _worker(
    *,
    size: int,
    dimension: int,
    queries: int,
    k: int,
    extension_path: Path,
) -> dict:
    generated_started = time.perf_counter_ns()
    entries = [
        (f"item-{index}", _vector(index + 1, dimension))
        for index in range(size)
    ]
    query_vectors = [
        _vector(10_000_000 + index, dimension) for index in range(queries)
    ]
    generation_ms = (time.perf_counter_ns() - generated_started) / 1_000_000
    rss_after_vectors = _max_rss_bytes()

    build_started = time.perf_counter_ns()
    full_entries = tuple(entries)
    full_build_ms = (time.perf_counter_ns() - build_started) / 1_000_000
    full_times: list[float] = []
    full_rankings: list[list[str]] = []
    for query in query_vectors:
        started = time.perf_counter_ns()
        hits = _full_scan(full_entries, query, k)
        full_times.append((time.perf_counter_ns() - started) / 1_000_000)
        full_rankings.append([entry_id for entry_id, _ in hits])

    result: dict = {
        "size": size,
        "dimension": dimension,
        "queries": queries,
        "k": k,
        "vector_generation_ms": round(generation_ms, 6),
        "rss_after_vectors_bytes": rss_after_vectors,
        "full_local_cosine": {
            "build_ms": round(full_build_ms, 6),
            "query": _summary(full_times),
        },
        "sqlite_vec": {"status": "NOT_TESTED"},
    }

    if extension_path.is_file():
        load_started = time.perf_counter_ns()
        index = SqliteVecVectorIndex(str(extension_path), dimension=dimension)
        load_ms = (time.perf_counter_ns() - load_started) / 1_000_000
        build_started = time.perf_counter_ns()
        await index.build(entries)
        sqlite_build_ms = (time.perf_counter_ns() - build_started) / 1_000_000
        sqlite_times: list[float] = []
        rankings_match = True
        for query_index, query in enumerate(query_vectors):
            started = time.perf_counter_ns()
            hits = await index.search(query, k)
            sqlite_times.append((time.perf_counter_ns() - started) / 1_000_000)
            rankings_match &= [hit.id for hit in hits] == full_rankings[query_index]
        result["sqlite_vec"] = {
            "status": "MEASURED",
            "extension_version": index.extension_version(),
            "load_ms": round(load_ms, 6),
            "build_ms": round(sqlite_build_ms, 6),
            "query": _summary(sqlite_times),
            "top_k_matches_full_scan": rankings_match,
        }
        index.close()

    result["max_rss_bytes"] = _max_rss_bytes()
    return result


def _run_worker(args: argparse.Namespace) -> None:
    result = asyncio.run(
        _worker(
            size=args.worker_size,
            dimension=args.worker_dimension,
            queries=args.queries,
            k=args.k,
            extension_path=args.extension_path,
        )
    )
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))


def _run_parent(args: argparse.Namespace) -> None:
    cases: list[dict] = []
    script = Path(__file__).resolve()
    for size in args.sizes:
        for dimension in args.dimensions:
            command = [
                sys.executable,
                str(script),
                "--worker-size",
                str(size),
                "--worker-dimension",
                str(dimension),
                "--queries",
                str(args.queries),
                "--k",
                str(args.k),
                "--extension-path",
                str(args.extension_path),
            ]
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                cwd=Path.cwd(),
                env=os.environ.copy(),
            )
            cases.append(json.loads(completed.stdout))

    extension: dict[str, object]
    if args.extension_path.is_file():
        extension = {
            "status": "PRESENT_EXISTING_ARTIFACT",
            "path": str(args.extension_path),
            "bytes": args.extension_path.stat().st_size,
            "sha256": _sha256(args.extension_path),
        }
    else:
        extension = {
            "status": "NOT_TESTED",
            "reason": "explicit sqlite-vec extension path is absent",
        }
    output = {
        "kind": "math_tutor_vector_index_decision_evidence",
        "scope": "EVALUATION_ONLY_NOT_DEFAULT_NOT_PRODUCTION_NOT_BUNDLED",
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "sqlite": sqlite3.sqlite_version,
        },
        "method": {
            "vectors": "deterministic synthetic L2-normalized; no embedding model",
            "comparison": "post-metadata-filter in-memory full cosine vs optional sqlite-vec adapter",
            "sizes": args.sizes,
            "dimensions": args.dimensions,
            "queries_per_case": args.queries,
            "k": args.k,
        },
        "extension": extension,
        "cases": cases,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sizes", type=int, nargs="+", default=[100, 1000, 5000])
    parser.add_argument("--dimensions", type=int, nargs="+", default=[64, 384, 768])
    parser.add_argument("--queries", type=int, default=10)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--extension-path", type=Path, default=DEFAULT_EXTENSION)
    parser.add_argument("--worker-size", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--worker-dimension", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.queries < 1 or args.k < 1:
        parser.error("--queries and --k must be positive")
    if any(value < 1 for value in (*args.sizes, *args.dimensions)):
        parser.error("sizes and dimensions must be positive")
    if (args.worker_size is None) != (args.worker_dimension is None):
        parser.error("worker arguments must be provided together")
    if args.worker_size is not None:
        _run_worker(args)
    else:
        _run_parent(args)


if __name__ == "__main__":
    main()
