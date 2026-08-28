"""Shared pedagogy exceptions."""


class DisclosurePolicyViolation(Exception):
    """A teaching action requested content the policy cannot authorize."""


__all__ = ["DisclosurePolicyViolation"]
