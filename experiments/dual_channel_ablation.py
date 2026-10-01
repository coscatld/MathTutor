"""Controlled ablation: dual-channel gate vs. single-channel and no-gate baselines.

Fault-injection experiment on the REAL components (SQLite knowledge store,
citation receipts, parser/solver/verifier, disclosure projector, output
guard). The "model outputs" are generated programmatically with known ground
truth, so every rate below is exact for this corpus; it measures what each
configuration lets through, NOT how often a real LLM makes each mistake.

Two experiments:

E1  claim gating (knowledge QA): 4 configurations over the same item set
    A  no gate          — everything the model writes is shown
    B  source only      — citation-verified RAG (receipts, verbatim, hash)
    C  math only        — LLM + deterministic solver, no citation checks
    D  dual channel     — this invention (KnowledgeTools.gate_final)

E2  answer disclosure (tutoring): prompt-only baseline (full solution in the
    model context, "please don't reveal") vs. projection + output guard, on
    injected leak utterances and clean hints, levels L1–L4.

Usage:  python experiments/dual_channel_ablation.py [--seed 7] [--out docs/experiments]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import random
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

from mathtutor.api.product_state import ProductState
from mathtutor.application.knowledge import KnowledgeError
from mathtutor.application.knowledge_tools import Final, KnowledgeTools
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.domain.dual_channel_gate import GATE_POLICY_VERSION, MathState, SourceState, Treatment, decide
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.schema import metadata

OWNER, CID = "alice", "A"


# --------------------------------------------------------------------------- corpus

def make_problems(rng: random.Random, n_linear=30, n_quadratic=15, n_system=15):
    problems = []
    for _ in range(n_linear):
        a, r, b = rng.randint(2, 9), rng.randint(-9, 12), rng.randint(-15, 15)
        c = a * r + b
        expr = f"{a}x{'+' if b >= 0 else '-'}{abs(b)}={c}"
        problems.append({"type": "linear", "expression": expr, "answer": f"x={r}",
                         "wrong": f"x={r + rng.choice([-2, -1, 1, 2])}", "roots": [r], "a": a, "b": b})
    for _ in range(n_quadratic):
        r1, r2 = rng.sample(range(-7, 9), 2)
        s, p = r1 + r2, r1 * r2
        expr = f"x^2{'-' if s >= 0 else '+'}{abs(s)}x{'+' if p >= 0 else '-'}{abs(p)}=0"
        lo, hi = sorted((r1, r2))
        problems.append({"type": "quadratic", "expression": expr, "answer": f"x={lo}或x={hi}",
                         "wrong": f"x={lo}或x={hi + 1}", "roots": [lo, hi], "p": p})
    for _ in range(n_system):
        x, y = rng.randint(-6, 9), rng.randint(-6, 9)
        expr = f"x+y={x + y}, x-y={x - y}"
        problems.append({"type": "system", "expression": expr, "answer": f"x={x}, y={y}",
                         "wrong": f"x={x}, y={y + 1}", "roots": [x, y]})
    return problems


async def build_state(tmp: pathlib.Path):
    engine = create_db_engine(tmp / "knowledge.db")
    async with engine.begin() as db:
        await db.run_sync(metadata.create_all)
    state = ProductState(engine=engine, data_dir=tmp, verification_backend=InProcessVerificationBackend())
    await state.conversations.ensure(OWNER, CID)
    return state, engine


async def seed_documents(state, problems, rng, erratum_rate):
    k = state.knowledge
    space = await k.create_space(OWNER, "教材例题")
    for i, problem in enumerate(problems):
        erratum = rng.random() < erratum_rate
        stated = problem["wrong"] if erratum else problem["answer"]
        sentence = f"例题{i + 1}：解方程 {problem['expression']}，得 {stated}。"
        body = f"# 例题{i + 1}\n{sentence}\n解完后要把结果代回原方程检验。\n"
        doc = await k.save_markdown(OWNER, space["space_id"], title=f"例题{i + 1}", body=body,
                                    operation_id=f"import:{i}")
        problem.update(document_id=str(doc["document_id"]), sentence=sentence, erratum=erratum, stated=stated)
    await k.configure(OWNER, CID, space_ids=[space["space_id"]])


async def read_example(executor, problem):
    """Register the example's exact range as a search hit, then really read it."""
    snap = await executor.knowledge.snapshot(OWNER, problem["document_id"])
    start = snap["body"].index(problem["sentence"])
    key = (problem["document_id"], snap["version"], start, start + len(problem["sentence"]))
    executor.search_hits[key] = "例题"
    receipt = await executor.execute("read_source", dict(zip(("document_id", "version", "start", "end"), key)), "r")
    assert receipt["ok"], receipt
    return receipt["result"]


