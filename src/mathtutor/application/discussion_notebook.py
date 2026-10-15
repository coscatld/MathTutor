"""Durable original question and discussion notes, never assessment evidence."""
from __future__ import annotations
import re

SCHEMA = "mt-discussion-v1"
FOLLOWUP = re.compile(r"^(?:为什么|为啥|怎么|我(?:还是|又|真)?(?:看不懂|没看懂|不懂|不会|觉得|认为)|看不懂|还是|这(?:一步|个|是|题)|那|刚才|然后|所以|能不能|不用|继续|换(?:个|一种)说法)")


def starts_new_question(text: str) -> bool:
    """A student's short formula is usually a step, not a replacement task."""
    text = text.strip()
    if FOLLOWUP.match(text):
        return False
    if (re.search(r"为什么|为何|看不懂|不明白|怎么想到|怎么算", text)
            and not re.match(r"^(?:换题|新题|下一题|已知|若)", text)):
        return False
    return bool(re.match(r"^(?:换题[：:]?|新题[：:]?|下一题[：:]?|已知|若|求|计算|化简|证明|解(?:方程|不等式)|函数|数列)", text)
                or re.search(r"_{3,}|（\s*）|\(\s*\)", text))


def public_discussion(context):
    if not context or context.get("schema_version") != SCHEMA:
        return None
    return {"problem_id": context["problem_id"], "display_text": context["display_text"],
            "skill_ids": [], "lifecycle": "discussion", "graphable": False,
            "current_subgoal": {"id": "discussion-focus", "prompt_target": context.get("student_focus", ""), "status": "discussion"}}


def model_context(context):
    if not public_discussion(context):
        return None
    return {"original_question": context["display_text"], "student_focus": context.get("student_focus", ""),
            "recent_explanations": context.get("discussed", []), "assessment_status": "not_machine_verified"}
