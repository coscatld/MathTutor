"""When the out-of-domain trained DKT may touch teaching at all.

The model was trained on ASSISTments, not on MathTutor students, and its
learning effect is unverified. It may move the next step or a practice
difficulty by at most one notch, and only when every condition holds:

- the policy is on (``MATHTUTOR_DKT_TEACHING=off`` disables it entirely);
- the forecast is a product-enabled one (``controls_teaching``);
- the skill maps to a product skill;
- the student has at least one own attempt on it (``history_updates``);
- the probability is a real number.

Every adjustment is recorded on the turn trace so its rate can be watched.
"""
from __future__ import annotations

import os


def dkt_enabled() -> bool:
    return os.environ.get("MATHTUTOR_DKT_TEACHING", "on").strip().lower() not in {"off", "0", "false", "no"}


def dkt_may_adjust(forecast: dict | None) -> bool:
    if not forecast or not dkt_enabled() or not forecast.get("controls_teaching"):
        return False
    probability = forecast.get("probability")
    return (bool(forecast.get("mapped_product_skills")) and int(forecast.get("history_updates") or 0) >= 1
            and isinstance(probability, (int, float)) and not isinstance(probability, bool))


def note_dkt(kind: str, direction: str) -> None:
    from mathtutor.application.tutor_runtime import note_turn
    note_turn(dkt={f"{kind}_{direction}": 1})


__all__ = ["dkt_enabled", "dkt_may_adjust", "note_dkt"]
