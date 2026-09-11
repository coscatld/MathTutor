"""Offline small LSTM training. Current label enters the cell AFTER prediction."""
from __future__ import annotations

import copy
import json
import time

import numpy as np

from .dataset import data_gaps, sequences, split_events
from .evaluation import fit_temperature, grouped_metrics, metrics, student_bootstrap, temperature_scale
from .events import GRAPH_VERSION, baseline_prediction
from .features import FeatureVocabulary
from .runtime import LSTMTracker, artifact_version


def build_model(vocabulary, *, hidden_size=64, embedding_size=64):
    # Training-only dependency. Import errors clearly stop the offline command,
    # never a chat request or normal application startup.
    import torch
    from torch import nn

    class SmallLSTM(nn.Module):
        def __init__(self):
            super().__init__()
            self.event_projection = nn.Linear(vocabulary.event_size, embedding_size)
            self.lstm = nn.LSTM(embedding_size, hidden_size, num_layers=1)
            self.prediction = nn.Linear(hidden_size + vocabulary.item_size, 1)

        def initialize(self):
            return torch.zeros(1, 1, hidden_size), torch.zeros(1, 1, hidden_size)

        def predict(self, state, event):
            item = torch.from_numpy(vocabulary.item(skill_ids=event.skill_ids, item_family_id=event.item_family_id,
                                                    difficulty=event.difficulty, skill_weights=event.skill_weights))
            return self.prediction(torch.cat([state[0].reshape(-1), item])).reshape(())

        def update(self, state, event):
            value = torch.tanh(self.event_projection(torch.from_numpy(vocabulary.event(event))))
            return self.lstm(value.reshape(1, 1, -1), state)[1]

    return SmallLSTM()


def export_model(model, vocabulary, *, seed, training_steps, graph_version=GRAPH_VERSION):
    weights = {name: value.detach().cpu().numpy().tolist() for name, value in model.state_dict().items()}
    vocab = vocabulary.to_dict()
    return {"format": "mathtutor_lstm_json_v1", "trained": training_steps > 0,
            "training_steps": training_steps, "hidden_size": model.lstm.hidden_size,
            "embedding_size": model.lstm.input_size, "graph_version": graph_version,
            "vocabulary": vocab, "weights": weights,
            "model_version": artifact_version(weights, vocab, seed), "seed": seed,
            "calibration_temperature": 1.0, "serving_mode": "shadow"}


def evaluate(tracker, events, *, history_prefix=()):
    prefixes = {seq[0].student_id: seq for seq in sequences(history_prefix) if seq}
    rows = []
    for history in sequences(events):
        state, prior = tracker.initialize(), list(prefixes.get(history[0].student_id, []))
        for event in prior:
            state = tracker.update(state, event)
        for event in history:
            if event.independent_target and tracker.vocabulary.covered(event.skill_ids):
                probability = tracker.predict(state, {"skill_ids": event.skill_ids,
                    "item_family_id": event.item_family_id, "difficulty": event.difficulty})
                rows.append({"label": int(event.correctness == "correct"), "probability": probability,
                    "baseline_probability": baseline_prediction(prior, event.skill_ids),
                    "constant_probability": .5, "student_id": event.student_id, "skill_ids": event.skill_ids,
                    "history_cutoff_seq": max((x.event_seq for x in prior), default=0),
                    "event_seq": event.event_seq, "sequence_length": "cold_0_4" if len(prior) < 5 else "short_5_19" if len(prior) < 20 else "long_20_plus"})
            state = tracker.update(state, event)
            prior.append(event)
    return rows


