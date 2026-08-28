"""Deterministic parse → solve → verify pipeline (design doc §4.1 stages 2/5).

- :mod:`~mathtutor.solving.parser` — text/LaTeX → canonical
  problem (MVP families, fail closed).
- :mod:`~mathtutor.solving.solver` — canonical problem →
  candidate solution with replayable steps.
- :mod:`~mathtutor.solving.verifier` — independent checks and
  the VERIFIED/FAILED decision.
"""

from __future__ import annotations

from mathtutor.solving.parser import ParseOutcome, ParsedProblem, parse_problem
from mathtutor.solving.solver import SolveOutcome, solve_problem
from mathtutor.solving.verifier import POLICIES, VerificationPolicy, verify

__all__ = ["POLICIES", "ParseOutcome", "ParsedProblem", "SolveOutcome", "VerificationPolicy", "parse_problem", "solve_problem", "verify"]
