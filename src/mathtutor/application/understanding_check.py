"""Small two-operation tasks; all candidates still need independent verification.

These are check candidates, never answers or mastery claims. Changing the
ordinal allows another check without repeating a previously exposed item.
"""
from __future__ import annotations


def check_statement(problem_type: str, ordinal: int = 0) -> str:
    offset = max(0, ordinal)
    if problem_type == "arithmetic":
        return f"({offset + 8}-3)*2"
    if problem_type == "polynomial":
        return f"2(z+{offset + 3})+3z"
    if problem_type == "linear":
        return f"3z+2={3 * (offset + 5) + 2}"
    if problem_type == "quadratic":
        first, second = offset + 3, offset + 4
        return f"z^2-{first + second}z+{first * second}=0"
    if problem_type == "linear_system":
        return f"u+v={offset + 9};u-v={offset + 3}"
    raise ValueError("This family has no independently verifiable understanding check")
