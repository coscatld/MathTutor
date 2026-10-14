"""Write backend-built scenes as fixtures for the frontend contract test.

    PYTHONPATH=src python scripts/export_scene_fixtures.py
"""
import json
import math
from pathlib import Path

from mathtutor.application.scene import build_scene, scene_from_text

REQUESTS = [
    "画出 x^2/4+y^2/3=1",
    "画出 x^2/4+y^2/3=1 和 y=kx+1",
    "画出圆 (x-1)^2+(y-2)^2=4",
    "画出 y>x^2-1 的区域",
    "画出 x^2+y^2<=4 与 y>=x",
    "画出 r=2(1+cos θ)",
    "画出 y=a*sin(bx)",
    "画出 x^2-y^2=1 和 y=2x",
    "画出 y^2=4x 和 y=x-1",
    "画出 y=ln(x) 和 y=e^x 和 y=x",
    "演示椭圆 x^2/4+y^2/3=1 上的动点 P(2cos t, √3 sin t) 到焦点 F(1,0) 的距离",
    "画出三角形 ABC，A(0,0)，B(4,0)，C(m,3)，三角形ABC的面积",
    "演示圆 x^2+y^2=4 上的动点 P(2cos t,2sin t)，A(-2,0)，B(2,0)，∠APB",
]

DEFINITIONS = [{
    "title": "椭圆上的动点到焦点的距离",
    "params": [{"name": "t", "min": 0, "max": 2 * math.pi, "step": 0.01, "value": 0.8, "animate": True}],
    "objects": [
        {"id": "E", "type": "implicit", "equation": "x^2/4+y^2/3=1", "label": "椭圆"},
        {"id": "F", "type": "point", "x": "1", "y": "0", "label": "F"},
        {"id": "P", "type": "point", "x": "2cos(t)", "y": "sqrt(3)sin(t)", "label": "P", "trace": True},
        {"id": "PF", "type": "segment", "from": "P", "to": "F"},
        {"id": "O", "type": "point", "x": "0", "y": "0", "label": "O"},
        {"id": "tri", "type": "polygon", "points": ["O", "P", "F"], "fill": True},
        {"id": "c", "type": "circle", "center": "F", "radius": "dist(P,F)"},
    ],
    "readouts": [{"label": "|PF|", "expr": "dist(P,F)"}, {"label": "∠OPF", "expr": "angle(O,P,F)"},
                 {"label": "面积", "expr": "area(O,P,F)"}],
}, {
    "title": "函数切线随切点移动",
    "params": [{"name": "a", "min": -2, "max": 2, "step": 0.05, "value": 1, "animate": True}],
    "objects": [
        {"id": "f", "type": "function", "expr": "x^3-3x", "label": "y=x³-3x"},
        {"id": "T", "type": "tangent", "of": "f", "at": "a"},
        {"id": "A", "type": "point", "x": "a", "y": "a^3-3a", "label": "A"},
        {"id": "L", "type": "text", "x": "a", "y": "a^3-3a+1", "text": "切点"},
    ],
    "readouts": [{"label": "切线斜率", "expr": "3a^2-3"}],
}]


def main():
    scenes = []
    for text in REQUESTS:
        scene = scene_from_text(text)
        assert scene is not None, text
        scenes.append({"request": text, "scene": scene})
    for definition in DEFINITIONS:
        scenes.append({"request": definition["title"], "scene": build_scene(definition, source="model")})
    out = Path("web/tests/fixtures/backend-scenes.json")
    out.write_text(json.dumps(scenes, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(scenes)} scenes to {out}")


if __name__ == "__main__":
    main()
