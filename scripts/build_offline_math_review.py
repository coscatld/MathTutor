"""Offline-only 0.4.2 evidence builder. Never loads credentials or live settings."""
from __future__ import annotations
import asyncio
import hashlib
import html
import json
from pathlib import Path
import re
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from offline_math_conditions import report as math_report
from offline_answer_annotations import EXPRESSION, DEGENERATE
from mathtutor.application.tutor_runtime import complete_tutor, current_turn
from mathtutor.domain.turn_result import TutorTurnResult
from mathtutor.infrastructure.generative_gateway import CompletionResult, OpenAICompatibleProvider

OLD = ROOT / "artifacts/live-acceptance-20260920-v4"
SAVED = ROOT / "artifacts/delivery-regression-20260920"
OUT = ROOT / "artifacts/offline-math-042"
FIXTURES = ROOT / "tests/fixtures/rag_math_conditions_v1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def check_history():
    for name, digest in read(OUT / "history-lock.json").items():
        assert sha((ROOT / name).read_bytes()) == digest, f"Historical evidence changed: {name}"
    return read(SAVED / "budget.json")


def corpus():
    import rag_hard_set_probe as historical
    bad = "若二次项系数为零，则方程退化为一次方程，处理方式随之改变。"
    corrected = "若二次项系数为零且一次项系数不为零，则为一元一次方程；若二者均为零，常数项非零时无解，常数项也为零时任意实数均为解。"
    changes, docs, bad_sources = [], [], []
    for doc in historical.HARD_DOCS:
        body = doc.body.replace(bad, corrected)
        path = FIXTURES / "normal" / doc.filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8", newline="\n")
        row = dict(key=doc.key, filename=doc.filename, historical_sha256=sha(doc.body.encode()),
            corrected_sha256=sha(body.encode()), replacements=doc.body.count(bad))
        docs.append(row)
        if row["replacements"]:
            changes.append(dict(document=doc.filename, before=bad, after=corrected, count=row["replacements"]))
            bad_sources.append(dict(filename=doc.filename, historical_body_sha256=sha(doc.body.encode()),
                erroneous_excerpt=bad, cohort="SOURCE_CONTAINS_ERROR", evidence_support="DIRECT",
                mathematics="FALSE_WITHOUT_b_NONZERO", counterexample="a=b=0,c=1 -> 1=0；a=b=c=0 -> 0=0",
                reference_status="PROVISIONAL_AI", historical_failures=["expression-fixed:hard:Q01", "expression-fixed:hard:Q05"]))
    supplement = (
        "# 参数与等价变形\n"
        "设a、b、c为实数。ax²+bx+c=0在a≠0时为一元二次方程。a=0且b≠0时为一元一次方程，x=-c/b；"
        "a=b=0且c≠0时无解；a=b=c=0时为恒等式，任意实数均为解。\n"
        "a≠0且c=0时，x(ax+b)=0，根为0和-b/a。b≠0时两根不同且恰有一根为零，不能称为一正一负；b=0时为二重零根。\n"
        "a≠0且b=0时，x²=-c/a。-c/a为正、零、负时，分别有两个相反的实根、二重零根、无实根。\n"
        "等式两边同乘0有定义，能保持原等式成立的正向蕴含，却一般不能逆推原式。例如x=1同乘0变成0=0，新式对x=0也成立，所以两式不等价。\n"
        "同除时除数必须非零。去分母须保留原分母非零的定义域限制，并检验候选解。例如x/(x-1)=1/(x-1)去分母得到x=1，"
        "但x=1使原式未定义，必须排除。\n"
    )
    (FIXTURES / "normal/参数与等价变形.md").write_text(supplement, encoding="utf-8", newline="\n")
    docs.append(dict(key="conditions", filename="参数与等价变形.md", historical_sha256=None,
        corrected_sha256=sha(supplement.encode()), replacements=0))
    write(FIXTURES / "source-error-cases.json", bad_sources)
    write(FIXTURES / "manifest.json", dict(version="math-conditions-corpus/1", parent_version="hard-corpus/2",
        annotation_version="math-conditions-annotations/1", human_review_status="PENDING", reference_status="PROVISIONAL_AI",
        historical_fixture_sha256=sha((ROOT / "scripts/rag_hard_set_probe.py").read_bytes()),
        documents=docs, changes=changes, source_errors="source-error-cases.json",
        boundaries="Text changes alter chunk boundaries; do not reuse old chunk IDs, annotations, retrieval metrics or Faithfulness scores",
        new_material_live_evaluation="NOT_RUN"))


