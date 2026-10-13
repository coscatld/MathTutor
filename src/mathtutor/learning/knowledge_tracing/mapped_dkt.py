"""Read the trained ASSISTments checkpoint for mapped MathTutor skills.

The LSTM cell and the weights stay in ``SourceModelPackage``. This module only
builds the feature vectors that checkpoint already expects, then calls
``predict_proba`` / ``update``. It does not train and it does not authorise
the package: ``controls_teaching`` on a forecast is a product-policy flag.
"""
from __future__ import annotations

import math

import numpy as np

from mathtutor.learning.knowledge_tracing.assistments2009 import SKILL_MAP
from mathtutor.learning.knowledge_tracing.events import valid_events

MAPPING_VERSION = "assist2009-mt-topic-v1"
EXCLUSIONS = (
    "", "scaffold", "repeat_problem", "unverified_answer_type", "help_before_first_attempt",
    "first_action_unknown", "unverified_first_answer", "contradictory_correct_and_help", "__unknown__",
)
COARSE_TO_PRODUCT = {
    "LINEAR_EQUATION": "linear_isolation",
    "ARITHMETIC": "signed_operations",
    "QUADRATIC_EQUATION": "quadratic_roots",
    "LINEAR_SYSTEM": "system_completeness",
    "POLYNOMIAL_BASIC": "distributive_law",
}


def _product_to_source() -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for source_id, (product_skill, _name) in SKILL_MAP.items():
        grouped.setdefault(product_skill, []).append(str(source_id))
    return {key: tuple(values) for key, values in grouped.items()}


PRODUCT_TO_SOURCE = _product_to_source()


def expand(skill_ids) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Return source ids, mapped product skills, and skills with no source id."""
    sources: list[str] = []
    products: list[str] = []
    unmapped: list[str] = []
    for raw in skill_ids or ():
        fine = COARSE_TO_PRODUCT.get(str(raw), str(raw))
        mapped = PRODUCT_TO_SOURCE.get(fine)
        if not mapped:
            if str(raw) not in unmapped:
                unmapped.append(str(raw))
            continue
        if fine not in products:
            products.append(fine)
        for source in mapped:
            if source not in sources:
                sources.append(source)
    return tuple(sources), tuple(products), tuple(unmapped)


def _layout_ok(package) -> bool:
    skills = getattr(package, "skills", None)
    return bool(skills) and package.item_size == len(skills) + 2 and package.event_size == package.item_size + 14 + len(EXCLUSIONS)


def query_vector(package, source_ids):
    """Fractional source-skill query. A missing mapped id is a refusal, not OOV."""
    if not _layout_ok(package):
        return None
    index = {skill: position for position, skill in enumerate(package.skills)}
    distinct: list[str] = []
    for source in source_ids:
        if source not in index:
            return None
        if source not in distinct:
            distinct.append(source)
    values = np.zeros(package.item_size, np.float32)
    if not distinct:
        values[-1] = 1
        return values
    share = 1 / len(distinct)
    for source in distinct:
        values[index[source]] += share
    return values


def event_vector(package, source_ids, *, correct: bool, prior_problem_seen: bool):
    """One eligible product attempt in the observation layout the weights expect.

    The row is not an ASSISTments record. It uses that schema's numeric slots:
    correct one-hot, label eligible, original, first action 0, no hints,
    one attempt, and the empty exclusion.
    """
    item = query_vector(package, source_ids)
    if item is None:
        return None
    values = np.zeros(package.event_size, np.float32)
    values[: package.item_size] = item
    offset = package.item_size
    values[offset + (1 if correct else 0)] = 1
    values[offset + 3] = 1
    values[offset + 4] = 1
    values[offset + 5] = 1
    values[offset + 11] = math.log1p(1) / math.log(101)
    values[offset + 13] = 1 if prior_problem_seen else 0
    values[offset + 14] = 1
    return values


def _eligible(event) -> bool:
    return (
        event.event_type == "attempt_assessed"
        and event.evidence_kind == "independent"
        and event.correctness in {"correct", "incorrect"}
        and event.completion_scope == "full_problem"
        and event.response_format == "free_response"
        and event.task_purpose not in {"diagnostic", "error_analysis"}
        and not event.prior_task_attempt
        and not event.target_answer_exposed_before_attempt
        and not event.provenance_uncertain
        and not event.duplicate_response
    )


def replay_state(package, history):
    if not _layout_ok(package):
        return None, 0
    state = package.initial_state()
    seen: set[str] = set()
    updates = 0
    for event in valid_events(history):
        if not _eligible(event):
            continue
        sources, _products, _unmapped = expand(event.skill_ids)
        if not sources:
            continue
        vector = event_vector(package, sources, correct=event.correctness == "correct", prior_problem_seen=event.problem_id in seen)
        if vector is None:
            continue
        state = package.update(state, vector)
        seen.add(event.problem_id)
        updates += 1
    return state, updates


def forecast_for(package, history, skill_ids) -> dict:
    """Calibrated source-domain probability for the mapped subset of ``skill_ids``."""
    sources, products, unmapped = expand(skill_ids)
    result = {
        "probability": None,
        "probability_source": "none",
        "coverage_status": "unsupported_target",
        "product_runtime_enabled": False,
        "controls_teaching": False,
        "mapping_version": MAPPING_VERSION,
        "source_skill_ids": list(sources),
        "mapped_product_skills": list(products),
        "unmapped_skill_ids": list(unmapped),
        "partial_coverage": bool(sources) and bool(unmapped),
        "learning_effect_verified": False,
        "history_updates": 0,
        "reason": "no mapped ASSISTments skill in assist2009-mt-topic-v1; probability stays empty",
    }
    if package is None or not sources:
        return result
    query = query_vector(package, sources)
    state, updates = replay_state(package, history)
    if query is None or state is None:
        result["reason"] = "trained checkpoint feature layout does not match this package"
        return result
    probability = float(package.predict_proba(state, query))
    if not math.isfinite(probability):
        result["reason"] = "trained model returned a non-finite probability"
        return result
    result.update(
        probability=probability,
        probability_source="assist2009_trained_dkt",
        coverage_status="mapped_source_skills",
        product_runtime_enabled=True,
        controls_teaching=True,
        history_updates=updates,
        reason="trained ASSISTments DKT via assist2009-mt-topic-v1; not a calibrated MathTutor mastery grade",
    )
    return result
