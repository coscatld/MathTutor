"""K-12 question bank: catalog tree by stage and verified practice per point.

Step-verifiable problems keep the existing local solver contract. Original
curriculum questions have separate reference answers and worked explanations;
they do not imply automatic verification of a student's free-form proof.
"""
from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path
from typing import Any

from mathtutor.question_bank.generators import GENERATORS, generate

CATALOG = Path(__file__).with_name("catalog_k12_v1.json")
REFERENCES = Path(__file__).with_name("curriculum_questions_v2.json")
STAGES = {"primary": ("小学", range(1, 7)), "middle": ("初中", range(7, 10)), "high": ("高中", range(10, 13))}
EMPTY_NOTE = "这个知识点暂无可核验题目，可以把题目发给 Tutor 讲解。"


class CatalogError(ValueError):
    """The bundled catalog is inconsistent."""


def load_catalog(path: Path = CATALOG) -> dict[str, Any]:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    terms, codes = catalog.get("terms") or [], set()
    if [t["order"] for t in terms] != list(range(1, len(terms) + 1)):
        raise CatalogError("学期顺序必须从 1 开始连续递增")
    for term in terms:
        label, grades = STAGES.get(term["stage"], (None, ()))
        if label is None or term["grade"] not in grades:
            raise CatalogError(f"{term['code']} 的学段与年级不一致")
        for unit in term["units"]:
            for point in unit["points"]:
                for code in (term["code"], unit["code"], point["code"]):
                    codes.add(code)
                for item in point.get("practice", ()):
                    if (item["family"], item["template"]) not in GENERATORS:
                        raise CatalogError(f"{point['code']} 引用了不存在的题目模板 {item['template']}")
        if term["code"] not in codes:
            raise CatalogError(f"{term['code']} 没有知识点")
    all_codes = [c for t in terms for c in (t["code"], *(u["code"] for u in t["units"]),
                                            *(p["code"] for u in t["units"] for p in u["points"]))]
    if len(all_codes) != len(set(all_codes)):
        raise CatalogError("目录中存在重复的编码")
    return catalog


class QuestionBankService:
    def __init__(self, backend=None, path: Path = CATALOG) -> None:
        from mathtutor.application.verification_backend import InProcessVerificationBackend
        self.catalog = load_catalog(path)
        payload = json.loads(REFERENCES.read_text(encoding="utf-8"))
        self.references = payload["questions"]
        for term in self.catalog["terms"]:
            for unit in term["units"]:
                for point in unit["points"]:
                    questions = self.references.get(point["code"], [])
                    if point.get("reference_ids", []) != [q["id"] for q in questions]:
                        raise CatalogError(f"{point['code']} 的课程题索引与题目文件不一致")
        self.backend = backend or InProcessVerificationBackend()
        self._problems: dict[str, list[dict[str, Any]]] = {}
        self._index = {p["code"]: (t, u, p) for t in self.catalog["terms"] for u in t["units"] for p in u["points"]}

    @cached_property
    def _counts(self) -> dict[str, int]:
        import asyncio
        return {code: len(asyncio.run(self._generate(code))) for code, (_, _, p) in self._index.items() if p.get("practice")}

    async def warm(self) -> None:
        for code, (_, _, point) in self._index.items():
            if point.get("practice"):
                await self.problems(code)

    def tree(self, stage: str | None) -> dict[str, Any]:
        terms = [t for t in self.catalog["terms"] if stage is None or t["stage"] == stage]
        return {"version": self.catalog["version"], "stage": stage, "source_note": self.catalog["source_note"],
                "terms": [{**{k: t[k] for k in ("code", "stage", "grade", "order", "label", "book")},
                           "recommended_grades": t.get("recommended_grades", [t["grade"]]),
                           "units": [{"code": u["code"], "title": u["title"],
                                      "points": [{"code": p["code"], "title": p["title"],
                                                  "problem_count": len(self._problems.get(p["code"], ())) if p["code"] in self._problems
                                                  else self._counts.get(p["code"], 0),
                                                  "reference_count": len(self.references.get(p["code"], ())),
                                                  "total_count": self._counts.get(p["code"], 0) + len(self.references.get(p["code"], ())),
                                                  "demo_count": len(p.get("demos", ()))} for p in u["points"]]}
                                     for u in t["units"]]} for t in terms]}

    async def _generate(self, code: str) -> list[dict[str, Any]]:
        from mathtutor.application.math_verification import ExpressionNotVerifiable, verified_problem
        _, _, point = self._index[code]
        problems, seen = [], set()
        for item in point.get("practice", ()):
            for text, difficulty in generate(code, item["family"], item["template"], item.get("count", 6)):
                if text in seen:
                    continue
                try:
                    problem, _ = await verified_problem(self.backend, text)
                except (ExpressionNotVerifiable, ValueError, ArithmeticError, KeyError, TypeError):
                    continue
                if problem.problem_type != item["family"]:
                    continue
                seen.add(text)
                problems.append({"id": f"{code}-{len(problems) + 1}", "text": text,
                                 "display_latex": problem.display_latex, "family": problem.problem_type,
                                 "difficulty": difficulty})
        return problems

    async def problems(self, code: str) -> list[dict[str, Any]]:
        if code not in self._problems:
            self._problems[code] = await self._generate(code)
        return self._problems[code]

    async def point(self, code: str) -> dict[str, Any] | None:
        if code not in self._index:
            return None
        term, unit, point = self._index[code]
        problems = await self.problems(code)
        demos = [dict(d) for d in point.get("demos", ())]
        return {"point": {"code": code, "title": point["title"], "term": term["label"], "unit": unit["title"]},
                "problems": problems, "reference_problems": [dict(q) for q in self.references.get(code, ())],
                "demos": demos, "note": "" if problems or demos or self.references.get(code) else EMPTY_NOTE}


__all__ = ["CATALOG", "CatalogError", "EMPTY_NOTE", "QuestionBankService", "STAGES", "load_catalog"]