def group_review(group, annotations):
    path = SAVED / group / "B-results.json"
    rows = []
    for row in read(path):
        records = [read(SAVED / group / f"request-{n:03}.json") for n in row["request_record_ids"]]
        context = next(json.loads(m["content"].split("\n",1)[1]) for m in records[0]["messages"]
            if isinstance(m.get("content"),str) and m["content"].startswith("本轮会话资料（"))
        evidence = context["chunks"]
        labels = re.findall(r"【[^】]+】", row["final_answer"])
        visible_labels = {f"【{e['filename']}·片段#{e['chunk']}】" for e in evidence}
        claims = [dict(c, claim_id=f"{row['case_id']}:C{i:02}", human_review_status="PENDING",
                       reference_status="PROVISIONAL_AI") for i,c in enumerate(annotations[row["case_id"]],1)]
        rows.append(dict(case_id=row["case_id"], question=row["question"],
            generating_version="0.4.1", review_version="0.4.2", review_method="OFFLINE_INDEPENDENT_AI",
            source_group=group, request_record_ids=row["request_record_ids"],
            request_sha256={str(n):sha((SAVED/group/f"request-{n:03}.json").read_bytes()) for n in row["request_record_ids"]},
            final_answer=row["final_answer"], answer_sha256=sha(row["final_answer"].encode()),
            actual_visible_evidence=evidence, claims=claims,
            citation_attribution=[dict(label=x, source_visible=x in visible_labels,
                assessment="PROVISIONAL_LOCAL_ATTRIBUTION; does not support every uncited sentence") for x in labels],
            task_completion="AI_FAILURE" if any(c["mathematical_correctness"]=="AI_FALSE" for c in claims) else "AI_REVIEW_PENDING_HUMAN",
            provider_stop_reason=row["finish_reason"], faithfulness_score=None,
            human_review_status="PENDING", reference_status="PROVISIONAL_AI",
            disputes=[c["claim_id"] for c in claims if c["disputed"]],
            non_claims="Encouragement and unanswered teaching questions excluded; complete prose retained for human checking"))
    result = dict(group=group, generating_version="0.4.1", review_version="0.4.2", source_results_sha256=sha(path.read_bytes()),
        original_B_scores_reused=False, semantic_labels="NEW_INDEPENDENT_AI_PROVISIONAL", faithfulness_macro=None,
        human_review_status="PENDING", rows=rows)
    write(OUT / f"{group}-review.json", result)
    return rows


async def replays():
    result = []
    for group, cid, numbers, root, version in [
        ("original-B", "easy:discriminant", [14,15], OLD/"execution", "0.4.0"),
        ("degenerate-fixed", "degenerate:b0", [72,73], SAVED/"degenerate-fixed", "0.4.1"),
        ("degenerate-fixed", "degenerate:c0", [74,75], SAVED/"degenerate-fixed", "0.4.1"),
    ]:
        rows = [read(root/f"request-{n:03}.json") for n in numbers]
        original = next(r for r in read(root/"B-results.json") if r["case_id"] == cid)
        class SavedResponses:
            calls = 0
            async def complete(self, messages, **kwargs):
                row = rows[self.calls]
                self.calls += 1
                return CompletionResult(**row["response"])
        turn = TutorTurnResult()
        token = current_turn.set(turn)
        try:
            response = await complete_tutor(SavedResponses(), rows[0]["messages"], **rows[0]["parameters"])
        finally:
            current_turn.reset(token)
        segments = [dict(request_id=r["request_id"], text=r["response"]["text"],
            sha256=sha(r["response"]["text"].encode()), finish_reason=r["response"]["finish_reason"]) for r in rows]
        raw_join = "".join(s["text"] for s in segments)
        assert raw_join == original["final_answer"]
        assert all(s["text"] in response.text for s in segments)
        result.append(dict(case_id=cid, source_group=group, generating_version=version, replay_version="0.4.2",
            segments=segments, old_final=original["final_answer"], old_answer_sha256=sha(original["final_answer"].encode()),
            original_merge="EXACT_CONCATENATION; no overlap removed", old_matches_raw_join=True,
            replay_final=response.text, replay_answer_sha256=sha(response.text.encode()), replay_turn=turn.wire(),
            generated_error="one-character incomplete continuation" if cid.endswith("discriminant") else
                "Restart instead of finishing prior sentence; c=0 opposite-sign and only-square-root claims already in generated segment" if cid.endswith("c0") else
                "Restart instead of finishing prior sentence",
            merge_error="No separator fused independent continuations; merge did not create or delete the mathematical assertion",
            offline_fix="Both raw segments retained; uncertain seam disclosed and status stays PARTIAL; no mathematical correction claimed",
            real_provider_calls=0))
    write(OUT/"continuation-replays.json", result)
    return result


