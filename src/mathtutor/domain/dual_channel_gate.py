"""Dual-channel gate: source support and mathematical correctness, merged.

Two independent channels judge a tutor output:

- the SOURCE channel answers "is this sentence backed by text the system
  actually read?" (citation receipts, verbatim quotes, support checks);
- the MATH channel answers "does this mathematical conclusion hold?"
  (parser + deterministic solver + attempt verifier).

Neither channel may stand in for the other: a verbatim textbook quote can
carry a wrong derivation, and a correct derivation can have no source. This
module is the ONE place that combines the two states into (a) how a claim is
displayed and (b) whether an observation may become a learning fact. Every
decision is a pure table lookup so the policy is auditable and testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

GATE_POLICY_VERSION = "mt-dual-channel-gate-v1"


class SourceState(StrEnum):
    QUOTE_OK = "quote_ok"        # verbatim quote of a range actually read
    SUMMARY_OK = "summary_ok"    # synthesis confirmed by the support checker
    REJECTED = "rejected"        # unread source, mismatch, changed hash, unsupported
    NONE = "none"                # no source claim involved


class MathState(StrEnum):
    CORRECT = "correct"
    PARTIAL = "partial"
    INCORRECT = "incorrect"
    UNDETERMINED = "undetermined"  # parsed, but cannot be judged reliably
    UNSUPPORTED = "unsupported"    # outside deterministic coverage / unparseable
    NONE = "none"                  # no mathematical assertion involved


class Treatment(StrEnum):
    SHOW = "show"                          # show as-is with its labels
    SHOW_MATH_UNVERIFIED = "show_math_unverified"  # show, math marked as not verified
    SHOW_SOURCE_MATH_CONFLICT = "show_source_math_conflict"  # verbatim quote kept, math warning
    DROP_MATH = "drop_math"                # remove the failed mathematical conclusion
    WITHHOLD = "withhold"                  # nothing of this claim reaches the student


@dataclass(frozen=True, slots=True)
class GateDecision:
    treatment: Treatment
    source_label: str
    math_label: str
    policy_version: str = GATE_POLICY_VERSION

    @property
    def visible(self) -> bool:
        return self.treatment not in {Treatment.WITHHOLD, Treatment.DROP_MATH}


_SOURCE_LABELS = {
    SourceState.QUOTE_OK: "原文摘录",
    SourceState.SUMMARY_OK: "AI 总结（已做证据覆盖检查，仍需核对）",
    SourceState.REJECTED: "",
    SourceState.NONE: "",
}
_MATH_LABELS = {
    MathState.CORRECT: "数学结论已验证",
    MathState.PARTIAL: "步骤有效，尚未完成",
    MathState.INCORRECT: "数学结论未通过验证",
    MathState.UNDETERMINED: "数学结论未核验",
    MathState.UNSUPPORTED: "数学结论未核验（超出确定性验证范围）",
    MathState.NONE: "",
}


def decide(source: SourceState, math: MathState) -> GateDecision:
    """Display treatment for one claim. Pure; the full table is unit-tested.

    | source \\ math | correct/partial | incorrect                  | undetermined/unsupported | none |
    |---------------|-----------------|----------------------------|--------------------------|------|
    | QUOTE_OK      | SHOW            | SHOW_SOURCE_MATH_CONFLICT  | SHOW_MATH_UNVERIFIED     | SHOW |
    | SUMMARY_OK    | SHOW            | DROP_MATH                  | SHOW_MATH_UNVERIFIED     | SHOW |
    | REJECTED      | WITHHOLD        | WITHHOLD                   | WITHHOLD                 | WITHHOLD |
    | NONE          | SHOW            | DROP_MATH                  | SHOW_MATH_UNVERIFIED     | SHOW |

    A rejected source is never shown, whatever the math says: a correct
    number next to a forged citation would still present the forgery. A
    verbatim quote whose mathematics fails is kept (it IS what the source
    says) but flagged — this is the "source support != mathematical
    correctness" case. Model-authored text (summary / no source) with a
    failed conclusion is removed instead of being corrected by the model.
    """
    source, math = SourceState(source), MathState(math)
    if source is SourceState.REJECTED:
        treatment = Treatment.WITHHOLD
    elif math in {MathState.CORRECT, MathState.PARTIAL, MathState.NONE}:
        treatment = Treatment.SHOW
    elif math is MathState.INCORRECT:
        treatment = (Treatment.SHOW_SOURCE_MATH_CONFLICT if source is SourceState.QUOTE_OK
                     else Treatment.DROP_MATH)
    else:
        treatment = Treatment.SHOW_MATH_UNVERIFIED
    return GateDecision(treatment, _SOURCE_LABELS[source], _MATH_LABELS[math])


def math_state_from_correctness(value) -> MathState:
    """Map an attempt-verifier ``Correctness`` (enum or str) onto the channel."""
    raw = getattr(value, "value", value)
    try:
        return MathState(str(raw))
    except ValueError:
        return MathState.UNDETERMINED


# --- learning-fact admission -------------------------------------------------

#: The highest assistance level that still counts as "assisted"; at or above
#: L5 the complete verified solution was disclosed.
POST_SOLUTION_LEVEL = 5


def evidence_kind(math: MathState, *, max_assistance_level: int, diagnostic: bool = False,
                  turn_status: str = "COMPLETED", source: SourceState = SourceState.NONE,
                  channel: str = "tutoring") -> str | None:
    """What an observation may be recorded as; ``None`` = never a learning fact.

    One policy for every path:
    - knowledge-QA verification is a check of a claim, not a student attempt:
      it never writes a learning fact;
    - an output whose source channel rejected it, or a turn that did not
      complete, cannot justify a fact;
    - an unjudgeable attempt is recorded as ``ungradable`` (counted, never
      scored); diagnostic items stay ``diagnostic``;
    - otherwise the help that preceded the attempt decides the kind.
    """
    if channel != "tutoring":
        return None
    if source is SourceState.REJECTED or turn_status != "COMPLETED":
        return None
    if diagnostic:
        return "diagnostic"
    if MathState(math) in {MathState.UNDETERMINED, MathState.UNSUPPORTED, MathState.NONE}:
        return "ungradable"
    if max_assistance_level >= POST_SOLUTION_LEVEL:
        return "post_solution"
    return "assisted" if max_assistance_level > 0 else "independent"


__all__ = ["GATE_POLICY_VERSION", "GateDecision", "MathState", "SourceState", "Treatment",
           "decide", "evidence_kind", "math_state_from_correctness"]
