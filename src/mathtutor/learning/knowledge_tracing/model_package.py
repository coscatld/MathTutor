"""Bundled, hash-pinned student-model packages for shadow-only DKT.

A package is a directory with ``manifest.json`` and the research checkpoint it
names. Loading verifies bytes, format, dimensions, finite weights, calibration
bounds and a recorded numeric self-check before any prediction is possible.
Only JSON is read; no pickle or package-supplied code is executed.

The package cannot authorise itself: every loaded model runs in ``shadow``
mode, never controls teaching, and yields no probability for MathTutor tasks
until a reviewed target mapping exists (``unsupported_target``).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from .package_paths import ASSETS, BUNDLED_PACKAGE

__all__ = ["ASSETS", "BUNDLED_PACKAGE", "SourceModelPackage", "load_bundled"]
PACKAGE_SCHEMA = "mathtutor_student_model_package_v1"
SOURCE_FORMAT = "tutor_model_dkt_v1"
MAX_MODEL_BYTES = 8 * 1024 * 1024
SELF_CHECK_TOLERANCE = 1e-5
_WEIGHT_SHAPES = {
    "event_projection.weight": ("embedding", "event"),
    "event_projection.bias": ("embedding",),
    "lstm.weight_ih_l0": ("gates", "embedding"),
    "lstm.weight_hh_l0": ("gates", "hidden"),
    "lstm.bias_ih_l0": ("gates",),
    "lstm.bias_hh_l0": ("gates",),
    "head.weight": ("one", "head"),
    "head.bias": ("one",),
}


def _sigmoid(values):
    # exp(-|x|) avoids overflow for either sign, matching the source runtime.
    exponent = np.exp(-np.abs(values))
    return np.where(values >= 0, 1 / (1 + exponent), exponent / (1 + exponent))


class SourceModelPackage:
    """NumPy inference for a verified ``tutor_model_dkt_v1`` checkpoint."""

    mode = "shadow"
    controls_teaching = False
    target_coverage = "unsupported_target"

    def __init__(self, directory: str | Path):
        directory = Path(directory)
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema") != PACKAGE_SCHEMA:
            raise ValueError("unsupported student-model package schema")
        entry = manifest["model"]
        name = Path(entry["file"]).name
        if name != entry["file"]:
            raise ValueError("model file must live directly in the package directory")
        raw = (directory / name).read_bytes()
        if len(raw) != entry["bytes"] or len(raw) > MAX_MODEL_BYTES:
            raise ValueError("model size does not match the package manifest")
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("model bytes do not match the package manifest")
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("format") != SOURCE_FORMAT:
            raise ValueError("unsupported DKT checkpoint format")

        config, vocabulary = payload["config"], payload["vocabulary"]
        self.event_size, self.item_size = int(config["event_size"]), int(config["item_size"])
        self.embedding_size, self.hidden_size = int(config["embedding_size"]), int(config["hidden_size"])
        if (vocabulary["event_size"], vocabulary["item_size"]) != (self.event_size, self.item_size):
            raise ValueError("vocabulary dimensions disagree with the model config")
        if len(vocabulary["event_feature_names"]) != self.event_size or len(vocabulary["item_feature_names"]) != self.item_size:
            raise ValueError("feature names disagree with the model config")
        dims = {"event": self.event_size, "embedding": self.embedding_size, "hidden": self.hidden_size,
                "gates": 4 * self.hidden_size, "head": self.hidden_size + self.item_size, "one": 1}
        weights = payload["state_dict"]
        if set(weights) != set(_WEIGHT_SHAPES):
            raise ValueError("unexpected checkpoint parameters")
        self.weights = {}
        for key, shape in _WEIGHT_SHAPES.items():
            array = np.asarray(weights[key], dtype=np.float32)
            if array.shape != tuple(dims[d] for d in shape):
                raise ValueError(f"parameter {key} has an unexpected shape")
            if not np.isfinite(array).all():
                raise ValueError(f"parameter {key} is not finite")
            self.weights[key] = array

        self.temperature = float(payload["calibration"]["temperature"])
        if not (np.isfinite(self.temperature) and 0.05 <= self.temperature <= 20):
            raise ValueError("calibration temperature is outside the accepted bounds")
        self.skill_vocabulary = frozenset(str(s) for s in vocabulary["skills"])
        self.package_id = manifest["package_id"]
        self.identity = {"package_id": self.package_id, "format": SOURCE_FORMAT,
                         "model_sha256": entry["sha256"], "mode": self.mode,
                         "controls_teaching": self.controls_teaching,
                         "target_coverage": self.target_coverage}
        self._self_check(manifest["self_check"])

    def initial_state(self):
        return np.zeros(self.hidden_size, dtype=np.float32), np.zeros(self.hidden_size, dtype=np.float32)

    def predict_proba(self, state, query) -> float:
        """Calibrated probability for a SOURCE-domain query vector."""
        query = np.asarray(query, dtype=np.float32)
        if query.shape != (self.item_size,):
            raise ValueError("query has an incorrect feature dimension")
        h, _ = state
        logit = self.weights["head.weight"] @ np.concatenate((h, query)) + self.weights["head.bias"]
        return float(_sigmoid(np.asarray(logit[0] / self.temperature, dtype=np.float32)))

    def update(self, state, event):
        """Incorporate one SOURCE-domain observation vector."""
        event = np.asarray(event, dtype=np.float32)
        if event.shape != (self.event_size,):
            raise ValueError("event has an incorrect feature dimension")
        h, c = state
        w = self.weights
        embedded = np.tanh(w["event_projection.weight"] @ event + w["event_projection.bias"])
        gates = w["lstm.weight_ih_l0"] @ embedded + w["lstm.bias_ih_l0"] + w["lstm.weight_hh_l0"] @ h + w["lstm.bias_hh_l0"]
        # PyTorch LSTM gate order: input, forget, candidate, output.
        i, f, g, o = np.split(gates, 4)
        c = _sigmoid(f) * c + _sigmoid(i) * np.tanh(g)
        h = _sigmoid(o) * np.tanh(c)
        return h.astype(np.float32, copy=False), c.astype(np.float32, copy=False)

    def covers(self, skill_ids) -> bool:
        """MathTutor skill ids live in another namespace: never covered here."""
        return False

    def run_sequence(self, events, queries):
        """Before-event probabilities for a synthetic source-domain sequence."""
        state, result = self.initial_state(), []
        for event, query in zip(events, queries):
            result.append(self.predict_proba(state, query))
            state = self.update(state, event)
        return result

    def _self_check(self, check):
        events = [self._one_hot(self.event_size, idx) for idx in check["event_indices"]]
        queries = [self._one_hot(self.item_size, idx) for idx in check["query_indices"]]
        actual = self.run_sequence(events, queries)
        expected = check["expected_probabilities"]
        if len(actual) != len(expected) or any(
                not abs(a - e) <= SELF_CHECK_TOLERANCE for a, e in zip(actual, expected)):
            raise ValueError("numeric self-check failed on this platform")

    @staticmethod
    def _one_hot(size, indices):
        vector = np.zeros(size, dtype=np.float32)
        for index in indices:
            if not 0 <= index < size:
                raise ValueError("self-check index out of range")
            vector[index] = 1
        return vector


def load_bundled(directory: str | Path = BUNDLED_PACKAGE) -> SourceModelPackage:
    return SourceModelPackage(directory)
