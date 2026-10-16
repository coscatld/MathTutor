"""When the out-of-domain trained DKT may touch teaching at all.

The model was trained on ASSISTments, not on MathTutor students, and its
learning effect is unverified. It may move the next step or a practice
difficulty by at most one notch, and only when every condition holds:

- the policy is on (``MATHTUTOR_DKT_TEACHING=off`` disables it entirely);
- the forecast is a product-enabled one (``controls_teaching``);
- the skill maps to a product skill;
- the student has at least one eligible independent item on a current mapped
  target (``target_history_by_skill``), rather than merely a global history;
- the probability is finite and within [0, 1].

Every adjustment is recorded on the turn trace so its rate can be watched.
"""
from __future__ import annotations

import os
import math


def dkt_enabled() -> bool:
    return os.environ.get("MATHTUTOR_DKT_TEACHING", "on").strip().lower() not in {"off", "0", "false", "no"}


def dkt_may_adjust(forecast: dict | None, *, skill_ids=None) -> bool:
    if not forecast or not dkt_enabled() or not forecast.get("controls_teaching"):
        return False
    probability = forecast.get("probability")
    if not (isinstance(probability, (int, float)) and not isinstance(probability, bool)
            and 0 <= probability <= 1 and math.isfinite(probability)):
        return False
    total = forecast.get("target_history_updates")
    if not isinstance(total, int) or isinstance(total, bool) or total < 1:
        return False
    global_updates = forecast.get("history_updates")
    if (not isinstance(global_updates, int) or isinstance(global_updates, bool)
            or global_updates < total):
        return False
    from mathtutor.learning.knowledge_tracing.mapped_dkt import expand
    mapped = forecast.get("mapped_product_skills")
    targets = forecast.get("target_skill_ids")
    counts = forecast.get("target_history_by_skill")
    if not (isinstance(mapped, (list, tuple)) and isinstance(targets, (list, tuple))
            and all(isinstance(skill, str) for skill in (*mapped, *targets)) and isinstance(counts, dict)):
        return False
    relevant = set(mapped).intersection(targets)
    if skill_ids is not None:
        _sources, current, _unmapped = expand(skill_ids)
        relevant.intersection_update(current)
    return any(isinstance(counts.get(skill), int) and not isinstance(counts.get(skill), bool)
               and 1 <= counts[skill] <= total for skill in relevant)


def note_dkt(kind: str, direction: str) -> None:
    from mathtutor.application.tutor_runtime import note_turn
    note_turn(dkt={f"{kind}_{direction}": 1})


__all__ = ["dkt_enabled", "dkt_may_adjust", "note_dkt"]
