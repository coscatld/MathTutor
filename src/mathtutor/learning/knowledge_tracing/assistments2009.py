"""Offline ASSISTments adapter/audit. No training or product-database writes.

This is a source observation format, deliberately separate from live verified
MathTutor events. A source problem log is not an invented sequence of actions.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .dataset import _partition

SOURCE_URL = "https://sites.google.com/site/assistmentsdata/home/2009-2010-assistment-data/skill-builder-data-2009-2010"
DICTIONARY_URL = "https://sites.google.com/site/assistmentsdata/an-explanation-on-how-to-interpret-our-data-sets"
DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id=1NNXHFRxcArrU0ZJSb9BIL56vmUt5FhlE"
SOURCE_SHA256 = "162ef8d2d28bcbfea6591a282994062bd8d5eaa00636544292a0d268dca6e5da"
ADAPTER_VERSION = "assist2009-corrected-v1"
# Topic correspondence only, not proof of target-domain task/skill equivalence.
# Do not infer a specific solution method from a systems/equation task label.
SKILL_MAP = {
    "277": ("signed_operations", "Addition and Subtraction Integers"),
    "279": ("signed_operations", "Multiplication and Division Integers"),
    "61": ("fraction_operations", "Division Fractions"),
    "67": ("fraction_operations", "Multiplication Fractions"),
    "280": ("fraction_operations", "Addition and Subtraction Fractions"),
    "340": ("distributive_law", "Distributive Property"),
    "311": ("linear_isolation", "Equation Solving Two or Fewer Steps"),
    "312": ("linear_isolation", "Equation Solving More Than Two Steps"),
    "356": ("quadratic_roots", "Quadratic Formula to Solve Quadratic Equation"),
    "350": ("system_completeness", "Solving Systems of Linear Equations"),
}
CHECKPOINTS = (0, 1, 3, 5, 10)


def number(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


@dataclass(frozen=True)
class SourceObservation:
    student_id: str
    order_id: int
    problem_id: str
    template_id: str
    source_skills: tuple[str, ...]
    mapped_skills: tuple[str, ...]
    original: bool
    first_action: int | None
    hint_count: int | None
    attempt_count: int | None
    source_correct: int | None
    label: int | None
    exclusion: str
    prior_problem_seen: bool = False

    def query(self):
        # No same-record answers, help, latency, or completion fields here.
        return {"problem_id": self.problem_id, "source_skills": self.source_skills,
                "mapped_skills": self.mapped_skills}


def adapt(rows):
    grouped = {}
    raw_count = 0
    for row in rows:
        raw_count += 1
        order = number(row.get("order_id"))
        student = row.get("user_id", "")
        if order is None or not student or not row.get("problem_id"):
            raise ValueError("missing original student/problem-log identity")
        key = (student, order)
        skills = {s for s in row.get("skill_id", "").split("_") if s and s != "NA"}
        if key in grouped:
            previous, combined = grouped[key]
            for field in ("problem_id", "template_id", "original", "correct", "first_action", "hint_count", "attempt_count", "answer_type"):
                if previous.get(field) != row.get(field):
                    raise ValueError(f"conflicting duplicate source field: {field}")
            combined.update(skills)
        else:
            grouped[key] = (row, skills)
        if len(skills) == 1:
            skill = next(iter(skills))
            if skill in SKILL_MAP and row.get("skill_name", "").strip() != SKILL_MAP[skill][1]:
                raise ValueError("source skill identity/name changed; review mapping")
    observations = []
    seen = set()
    for (student, order), (row, skills) in sorted(grouped.items()):
        original = row.get("original") == "1"
        action = number(row.get("first_action"))
        correct = number(row.get("correct"))
        hints = number(row.get("hint_count"))
        attempts = number(row.get("attempt_count"))
        problem = row["problem_id"]
        prior = (student, problem) in seen
        # Preserve exposure/first-position even when the verdict is unusable.
        seen.add((student, problem))
        exclusion = ""
        if not original:
            exclusion = "scaffold"
        elif prior:
            exclusion = "repeat_problem"
        elif row.get("answer_type") not in {"algebra", "choose_1", "fill_in_1", "choose_n"}:
            exclusion = "unverified_answer_type"
        elif action in {1, 2}:
            exclusion = "help_before_first_attempt"
        elif action != 0:
            exclusion = "first_action_unknown"
        elif correct not in {0, 1} or attempts is None or attempts < 1:
            exclusion = "unverified_first_answer"
        elif correct == 1 and hints and hints > 0:
            exclusion = "contradictory_correct_and_help"
        # action=attempt + correct=0 stays zero even if later hints were used.
        mapped = tuple(sorted({SKILL_MAP[s][0] for s in skills})) if skills and skills <= SKILL_MAP.keys() else ()
        observations.append(SourceObservation(student, order, problem,
            row.get("template_id") or "unknown", tuple(sorted(skills)), mapped,
            original, action, hints, attempts, correct,
            None if exclusion else correct, exclusion, prior))
    return observations, {"raw_rows": raw_count, "unique_problem_logs": len(observations),
                          "duplicate_or_skill_expansion_rows_removed": raw_count - len(observations)}


def temporal_views(history, checkpoints=CHECKPOINTS):
    """Exact k prior main-problem logs, including help/unknown/repeats.

    History includes intervening scaffolding; query is taken at presentation,
    with its label separate. Never jump to a later eligible query to fill k.
    """
    prior = []
    completed_main = 0
    for row in sorted(history, key=lambda x: x.order_id):
        if row.original:
            if completed_main in checkpoints:
                yield {"checkpoint": completed_main, "history": tuple(prior),
                       "history_cutoff_order_id": prior[-1].order_id if prior else None,
                       "query": row.query(), "query_order_id": row.order_id,
                       "label": row.label, "exclusion": row.exclusion}
            completed_main += 1
        prior.append(row)


def counts(rows):
    return {"students": len({r.student_id for r in rows}), "problem_logs": len(rows),
            "main_problem_logs": sum(r.original for r in rows),
            "legal_labels": sum(r.label is not None for r in rows),
            "skill_tagged_legal_labels": sum(r.label is not None and bool(r.source_skills) for r in rows),
            "mapped_legal_labels": sum(r.label is not None and bool(r.mapped_skills) for r in rows)}


def split_audit(rows, seed, mode):
    students = _partition([r.student_id for r in rows], seed)
    items = _partition([r.template_id if mode == "student_family" else r.problem_id for r in rows], seed + 1)
    result = {}
    retained = 0
    for fold, name in enumerate(("train", "validation", "test")):
        population = [r for r in rows if students[r.student_id] == fold]
        kept = population if mode == "student" else [r for r in population if items[r.template_id if mode == "student_family" else r.problem_id] == fold]
        retained += len(kept)
        # In double cold-start stress tests the entire history must obey the
        # content holdout, too; checkpoint counts refer to retained histories.
        histories = defaultdict(list)
        for row in kept:
            histories[row.student_id].append(row)
        checkpoints = {str(k): Counter(available=0, legal=0, skill_tagged_legal=0, mapped_legal=0) for k in CHECKPOINTS}
        for history in histories.values():
            for view in temporal_views(history):
                c = checkpoints[str(view["checkpoint"])]
                c["available"] += 1
                c["legal"] += view["label"] is not None
                c["skill_tagged_legal"] += view["label"] is not None and bool(view["query"]["source_skills"])
                c["mapped_legal"] += view["label"] is not None and bool(view["query"]["mapped_skills"])
        result[name] = {**counts(kept), "checkpoints": checkpoints}
    return {"mode": mode, "seed": seed, "discarded_by_joint_holdout": len(rows)-retained, "folds": result}


def audit(rows, dedup, sha):
    mapped = sorted({s for r in rows for s in r.mapped_skills})
    return {"schema_version": ADAPTER_VERSION, "source": {"url": SOURCE_URL,
        "dictionary_url": DICTIONARY_URL, "download_url": DOWNLOAD_URL,
        "file": "skill_builder_data_corrected_collapsed.csv", "sha256": sha,
        "encoding": "latin-1", "license": "Official page: free to use; cite exact data URL and ASSISTments paper. No SPDX license specified.",
        "scope": "public ASSISTments source only; MathTutor target-domain students = 0"},
        "deduplication": dedup, "population": counts(rows),
        "exclusions": dict(Counter(r.exclusion or "eligible" for r in rows)),
        "help": {"first_action_missing_or_invalid": sum(r.first_action not in {0,1,2} for r in rows),
                 "hint_count_missing": sum(r.hint_count is None for r in rows),
                 "complete_action_sequence_unavailable": len(rows),
                 "first_wrong_then_help_retained": sum(r.label == 0 and bool(r.hint_count) for r in rows)},
        "mapping": {"version": "assist2009-mt-topic-v1", "covered_skills": mapped,
                    "coverage_denominator": 13, "source_skill_ids": len({s for r in rows for s in r.source_skills}),
                    "map": SKILL_MAP, "scope": "topic proxy; does not validate fine-grained method mastery or MathTutor task equivalence"},
        "splits": [split_audit(rows, seed, mode) for seed in (17,29,43) for mode in ("student", "student_item", "student_family")],
        "conclusions": {"formal_abcd_started": False, "target_transfer_validated": False,
                        "time_gap_features_available": False, "training_weights_exported": False}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="Offline data directory outside the source checkout")
    args = parser.parse_args()
    repository = Path(__file__).resolve().parents[4]
    if args.output.resolve().is_relative_to(repository):
        parser.error("keep individual source observations outside the checkout")
    sha = hashlib.sha256(args.input.read_bytes()).hexdigest()
    if sha != SOURCE_SHA256:
        parser.error("source hash differs from frozen official corrected version")
    with args.input.open(encoding="latin-1", newline="") as handle:
        rows, dedup = adapt(csv.DictReader(handle))
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "source-observations.jsonl").open("w") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row), ensure_ascii=False) + "\n")
    report = audit(rows, dedup, sha)
    (args.output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), **report["population"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