def human_packet(rows):
    # Strict allowlist: never includes prompts, credentials, raw API diagnostics,
    # hidden reasoning, token usage or former-group scores.
    evidence_pool, answers = {}, []
    for row in sorted(rows, key=lambda r: (not any(c["mathematical_correctness"]=="AI_FALSE" for c in r["claims"]), not bool(r["disputes"]), r["case_id"])):
        refs = []
        for e in row["actual_visible_evidence"]:
            item = dict(filename=e["filename"], chunk=e["chunk"], text=e["text"])
            key = sha(json.dumps(item,sort_keys=True,ensure_ascii=False).encode())
            evidence_pool[key] = item
            refs.append(key)
        answers.append(dict(question=row["question"], case_id=row["case_id"], source_group=row["source_group"],
            generating_version=row["generating_version"], answer_sha256=row["answer_sha256"], request_record_ids=row["request_record_ids"],
            visible_evidence=refs, complete_answer=row["final_answer"], claims=row["claims"], disputes=row["disputes"],
            human_review_status="PENDING"))
    packet = dict(reference_status="PROVISIONAL_AI_NOT_HUMAN_ACCEPTED", answers=answers, evidence=evidence_pool)
    write(OUT/"human-review/packet.json", packet)
    sections=[]
    for a in answers:
        claims = "".join("<tr>"+"".join(f"<td>{html.escape(str(v))}</td>" for v in
            (c["claim_id"],c["statement"],c["evidence_support"],c["mathematical_correctness"],c["basis"],"需复核" if c["disputed"] else "待人工"))+"</tr>" for c in a["claims"])
        evidence_html="".join(f"<details><summary>{html.escape(evidence_pool[k]['filename'])} · #{evidence_pool[k]['chunk']}</summary><pre>{html.escape(evidence_pool[k]['text'])}</pre></details>" for k in a["visible_evidence"])
        sections.append(f"<details><summary>{html.escape(a['case_id'])} · {len(a['disputes'])} 个争议/待核对项</summary><h3>{html.escape(a['question'])}</h3><p>原生成版本 {a['generating_version']} · 请求 {a['request_record_ids']} · 回答 SHA256 {a['answer_sha256']}</p><h4>完整实际回答</h4><pre>{html.escape(a['complete_answer'])}</pre><h4>逐声明 AI 标签（未人工验收）</h4><table><thead><tr><th>ID</th><th>声明</th><th>证据支持</th><th>数学</th><th>依据/反例</th><th>争议</th></tr></thead><tbody>{claims}</tbody></table><h4>实际可见证据</h4>{evidence_html}</details>")
    page="<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>0.4.1 实际回答：人工复核包</title><style>body{max-width:1100px;margin:32px auto;font:16px/1.6 sans-serif;padding:16px;color:#202830}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f6f8;padding:16px}details{margin:16px 0;border:1px solid #ccd3dc;padding:12px}summary{cursor:pointer;font-weight:bold}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:8px;text-align:left}h1{font-size:26px}</style><h1>人工复核包：先看已标错与争议项</h1><p>全部标签为独立 AI 初审，尚未人工验收。声明映射和参数推理也需人工确认；算式验证不证明全文正确。原文完整保留，公式以原始 LaTeX 显示。</p>"+"".join(sections)+"</html>"
    (OUT/"human-review/index.html").write_text(page,encoding="utf-8")


def main():
    before = check_history()
    async def forbidden(*args, **kwargs):
        raise AssertionError("Live Provider dispatch forbidden in offline evaluation")
    with patch.object(OpenAICompatibleProvider,"complete",forbidden), patch.object(OpenAICompatibleProvider,"_post_chat",forbidden):
        corpus()
        write(OUT/"math-condition-regression.json",math_report())
        expression = group_review("expression-fixed",EXPRESSION)
        degenerate = group_review("degenerate-fixed",DEGENERATE)
        asyncio.run(replays())
        human_packet(expression+degenerate)
    after = check_history()
    assert before == after
    write(OUT/"offline-status.json",dict(version="0.4.2", real_provider_calls=0,
        historical_files_unchanged=True, budget_unchanged=True, budget=after,
        original_B_review="READ_ONLY_NOT_REUSED", independently_reviewed_groups=["expression-fixed","degenerate-fixed"],
        human_review="PENDING", normal_corpus="math-conditions-corpus/1 PROVISIONAL_AI",
        prompt_change_live_validation="NOT_RUN", real_model_quality="NOT_REEVALUATED", package="NOT_REBUILT"))


if __name__ == "__main__":
    main()
