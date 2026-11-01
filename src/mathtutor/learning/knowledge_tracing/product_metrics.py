"""§17 funnel metrics over committed facts, with explicit missing denominators.

No started-cycle denominator is reconstructed from successful attempts. That
would silently drop failures and exits. A supported, unambiguous start must be
recorded as ``problem_started(eligible_cycle=True)`` by the application.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

from .dataset import sequences
from .events import INDEPENDENT_OPPORTUNITY_POLICY, independent_opportunity, valid_events

PRODUCT_FUNNEL_SCHEMA = "product_funnel_v2"


def proportion(numerator, denominator, *, unavailable_reason=""):
    return {
        "numerator": numerator, "denominator": denominator,
        "value": numerator / denominator if denominator else None,
        "status": "observed" if denominator else "unavailable",
        "uncertainty": "样本有限，不能推断学习效果" if 0 < denominator < 30 else "描述性观察，不是因果效果" if denominator else "没有可用分母",
        **({"reason": unavailable_reason} if denominator == 0 and unavailable_reason else {}),
    }


def _whole_attempt(event):
    return (event.event_type == "attempt_assessed" and event.completion_scope == "full_problem"
            and event.task_purpose not in {"diagnostic", "error_analysis"})


def _exposure(event):
    return event.event_type in {"help_possibly_exposed", "help_presented"}


def _solving_category(event, *, help_before):
    """One completion bucket per cycle; recorded evidence_kind alone is insufficient."""
    if event.response_format == "single_choice" or event.options_exposed:
        return "solved_diagnostic"
    if independent_opportunity(event) and not help_before:
        return "solved_independent"
    if event.provenance_uncertain or event.evidence_kind not in {"independent", "assisted"}:
        return "solved_help_provenance_unknown"
    if event.evidence_kind == "assisted" or event.prior_help_event_ids or help_before:
        return "solved_assisted"
    if event.prior_task_attempt:
        return "solved_after_retry"
    return "solved_help_provenance_unknown"


def product_funnel(events, *, turn_records=()):
    """Return counts and ratios, never turn missing data into 0% failures.

    ``turn_records`` is optional trusted, complete pre-completion telemetry: one ``turn_id``,
    ``student_id``, ``cycle_id``, ``student_math_message`` and
    ``tutor_presented`` flag per logical turn. Retry frames reuse turn_id.
    Without these actual pairs round statistics are unavailable, not zero.

    Version 2 excludes choices and prior option exposure from independent
    opportunities/successes. New diagnostic/retry buckets partition completed
    cycles with the retained buckets; started denominators are unchanged.
    Replaying old facts changes the metric policy, not their recorded labels.
    """
    by_cycle = defaultdict(list)
    for history in sequences(events):
        for event in valid_events(history):
            by_cycle[(event.student_id, event.cycle_id)].append(event)
    eligible, unknown_eligibility, ineligible = {}, 0, 0
    for key, history in by_cycle.items():
        start = next((x for x in history if x.event_type == "problem_started"), None)
        if start is None or start.eligible_cycle is None:
            unknown_eligibility += 1
        elif start.eligible_cycle:
            eligible[key] = history
        else:
            ineligible += 1
    counts = defaultdict(int)
    cycle_details = []
    request_pairs, approved_pairs = set(), set()
    target_authorized, unexpected_target, missing_authorization = set(), set(), set()
    for key, history in eligible.items():
        start = next(x for x in history if x.event_type == "problem_started")
        attempts = [x for x in history if _whole_attempt(x)]
        relevant_help = [x for x in history if _exposure(x)]
        target = [x for x in relevant_help if x.target_answer_exposed]
        target_seq = min((x.event_seq for x in target), default=float("inf"))
        completed_before = next((x for x in attempts if x.correctness == "correct"
            and not x.duplicate_response and not x.target_answer_exposed_before_attempt
            and x.event_seq < target_seq), None)
        if completed_before:
            counts["student_solved"] += 1
            category = _solving_category(completed_before, help_before=any(
                x.event_seq < completed_before.event_seq for x in relevant_help))
            counts[category] += 1
        first = next((x for x in attempts if not x.duplicate_response), None)
        first_exposure_seq = min((x.event_seq for x in history
            if _exposure(x) or x.event_type == "options_exposed"), default=float("inf"))
        independent_first = (first is not None and independent_opportunity(first)
                             and first.event_seq < first_exposure_seq)
        if independent_first:
            counts["first_independent_opportunity"] += 1
            if first.correctness == "correct":
                counts["first_independent_correct"] += 1
            elif first.correctness in {None, "unknown"}:
                counts["first_independent_unknown"] += 1
        # Help requested after a completed independent solution is review,
        # not an assisted-solving opportunity retroactively added to the task.
        had_help_while_solving = any(x.event_seq < target_seq
            and (completed_before is None or x.event_seq < completed_before.event_seq) for x in relevant_help)
        if had_help_while_solving:
            counts["helped_cycles"] += 1
            counts["helped_completed"] += int(completed_before is not None)
        after_answer = [x for x in attempts if x.event_seq > target_seq or x.target_answer_exposed_before_attempt]
        if after_answer:
            counts["post_solution_attempted_cycles"] += 1
            counts["post_solution_correct_cycles"] += int(any(x.correctness == "correct" for x in after_answer))
        if start.task_purpose == "transfer":
            counts["transfer_started"] += 1
            counts["transfer_first_independent_correct"] += int(independent_first and first.correctness == "correct")
        end = next((x for x in reversed(history) if x.event_type == "problem_ended"), None)
        if not completed_before:
            if end and end.lifecycle_status == "exited":
                counts["exited_unsolved"] += 1
                outcome = "exited"
            elif end and end.lifecycle_status == "failed":
                counts["failed_unsolved"] += 1
                outcome = "failed"
            else:
                counts["unknown_or_incomplete"] += 1
                outcome = "unknown_or_incomplete"
        else:
            outcome = "student_solved_before_answer"
        cycle_details.append({"student_id": key[0], "cycle_id": key[1], "outcome": outcome,
                              "whole_attempts": len(attempts), "answer_exposed": bool(target)})
        for event in history:
            if event.event_type == "help_requested" and event.help_kind == "solution" and event.request_id:
                request_pairs.add((*key, event.request_id))
            if event.event_type == "help_presented" and event.target_answer_exposed and event.request_id:
                approved_pairs.add((*key, event.request_id))
            if _exposure(event):
                identity = (*key, event.delivery_id or event.event_id)
                if event.target_answer_authorized is None:
                    missing_authorization.add(identity)
                elif event.target_answer_authorized is False:
                    # Denominator: teaching deliveries without explicit
                    # permission to show a target answer, whether or not
                    # an answer was actually exposed. Authorized solutions
                    # do not dilute this safety metric's denominator.
                    target_authorized.add(identity)
                    if event.target_answer_exposed:
                        unexpected_target.add(identity)
    n = len(eligible)
    pairs = {}
    for turn in turn_records:
        key = (str(turn.get("student_id", "")), str(turn.get("cycle_id", "")))
        if key not in eligible or not turn.get("turn_id"):
            continue
        identity = (*key, turn["turn_id"])
        previous = pairs.get(identity, {})
        pairs[identity] = {"student_math_message": previous.get("student_math_message", False) or bool(turn.get("student_math_message")),
                           "tutor_presented": previous.get("tutor_presented", False) or bool(turn.get("tutor_presented"))}
    round_counts = defaultdict(int)
    for identity, pair in pairs.items():
        if pair["student_math_message"] and pair["tutor_presented"]:
            round_counts[identity[:2]] += 1
    solved_keys = {(x["student_id"], x["cycle_id"]) for x in cycle_details if x["outcome"] == "student_solved_before_answer"}
    observed_rounds = sorted(value for key, value in round_counts.items() if key in solved_keys)
    return {
        "schema_version": PRODUCT_FUNNEL_SCHEMA,
        "independent_opportunity_policy": INDEPENDENT_OPPORTUNITY_POLICY,
        "learning_effect_verified": False,
        "eligibility": {"supported_started": n, "unknown_start_eligibility": unknown_eligibility, "explicitly_ineligible": ineligible},
        "student_problem_solved": proportion(counts["student_solved"], n, unavailable_reason="missing_supported_problem_started_events"),
        "solving_breakdown": {key: counts[key] for key in ("solved_independent", "solved_assisted", "solved_diagnostic", "solved_after_retry", "solved_help_provenance_unknown", "exited_unsolved", "failed_unsolved", "unknown_or_incomplete")},
        "first_independent_correct": proportion(counts["first_independent_correct"], counts["first_independent_opportunity"]),
        "first_independent_unknown": counts["first_independent_unknown"],
        "assisted_completion": proportion(counts["helped_completed"], counts["helped_cycles"]),
        "post_solution_reproduction": proportion(counts["post_solution_correct_cycles"], counts["post_solution_attempted_cycles"]),
        "transfer_success": proportion(counts["transfer_first_independent_correct"], counts["transfer_started"]),
        "system_solution_availability": proportion(len(request_pairs & approved_pairs), len(request_pairs), unavailable_reason="missing_correlated_solution_request_and_presented_events"),
        "unexpected_target_exposure": proportion(len(unexpected_target), len(target_authorized), unavailable_reason="missing_explicit_authorization_facts"),
        "exposure_authorization_unknown": len(missing_authorization - target_authorized),
        "completion_rounds": {"observed_completed_cycles": len(observed_rounds), "completed_cycles_without_turn_telemetry": len(solved_keys) - len(observed_rounds),
            "median": median(observed_rounds) if observed_rounds else None,
            "p90": observed_rounds[max(0, (9 * len(observed_rounds) + 9) // 10 - 1)] if observed_rounds else None,
            "status": "observed" if observed_rounds else "unavailable"},
        "invitation_acceptability": {"value": None, "status": "unavailable", "reason": "requires_owner_scoped_offer_release_acceptance_receipts"},
        "cycles": cycle_details,
    }