def items_for(problem, source_id):
    """Model outputs with injected faults; each item carries its ground truth."""
    expr, sentence = problem["expression"], problem["sentence"]
    quote = lambda text, evidence=None, sid=source_id: {  # noqa: E731
        "text": text, "kind": "quote", "evidence": [{"source_id": sid, "quote": evidence or text}]}
    summary = lambda text: {"text": text, "kind": "summary",  # noqa: E731
                            "evidence": [{"source_id": source_id, "quote": f"解方程 {expr}"}]}
    assertion = lambda answer, index=0: {"expression": expr, "answer": answer, "claim_index": index}  # noqa: E731
    items = []
    if problem["erratum"]:
        items.append(("source_ok_math_wrong", {"claims": [quote(sentence)], "math_assertions": [assertion(problem["stated"])]}))
    else:
        items.append(("clean", {"claims": [quote(sentence)], "math_assertions": [assertion(problem["stated"])]}))
    items += [
        ("forged_citation", {"claims": [quote(f"教材指出：{expr} 的解是 {problem['answer']}。")],
                             "math_assertions": [assertion(problem["answer"])]}),
        ("forged_citation", {"claims": [quote(sentence.replace("：", "，").replace("，得", "，可得"))],
                             "math_assertions": [assertion(problem["answer"])]}),
        ("forged_citation", {"claims": [quote(sentence, sid="s-" + "0" * 24)],
                             "math_assertions": [assertion(problem["answer"])]}),
        ("model_math_error", {"claims": [summary(f"按例题的方法可得 {problem['wrong']}")],
                              "math_assertions": [assertion(problem["wrong"])]}),
        ("clean", {"claims": [summary(f"按例题的方法可得 {problem['answer']}")],
                   "math_assertions": [assertion(problem["answer"])]}),
        ("model_math_error", {"claims": [], "math_assertions": [{"expression": expr, "answer": problem["wrong"]}]}),
        ("clean", {"claims": [], "math_assertions": [{"expression": expr, "answer": problem["answer"]}]}),
    ]
    return items


# ----------------------------------------------------------------- E1 configurations

FLAGGING = {Treatment.SHOW_MATH_UNVERIFIED, Treatment.SHOW_SOURCE_MATH_CONFLICT}


async def channel_states(executor, final):
    """Run both channels once; every configuration combines the same states."""
    source = await executor.source_state(final.claims[0]) if final.claims else SourceState.NONE
    a = final.math_assertions[0]
    math = await executor.math_state(a.expression, a.answer)
    return source, math


def outcome(config, source, math):
    """(shown, flagged, conflict) for one item under a configuration."""
    if config == "A_no_gate":
        return True, False, False
    if config == "B_source_only":
        return source is not SourceState.REJECTED, False, False
    if config == "C_math_only":
        decision = decide(SourceState.NONE, math)   # no citation checks: all text is model text
        return decision.visible, decision.treatment in FLAGGING, False
    raise ValueError(config)


async def dual_channel(executor, final):
    executor.gate_log.clear()
    try:
        await executor.gate_final(final)
    except KnowledgeError:
        return False, False, False
    treatment = Treatment(executor.gate_log[0]["treatment"])
    return (treatment not in {Treatment.WITHHOLD, Treatment.DROP_MATH}, treatment in FLAGGING,
            treatment is Treatment.SHOW_SOURCE_MATH_CONFLICT)


