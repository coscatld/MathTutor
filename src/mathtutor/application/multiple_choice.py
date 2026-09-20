"""Versioned, deterministic choices for the verifier-covered practice families.

Only call with an exact VERIFIED solution. Offsets preserve answer type and
cannot equal the verified answer (rational arithmetic, no LLM answer keys).
"""
from fractions import Fraction
from hashlib import sha256

from mathtutor.domain.hashing import content_hash

CHOICE_VERSION = "verified_choices_v1"


def _fraction(value):
    return Fraction(value["n"], value["d"])


def make_choices(problem, candidate, *, salt: str):
    final = candidate.final_answer
    kind = final["kind"]

    def answer(offset):
        if kind == "rational":
            return str(_fraction(final["value"]) + offset)
        if kind == "polynomial":
            coeffs = {int(k): _fraction(v) for k, v in final["coeffs"].items()}
            coeffs[0] = coeffs.get(0, Fraction()) + offset
            return " + ".join(f"({value})" + (f"{final['var']}" + (f"^{degree}" if degree > 1 else "") if degree else "")
                              for degree, value in sorted(coeffs.items(), reverse=True) if value) or "0"
        if kind == "roots" and final["roots"] and all(r["kind"] == "rational" for r in final["roots"]):
            # Shift the entire finite root set, not just one root.
            return ", ".join(str(_fraction(r["value"]) + offset) for r in final["roots"])
        if kind == "assignments":
            return "; ".join(f"{var}={_fraction(value) + offset}" for var, value in sorted(final["values"].items()))
        raise ValueError("当前题型尚无经过验证的单选题选项模板")

    values = [answer(offset) for offset in (0, 1, -1, 2)]
    values.sort(key=lambda value: sha256(f"{CHOICE_VERSION}:{salt}:{value}".encode()).hexdigest())
    choices = [{"id": chr(65 + i), "text": value} for i, value in enumerate(values)]
    version = content_hash({"schema": CHOICE_VERSION, "problem": problem.content_hash, "choices": choices, "salt": salt})
    from uuid import uuid4
    from mathtutor.learning.attempt_parser import parse_student_attempt
    from mathtutor.learning.attempt_verifier import verify_attempt
    outcomes = [verify_attempt(parse_student_attempt(attempt_submission_id=uuid4(), student_id=uuid4(),
        cycle_id=uuid4(), raw_text=option["text"], attempt_index=1), problem, candidate).correctness.value for option in choices]
    if sorted(outcomes) != ["correct", "incorrect", "incorrect", "incorrect"]:
        raise ValueError("选项必须有且仅有一个可验证的完整正确答案")
    return {"format": "single_choice", "version": version, "options": choices}


def resolve_choice(choices, option_id, version):
    if not choices or version != choices["version"]:
        raise ValueError("选项已更新，请重新同步题目。")
    for option in choices["options"]:
        if option["id"] == option_id:
            return option["text"]
    raise ValueError("请选择当前题目的一个有效选项。")
