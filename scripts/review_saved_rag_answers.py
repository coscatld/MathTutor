"""Publish explicit independent AI annotations of the frozen first-run answers.

No model calls. These annotations are provisional, not human-approved gold.
Evidence support and mathematical truth are intentionally separate dimensions.
"""
import hashlib
import json
from pathlib import Path
from rag_delivery_regression import OLD, OUT
from rag_live_acceptance import write

# text, visible evidence index (one based), support, mathematics, reasoning
# DIRECT = stated; DERIVED = local application of stated rule; UNSTATED =
# requires a new mathematical premise; ERROR = counterexample/invalid prose.
DATA = {
"easy:canonical_term": [
 ("只含一个未知数",1,"DIRECT","CORRECT","定义的必要条件"),
 ("未知数最高次数为一",1,"DIRECT","CORRECT","定义的必要条件"),
 ("必须是整式方程，未知数不在分母",1,"DERIVED","CORRECT","解释整式限制；按中学方程原始形式分类"),
 ("x²=4 不是一次方程",1,"DERIVED","CORRECT","次数为二"),
 ("1/x=2 不是整式方程",1,"DERIVED","CORRECT","未知数在分母"),
 ("2x+3=7 是一元一次方程",1,"DERIVED","CORRECT","一个未知数，最高次数一，整式"),
 ("5-x=0 是一元一次方程",1,"DERIVED","CORRECT","同上"),
 ("2/x=1 不是一元一次方程",1,"DERIVED","CORRECT","原式为分式方程"),
 ("x+y=3 不是一元一次方程",1,"DERIVED","CORRECT","两个未知数"),
],
"easy:spoken_variant": [
 ("两边同加或同减一个数保持等式",1,"DIRECT","CORRECT","逐义对应原文"),
 ("减同一个数等同于加其相反数",1,"UNSTATED","CORRECT","额外使用减法定义，摘录未陈述；不将数学正确等同于原文支持"),
 ("x+3=7 两边减3得到 x+3-3=7-3",1,"DERIVED","CORRECT","同减性质的具体应用"),
 ("3和-3抵消得到x=4",1,"DERIVED","CORRECT","局部算术，4+3=7"),
 ("+3移到右边成为-3，是两边同减3",1,"DERIVED","CORRECT","原文移项规则及所示推导一致"),
],
"easy:transposition": [
 ("移项要变号",1,"DIRECT","CORRECT","原文明示"),
 ("移项基于两边同加或同减",1,"DERIVED","CORRECT","原文等式性质与移项规则"),
 ("x+3=7 同减3得到x=4",1,"DERIVED","CORRECT","具体推导及代回一致"),
 ("移项加变减、减变加",1,"DIRECT","CORRECT","变号规则的解释"),
 ("-2x=6 同除以-2得到x=-3",1,"UNSTATED","CORRECT","摘录列出系数化1，但未给出等式同除非零数规则；算术正确"),
 ("系数化1与移项是不同步骤",1,"DIRECT","CORRECT","原文步骤明确区分"),
 ("一般步骤：去分母、去括号、移项、合并同类项、系数化1",1,"DIRECT","CORRECT","与可见原文一致"),
],
"easy:discriminant": [
 ("二次方程ax²+bx+c=0要求a≠0",1,"UNSTATED","CORRECT","本题可见片段#2未写一般形式或a≠0；条件数学正确"),
 ("Δ=b²-4ac",1,"DIRECT","CORRECT","定义一致"),
 ("x=(-b±√Δ)/(2a)",1,"DIRECT","CORRECT","在随后说明的实根条件下使用"),
 ("Δ>0有两个不同实根",1,"DIRECT","CORRECT","实系数语境"),
 ("Δ=0有两个相等实根",1,"DIRECT","CORRECT","按重数计两个，只有一个不同实根"),
 ("Δ<0无实根",1,"DIRECT","CORRECT","限定实数范围"),
 ("Δ>0时±√Δ给出不同的值",1,"DERIVED","CORRECT","给定求根公式的局部解释"),
 ("Δ=0时±0相同",1,"DERIVED","CORRECT","给定求根公式的局部解释"),
 ("负数在实数范围内没有平方根",1,"UNSTATED","CORRECT","摘录未给平方根定义；数学正确"),
 ("x²-5x+6=0 的Δ=1",1,"DERIVED","CORRECT","25-24=1"),
 ("该例根为2和3",1,"DERIVED","CORRECT","代回均为零，或使用可见求根公式"),
 ("x²-4x+4=0 的Δ=16-16=接",1,"ERROR","INCOMPLETE","最终学生正文中等式未完成；不能以此前正确算式抵消"),
],
"easy:commutative": [
 ("交换两个加数的位置，和不变",1,"DIRECT","CORRECT","原文明示"),
 ("a+b=b+a",1,"DIRECT","CORRECT","字母式一致"),
 ("3+5=8",1,"DERIVED","CORRECT","交换律的具体算术例子"),
 ("5+3=8",1,"DERIVED","CORRECT","同上"),
 ("乘法也有交换律a×b=b×a",4,"DIRECT","CORRECT","乘法摘录确实在本轮可见"),
],
"easy:associative": [
 ("三个数相加，先加前两个或后两个结果相同",1,"DIRECT","CORRECT","原文定义"),
 ("(a+b)+c=a+(b+c)",1,"DIRECT","CORRECT","原文字母式"),
 ("结合律改变运算顺序",2,"DIRECT","CORRECT","指分组先后，非加数排列"),
 ("交换律改变运算对象的位置",2,"DIRECT","CORRECT","原文区分"),
],
"easy:mixed_cjk_latex": [
 ("一元二次方程要求a≠0",1,"DIRECT","CORRECT","限定本段的二次方程语境，非所有多项式方程"),
 ("a=0时二次项消失，成为bx+c=0",1,"DERIVED","CORRECT","将a=0代入一般形式"),
 ("这已经是一次方程（仅由a=0得出）",1,"ERROR","INCORRECT","漏b≠0。a=b=0,c=1为1=0无解；a=b=c=0为恒等式。最后的条件提问未撤回该断言"),
 ("a=0时不再是一元二次方程",1,"DERIVED","CORRECT","二次项消失"),
 ("求根公式分母2a要求a≠0",3,"DERIVED","CORRECT","公式与本题可见分母非零规则共同支持"),
 ("b可以为零而仍是二次方程",1,"DERIVED","CORRECT","a≠0即可保持二次项"),
 ("c可以为零而仍是二次方程",1,"DERIVED","CORRECT","a≠0即可保持二次项"),
 ("x²-4=0是b=0的一元二次方程",1,"DERIVED","CORRECT","a=1,b=0,c=-4"),
],
"hard:Q04": [
 ("中间项为两数乘积的2倍，即2ab",1,"DIRECT","CORRECT_IN_CONTEXT","后文立即区分和差及正负；若孤立截取首句会漏符号条件"),
 ("首末两项为两数平方",1,"DIRECT","CORRECT","原文明示"),
 ("(a+b)²=a²+2ab+b²",1,"DERIVED","CORRECT","给定首末平方及中间两倍乘积规则"),
 ("(a-b)²=a²-2ab+b²",1,"DERIVED","CORRECT","将第二个数取-b应用上述规则"),
 ("和式取+2ab，差式取-2ab",1,"DERIVED","CORRECT","代入-b后符号改变"),
 ("(x-3)²中间项=-6x",1,"DERIVED","CORRECT","-2*x*3=-6x"),
 ("(x-3)²=x²-6x+9",1,"DERIVED","CORRECT","给定规则代入；逐项核对"),
],
}

