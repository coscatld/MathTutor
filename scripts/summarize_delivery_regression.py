"""Join retained request, product and independent review evidence without reruns."""
import hashlib
import json
from pathlib import Path
from rag_delivery_regression import ROOT, OLD, OUT
from rag_live_acceptance import write


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    prior_manifest = read(OLD / "evidence-manifest.json")
    assert all(hashlib.sha256((OLD / name).read_bytes()).hexdigest() == digest
               for name, digest in prior_manifest.items()), "Original evidence changed"
    old_b = read(OLD / "execution/B-results.json")
    association = {n: row for row in old_b for n in row["request_record_ids"]}
    chain = []
    for number in range(1, 25):
        request = read(OLD / "execution" / f"request-{number:03}.json")
        product = association.get(number)
        response = request.get("response", {})
        row = dict(request_id=number, case_id=request["case_id"],
            route="connectivity" if number == 1 else "A:production support checker" if number < 10 else "B:expression WebSocket",
            gateway_outcome=request["execution_status"], gateway_finish_reason=response.get("finish_reason"),
            request_max_tokens=request["parameters"]["max_tokens"],
            runtime_finish_reason=product.get("finish_reason") if product else None,
            product_status=product.get("application_status") if product else None)
        if request.get("error_category") == "response_incomplete":
            row.update(earliest_observable_failure="Gateway._post_chat empty/truncated-content rejection, before CompletionResult",
                raw_provider_response="NOT_RETAINED; HTTP status, finish_reason, text/reasoning/usage cannot be recovered",
                gateway_parsing="Category merges empty-content and length-with-empty-content branches; exact branch unknown historically",
                runtime="complete_tutor catches exception -> PROVIDER_ERROR; no result to continue",
                continuation="NOT_ATTEMPTED; do not confuse grace_call_used with a second call",
                fallback="TutorChatResponder exception handler -> fallback_tutor_reply",
                final_student_text=product["final_answer"], task_completion=False,
                provider_fault_attribution="NOT_ESTABLISHED by error label")
        elif number in (14, 15):
            row.update(earliest_observable_failure="Provider normalized result finish_reason=length; nonempty text accepted by Gateway",
                runtime="Append partial content; one continuation; second length exhausts two-step policy",
                continuation="initial" if number == 14 else "executed; only one visible character despite 512 output tokens",
                fallback="NONE", task_completion=False)
        chain.append(row)
    write(OUT / "original-request-causal-map.json", dict(original_manifest_verified=True, requests=chain,
        discriminant=dict(initial=14, continuation=15, caps=[512,512], finish_reasons=["length","length"],
            input_tokens=1883, output_tokens=1024, max_total_tokens=16384, remaining_total_tokens=13477,
            steps_used=2, max_steps=2, remaining_steps=0,
            conclusion="Per-request output ceilings and exhausted continuation policy, NOT total-turn token exhaustion; old hidden reasoning allocation unrecorded",
            final_tail=association[15]["final_answer"][-40]),
        diagnosis=dict(requests=list(range(25,32)), generation_parameters_changed=False,
            reproduced_empty_content=[28,31], http_status=200, finish_reason="length", output_tokens=512,
            reasoning_tokens=512, visible_characters=0,
            caveat="New diagnostic samples establish a reproducible mechanism, not missing historical raw responses")))

    notes = {
        "easy:canonical_term": ("NO_ERROR_FOUND", "定义三个条件及3x+5=11、二次和分式反例正确；末尾提问未冒充结论。"),
        "easy:spoken_variant": ("NO_ERROR_FOUND", "同减性质及x+3=7到x=4正确；2x=6减2得x=2以疑问题提出，不作错误断言。"),
        "easy:transposition": ("NO_ERROR_FOUND", "移项推导和符号正确，最后提问未作答。"),
        "easy:formula": ("NO_ERROR_FOUND", "一般形式、a≠0、求根式、Δ实根分类正确；±两根需连同后文重根/实根限制阅读。"),
        "easy:discriminant": ("NO_ERROR_FOUND", "完整交付；Δ三种情况正确；只有一个实根指一个不同实根，已解释重合。"),
        "easy:commutative": ("NO_ERROR_FOUND", "交换律、结合律区别、算术例子正确。"),
        "easy:associative": ("NO_ERROR_FOUND", "字母表示、两种分组算术均为9，区别正确。"),
        "easy:cross_topic": ("FAIL", "‘等式两边同乘0是没有意义的操作’错误：同乘0有定义且保持已成立的等式，但不保留逆向等价；本题真正问题是分式定义域限制。两个例题算式正确不能抵消该正文错误。"),
        "easy:mixed_cjk_latex": ("NO_ERROR_FOUND", "本次明确一次方程须b≠0；公式分母非零正确，b=c=0作为开放问题而非断言。"),
        "hard:Q01": ("FAIL", "正文‘a=0则退化成一次方程’漏b≠0；原始hard语料也有此错误，因此可能忠于证据但数学错误。"),
        "hard:Q02": ("NO_ERROR_FOUND", "完整减3、除2步骤、非零条件、代入检验正确。"),
        "hard:Q03": ("NO_ERROR_FOUND", "和差平方式及中间项正负条件完整。"),
        "hard:Q04": ("NO_ERROR_FOUND", "和差平方式与符号说明一致，末尾为练习问题。"),
        "hard:Q05": ("FAIL", "漏b≠0的一次方程断言；把判别式与除以a的公式一并说成‘这些公式里会出现除以a’也不严谨，Δ=b²-4ac本身不除a。"),
    }
    expressions = []
    import re
    for row in read(OUT / "expression-fixed/B-results.json"):
        status, reason = notes[row["case_id"]]
        expressions.append(dict(case_id=row["case_id"], final_answer=row["final_answer"],
            delivery=row["finish_reason"], request_record_ids=row["request_record_ids"],
            mathematics=status, entire_prose_review=reason, citation_labels=re.findall(r"【[^】]+】",row["final_answer"]),
            task_completion="FAIL_MATH" if status == "FAIL" else "COMPLETE_PROVISIONAL",
            human_review_status="PENDING"))
    degenerate = []
    for row in read(OUT / "degenerate-fixed/B-results.json"):
        cid = row["case_id"]
        reason = {
            "degenerate:a0": "b≠0为一次且x=-c/b；b=0,c≠0矛盾无解；b=c=0恒等且R，正文全部区分正确。",
            "degenerate:b0": "a≠0所以仍二次；-c/a三种符号、重根及图像说明正确；续写接缝‘简单刚才’破坏句子，交付正文有瑕疵。",
            "degenerate:c0": "初段x(ax+b)=0与根0,-b/a正确；续写称其‘一正一负（或一零一非零）’是矛盾断言，零不为正或负。取a=b=1,c=0得0,-1。另‘只能靠开平方’过强，结尾自行列出判别式方法。续写接缝亦不完整。",
        }[cid]
        degenerate.append(dict(case_id=cid, final_answer=row["final_answer"], request_record_ids=row["request_record_ids"],
            delivery=row["finish_reason"], math_correctness="FAIL" if cid.endswith("c0") else "NO_ERROR_FOUND",
            prose_completion="DEFECT_AT_CONTINUATION_JOIN" if row["actual_requests"] > 1 else "COMPLETE",
            entire_prose_review=reason, human_review_status="PENDING", reference_status="PROVISIONAL"))
    knowledge = []
    for row in read(OUT / "knowledge-final/K-results.json"):
        tool_events = [e for e in row["events"] if e["event"] == "tool_executed"]
        checks = [e for e in row["events"] if e["event"] == "support_check"]
        searches = [e for e in tool_events if e["tool"] == "search_knowledge"]
        knowledge.append(dict(case_id=row["case_id"], request_record_ids=row["request_record_ids"],
            actual_mount=row["actual_mount"], final_answer=row["final_answer"], finish_reason=row["finish_reason"],
            actual_tools=[dict(name=e["tool"], ok=e["receipt"]["ok"]) for e in tool_events],
            support_checks=checks, agent_search_hops=[e["receipt"]["result"].get("retrieval_hop") for e in searches],
            direct_seed_read_without_search=bool(tool_events and tool_events[0]["tool"] == "read_source" and tool_events[0]["receipt"]["ok"]),
            contract_assessment="PASS_PROVISIONAL", human_review_status="PENDING",
            review="总结与可读证据相符且检查实际发生；非人工数学认证。" if checks else
                   "逐字引用可回溯；quote无需support_check。" if row["case_id"] == "K2_quote" else
                   "真实补搜仍无作者信息，最终说明缺口，没有编造姓名日期。" if row["case_id"] == "K3_absent" else
                   "提示边界在检索前生效，没有工具或模型调用。"))
    all_requests = [read(p) for p in OUT.glob("*/request-*.json")]
    known_usage = sum(r.get("charged_tokens",0) for r in all_requests if r.get("usage_estimated") is False)
    old_review = read(OUT / "original-B-atomic-review.json")
    write(OUT / "final-review.json", dict(version="0.4.1", human_review_status="PENDING", reference_status="PROVISIONAL",
        original_atomic_review_summary=old_review["summary"], expressions=expressions,
        degenerate=degenerate, knowledge=knowledge,
        status=dict(real_calls="COMPLETE_WITH_RETAINED_FAILURES", delivery_fix="14/14 original expression cases delivered after thinking-only change",
            expression_coverage=14, knowledge_model_cases=3, knowledge_hint_gate_cases=1,
            semantic_scoring="SAVED_ORIGINAL_B_ATOMIC_REVIEW_COMPLETE_PROVISIONAL", development_quality="FAIL",
            formal_acceptance="INSUFFICIENT_EVIDENCE", remaining="Mathematical prose errors; continuation joins; no human-calibrated labels/holdout/repeats"),
        budget=dict(**read(OUT / "budget.json"), new_requests=len(all_requests), new_known_usage=known_usage,
            original_known_usage=14656, original_unknown_usage_requests=6, automatic_retries=0,
            note="All 169364 original reservations retained; new complete usage settles only new reservations; unknown never zero")))
    source_paths = list((ROOT / "src").rglob("*.py"))
    source_paths += [ROOT / name for name in (
        "pyproject.toml", "web/package.json", "web/package-lock.json", "web/next.config.js",
        "desktop/package.json", "desktop/package-lock.json",
        "scripts/rag_live_acceptance.py", "scripts/rag_delivery_regression.py",
        "scripts/review_saved_rag_answers.py", "scripts/summarize_delivery_regression.py",
        "tests/test_live_delivery_replay.py", "tests/test_delivery_evaluation_guards.py",
        "tests/test_agentic_retrieval.py", "tests/test_gateway_cutover.py", "tests/test_release_config.py")]
    hashes = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_paths)}
    digest = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    write(OUT / "source-manifest.json", dict(version="0.4.1", aggregate_sha256=digest, files=hashes,
        scope="Final source state, including preexisting working-tree changes; not an attribution of all changes to this round",
        round_changes=["Gateway safe completion diagnostics and explicit DeepSeek thinking disabled",
            "Knowledge initial validated read_source arguments exposed to model",
            "Existing quote/summary validation contract explained in schema; validator unchanged",
            "Cumulative evaluation ledger, preserved phases, atomic AI review, regression tests and version metadata"],
        packaging="NOT_REBUILT; no 0.4.0 package verification claimed for 0.4.1"))
    logs = {
        "backend_full": ("delivery-041-full-backend.log", "1356 passed, 11 skipped"),
        "targeted": ("delivery-041-targeted-final.log", "86 passed"),
        "web": ("delivery-041-web.log", "# pass 164"),
        "desktop": ("delivery-041-desktop.log", "# pass 44"),
    }
    evidence = {}
    for key, (filename, expected) in logs.items():
        path = ROOT / "artifacts" / filename
        body = path.read_text(encoding="utf-8", errors="replace")
        assert expected in body, f"Missing completed validation: {filename}"
        evidence[key] = dict(path=path.relative_to(ROOT).as_posix(), result=expected,
                             sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    write(OUT / "engineering-validation.json", dict(version="0.4.1", source_manifest_sha256=digest,
        tests=evidence, additional_guards="Seven evaluation guards added after full collection passed in the final 86-test targeted suite",
        skipped="Optional torch/PyMuPDF and platform-specific sqlite-vec probes; Desktop two platform cases",
        package="NOT_REBUILT"))


if __name__ == "__main__":
    main()
