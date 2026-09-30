"""Write the manifest for a bundled shadow-only student-model package.

Usage:
    python scripts/build_student_model_package.py <package-dir>

The package directory must already contain the research checkpoint
``model.json`` copied byte-for-byte from the frozen delivery. Self-check
expectations come from an independent float64 reference implementation and
must agree with the product loader before the manifest is written.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mathtutor.learning.knowledge_tracing.model_package import (  # noqa: E402
    PACKAGE_SCHEMA, SELF_CHECK_TOLERANCE, SOURCE_FORMAT, SourceModelPackage)

STEPS = 16
PROVENANCE = {
    "dataset": "ASSISTments 2009-2010 skill builder (corrected, collapsed); public research dataset",
    "research_run": "assist2009-windows-source-v2 / dkt_init29",
    "selection": "lowest validation (selection) student-macro log loss among seeds 17/29/43; test split not consulted",
    "best_selection_loss": 0.538249,
    "research_delivery_manifest_sha256": "d30fb23c69ce995874ad6466d7a32ec41accca2f6afcebe2e62dd3603a3c03a4",
    "torch_numpy_parity": {"status": "passed", "steps": 64, "max_logit_absolute_error": 2.384185791015625e-07,
                           "source": "deliverables/acceptance/new_model_runtime.json"},
}
POLICY = {
    "serving_mode": "shadow",
    "controls_teaching": False,
    "target_coverage": "unsupported_target",
    "target_domain_validated": False,
    "reason": "ASSISTments source skills have no approved runtime mapping to MathTutor skills "
              "(source_skill_mapping_v1: runtime_enabled=false); MathTutor task probabilities stay null.",
}


def reference_sequence(payload, events, queries):
    """Independent float64 LSTM, written from the PyTorch cell equations."""
    w = {k: np.asarray(v, dtype=np.float64) for k, v in payload["state_dict"].items()}
    temperature = float(payload["calibration"]["temperature"])
    hidden = int(payload["config"]["hidden_size"])
    h, c, out = np.zeros(hidden), np.zeros(hidden), []
    sig = lambda x: 1.0 / (1.0 + np.exp(-x))  # noqa: E731
    for event, query in zip(events, queries):
        logit = float(w["head.weight"][0] @ np.concatenate([h, query]) + w["head.bias"][0])
        out.append(float(sig(logit / temperature)))
        x = np.tanh(w["event_projection.weight"] @ event + w["event_projection.bias"])
        z = w["lstm.weight_ih_l0"] @ x + w["lstm.bias_ih_l0"] + w["lstm.weight_hh_l0"] @ h + w["lstm.bias_hh_l0"]
        gi, gf, gg, go = (z[k * hidden:(k + 1) * hidden] for k in range(4))
        c = sig(gf) * c + sig(gi) * np.tanh(gg)
        h = sig(go) * np.tanh(c)
    return out


def main(directory: Path):
    raw = (directory / "model.json").read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if payload["format"] != SOURCE_FORMAT:
        raise SystemExit("unexpected checkpoint format")
    event_size, item_size = payload["config"]["event_size"], payload["config"]["item_size"]
    skills = len(payload["vocabulary"]["skills"])
    # Synthetic one-hot source vectors: operator/platform conformance only,
    # never a claim about source or target accuracy.
    event_indices = [[(7 * i) % skills, skills + (i % (event_size - skills))] for i in range(STEPS)]
    query_indices = [[(11 * i + 3) % skills] for i in range(STEPS)]
    one_hot = lambda size, idx: np.bincount(idx, minlength=size).astype(np.float64)  # noqa: E731
    events = [one_hot(event_size, idx) for idx in event_indices]
    queries = [one_hot(item_size, idx) for idx in query_indices]
    expected = reference_sequence(payload, events, queries)

    manifest = {
        "schema": PACKAGE_SCHEMA,
        "package_id": directory.name,
        "model": {"file": "model.json", "format": SOURCE_FORMAT, "bytes": len(raw),
                  "sha256": hashlib.sha256(raw).hexdigest(),
                  "source_skills": skills, "event_size": event_size, "item_size": item_size,
                  "hidden_size": payload["config"]["hidden_size"],
                  "calibration_temperature": payload["calibration"]["temperature"]},
        "provenance": PROVENANCE,
        "policy": POLICY,
        "self_check": {"method": "independent float64 reference; synthetic one-hot source vectors",
                       "tolerance": SELF_CHECK_TOLERANCE, "event_indices": event_indices,
                       "query_indices": query_indices, "expected_probabilities": expected},
    }
    if manifest["model"]["sha256"] != PROVENANCE["research_delivery_manifest_sha256"]:
        raise SystemExit("model bytes differ from the frozen research delivery")
    target = directory / "manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    SourceModelPackage(directory)  # the product loader must accept it, self-check included
    print(json.dumps({"package_id": directory.name, "sha256": manifest["model"]["sha256"], "steps": STEPS}))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]).resolve())
