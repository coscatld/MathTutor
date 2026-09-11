"""Project observed student work without smuggling reference answers into Writer.

Verifier records may contain expected roots and diagnostic comparisons. These
are private facts, not student progress or an additional disclosure channel.
"""
from copy import deepcopy


def verified_claim_view(claim):
    kind = claim.get("claim", "")
    if kind == "equivalent_equation":
        return {"claim": kind}  # its private root/roots certify equivalence
    return {key: deepcopy(value) for key, value in claim.items()
            if key in {"claim", "value", "variable", "coeffs", "roots", "equations_checked"}}


def progress_view(rows):
    return tuple({"assessment_id": row["assessment_id"], "text": row["text"],
                  "verified_claims": [verified_claim_view(claim) for claim in row.get("verified_claims", [])]}
                 for row in rows)


def assessment_view(rows):
    result = []
    for row in rows:
        public = {key: deepcopy(value) for key, value in row.items() if key in {
            "assessment_id", "raw_text", "assessment_scope", "math_validity", "task_completion",
            "misconception_candidates", "help_before_attempt", "evidence_kind"}}
        public["verified_steps"] = [verified_claim_view(claim) for claim in row.get("verified_steps", [])]
        public["invalid_claims"] = [{key: deepcopy(value) for key, value in claim.items()
                                    if key in {"claim", "actual", "reason", "variable"}}
                                   for claim in row.get("invalid_claims", [])]
        public["remaining_requirements"] = [{"requirement": claim["requirement"]}
                                            for claim in row.get("remaining_requirements", []) if "requirement" in claim]
        result.append(public)
    return tuple(result)
