"""Leakage-auditable student/time/family splits, never a random row split."""
from __future__ import annotations

import hashlib
from collections import defaultdict

from .events import LearningEvent, ordered_attempts, valid_events


def sequences(events):
    groups = defaultdict(list)
    for event in events:
        groups[event.student_id].append(event)
    return [ordered_attempts(value) for _, value in sorted(groups.items())]


def _partition(keys, seed):
    ordered = sorted(set(keys), key=lambda key: hashlib.sha256(f"{seed}:{key}".encode()).digest())
    if len(ordered) < 3:
        raise ValueError("at least three independent groups are needed for train/validation/test")
    train_end = max(1, min(len(ordered) - 2, int(len(ordered) * .6)))
    validation_end = max(train_end + 1, min(len(ordered) - 1, int(len(ordered) * .8)))
    return {key: 0 if i < train_end else 1 if i < validation_end else 2 for i, key in enumerate(ordered)}


def split_events(events, *, mode="student", seed=17):
    """Each reported experiment has its own held-out test population.

    ``student`` permits different students to answer shared course items.
    ``student_item`` / ``student_family`` hold out both students and content;
    ``family`` alone does not imply unseen students. Legacy time/family
    experiments purge repeated content from later folds. No fold fits a
    vocabulary/calibrator on held-out outcomes.
    """
    dedup = []
    for history in sequences(events):
        dedup.extend(valid_events(history))
    folds = [[], [], []]
    if mode in {"student", "family", "student_item", "student_family"}:
        key = (lambda x: x.item_family_id) if mode == "family" else (lambda x: x.student_id)
        mapping = _partition([key(x) for x in dedup], seed)
        for event in dedup:
            folds[mapping[key(event)]].append(event)
    elif mode == "time":
        for history in sequences(dedup):
            history = sorted(history, key=lambda x: (x.occurred_at, x.event_seq))
            if len(history) < 3:
                folds[0].extend(history)
                continue
            a = max(1, min(len(history) - 2, int(len(history) * .6)))
            b = max(a + 1, min(len(history) - 1, int(len(history) * .8)))
            folds[0].extend(history[:a]); folds[1].extend(history[a:b]); folds[2].extend(history[b:])
    else:
        raise ValueError("split must be student, student_item, student_family, time or family")
    # problem_revision is the canonical math-content hash, not a random row ID.
    # Keep an entire repeated item / its derived subgoals in its earliest fold.
    seen_items = set()
    purged = 0
    shared = set()
    for fold in folds:
        items = {e.leakage_group_id or e.problem_revision for e in fold}
        shared.update(items & seen_items)
        seen_items.update(items)
    seen_items = set()
    item_mapping = None
    if mode in {"student_item", "student_family"}:
        item_key = lambda e: e.item_family_id if mode == "student_family" else (e.leakage_group_id or e.problem_revision)
        item_mapping = _partition([item_key(e) for e in dedup], seed + 1)
    for i, fold in enumerate(folds):
        kept = fold if mode == "student" else [e for e in fold if
            (item_mapping[item_key(e)] == i if item_mapping is not None else
             (e.leakage_group_id or e.problem_revision) not in seen_items)]
        purged += len(fold) - len(kept)
        folds[i] = kept
        seen_items.update(e.leakage_group_id or e.problem_revision for e in kept)
    return {"train": folds[0], "validation": folds[1], "test": folds[2],
            "audit": {"mode": mode, "seed": seed, "purged_cross_split_item_events": purged,
                      "shared_course_items_before_filter": len(shared),
                      "protocol": "new_student_existing_course" if mode == "student" else mode,
                      "sizes": {name: len(fold) for name, fold in zip(("train", "validation", "test"), folds)}}}


def data_gaps(events):
    valid = [e for history in sequences(events) for e in valid_events(history)]
    return {
        "students": len({e.student_id for e in valid}), "events": len(valid),
        "independent_binary_targets": sum(e.independent_target for e in valid),
        "assisted_targets_excluded": sum(e.evidence_kind == "assisted" for e in valid),
        "post_solution_targets_excluded": sum(e.evidence_kind == "post_solution" for e in valid),
        "uncertain_provenance_excluded": sum(e.provenance_uncertain for e in valid),
        "duplicate_responses_excluded": sum(e.duplicate_response for e in valid),
        "missing_or_unknown_labels": sum(e.correctness in {None, "unknown"} for e in valid),
        "unmapped_skills": sum(not e.skill_ids for e in valid),
        "missing_near_duplicate_group": sum(not e.leakage_group_id for e in valid),
        "graph_versions": sorted({e.graph_version for e in valid}),
        "families": len({e.item_family_id for e in valid}),
        "policy_status": "shadow_only_pending_real_student_validation",
    }
