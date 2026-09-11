"""NumPy inference for exported, actually trained one-layer PyTorch LSTMs.

No gradients or training dependency is imported on the product request path.
The standard i/f/g/o cell equations are tested against the training model.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from .events import FEATURE_SCHEMA, LearningEvent
from .features import FeatureVocabulary


def _sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -60, 60)))


class LSTMTracker:
    def __init__(self, artifact: dict):
        if not artifact.get("trained") or artifact.get("training_steps", 0) < 1:
            raise ValueError("untrained models cannot enter runtime")
        self.vocabulary = FeatureVocabulary.from_dict(artifact["vocabulary"])
        self.model_version = artifact["model_version"]
        self.graph_version = artifact["graph_version"]
        self.hidden_size = int(artifact["hidden_size"])
        self.temperature = float(artifact.get("calibration_temperature", 1))
        if not 0.05 <= self.temperature <= 20:
            raise ValueError("invalid calibration temperature")
        self.weights = {k: np.asarray(v, dtype=np.float32) for k, v in artifact["weights"].items()}
        if any(not np.isfinite(v).all() for v in self.weights.values()):
            raise ValueError("invalid model weights")
        self.report = artifact.get("evaluation", {})
        # Serving gate is deliberately closed until a reviewed, real-data
        # multi-seed report exists. An artifact cannot self-authorize policy.
        self.mode = "shadow"
        self._validate_shapes()

    def _validate_shapes(self):
        width = self.weights["event_projection.weight"].shape[0]
        expected = {
            "event_projection.weight": (width, self.vocabulary.event_size),
            "event_projection.bias": (width,),
            "lstm.weight_ih_l0": (4 * self.hidden_size, width),
            "lstm.weight_hh_l0": (4 * self.hidden_size, self.hidden_size),
            "lstm.bias_ih_l0": (4 * self.hidden_size,),
            "lstm.bias_hh_l0": (4 * self.hidden_size,),
            "prediction.weight": (1, self.hidden_size + self.vocabulary.item_size),
            "prediction.bias": (1,),
        }
        if set(expected) != set(self.weights) or any(self.weights[k].shape != shape for k, shape in expected.items()):
            raise ValueError("model/feature shape mismatch")

    @classmethod
    def load(cls, path):
        # JSON only: model loading does not execute pickle payloads.
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def initialize(self):
        return np.zeros(self.hidden_size, dtype=np.float32), np.zeros(self.hidden_size, dtype=np.float32)

    def predict(self, state, item_context):
        if not self.vocabulary.covered(item_context.get("skill_ids", ())):
            raise ValueError("skill_out_of_vocabulary")
        h, _ = state
        item = self.vocabulary.item(**{k: item_context.get(k) for k in ("skill_ids", "item_family_id", "difficulty")})
        logit = float((self.weights["prediction.weight"] @ np.concatenate([h, item]) + self.weights["prediction.bias"])[0])
        return float(_sigmoid(logit / self.temperature))

    def update(self, state, observed_event: LearningEvent):
        h, c = state
        x = np.tanh(self.weights["event_projection.weight"] @ self.vocabulary.event(observed_event) + self.weights["event_projection.bias"])
        gates = (self.weights["lstm.weight_ih_l0"] @ x + self.weights["lstm.weight_hh_l0"] @ h
                 + self.weights["lstm.bias_ih_l0"] + self.weights["lstm.bias_hh_l0"])
        i, f, g, o = np.split(gates, 4)
        c = _sigmoid(f) * c + _sigmoid(i) * np.tanh(g)
        h = _sigmoid(o) * np.tanh(c)
        return h.astype(np.float32), c.astype(np.float32)

    def snapshot(self, state, *, student_id, last_event_seq):
        h, c = state
        return {"student_id": student_id, "last_event_seq": last_event_seq,
                "model_version": self.model_version, "feature_schema_version": FEATURE_SCHEMA,
                "graph_version": self.graph_version, "h": h.tolist(), "c": c.tolist()}

    def restore(self, snapshot, *, student_id):
        if (snapshot.get("student_id") != student_id or snapshot.get("model_version") != self.model_version
                or snapshot.get("feature_schema_version") != FEATURE_SCHEMA or snapshot.get("graph_version") != self.graph_version):
            raise ValueError("snapshot binding/version mismatch; replay required")
        h, c = np.asarray(snapshot["h"], dtype=np.float32), np.asarray(snapshot["c"], dtype=np.float32)
        if h.shape != (self.hidden_size,) or c.shape != h.shape or not np.isfinite(h).all() or not np.isfinite(c).all():
            raise ValueError("invalid recurrent state; replay required")
        return h, c


def artifact_version(weights, vocabulary, seed):
    data = json.dumps({"weights": weights, "vocabulary": vocabulary, "seed": seed}, sort_keys=True, separators=(",", ":"))
    return "lstm-dkt-v1-" + hashlib.sha256(data.encode()).hexdigest()[:20]
