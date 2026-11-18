"""Closed rectangle constraints with exact witnesses for non-unique area."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from fractions import Fraction


_NUMBER = r"[+-]?[0-9]{1,6}(?:\.[0-9]{1,3})?"
_UNIT = r"(?:毫米|厘米|分米|千米|米|mm|cm|dm|km|m)"
_UNITS = {"毫米": "mm", "厘米": "cm", "分米": "dm", "米": "m", "千米": "km"}
_LABELS = {"mm": "毫米", "cm": "厘米", "dm": "分米", "m": "米", "km": "千米"}
_SIDE = rf"[，,；;]?(?:且|其中)?(?:长|宽|一条边|一边)(?:长)?(?:为|是|等于|=)?{_NUMBER}{_UNIT}?"
_TASK = re.compile(
    rf"(?:已知|求)?(?:一个)?长方形(?:的)?周长(?:是|为|等于|=)?(?P<perimeter>{_NUMBER})"
    rf"(?P<unit>{_UNIT})?(?P<sides>(?:{_SIDE}){{0,2}})[，,；;]?(?:请)?(?:求(?:它|其)?(?:的)?|(?:它|其)(?:的)?)?"
    rf"面积(?:是|为|等于)?(?:多少)?(?:[。？?])?"
)
_SIDE_PART = re.compile(
    rf"[，,；;]?(?:且|其中)?(?P<name>长|宽|一条边|一边)(?:长)?(?:为|是|等于|=)?"
    rf"(?P<value>{_NUMBER})(?P<unit>{_UNIT})?"
)


def _number(value: Fraction) -> str:
    denominator = value.denominator
    places = 0
    while denominator > 1 and denominator % 2 == 0:
        denominator //= 2
    while denominator > 1 and denominator % 5 == 0:
        denominator //= 5
    if denominator != 1:
        return str(value)
    scale = 1
    while scale % value.denominator:
        scale *= 10
        places += 1
    scaled = value.numerator * (scale // value.denominator)
    if not places:
        return str(scaled)
    digits = str(abs(scaled)).zfill(places + 1)
    return ("-" if scaled < 0 else "") + (digits[:-places] + "." + digits[-places:]).rstrip("0").rstrip(".")


@dataclass(frozen=True)
class RectangleAreaTask:
    perimeter: Fraction
    perimeter_text: str
    unit: str
    sides: tuple[tuple[str, Fraction, str], ...]
    status: str

    def expression(self) -> str | None:
        if self.status != "determined":
            return None
        side = self.sides[0][2]
        return f"({side})*(({self.perimeter_text})/2-({side}))"

    def witnesses(self):
        if self.status != "underdetermined":
            return ()
        return ((self.perimeter * Fraction(3, 10), self.perimeter / 5),
                (self.perimeter * Fraction(7, 20), self.perimeter * Fraction(3, 20)))

    def receipt(self):
        return {"policy": "rectangle-constraints-v1", "scope": "positive_real_sides_same_unit",
                "status": self.status, "perimeter": str(self.perimeter), "length_unit": self.unit,
                "given_sides": [{"name": name, "value": str(value)} for name, value, _ in self.sides],
                "rules": ["length > 0", "width > 0", "2*(length+width)=perimeter", "area=length*width"],
                "witnesses": [{"length": str(left), "width": str(right),
                               "perimeter": str(2 * (left + right)), "area": str(left * right)}
                              for left, right in self.witnesses()]}

    def boundary_message(self) -> str:
        if self.status == "infeasible":
            return ("这些数据不能构成边长为正的长方形：周长必须大于零，每条边都要大于零且小于周长的一半；"
                    "若长宽都已给出，还应满足周长等于长宽之和的两倍。请核对周长和边长，不能用这些数据给出有效面积。")
        if self.status != "underdetermined":
            return ""
        length_unit = _LABELS.get(self.unit, "")
        area_unit = "平方" + length_unit if length_unit else ""
        examples = []
        for left, right in self.witnesses():
            examples.append(f"长 {_number(left)}{length_unit}、宽 {_number(right)}{length_unit}，"
                            f"周长为 2×({_number(left)}+{_number(right)})={_number(self.perimeter)}{length_unit}，"
                            f"面积为 {_number(left)}×{_number(right)}={_number(left * right)}{area_unit}")
        return (f"仅知道周长 {_number(self.perimeter)}{length_unit}，只能确定长与宽的和是 {_number(self.perimeter / 2)}{length_unit}，"
                "还不能唯一确定面积。请补充一条边长，或长宽之间的关系。\n\n"
                + "；\n".join(examples) + "。\n两组边长都为正，周长相同但面积不同，因此不能猜一个唯一面积。")


def rectangle_area_task(text: str) -> RectangleAreaTask | None:
    if not text or len(text) > 160:
        return None
    compact = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).replace("−", "-")
    matched = _TASK.fullmatch(compact)
    if matched is None:
        return None
    perimeter = Fraction(matched["perimeter"])
    units = {_UNITS.get(matched["unit"], matched["unit"])} if matched["unit"] else set()
    sides = []
    for item in _SIDE_PART.finditer(matched["sides"]):
        if item["unit"]:
            units.add(_UNITS.get(item["unit"], item["unit"]))
        sides.append((item["name"], Fraction(item["value"]), item["value"]))
    if len(units) > 1 or (len(sides) == 2 and {side[0] for side in sides} != {"长", "宽"}):
        return None
    feasible = perimeter > 0 and all(0 < value < perimeter / 2 for _, value, _ in sides)
    if len(sides) == 2:
        feasible = feasible and sum(side[1] for side in sides) == perimeter / 2
    status = "infeasible" if not feasible else "determined" if sides else "underdetermined"
    return RectangleAreaTask(perimeter, matched["perimeter"], next(iter(units), ""), tuple(sides), status)
