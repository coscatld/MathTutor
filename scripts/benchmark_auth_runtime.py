"""Measure synthetic bcrypt login and event-loop lag in an isolated account store.

PYTHONPATH=src python scripts/benchmark_auth_runtime.py --samples 30 --output report.json
Thresholds are declared before measurements. This is a local serial regression
probe, not a concurrent capacity or production throughput benchmark.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import tempfile
import time

import bcrypt

from mathtutor.security.auth import AuthSettings, LocalAuthProvider
from mathtutor.security.auth_runtime import AuthExecutor

THRESHOLDS_MS = {"event_loop_lag_p99": 100, "login_p95": 2000, "login_p99": 3000}


def percentile(values, percent):
    return sorted(values)[max(0, math.ceil(len(values) * percent / 100) - 1)] if values else None


async def measure(samples):
    timings, lags, failed = [], [], 0
    runtime = AuthExecutor()
    stopped = False

    async def heartbeat():
        while not stopped:
            expected = time.perf_counter() + .005
            await asyncio.sleep(.005)
            lags.append(max(0, time.perf_counter() - expected) * 1000)

    with tempfile.TemporaryDirectory(prefix="mathtutor-auth-benchmark-") as directory:
        account = LocalAuthProvider(AuthSettings(enabled=True, secret="synthetic-benchmark-only-" * 3), Path(directory))
        pulse = asyncio.create_task(heartbeat())
        try:
            owner = await runtime.run(account.register_first_user, "synthetic-user", "synthetic-password-only")
            cost = int(account._load_users()["synthetic-user"]["hash"].split("$")[2])
            await runtime.run(account.authenticate, "synthetic-user", "synthetic-password-only")  # warmup
            for _ in range(samples):
                start = time.perf_counter()
                try:
                    result = await runtime.run(account.authenticate, "synthetic-user", "synthetic-password-only")
                    failed += int(result != owner)
                except Exception:
                    failed += 1
                timings.append((time.perf_counter() - start) * 1000)
        finally:
            stopped = True
            await pulse
            await runtime.shutdown()
    metrics = {
        "event_loop_lag_p99": percentile(lags, 99),
        "login_p95": percentile(timings, 95), "login_p99": percentile(timings, 99),
    }
    return {"schema_version": 1, "status": "PASS" if failed == 0 and all(metrics[k] is not None and metrics[k] < limit for k, limit in THRESHOLDS_MS.items()) else "FAIL",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "scope": "Synthetic serial local logins with default bcrypt cost; no real credentials, model calls or user database.",
            "runtime": {"python": platform.python_version(), "os": platform.system(), "architecture": platform.machine(), "bcrypt": bcrypt.__version__},
            "samples": samples, "failed": failed, "failure_rate": failed / samples,
            "heartbeat_interval_ms": 5, "heartbeat_samples": len(lags), "percentile": "nearest_rank",
            "bcrypt_cost": cost, "worker_capacity": runtime.capacity, "thresholds_ms": THRESHOLDS_MS,
            "measurements_ms": metrics, "login_samples_ms": timings}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.samples <= 1000:
        parser.error("--samples must be between 1 and 1000")
    result = asyncio.run(measure(args.samples))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "samples", "failed", "measurements_ms")}, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
