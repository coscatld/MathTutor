"""Versioned mastery estimator (Phase 4 learning loop, step 5).

``mt-estimator-v1``: a transparent, deterministic increment/decrement rule
over mastery in [0, 1]. ALL parameters live in the class constant table —
no magic numbers anywhere else in the pipeline.

Rules (per evidence, on the evidence's skill):

- correct  -> ``+GAINS_BY_ASSISTANCE_LEVEL[level]``
              (L0 > L2 > L4: 1.0 > 0.6 > 0.2 — help given dilutes the gain);
- incorrect -> ``-INCORRECT_PENALTY`` (small, symmetric punishment);
- partial  -> ``+GAINS_BY_ASSISTANCE_LEVEL[level] * score`` (proportional);
- mastery is clamped to ``[MIN_MASTERY, MAX_MASTERY]`` (the confidence cap).

The same inputs always produce the same output (float arithmetic on the
same canonical values); the version string is persisted with every
projection so future estimator versions can be replayed separately.
"""

from __future__ import annotations

from mathtutor.learning.evidence import LearningEvidence

ESTIMATOR_VERSION = "mt-estimator-v1"


class MasteryEstimator:
    """Deterministic v1 mastery estimator."""

    VERSION = ESTIMATOR_VERSION

    # Gain table indexed by effective assistance level (0..5).
    # L0 (independent) > L2 (strategy help) > L4 (answer-adjacent help).
    GAINS_BY_ASSISTANCE_LEVEL: tuple[float, ...] = (1.0, 0.8, 0.6, 0.4, 0.2, 0.1)

    INCORRECT_PENALTY: float = 0.2

    MAX_MASTERY: float = 1.0
    MIN_MASTERY: float = 0.0
    NEW_SKILL_BASELINE: float = 0.0

    def initial_mastery(self) -> float:
        """Mastery of a skill with no evidence yet."""
        return self.NEW_SKILL_BASELINE

    def delta_for(self, evidence: LearningEvidence) -> float:
        """Signed mastery delta for one piece of evidence (pure)."""
        level = max(0, min(len(self.GAINS_BY_ASSISTANCE_LEVEL) - 1, evidence.effective_assistance_level))
        gain = self.GAINS_BY_ASSISTANCE_LEVEL[level]
        if evidence.correctness == "correct":
            return gain
        if evidence.correctness == "incorrect":
            return -self.INCORRECT_PENALTY
        # partial: proportional to the assessment score (0 < score <= 1).
        score = max(0.0, min(1.0, evidence.score))
        return gain * score

    def apply(self, mastery: float, evidence: LearningEvidence) -> float:
        """Apply one evidence to a mastery value with clamping (pure)."""
        updated = mastery + self.delta_for(evidence)
        return max(self.MIN_MASTERY, min(self.MAX_MASTERY, updated))


__all__ = ["ESTIMATOR_VERSION", "MasteryEstimator"]
