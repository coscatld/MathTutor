"""Versioned learning facts, evidence baseline and optional trained LSTM tracing.

Product imports deliberately do not import torch. Training is an offline,
explicit operation; untrained/missing models never supply teaching decisions.
"""

from .events import LearningEvent, evidence_summary
from .service import StudentStateService

__all__ = ["LearningEvent", "StudentStateService", "evidence_summary"]
