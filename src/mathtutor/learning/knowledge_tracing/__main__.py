"""Explicit offline CLI: python -m mathtutor.learning.knowledge_tracing.

Requires --output outside the repository. --synthetic only verifies the
engineering pipeline; it can never open the product policy serving gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .events import LearningEvent


def read_database_events(path):
    """Explicit offline read-only source; never migrates a user's database."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise ValueError("学习事件数据库不存在")
    try:
        from mathtutor.infrastructure import db_crypto
        with db_crypto.connect(path, key=db_crypto.db_key(path), readonly=True) as connection:
            rows = connection.execute("SELECT student_id,event_seq,payload FROM learning_events ORDER BY student_id,event_seq").fetchall()
        result = []
        for student_id, seq, payload in rows:
            event = LearningEvent.model_validate_json(payload)
            if event.student_id != student_id or event.event_seq != seq:
                raise ValueError("学习事件身份或顺序与数据库记录不一致")
            result.append(event)
        return result
    except (sqlite3.Error, ValueError, TypeError):
        # Validation exceptions can include full input values. Do not echo
        # student-owned payloads or accidental credentials into CLI logs.
        raise ValueError("无法读取有效的 learning_event_v2；请先检查迁移与事件完整性") from None


def synthetic_events(*, students=18, events_per_student=24, seed=17):
    import numpy as np
    rng = np.random.default_rng(seed)
    result = []
    origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for student in range(students):
        ability = .25 if student % 2 else .8
        for seq in range(1, events_per_student + 1):
            identity = f"synthetic-{student}-{seq}"
            correct = "correct" if rng.random() < ability else "incorrect"
            result.append(LearningEvent(event_id=identity, student_id=f"synthetic-{student}",
                session_id=f"session-{student}", cycle_id=identity, event_seq=seq,
                event_type="attempt_assessed", occurred_at=(origin + timedelta(days=seq, seconds=student)).isoformat(),
                problem_id=identity, problem_revision=identity, item_family_id=f"template-{seq % 9}",
                leakage_group_id=identity,
                skill_ids=("equality_preservation" if seq % 2 else "linear_isolation",),
                assessment_id=f"assessment-{identity}", attempt_id=identity,
                correctness=correct, evidence_kind="independent", task_purpose="practice"))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Train/evaluate a shadow-only LSTM DKT from structured learning facts")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="JSONL LearningEvent v2 export; no raw chat text")
    source.add_argument("--database", type=Path, help="Read only the learning_events table from an explicitly selected SQLite database")
    source.add_argument("--synthetic", action="store_true", help="Pipeline test only, not learning-effect evidence")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--seeds", default="17,29,43")
    parser.add_argument("--splits", default="student,time,family")
    args = parser.parse_args(argv)
    output = args.output.expanduser().resolve()
    # Model artifacts and reports can contain student-derived state. Prevent
    # accidental source-tree training output even when gitignore exists.
    repo_root = next((p for p in Path(__file__).resolve().parents if (p / ".git").exists()), None)
    if repo_root and output.is_relative_to(repo_root):
        parser.error("model output must be outside the repository (temporary or application user data directory)")
    try:
        events = synthetic_events() if args.synthetic else read_database_events(args.database) if args.database else [
            LearningEvent.model_validate_json(line) for line in args.input.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError, TypeError):
        parser.error("输入不是可用的 learning_event_v2 事件数据；原始内容未写入日志")
    output.mkdir(parents=True, exist_ok=True)
    from .training import train_pipeline
    reports = []
    data_version = hashlib.sha256("\n".join(e.model_dump_json() for e in events).encode()).hexdigest()
    for mode in args.splits.split(","):
        for seed in map(int, args.seeds.split(",")):
            artifact, report = train_pipeline(events, seed=seed, epochs=args.epochs, split_mode=mode, synthetic=args.synthetic)
            report["data_version"] = data_version
            artifact["data_version"] = data_version
            filename = f"lstm-{mode}-seed-{seed}.json"
            (output / filename).write_text(json.dumps(artifact, ensure_ascii=False), encoding="utf-8")
            reports.append({"artifact": filename, **report})
    summary = {"runs": reports, "policy_mode": "shadow", "real_student_effect_verified": False,
               "dataset_kind": "synthetic_pipeline_only" if args.synthetic else "provided_learning_events"}
    (output / "evaluation-report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"runs": len(reports), "report": str(output / "evaluation-report.json"),
                      "policy_mode": "shadow", "real_student_effect_verified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