REQUIREMENTS = {
"easy:canonical_term": ["一元", "一次", "整式"],
"easy:spoken_variant": ["可以", "同减保持等式"],
"easy:transposition": ["必须变号", "等式性质解释"],
"easy:formula": ["一般形式及a≠0", "求根公式", "实根判别条件"],
"easy:discriminant": ["判别式定义", "正零负三种实根情况"],
"easy:commutative": ["加法交换律", "字母表示"],
"easy:associative": ["结合律字母表示"],
"easy:cross_topic": ["可能产生增根", "代回原方程检验及分母非零"],
"easy:mixed_cjk_latex": ["二次项非零", "a=0后不再二次"],
"hard:Q01": ["Δ定义", "一元二次方程a≠0"],
"hard:Q02": ["同减3得到2x=4", "同除2得到x=2", "步骤依据"],
"hard:Q03": ["中间项两倍乘积", "区分和差符号"],
"hard:Q04": ["中间项两倍乘积", "区分和差符号"],
"hard:Q05": ["二次项系数非零", "否则不再二次"],
}


def main():
    packet_path = OLD / "execution/B-review-packet.json"
    original = json.loads(packet_path.read_text(encoding="utf-8"))
    rows = []
    for item in original:
        cid = item["case_id"]
        claims = []
        for n, (text, source, support, math, reason) in enumerate(DATA.get(cid, []), 1):
            evidence = item["actual_visible_evidence"][source-1]
            label = f"【{evidence['filename']}·片段#{evidence['chunk']}】"
            claims.append(dict(claim_id=f"{cid}:C{n:02}", statement=text,
                evidence_support=support, mathematical_correctness=math, rationale=reason,
                evidence_reference=dict(filename=evidence["filename"], chunk=evidence["chunk"], text=evidence["text"]),
                citation_attribution="MATCHING_VISIBLE_SOURCE" if label in item["final_answer"] else "NO_EXPLICIT_MATCHING_CITATION",
                citation_label=label if label in item["final_answer"] else None,
                reference_status="PROVISIONAL", human_review_status="PENDING"))
        fallback = item["template_fallback_observed"]
        score = sum(c["evidence_support"] in {"DIRECT", "DERIVED"} for c in claims) / len(claims) if claims else 0.0
        task = "NOT_ANSWERED_TEMPLATE" if fallback else "INCOMPLETE_DELIVERY" if cid == "easy:discriminant" else "ANSWERED_WITH_MATH_ERROR" if cid == "easy:mixed_cjk_latex" else "COMPLETE_AI_REVIEW"
        nonmath = ("模板没有回答实际问题；其系统能力陈述不受资料支持。" if fallback else
                   "鼓励语、主观教学措辞及结尾未作答的练习提问不作为事实断言计分。")
        if cid == "hard:Q01":
            nonmath += "‘配好模型服务后’还与实际已配置并发出请求的事实冲突。"
        citations = [dict(**c, semantic_attribution="SUPPORTED_IN_CONTEXT_PROVISIONAL",
                         scope="nearest substantive assertion and its locally explained rule, not the entire answer") for c in item["citations"]]
        rows.append(dict(case_id=cid, question=item["question"], final_answer=item["final_answer"],
            final_answer_sha256=hashlib.sha256(item["final_answer"].encode()).hexdigest(),
            request_record_ids=item["request_record_ids"], claims=claims, nonmathematical_review=nonmath,
            citations=citations, task_completion=task,
            required_content=[dict(item=x, covered=not fallback) for x in REQUIREMENTS[cid]],
            required_content_coverage=0.0 if fallback else 1.0,
            faithfulness_score=score,
            mathematical_correctness="NOT_ASSESSABLE_NO_ANSWER" if fallback else "FAIL" if cid in {"easy:discriminant", "easy:mixed_cjk_latex"} else "NO_ERROR_FOUND_AI_REVIEW",
            human_review_status="PENDING", reference_status="PROVISIONAL"))
    result = dict(schema="mathtutor.atomic-answer-review/1", reviewer="Codex independent AI review, not DeepSeek self-grading",
        source_packet=str(packet_path),
        source_sha256=hashlib.sha256(packet_path.read_bytes()).hexdigest(), human_review_status="PENDING",
        reference_status="PROVISIONAL", criteria_status="REVIEW_RUBRIC_NOT_FROZEN_FORMAL_ACCEPTANCE",
        rubric=dict(support="DIRECT or local DERIVED from visible premises; UNSTATED true facts remain unsupported; ERROR includes unfinished assertions",
            failure_templates="0 end-to-end faithfulness; no mathematical score; never vacuous 1",
            macro="all 14 original answers including six templates; no denominator removal",
            content_coverage="post-run explicit AI requirements, independent of final delivery/mathematical correctness; not human gold",
            atomicity="distinct substantive mathematical assertions; repeated paraphrases coalesced; final full prose retained"),
        rows=rows, summary=dict(answer_count=len(rows), claim_count=sum(len(r["claims"]) for r in rows),
            faithfulness_macro=sum(r["faithfulness_score"] for r in rows)/len(rows),
            faithfulness_min=min(r["faithfulness_score"] for r in rows),
            content_coverage_macro=sum(r["required_content_coverage"] for r in rows)/len(rows),
            task_complete=sum(r["task_completion"] == "COMPLETE_AI_REVIEW" for r in rows),
            task_denominator=len(rows), citation_links=sum(len(r["citations"]) for r in rows),
            formal_acceptance="INSUFFICIENT_EVIDENCE", development_quality="FAIL"))
    write(OUT / "original-B-atomic-review.json", result)


if __name__ == "__main__":
    main()
