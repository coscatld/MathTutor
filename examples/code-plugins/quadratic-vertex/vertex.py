"""A minimal exact-arithmetic MathTutor code plugin.

Invoked via /vertex a b c where a,b,c are integer coefficients.
The host provides {"text": "...", "config": {...}}; do not read user files.
"""
from fractions import Fraction


def run(request: dict) -> dict:
    text = request.get("text", "")
    if not isinstance(text, str):
        return {"text": "请输入三个整数系数，如 /vertex 1 -4 3。"}
    parts = text.strip().split()
    if len(parts) != 3:
        return {"text": "格式：/vertex a b c，其中 a、b、c 均为整数且 a 不为 0。"}
    try:
        a, b, c = (int(part) for part in parts)
    except ValueError:
        return {"text": "系数必须为整数。"}
    if a == 0 or max(abs(a), abs(b), abs(c)) > 1000:
        return {"text": "要求 0 < |a| ≤ 1000，且 |b|、|c| ≤ 1000。"}

    h = Fraction(-b, 2 * a)
    k = Fraction(4 * a * c - b * b, 4 * a)
    discriminant = b * b - 4 * a * c
    return {
        "text": f"顶点坐标：({h}, {k})；判别式 Δ = {discriminant}。"
                "这是计算结果，不表示学生的解题步骤已验证。",
        "data": {
            "a": a,
            "b": b,
            "c": c,
            "vertex_x": str(h),
            "vertex_y": str(k),
            "discriminant": discriminant,
        },
    }