async def experiment_claims(state, problems):
    executor = KnowledgeTools(state, OWNER, CID, generation=await state.knowledge.generation(OWNER))

    async def supports(_):
        # Summary entailment is a separate, pre-existing component (an LLM
        # check in production). Every summary in this corpus quotes real
        # evidence, so the stub accepts them all: E1 isolates the merge.
        return True
    executor.support_checker = supports
    configs = ["A_no_gate", "B_source_only", "C_math_only", "D_dual_channel"]
    tallies = {c: defaultdict(Counter) for c in configs}
    states = Counter()
    for problem in problems:
        source = await read_example(executor, problem)
        for label, payload in items_for(problem, source["source_id"]):
            final = Final.model_validate(payload)
            src, math = await channel_states(executor, final)
            states[(label, src.value, math.value)] += 1
            for config in configs:
                shown, flagged, conflict = (await dual_channel(executor, final) if config == "D_dual_channel"
                                            else outcome(config, src, math))
                t = tallies[config][label]
                t["n"] += 1
                t["shown"] += shown
                t["shown_unflagged"] += shown and not flagged
                t["conflict_flagged"] += shown and conflict
    return tallies, states


def claim_metrics(tallies):
    rows = {}
    for config, by_label in tallies.items():
        wrong = [by_label[k] for k in ("model_math_error", "source_ok_math_wrong")]
        n_wrong = sum(t["n"] for t in wrong)
        forged, clean, erratum = by_label["forged_citation"], by_label["clean"], by_label["source_ok_math_wrong"]
        rows[config] = {
            "wrong_math_shown_unflagged": sum(t["shown_unflagged"] for t in wrong) / n_wrong,
            "forged_citation_shown": forged["shown"] / forged["n"],
            "clean_retained": clean["shown"] / clean["n"],
            "source_math_conflict_flagged": (erratum["conflict_flagged"] / erratum["n"]) if erratum["n"] else None,
            "erratum_quote_retained": (erratum["shown"] / erratum["n"]) if erratum["n"] else None,
            "n": {label: t["n"] for label, t in by_label.items()},
        }
    return rows


# ------------------------------------------------------------------- E2 disclosure

def leak_and_clean(problem):
    roots = problem["roots"]
    if problem["type"] == "linear":
        r, a, b = roots[0], problem["a"], problem["b"]
        leaks = {"assignment": f"所以 x={r}。", "spaced": f"答案是 x = {r}。", "bare_value": f"最后结果是 {r}。",
                 "unreduced": f"未知数等于 {2 * r}/2。", "equivalent_root_eq": f"其实就是 x-{r}=0 的根。" if r >= 0
                 else f"其实就是 x+{-r}=0 的根。"}
        clean = {"move_constant": f"先把常数项 {b} 移到等号另一边，注意变号。",
                 "divide_coefficient": f"再两边同时除以系数 {a}。", "concept": "回忆等式的基本性质。"}
    elif problem["type"] == "quadratic":
        lo, hi = roots
        leaks = {"assignment": f"所以 x={lo}或x={hi}。", "indexed": f"x1={lo}，x2={hi}。",
                 "bare_values": f"两个根是 {lo} 和 {hi}。", "factored": f"可以写成 (x-({lo}))(x-({hi}))=0。"}
        clean = {"discriminant": "先算一算判别式，判断有几个实根。",
                 "factor_hint": f"试着找两个数，它们的积是 {problem['p']}。", "concept": "回忆因式分解法的步骤。"}
    else:
        x, y = roots
        leaks = {"assignment": f"所以 x={x}, y={y}。", "partial_assignment": f"先告诉你 x={x}。",
                 "reversed": f"y={y}，x={x}。"}
        clean = {"eliminate": "把两个方程相加，可以消去 y。", "concept": "回忆加减消元法。"}
    return leaks, clean


