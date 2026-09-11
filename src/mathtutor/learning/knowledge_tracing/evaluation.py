"""Probability metrics and held-out temperature calibration, no sklearn needed."""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np


def metrics(labels, probabilities, bins=10):
    if not labels:
        return {"count": 0, "auroc": None, "auprc": None, "log_loss": None, "brier": None, "ece": None, "calibration": []}
    y = np.asarray(labels, dtype=float)
    p = np.clip(np.asarray(probabilities, dtype=float), 1e-7, 1 - 1e-7)
    if len(y) != len(p) or not np.isfinite(p).all() or not set(y).issubset({0, 1}):
        raise ValueError("invalid evaluation observations")
    pos, neg = int(y.sum()), int(len(y) - y.sum())
    # Average ranks correctly treat equal-probability ties as half wins.
    ordered = np.argsort(p, kind="stable")
    ranks = np.empty(len(p), dtype=float)
    start = 0
    while start < len(p):
        end = start + 1
        while end < len(p) and p[ordered[end]] == p[ordered[start]]:
            end += 1
        ranks[ordered[start:end]] = (start + 1 + end) / 2
        start = end
    auc = float((ranks[y == 1].sum() - pos * (pos + 1) / 2) / (pos * neg)) if pos and neg else None
    ap = None
    if pos:
        tp = fp = 0
        ap = 0.0
        for threshold in sorted(set(p.tolist()), reverse=True):
            group = y[p == threshold]
            added = int(group.sum())
            tp += added; fp += len(group) - added
            ap += (added / pos) * tp / (tp + fp)
    curve, ece = [], 0.0
    for i in range(bins):
        mask = (p >= i / bins) & (p <= 1 if i == bins - 1 else p < (i + 1) / bins)
        n = int(mask.sum())
        if n:
            predicted, observed = float(p[mask].mean()), float(y[mask].mean())
            ece += n / len(y) * abs(predicted - observed)
            curve.append({"lower": i / bins, "upper": (i + 1) / bins, "count": n,
                          "predicted": predicted, "observed": observed})
    return {"count": len(y), "positive": pos, "negative": neg, "auroc": auc, "auprc": ap,
            "log_loss": float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()),
            "brier": float(np.square(p - y).mean()), "ece": ece, "calibration": curve}


def temperature_scale(probabilities, temperature):
    p = np.clip(np.asarray(probabilities, dtype=float), 1e-7, 1 - 1e-7)
    logits = np.log(p / (1 - p)) / temperature
    return (1 / (1 + np.exp(-np.clip(logits, -60, 60)))).tolist()


def fit_temperature(labels, probabilities):
    if len(labels) < 2 or len(set(labels)) < 2:
        return 1.0, "insufficient_validation_labels_uncalibrated"
    candidates = np.geomspace(.25, 4, 61)
    best = min(candidates, key=lambda t: metrics(labels, temperature_scale(probabilities, t))["log_loss"])
    return float(best), "temperature_grid_fitted_validation_only"


def grouped_metrics(rows, field):
    groups = defaultdict(list)
    for row in rows:
        value = row[field]
        keys = value if isinstance(value, (list, tuple)) else [value]
        for key in keys:
            groups[str(key)].append(row)
    return {name: metrics([r["label"] for r in group], [r["probability"] for r in group]) for name, group in sorted(groups.items())}


def student_bootstrap(rows, *, seed=17, samples=200):
    """Student-cluster bootstrap; correlated attempts are resampled together."""
    groups = defaultdict(list)
    for row in rows:
        groups[row["student_id"]].append(row)
    if len(groups) < 3:
        return {"status": "too_few_students", "students": len(groups)}
    rng = np.random.default_rng(seed)
    keys = list(groups)
    values = []
    for _ in range(samples):
        selected = [row for key in rng.choice(keys, size=len(keys), replace=True) for row in groups[key]]
        values.append(metrics([r["label"] for r in selected], [r["probability"] for r in selected])["log_loss"])
    return {"status": "student_cluster_bootstrap", "students": len(groups), "samples": samples,
            "log_loss_interval_95": np.quantile(values, [.025, .975]).tolist()}
