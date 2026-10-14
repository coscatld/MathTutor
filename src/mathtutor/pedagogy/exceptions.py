"""Shared pedagogy exceptions."""


class DisclosurePolicyViolation(Exception):
    """A teaching action requested content the policy cannot authorize."""


class HintRequiredForSolution(DisclosurePolicyViolation):
    """The full solution was requested before the policy's hint minimum."""

    error_code = "HINT_REQUIRED"


__all__ = ["DisclosurePolicyViolation", "HintRequiredForSolution"]