def heldout_leak_and_clean(problem):
    """Held-out phrasings, written AFTER the guard fix and never used to tune it."""
    roots = problem["roots"]
    if problem["type"] == "linear":
        r, a, b = roots[0], problem["a"], problem["b"]
        leaks = {"fullwidth_equals": f"解得x＝{r}。", "answer_colon": f"答：{r}", "decimal": f"x 的值是 {r}.0。",
                 "substitute_claim": f"把 x={r} 代回原方程正好成立，所以就是它。"}
        clean = {"add_both_sides": f"等式两边同时加上 {abs(b)}。", "coefficient": f"x 的系数是 {a}。",
                 "check_wrong_value": f"检查一下 x={r + 3} 是不是解？"}
    elif problem["type"] == "quadratic":
        lo, hi = roots
        leaks = {"subscript": f"x₁={lo}, x₂={hi}。", "solution_set": f"解集为 {{{lo}, {hi}}}。",
                 "shared_variable": f"x = {lo}, {hi}。"}
        clean = {"vieta_hint": "两根之和与两根之积分别和系数有什么关系？",
                 "check_wrong_value": f"把 x={hi + 2} 代进去试试，看看等不等于 0。"}
    else:
        x, y = roots
        leaks = {"tuple": f"(x, y) = ({x}, {y})。", "chinese_is": f"x是{x}，y是{y}。"}
        clean = {"substitute_hint": "先用第一个方程把 y 用 x 表示出来。",
                 "check_wrong_value": f"试试 x={x + 2} 能不能同时满足两个方程？"}
    return leaks, clean


def heldout2_leak_and_clean(problem):
    """Second held-out set, written BEFORE the generic normalization fix."""
    roots = problem["roots"]
    if problem["type"] == "linear":
        r, a, b = roots[0], problem["a"], problem["b"]
        leaks = {"value_is_x": f"{r} 就是要求的 x。", "fill_in": f"x 应该填 {r}。", "approx": f"结果：x ≈ {r}。"}
        clean = {"coefficient_first": f"x 前面的系数为 {a}，先处理它。",
                 "rhs_constant": f"注意 {a * r + b} 在等号右边。"}
    elif problem["type"] == "quadratic":
        lo, hi = roots
        leaks = {"enumeration_comma": f"两个解分别为 {lo}、{hi}。", "equals_or": f"x 等于 {lo} 或 {hi}。",
                 "roots_and": f"根为 {lo} 与 {hi}。"}
        clean = {"constant_term": f"常数项是 {problem['p']}，想想它能分解成哪两个数的积。"}
    else:
        x, y = roots
        leaks = {"respectively": f"x 与 y 分别是 {x} 和 {y}。", "fullwidth_semicolon": f"x={x}；y={y}。"}
        clean = {"subtract_hint": "两式相减，可以先求出 2y。"}
    return leaks, clean


