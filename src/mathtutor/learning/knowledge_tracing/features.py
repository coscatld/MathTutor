"""Train-only vocabularies and explicit missing/OOV masks; no raw text or IDs."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Sequence

import numpy as np

from .events import FEATURE_SCHEMA, LearningEvent
from mathtutor.learning.skill_graph import SKILLS

EVENT_TYPES = (
    "attempt_assessed", "help_requested", "help_committed", "help_possibly_exposed",
    "help_presented", "self_explanation", "problem_started", "problem_ended",
)
RESULTS = ("missing", "correct", "incorrect", "partial", "unknown")
SCOPES = ("full_problem", "subgoal", "reflection", "error_analysis")
KINDS = ("none", "independent", "assisted", "post_solution", "unknown")
HELP = ("", "hint", "explanation", "example", "solution")
PURPOSES = ("practice", "diagnostic", "review", "error_analysis", "transfer")


@dataclass(frozen=True)
class FeatureVocabulary:
    skills: tuple[str, ...]
    families: tuple[str, ...]
    misconceptions: tuple[str, ...] = ()
    schema_version: str = FEATURE_SCHEMA

    @classmethod
    def fit(cls, events: Sequence[LearningEvent]):
        return cls(
            tuple(sorted({s for e in events for s in e.skill_ids if s in SKILLS})),
            tuple(sorted({e.item_family_id for e in events})),
            tuple(sorted({s for e in events for s in e.misconception_codes})),
        )

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if data.get("schema_version") != FEATURE_SCHEMA:
            raise ValueError("unsupported feature schema")
        return cls(tuple(data["skills"]), tuple(data["families"]), tuple(data.get("misconceptions", ())))

    @property
    def item_size(self):
        return len(self.skills) + 1 + len(self.families) + 1 + 4

    @property
    def event_size(self):
        return self.item_size + sum(map(len, (EVENT_TYPES, RESULTS, SCOPES, KINDS, HELP, PURPOSES))) + len(self.misconceptions) + 1 + 7

    def covered(self, skill_ids: Sequence[str]) -> bool:
        return bool(skill_ids) and all(x in self.skills for x in skill_ids)

    def item(self, *, skill_ids, item_family_id, difficulty=None, skill_weights=()):
        vector = np.zeros(self.item_size, dtype=np.float32)
        weights = skill_weights or [1] * len(skill_ids)
        total = sum(weights) or 1
        for skill, weight in zip(skill_ids, weights):
            index = self.skills.index(skill) if skill in self.skills else len(self.skills)
            vector[index] += weight / total
        offset = len(self.skills) + 1
        family = self.families.index(item_family_id) if item_family_id in self.families else len(self.families)
        vector[offset + family] = 1
        vector[-4:] = [
            0 if difficulty is None else (difficulty - 1) / 4,
            float(difficulty is not None),
            float(not self.covered(skill_ids)),
            float(item_family_id not in self.families),
        ]
        return vector

    def event(self, event: LearningEvent):
        arrays = [self.item(skill_ids=event.skill_ids, item_family_id=event.item_family_id,
                            difficulty=event.difficulty, skill_weights=event.skill_weights)]
        for vocabulary, value in (
            (EVENT_TYPES, event.event_type), (RESULTS, event.correctness or "missing"),
            (SCOPES, event.completion_scope), (KINDS, event.evidence_kind),
            (HELP, event.help_kind), (PURPOSES, event.task_purpose),
        ):
            vector = np.zeros(len(vocabulary), dtype=np.float32)
            if value in vocabulary:
                vector[vocabulary.index(value)] = 1
            arrays.append(vector)
        errors = np.zeros(len(self.misconceptions) + 1, dtype=np.float32)
        for code in event.misconception_codes:
            errors[self.misconceptions.index(code) if code in self.misconceptions else -1] = 1
        arrays.append(errors)
        arrays.append(np.asarray([
            float(event.target_answer_exposed or event.target_answer_exposed_before_attempt),
            float(bool(event.prior_help_event_ids)), float(event.provenance_uncertain),
            min(math.log1p(event.active_response_ms or 0), math.log1p(600_000)) / math.log1p(600_000),
            float(event.active_response_ms is not None),
            min(math.log1p(event.time_gap_ms or 0), math.log1p(30 * 86_400_000)) / math.log1p(30 * 86_400_000),
            float(event.time_gap_ms is not None),
        ], dtype=np.float32))
        return np.concatenate(arrays)
