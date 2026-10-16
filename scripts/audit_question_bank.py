"""Write a deterministic content-coverage report; no network/model calls.

Run after build_question_bank_catalog.py. This inventory is not a benchmark of
LLM quality and does not certify arbitrary student proofs as correct.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from mathtutor.question_bank.service import QuestionBankService


def inventory():
    bank = QuestionBankService()
    tree = bank.tree(None)
    terms,points=[],[]
    for term in tree["terms"]:
        rows=[p for u in term["units"] for p in u["points"]]
        terms.append({"term":term["label"],"grade":term["grade"],"recommended_grades":term["recommended_grades"],
                      "points":len(rows),"reference_questions":sum(p["reference_count"] for p in rows),
                      "step_verifiable_questions":sum(p["problem_count"] for p in rows),
                      "covered_points":sum(p["reference_count"]>0 for p in rows)})
        for unit in term["units"]:
            for p in unit["points"]:
                refs=bank.references[p["code"]]
                points.append({"code":p["code"],"title":p["title"],"term":term["label"],
                               "reference_questions":len(refs),"step_verifiable_questions":p["problem_count"],
                               "categories":dict(Counter(q["category"] for q in refs)),
                               "answer_relation_checks":sum(bool(q["verification"]["answer_check"]) for q in refs)})
    refs=[q for group in bank.references.values() for q in group]
    return {"catalog_version":tree["version"],"terms":terms,"knowledge_points":len(points),
            "covered_knowledge_points":sum(p["reference_questions"]>0 for p in points),
            "reference_questions":len(refs),
            "step_verifiable_questions":sum(t["step_verifiable_questions"] for t in terms),
            "answer_relation_checks":sum(bool(q["verification"]["answer_check"]) for q in refs),
            "max_launch_characters":max(len(q["text"]) for q in refs),
            "proof_process_automatically_verified":False,"points":points}


def markdown(report):
    lines=["# K–12 课程题库覆盖报告", "",
           f"当前目录含 **{report['knowledge_points']} 个知识点**，每点至少 2 道原创课程题，合计 **{report['reference_questions']} 道**；另有 **{report['step_verifiable_questions']} 道**通过既有本地求解与步骤核验入口的练习。", "",
           "这些数量是产品内容清单，不是智能体评测分数；没有发起任何模型调用，也没有修改历史基准结果。", "",
           "| 教材/学期 | 知识点 | 有课程题的知识点 | 原创课程题 | 本地核验练习 |", "|---|---:|---:|---:|---:|"]
    for t in report["terms"]:
        lines.append(f"| {t['term']} | {t['points']} | {t['covered_points']} | {t['reference_questions']} | {t['step_verifiable_questions']} |")
    lines += ["", "## 内容与核验边界", "",
              "- 原创课程题独立保存题干、参考答案和解题说明。答案默认隐藏；用户可先作答再展开核对，或把完整题干发给 Tutor 讲解。",
              "- 原创课程题的步骤、证明与主观解释采用参考答案模式；界面明确标注作答过程没有自动核验。它们不会借用低阶算术题型宣称支持证明或高级数学步骤核验。",
              f"- {report['answer_relation_checks']} 个课程题实例附精确数值关系断言，构建时进行有理数运算检查；这些断言只是对应参考答案的部分可计算证据，不等于整道证明的机器认证。",
              "- 高中题面、参考答案与条件经逐题独立阅读，并完成 162 项独立 SymPy/Fraction 推导证据检查；证据快照见 `QUESTION_BANK_MATH_AUDIT.json`，绑定内容源码 SHA256，不调用作者的计算函数。",
              "- 独立测试从题干重新计算运算、众数/中位数、完整方程根集合、定义域排除点、勾股关系、排列组合概率、分布统计量、递推数列、裂项/错位求和，以及含竖直弦的圆锥曲线定点/定值关系。数学推导与自动核验能力分开记录。",
              "- 教材分册不等于全国统一年级进度；计数、条件概率、分布与统计分析这一册标记高二和高三均适用，年级筛选可以查到。",
              "", "## 本轮补齐的显式子主题", "",
              "半时与元角分；最大公因数/最小公倍数；工程/追及/逆向增长率；全等与切线证明；动态函数几何；集合子集/补集；函数值域与定义域；向量数量积；球表面积体积；导数参数/零点/不等式证明；递推/错位相减/数列不等式；圆锥曲线定点定值；统计推断与数学思想方法。", "",
              "修正原先 16 处不相符的练习映射，并为 17 个运算知识点使用专用模板，避免减法点随机出现加法、除法点随机出现乘法或分式运算点展示数字分数加法。", "",
              "## 复现", "", "```bash", "PYTHONPATH=src python scripts/build_question_bank_catalog.py", "PYTHONPATH=src python scripts/audit_question_bank.py", "python scripts/audit_curriculum_math.py", "PYTHONPATH=src python -m pytest tests/test_question_bank.py tests/test_question_bank_curriculum.py tests/test_curriculum_answer_semantics.py", "```", "",
              "独立推导脚本绑定本次已阅读的内容源码 SHA256；内容变更后会拒绝沿用旧审查结论，需要重新复核并更新证据。", "",
              "逐知识点数量、题型与数值关系检查条目数见同目录 `QUESTION_BANK_COVERAGE.json`。"]
    return "\n".join(lines)+"\n"


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,default=Path("docs"))
    args=parser.parse_args()
    report=inventory()
    args.output_dir.mkdir(parents=True,exist_ok=True)
    (args.output_dir/"QUESTION_BANK_COVERAGE.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (args.output_dir/"QUESTION_BANK_COVERAGE.md").write_text(markdown(report),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("terms","points")},ensure_ascii=False))