def experiment_disclosure(problems, templates=leak_and_clean):
    from mathtutor.domain.problem import MathProblem
    from mathtutor.domain.solution import VerifiedSolutionRef
    from mathtutor.domain.tutoring import TutorAction
    from mathtutor.pedagogy.disclosure import SolutionDisclosureProjector
    from mathtutor.pedagogy.output_guard import TutorOutputGuard
    from mathtutor.pedagogy.tutor_writer import TutorWriterCandidate
    from mathtutor.solving import parse_problem, solve_problem, verify

    guard, projector = TutorOutputGuard(), SolutionDisclosureProjector()
    leak_stats, clean_stats, context = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    for problem in problems:
        parsed = parse_problem(problem["expression"].replace(", ", "; ")).problem
        canon = MathProblem.canonicalize(problem_type=parsed.problem_type, normalized_ast=parsed.normalized_ast,
                                         display_latex=parsed.display_latex)
        solved = solve_problem(canon, parsed)
        decision = verify(canon, solved.candidate)
        if decision.verdict != "VERIFIED":
            continue
        ref = VerifiedSolutionRef(verification_log_id=decision.decision_id, problem_id=canon.problem_id,
                                  problem_content_hash=canon.content_hash, solution_candidate_id=solved.candidate.candidate_id,
                                  solution_payload_hash=solved.candidate.payload_hash, policy_id=decision.policy_id,
                                  policy_version=decision.policy_version, attestation_hash="experiment")
        leaks, clean = templates(problem)
        last_step = solved.candidate.steps[-1] if solved.candidate.steps else None
        for level in (1, 2, 3, 4):
            action = TutorAction(action="GIVE_HINT", effective_assistance_level=level,
                                 solution_visibility="hint" if level < 3 else "step")
            projected = projector.project(ref, solved.candidate, action, concept_hint="概念", strategy_hint="策略")
            steps = ([projected.approved_step] if projected.approved_step else []) + list(projected.approved_prefix)
            context[level]["n"] += 1
            context[level]["answer_in_projected_context"] += bool(projected.full_solution) or (last_step in steps)
            for name, text in leaks.items():
                out = guard.guard_or_fallback(candidate=TutorWriterCandidate(text=text, writer_version="experiment"),
                                              candidate_solution=solved.candidate, disclosure=projected, action=action)
                key = f"{problem['type']}:{name}"
                leak_stats[key]["n"] += 1
                leak_stats[key]["blocked"] += out.fallback_used
            for name, text in clean.items():
                out = guard.guard_or_fallback(candidate=TutorWriterCandidate(text=text, writer_version="experiment"),
                                              candidate_solution=solved.candidate, disclosure=projected, action=action)
                key = f"{problem['type']}:{name}"
                clean_stats[key]["n"] += 1
                clean_stats[key]["false_block"] += out.fallback_used
    return leak_stats, clean_stats, context


# --------------------------------------------------------------------------- report

def pct(x):
    return "—" if x is None else f"{100 * x:.1f}%"


def render_markdown(meta, claims, states, leak_sets, context):
    lines = [f"# 双通道门控对照实验（{meta['date']}）", "",
             f"- 门控策略版本：`{GATE_POLICY_VERSION}`；随机种子：{meta['seed']}；题目：{meta['problems']} 道"
             f"（一次方程 {meta['by_type']['linear']}、二次方程 {meta['by_type']['quadratic']}、二元一次方程组 {meta['by_type']['system']}）",
             f"- 教材例题勘误比例（模拟资料自身有错）：{meta['errata']} / {meta['problems']}",
             "- 方法：故障注入。模型输出按已知真值程序化生成，全部经过真实的知识库、引用凭证、解析/求解/验证器、披露投影与输出守卫。",
             "  结果是各配置“放行了什么”的精确比例，不代表真实大模型犯各类错误的频率。",
             "- 总结支持检查器在本实验中恒为“支持”（语料中的总结都引用了真实原文），E1 只隔离合流规则的作用。", "",
             "## E1 声明门控：四种配置", "",
             "| 配置 | 错误数学结论无警示展示率 ↓ | 虚假引用展示率 ↓ | 正确内容保留率 ↑ | 原文-数学冲突提示率 ↑ | 勘误原文保留率 |",
             "|---|---|---|---|---|---|"]
    names = {"A_no_gate": "A 无门控", "B_source_only": "B 仅来源核验", "C_math_only": "C 仅数学核验",
             "D_dual_channel": "D 双通道门控（本发明）"}
    for key, row in claims.items():
        lines.append(f"| {names[key]} | {pct(row['wrong_math_shown_unflagged'])} | {pct(row['forged_citation_shown'])} | "
                     f"{pct(row['clean_retained'])} | {pct(row['source_math_conflict_flagged'])} | {pct(row['erratum_quote_retained'])} |")
    n = claims["D_dual_channel"]["n"]
    lines += ["", "样本数：" + "，".join(f"{k} {v}" for k, v in n.items()), "",
              "### 通道状态分布（真值标签 × 来源状态 × 数学状态）", "", "| 标签 | 来源 | 数学 | 数量 |", "|---|---|---|---|"]
    for (label, src, math), count in sorted(states.items()):
        lines.append(f"| {label} | {src} | {math} | {count} |")
    lines += ["", "## E2 答案披露：投影 + 输出守卫", "",
              "| 等级 | 基线（完整解答放入上下文）答案在上下文中 | 投影后答案在上下文中 |", "|---|---|---|"]
    for level in sorted(context):
        c = context[level]
        lines.append(f"| L{level} | 100.0% | {pct(c['answer_in_projected_context'] / c['n'])} |")
    for title, (leak_stats, clean_stats) in leak_sets:
        lines += ["", f"### {title}", "", "| 注入的泄露形式 | 样本 | 守卫拦截率 |", "|---|---|---|"]
        for key in sorted(leak_stats):
            s = leak_stats[key]
            lines.append(f"| {key} | {s['n']} | {pct(s['blocked'] / s['n'])} |")
        total_leak = sum(s["n"] for s in leak_stats.values())
        total_blocked = sum(s["blocked"] for s in leak_stats.values())
        lines += [f"| **合计** | {total_leak} | **{pct(total_blocked / total_leak)}** |", "",
                  "| 正常提示（不应拦截） | 样本 | 误拦截率 |", "|---|---|---|"]
        for key in sorted(clean_stats):
            s = clean_stats[key]
            lines.append(f"| {key} | {s['n']} | {pct(s['false_block'] / s['n'])} |")
        total_clean = sum(s["n"] for s in clean_stats.values())
        total_false = sum(s["false_block"] for s in clean_stats.values())
        lines += [f"| **合计** | {total_clean} | **{pct(total_false / total_clean)}** |"]
    lines.append("")
    return "\n".join(lines)


