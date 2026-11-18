"""Small, attributable concept explanations from the local foundation curriculum."""

from __future__ import annotations

import re
from dataclasses import dataclass

from mathtutor.application.exploration_evidence import text_hash
from mathtutor.application.foundation_references import authored_reference
from mathtutor.learning.skill_graph import GRAPH_VERSION, SKILLS


VERSION = "offline-foundations-v1"
_CONCEPTS = (
    ("equality_preservation", r"移项|等式(?:的)?性质|等式两边|两边同(?:时)?(?:加|减)|\btranspos(?:e|ing|ition)\b"),
    ("fraction_operations", r"通分|约分|分数(?:加|减|乘|除|运算)|\bcommon denominator\b"),
    ("distributive_law", r"分配律|去括号|\bdistributive\b"),
    ("combine_like_terms", r"同类项|\blike terms\b"),
)
_EXPLANATIONS = {
    "equality_preservation": (
        "移项是等式两边同时加或减同一项后的简写。"
        "例如由 A+t=B，两边都减去 t，得到 A=B−t；变号来自同减 t，"
        "不是某一项跨过等号就自动改变性质。"
        "这里各表达式须有定义；乘除变形还要检查乘数、除数是否为零，不能把所有同做运算都当作等价变形。"
    ),
    "fraction_operations": (
        "分数相加或相减，要先把份的大小统一：通分把它们写成分母相同的等值分数，再加减分子。"
        "分数相乘则分子相乘、分母相乘，不要求先通分；分数相除可乘除数的倒数，但除数必须非零。"
        "约分只能约去分子与分母共有的非零因子，不能跨加法项直接约去。"
    ),
    "distributive_law": (
        "分配律把一个数乘一个和，改写成分别乘每一项再求和。"
        "所以去括号时，括号外的因子要作用于每一项；括号前是负号时，相当于每一项都乘负一。"
    ),
    "combine_like_terms": (
        "同类项的字母和对应指数必须相同；合并时只把系数相加，字母部分保持原样。"
        "不同次数的项不能合成一个同类项，常数项可彼此合并。"
    ),
}
_ACCOUNTING = (
    "生活收支类比中的正负号取决于记账约定，例如把收入记为正、支出记为负；"
    "移项变号则来自等式两边同加或同减。类比可以帮助记忆，"
    "但不能代替等量关系，也不能把一笔收入改写成支出后就当作同一笔账。"
)


@dataclass(frozen=True)
class OfflineExplanation:
    text: str
    references: tuple[dict, ...]

    def receipt(self):
        return {"policy": VERSION, "scope": "local_foundation_concept",
                "source_state": "authored_local", "math_scope": "explanation_not_student_assessment",
                "references": list(self.references), "text": self.text, "text_sha256": text_hash(self.text)}


def offline_concept_reply(text: str) -> OfflineExplanation | None:
    if not text or len(text) > 2000 or not re.search(r"[\u4e00-\u9fff]", text):
        return None
    selected = [skill for skill, pattern in _CONCEPTS if re.search(pattern, text, re.I)][:2]
    if not selected:
        return None
    references, paragraphs = [], []
    for skill_id in selected:
        skill = SKILLS[skill_id]
        explanation = _EXPLANATIONS[skill_id]
        if skill_id == "equality_preservation" and re.search(r"收支|收入|支出|记账|账本", text):
            explanation += "\n\n" + _ACCOUNTING
        references.append(authored_reference(
            "foundation-concept:" + skill_id, version=VERSION, prompt=skill.label,
            explanation=explanation, conditions=skill.definition, skill_id=skill_id,
            conditions_version=GRAPH_VERSION, authorship="MathTutor application-authored foundation explanation",
            review_scope="Fixed local explanation; no model generation or automatic assessment of student reasoning.",
        ))
        paragraphs.append(explanation)
    paragraphs.append("资料：MathTutor 内置数学基础。这里只说明上述规则；若需结合更多条件继续解释，可在设置中配置模型，或发一道基础练习。")
    return OfflineExplanation("\n\n".join(paragraphs), tuple(references))
