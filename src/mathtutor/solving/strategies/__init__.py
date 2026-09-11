"""Deterministic solver strategies for the MVP problem families.

Every strategy is exact (stdlib ``fractions``) and emits replayable steps
so the verifier can re-derive them independently.
"""

from __future__ import annotations

from mathtutor.solving.strategies import arithmetic, linear, polynomial, quadratic, linear_system

STRATEGIES = {
    "arithmetic": arithmetic.STRATEGY_NAME,
    "polynomial": polynomial.STRATEGY_NAME,
    "linear": linear.STRATEGY_NAME,
    "quadratic": quadratic.STRATEGY_NAME,
    "linear_system": linear_system.STRATEGY_NAME,
}

__all__ = ["STRATEGIES", "arithmetic", "linear", "polynomial", "quadratic"]