async def main(seed: int, out: pathlib.Path):
    rng = random.Random(seed)
    problems = make_problems(rng)
    with tempfile.TemporaryDirectory() as tmp:
        state, engine = await build_state(pathlib.Path(tmp))
        try:
            await seed_documents(state, problems, rng, erratum_rate=0.2)
            tallies, states = await experiment_claims(state, problems)
        finally:
            await state.shutdown_runtime()
            await engine.dispose()
    claims = claim_metrics(tallies)
    leak_stats, clean_stats, context = experiment_disclosure(problems)
    held_leaks, held_clean, _ = experiment_disclosure(problems, heldout_leak_and_clean)
    held2_leaks, held2_clean, _ = experiment_disclosure(problems, heldout2_leak_and_clean)
    leak_sets = [("开发集（第一轮修复守卫时可见的表述）", (leak_stats, clean_stats)),
                 ("留出集 1（第一轮修复后新写；第二轮通用修复时可见）", (held_leaks, held_clean)),
                 ("留出集 2（第二轮修复前写好，从未用于调整守卫）", (held2_leaks, held2_clean))]
    meta = {"date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "seed": seed, "problems": len(problems),
            "by_type": dict(Counter(p["type"] for p in problems)), "errata": sum(p["erratum"] for p in problems),
            "gate_policy": GATE_POLICY_VERSION}
    out.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "claims": claims,
               "channel_states": [{"label": k[0], "source": k[1], "math": k[2], "count": v} for k, v in sorted(states.items())],
               "leaks": {k: dict(v) for k, v in leak_stats.items()}, "clean": {k: dict(v) for k, v in clean_stats.items()},
               "heldout_leaks": {k: dict(v) for k, v in held_leaks.items()}, "heldout_clean": {k: dict(v) for k, v in held_clean.items()},
               "heldout2_leaks": {k: dict(v) for k, v in held2_leaks.items()}, "heldout2_clean": {k: dict(v) for k, v in held2_clean.items()},
               "context": {f"L{k}": dict(v) for k, v in context.items()}}
    (out / f"dual_channel_ablation_seed{seed}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    report = render_markdown(meta, claims, states, leak_sets, context)
    (out / f"dual_channel_ablation_seed{seed}.md").write_text(report, encoding="utf-8", newline="\n")
    print(report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("docs/experiments"))
    args = parser.parse_args()
    asyncio.run(main(args.seed, args.out))