def train_pipeline(events, *, seed=17, epochs=5, hidden_size=64, embedding_size=64, window=100, split_mode="student", synthetic=False):
    import torch
    if epochs < 1 or not 1 <= window <= 1000:
        raise ValueError("positive epochs and a bounded training window required")
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    splits = split_events(events, mode=split_mode, seed=seed)
    train = splits["train"]
    if not any(e.independent_target for e in train):
        raise ValueError("no trustworthy independent labels in the training split")
    graph_versions = {e.graph_version for e in train}
    if len(graph_versions) != 1:
        raise ValueError("map graph versions before training; implicit remapping is forbidden")
    vocabulary = FeatureVocabulary.fit(train)
    if not any(e.independent_target and vocabulary.covered(e.skill_ids) for e in train):
        raise ValueError("no graph-mapped independent training labels")
    model = build_model(vocabulary, hidden_size=hidden_size, embedding_size=embedding_size)
    optimizer = torch.optim.Adam(model.parameters(), lr=.003)
    initial = {k: v.detach().clone() for k, v in model.state_dict().items()}
    best, best_loss, best_epoch, steps, losses = None, float("inf"), 0, 0, []
    started = time.monotonic()
    for epoch in range(epochs):
        model.train()
        epoch_losses = []
        for history in sequences(train):
            state = model.initialize()
            for start in range(0, len(history), window):
                terms = []
                optimizer.zero_grad()
                for event in history[start:start + window]:
                    # No correctness/help-outcome features are available to
                    # the prediction head before this exact current loss.
                    if event.independent_target and vocabulary.covered(event.skill_ids):
                        logit = model.predict(state, event)
                        label = torch.tensor(float(event.correctness == "correct"))
                        terms.append(torch.nn.functional.binary_cross_entropy_with_logits(logit, label))
                    state = model.update(state, event)
                if terms:
                    loss = torch.stack(terms).mean()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
                    optimizer.step()
                    steps += 1
                    epoch_losses.append(float(loss.detach()))
                state = tuple(x.detach() for x in state)
        artifact = export_model(model, vocabulary, seed=seed, training_steps=steps, graph_version=next(iter(graph_versions)))
        tracker = LSTMTracker(artifact)
        prefix = train if split_mode == "time" else ()
        validation = evaluate(tracker, splits["validation"], history_prefix=prefix)
        val = metrics([x["label"] for x in validation], [x["probability"] for x in validation])
        score = val["log_loss"] if val["log_loss"] is not None else float(np.mean(epoch_losses))
        losses.append({"epoch": epoch + 1, "train_log_loss": float(np.mean(epoch_losses)), "validation_log_loss": val["log_loss"]})
        if score < best_loss:
            best, best_loss, best_epoch = copy.deepcopy(artifact), score, epoch + 1
    if best is None:
        raise ValueError("training produced no model")
    tracker = LSTMTracker(best)
    validation = evaluate(tracker, splits["validation"], history_prefix=train if split_mode == "time" else ())
    temperature, calibration_status = fit_temperature([x["label"] for x in validation], [x["probability"] for x in validation])
    best["calibration_temperature"] = temperature
    tracker = LSTMTracker(best)
    inference_started = time.monotonic()
    test = evaluate(tracker, splits["test"], history_prefix=train + splits["validation"] if split_mode == "time" else ())
    inference_seconds = time.monotonic() - inference_started
    labels = [x["label"] for x in test]
    report = {
        "dataset_kind": "synthetic_pipeline_only" if synthetic else "provided_learning_events",
        "learning_effect_verified": False, "policy_mode": "shadow",
        "gate_reason": "real_student_multi_seed_and_cold_start_review_required",
        "data_gaps": data_gaps(events), "split": splits["audit"], "seed": seed,
        "epochs": epochs, "best_epoch": best_epoch, "window": window, "losses": losses,
        "training_steps": steps, "training_seconds": time.monotonic() - started,
        "evaluation_ms_per_event": inference_seconds * 1000 / max(len(splits["test"]), 1),
        "model_bytes": len(json.dumps(best).encode()),
        "parameters_changed": any(not torch.equal(initial[k], v.detach()) for k, v in model.state_dict().items()),
        "calibration": {"method": calibration_status, "temperature": temperature, "fit_split": "validation"},
        "test": metrics(labels, [x["probability"] for x in test]),
        "evidence_baseline": metrics(labels, [x["baseline_probability"] for x in test]),
        "constant_baseline": metrics(labels, [.5] * len(labels)),
        "by_skill": grouped_metrics(test, "skill_ids"), "by_student": grouped_metrics(test, "student_id"),
        "by_sequence_length": grouped_metrics(test, "sequence_length"),
        "uncertainty": student_bootstrap(test, seed=seed),
    }
    best["evaluation"] = report
    return best, report
