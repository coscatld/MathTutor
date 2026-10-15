"""Canvas drawing skill: the only way the tutor model can show a figure.

``SKILL_TEXT`` is the instruction text (``SKILL.md``) included in the system
message whenever ``draw_scene`` is offered. ``DRAW_SCENE_TOOL`` is the native
tool schema; the application validates every call with ``build_scene`` and
appends the rendered scene to the final message. ``enforce.sanitize_figures``
removes every other kind of figure from model-authored text.

This package does not import the scene module at import time, so that
``mathtutor.application.scene`` can reuse the same text for its prompt.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

SKILL_PATH = Path(__file__).with_name("SKILL.md")
# Mirrors the Scene v2 limits in mathtutor.application.scene (a test keeps them equal).
MAX_PARAMS, MAX_OBJECTS, MAX_READOUTS, MAX_LABEL = 4, 40, 8, 60
MAX_DRAWN, MAX_DRAW_ATTEMPTS = 2, 4


@lru_cache(maxsize=1)
def _raw() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def section(name: str) -> str:
    """The text between ``<!-- name -->`` and ``<!-- /name -->`` in SKILL.md."""
    match = re.search(rf"<!-- {name} -->\n(.*?)\n<!-- /{name} -->", _raw(), re.S)
    if match is None:
        raise RuntimeError(f"SKILL.md has no {name} section")
    return match.group(1).strip()


@lru_cache(maxsize=1)
def skill_text() -> str:
    """SKILL.md without the section markers."""
    text = re.sub(r"<!-- /?[a-z]+ -->", "", _raw())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


SKILL_TEXT = skill_text()
DEFINITION_FORMAT = section("format")
DRAWING_RULES = section("rules")

_EXPR = {"type": "string", "maxLength": 300}
_NUMBER = {"type": ["number", "string"]}
_INTERVAL = {"type": "array", "minItems": 2, "maxItems": 2, "items": _NUMBER}

DRAW_SCENE_TOOL = {"type": "function", "function": {
    "name": "draw_scene",
    "description": ("用应用的画布画一张数形结合示意图。只给定义（字符串表达式），坐标、交点和读数由应用计算。"
                    "返回 drawn（已画好，会附在回答后）或 rejected（附中文原因，可改正后再试）。"
                    "这是唯一能向学生展示图形的方式。"),
    "parameters": {
        "type": "object", "additionalProperties": False, "required": ["title", "objects"],
        "properties": {
            "title": {"type": "string", "maxLength": MAX_LABEL},
            "params": {"type": "array", "maxItems": MAX_PARAMS, "items": {
                "type": "object", "required": ["name", "min", "max"],
                "properties": {"name": {"type": "string", "maxLength": 1}, "min": _NUMBER, "max": _NUMBER,
                               "step": _NUMBER, "value": _NUMBER, "animate": {"type": "boolean"},
                               "label": {"type": "string", "maxLength": MAX_LABEL}}}},
            "objects": {"type": "array", "minItems": 1, "maxItems": MAX_OBJECTS, "items": {
                "type": "object", "required": ["id", "type"],
                "properties": {
                    "id": {"type": "string", "maxLength": 8},
                    "type": {"type": "string", "enum": ["function", "implicit", "parametric", "region", "point",
                                                        "segment", "line", "ray", "vector", "polygon", "circle",
                                                        "tangent", "text"]},
                    "expr": _EXPR, "equation": _EXPR, "inequality": _EXPR, "x": _EXPR, "y": _EXPR, "r": _EXPR,
                    "s_range": _INTERVAL, "domain": _INTERVAL, "trace": {"type": "boolean"},
                    "from": {"type": "string"}, "to": {"type": "string"},
                    "points": {"type": "array", "items": {"type": "string"}}, "fill": {"type": "boolean"},
                    "center": {"type": "string"}, "radius": _EXPR, "of": {"type": "string"}, "at": _EXPR,
                    "text": {"type": "string", "maxLength": MAX_LABEL},
                    "label": {"type": "string", "maxLength": MAX_LABEL}, "hidden": {"type": "boolean"}}}},
            "readouts": {"type": "array", "maxItems": MAX_READOUTS, "items": {
                "type": "object", "required": ["label", "expr"],
                "properties": {"label": {"type": "string", "maxLength": MAX_LABEL}, "expr": _EXPR,
                               "digits": {"type": "integer", "minimum": 0, "maximum": 10}}}}}}}}

_FIGURE_REQUEST = re.compile(r"画|作图|配图|配个图|图示|示意图|图像|图象|图形|可视化|数形结合|看图|plot|graph|draw", re.I)


def wants_figure(text: str) -> bool:
    """The student explicitly asks for a picture in free chat."""
    return bool(_FIGURE_REQUEST.search(str(text or "")))


_DRAWING_SUBJECT = re.compile(
    r"椭圆|抛物线|双曲线|反比例|正比例|一次函数|二次函数|函数|正弦|余弦|正切|三角形|四边形|"
    r"正方形|矩形|圆(?:的|心|周|内|外|上)|切线|渐近线|焦点|坐标|向量|轨迹|动点|几何|不等式|数形结合")
_DRAWING_FOLLOWUP = re.compile(
    r"(?:都可以|随便|你(?:来)?(?:定|选)|好(?:的|啊)?|可以|行|继续|画吧|为什么|怎么(?:看|理解|回事)|"
    r"没(?:看|听)?懂|不(?:太)?(?:明白|理解|懂)|再(?:讲|说|解释)(?:一下)?|讲讲)[。！？?!，,\s]*")


def can_offer_drawing(text: str, history: tuple[dict, ...] = ()) -> bool:
    """Let the model choose a canvas for math topics and short related replies.

    Check only the immediately preceding student topic; greetings and new
    unrelated topics keep the normal chat/streaming path.
    """
    current = str(text or "").strip()
    if wants_figure(current) or _DRAWING_SUBJECT.search(current):
        return True
    if not _DRAWING_FOLLOWUP.fullmatch(current):
        return False
    previous = list(history)
    if previous and previous[-1].get("role") == "student" and previous[-1].get("content", "").strip() == current:
        previous.pop()
    for item in reversed(previous[-20:]):
        if item.get("role") != "student":
            continue
        prior = str(item.get("content", "")).strip()
        if wants_figure(prior) or _DRAWING_SUBJECT.search(prior):
            return True
        if not _DRAWING_FOLLOWUP.fullmatch(prior):
            return False
    return False


__all__ = ["DEFINITION_FORMAT", "DRAWING_RULES", "DRAW_SCENE_TOOL", "MAX_DRAWN", "MAX_DRAW_ATTEMPTS", "SKILL_PATH",
           "SKILL_TEXT", "section", "skill_text", "wants_figure", "can_offer_drawing"]
