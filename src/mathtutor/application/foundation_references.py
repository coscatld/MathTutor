"""Versioned, authored foundation material; distinct from community sources."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

from mathtutor.application.exploration_evidence import text_hash
from mathtutor.learning.skill_graph import GRAPH_VERSION, SKILLS

FRACTION_UNITS = ("g3a-u8-", "g5b-u4-", "g5b-u6-", "g6a-u1-", "g6a-u3-")
DOMAIN_REVIEW_VERSION = "fraction-domain-review-v1"


def authored_reference(reference_id, *, version, prompt, explanation, answer="", check="", conditions="", **metadata):
    text = "\n".join(value for value in (
        "问题：" + prompt, "解释：" + explanation,
        "参考答案：" + answer if answer else "",
        "数值自检式：" + check if check else "",
        "适用范围：" + conditions if conditions else "",
    ) if value)
    return {"id": reference_id, "provider": "mathtutor", "kind": "authored_foundation",
            "version": version, "prompt": prompt, "explanation": explanation,
            "reference_answer": answer, "answer_check": check, "conditions": conditions,
            "text": text, "text_sha256": text_hash(text), **metadata}


@lru_cache(maxsize=1)
def _fraction_family():
    content = json.loads(files("mathtutor.question_bank").joinpath("curriculum_questions_v2.json").read_text(encoding="utf-8"))
    version = content["version"]
    condition = SKILLS["fraction_operations"].definition
    result = {}
    for point, questions in content["questions"].items():
        if not point.startswith(FRACTION_UNITS):
            continue
        for row in questions:
            reference_id = "curriculum:" + row["id"]
            result[reference_id] = authored_reference(reference_id, version=version,
                prompt=row["text"], explanation=row["explanation"], answer=row["reference_answer"],
                check=row["verification"].get("answer_check", ""), conditions=condition,
                curriculum_point=point, license=content["license"], authorship=content["authorship"],
                conditions_version=GRAPH_VERSION, student_steps_auto_verified=False,
                review_scope="Original reference exercise; arithmetic checks do not prove all prose or learner reasoning.")
    key = "review:fraction-domain"
    result[key] = authored_reference(key, version=DOMAIN_REVIEW_VERSION,
        prompt="分数运算的定义域条件是什么？",
        explanation="分数的分母不能为零。除以一个分数还要求该分数本身非零；零没有乘法倒数。",
        conditions=condition, conditions_version=GRAPH_VERSION,
        authorship="MathTutor application-authored domain clarification, added in this iteration",
        review_scope="AI-authored clarification, separate from the original exercises; exact rational boundary regression, not human expert certification.")
    return result


def fraction_foundations():
    return {key: dict(value) for key, value in _fraction_family().items()}
