"""Fixed multi-turn tutoring evaluation, scored automatically.

Each scenario in ``tutor_multiturn_v1.json`` is played through the real
product app over the student WebSocket, in a throwaway database. Every
tutor turn is scored by rules and the local verifier on the six dimensions
of the tutor-v2 matrix. No human rater is involved; this is an automated
regression and release gate, not a human quality review.

Modes:
- ``template``: no model is configured, the deterministic template writer
  speaks. Runs offline and in CI.
- ``live``: an OpenAI-compatible model is registered for every role. Use
  it as the gate before a model goes to production.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCENARIOS = Path(__file__).with_name("tutor_multiturn_v1.json")
DIMENSIONS = {
    "math": "数学正确",
    "relevance": "目标相关",
    "evidence": "学生证据",
    "actionability": "可执行性",
    "adaptation": "适配",
    "coherence": "连贯",
}
GATE_MIN = {"math": 1.0, "relevance": 0.9, "evidence": 1.0, "actionability": 0.8, "adaptation": 0.9, "coherence": 0.95}
TEACHING_ACTIONS = {"GIVE_HINT", "EXPLAIN_CONCEPT", "SHOW_EXAMPLE", "ASK_STUDENT", "CORRECT_STEP"}
_NEXT_STEP = re.compile(r"[？?]|试试|试一试|写出|写下|再写|先|想一想|想想|算一算|下一步|接下来|接着|你来|你可以|看看|说出|请")


@dataclass
class Check:
    dimension: str
    passed: bool
    detail: str
    critical: bool = False


@dataclass
class ScenarioResult:
    id: str
    title: str
    checks: list[Check] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)

    def add(self, dimension: str, passed: bool, detail: str, *, critical: bool = False) -> None:
        self.checks.append(Check(dimension, bool(passed), detail, critical))

    @property
    def critical_failures(self) -> list[Check]:
        return [c for c in self.checks if c.critical and not c.passed]

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)


@contextmanager
def _client(db_path: Path, live: dict | None, prepare=None):
    from fastapi.testclient import TestClient
    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import get_product_state, reset_product_state
    from mathtutor.security.settings import MathTutorSecuritySettings

    reset_product_state()
    app = create_math_tutor_app(MathTutorSecuritySettings(environment="development", host="127.0.0.1"),
                                auth_enabled=False, db_path=str(db_path))
    try:
        with TestClient(app) as client:
            if live:
                _register_live_model(get_product_state(), live)
            if prepare:
                prepare(get_product_state())
            yield client
    finally:
        reset_product_state()


def _register_live_model(state, live: dict) -> None:
    from mathtutor.api.product_state import _build_writer
    from mathtutor.infrastructure.generative_gateway import ModelRole, OpenAICompatibleProvider

    key = live["api_key"]

    async def resolve_key():
        return key

    for role in ModelRole:
        state.gateway.register_provider(role, OpenAICompatibleProvider(
            base_url=live["base_url"], model=live["model"], api_key_resolver=resolve_key,
            provider_id="eval-live"))
    state.controller.writer = _build_writer(state.gateway)


def _collect(ws) -> list[dict]:
    frames = []
    while True:
        frame = ws.receive_json()
        frames.append(frame)
        if frame["event_type"] == "turn_end":
            return frames


def _send(ws, session: str, command: str, key: str, payload: dict | None = None) -> list[dict]:
    ws.send_json(dict(protocol_version=2, request_id=key, idempotency_key=key, session_id=session,
                      command=command, payload=payload or {}))
    return _collect(ws)


def _turn_view(frames: list[dict]) -> dict:
    terminal = next((f for f in reversed(frames) if f["event_type"] in
                     {"assistant_complete", "assistant_partial", "assistant_error"}), None)
    payload = (terminal or {}).get("payload", {})
    return {
        "actions": [f["payload"]["action"] for f in frames if f["payload"].get("action")],
        "errors": [f["payload"].get("error_code") for f in frames if f["event_type"] == "turn_error"],
        "status": payload.get("status", ""),
        "text": payload.get("final_text") or payload.get("error") or "",
        "deliveries": [f["delivery_id"] for f in frames if f.get("delivery_id")],
    }


async def _refuted_formulas(text: str, anchor) -> list[str]:
    from mathtutor.application.math_claims import certify
    from mathtutor.application.verification_backend import InProcessVerificationBackend

    result = await certify(text, InProcessVerificationBackend(), anchor=anchor)
    return [statement.shown for statement, _ in result.refuted]


def run_scenario(scenario: dict, workdir: Path, live: dict | None = None, prepare=None) -> ScenarioResult:
    from mathtutor.application.math_claims import anchor_for
    from mathtutor.solving.parser import parse_problem

    result = ScenarioResult(scenario["id"], scenario["title"])
    parsed = parse_problem(scenario["problem"]).problem if scenario.get("problem") else None
    anchor = anchor_for(parsed) if parsed else None
    forbidden = [re.compile(p) for p in scenario.get("forbidden_before_solution", [])]
    session = f"eval-{scenario['id']}"
    solution_shown = False
    previous_strategy = None
    with _client(workdir / f"{scenario['id']}.db", live, prepare) as client, \
            client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        def snapshot():
            response = client.get(f"/api/v2/math-tutor/sessions/{session}")
            return response.json() if response.status_code == 200 else {}

        for index, step in enumerate(scenario["steps"]):
            key = f"{scenario['id']}-{index}"
            frames = _send(ws, session, step["send"], key, step.get("payload"))
            view = _turn_view(frames)
            if step.get("ack"):
                for delivery in view["deliveries"]:
                    ws.send_json({"type": "delivery_presented", "delivery_id": delivery})
            state = snapshot()
            expect = step.get("expect", {})
            label = f"第 {index + 1} 轮 {step['send']}"
            result.transcript.append({"step": index + 1, "send": step["send"], "payload": step.get("payload", {}),
                                      **{k: view[k] for k in ("actions", "errors", "status", "text")},
                                      "state": state.get("state", "")})

            # Coherence: only expected errors, no unfinished output.
            expected_error = expect.get("error_code")
            result.add("coherence", view["errors"] == ([expected_error] if expected_error else []),
                       f"{label}：错误码 {view['errors'] or '无'}（预期 {expected_error or '无'}）",
                       critical=not expected_error and bool(view["errors"]))
            if view["status"] == "PARTIAL" and not expected_error:
                result.add("coherence", False, f"{label}：回答未完成（PARTIAL）")
            if "state" in expect:
                result.add("coherence", state.get("state") == expect["state"],
                           f"{label}：状态 {state.get('state')}（预期 {expect['state']}）")
            if "state_not" in expect:
                result.add("coherence", state.get("state") != expect["state_not"],
                           f"{label}：状态 {state.get('state')}（不应为 {expect['state_not']}）")
            if step.get("replay"):
                again = _send(ws, session, step["send"], key, step.get("payload"))
                result.add("coherence", again == frames, f"{label}：重发同一请求的回放一致")

            # Relevance: the turn did what the student asked for.
            for action in expect.get("actions", []):
                result.add("relevance", action in view["actions"],
                           f"{label}：出现动作 {action}（实际 {view['actions']}）")
            for fragment in expect.get("contains", []):
                result.add("relevance", fragment in view["text"], f"{label}：包含「{fragment}」")

            # Math: every formula the tutor wrote passes verify_math.
            if view["text"]:
                wrong = asyncio.run(_refuted_formulas(view["text"], anchor))
                result.add("math", not wrong, f"{label}：算式核验" + (f"未通过 {wrong}" if wrong else "通过"),
                           critical=bool(wrong))

            # Answer exposure before the student earned or asked for it.
            if expect.get("no_answer") or (forbidden and not solution_shown and "SHOW_SOLUTION" not in view["actions"]
                                           and state.get("state") not in {"solved", "solution_shown"}):
                leaked = [p.pattern for p in forbidden if p.search(view["text"])]
                result.add("adaptation", not leaked, f"{label}：未提前给出答案" + (f"（命中 {leaked}）" if leaked else ""),
                           critical=bool(leaked))
            if expect.get("solution_shown") or "SHOW_SOLUTION" in view["actions"]:
                solution_shown = True

            # Actionability: teaching turns end with a question or a next step.
            if TEACHING_ACTIONS & set(view["actions"]) and not view["errors"]:
                result.add("actionability", bool(_NEXT_STEP.search(view["text"][-160:])),
                           f"{label}：给出可执行的下一步")

            # Adaptation: repeated difficulty changes the teaching strategy.
            strategy = (state.get("teaching_plan") or {}).get("strategy")
            if expect.get("strategy_changed"):
                result.add("adaptation", bool(strategy) and strategy != previous_strategy,
                           f"{label}：教学策略由 {previous_strategy} 变为 {strategy}")
            previous_strategy = strategy or previous_strategy

        final = scenario.get("final", {})
        if final:
            state = snapshot()
            evidence = state.get("evidence_summary") or {}
            for kind, count in final.get("evidence", {}).items():
                result.add("evidence", evidence.get(kind, 0) == count,
                           f"证据 {kind} = {evidence.get(kind, 0)}（预期 {count}）", critical=True)
            if final.get("misconceptions"):
                profile = client.get("/api/v2/math-tutor/desktop/student-summary").json()
                found = [row["rule_id"] for row in profile.get("misconceptions", [])]
                for rule in final["misconceptions"]:
                    result.add("evidence", rule in found, f"画像错误概念包含 {rule}（实际 {found}）")
    return result


def score(results: list[ScenarioResult]) -> dict:
    by_dimension = {}
    for dimension, name in DIMENSIONS.items():
        checks = [c for r in results for c in r.checks if c.dimension == dimension]
        passed = sum(c.passed for c in checks)
        by_dimension[dimension] = {"name": name, "passed": passed, "total": len(checks),
                                   "score": round(passed / len(checks), 4) if checks else None}
    critical = [{"scenario": r.id, "detail": c.detail} for r in results for c in r.critical_failures]
    gate_failures = [f"{DIMENSIONS[d]} {v['score']} < {GATE_MIN[d]}" for d, v in by_dimension.items()
                     if v["score"] is not None and v["score"] < GATE_MIN[d]]
    if critical:
        gate_failures.insert(0, f"关键检查失败 {len(critical)} 项")
    return {"dimensions": by_dimension, "critical_failures": critical,
            "scenarios_passed": sum(r.passed for r in results), "scenarios_total": len(results),
            "gate": {"passed": not gate_failures, "thresholds": GATE_MIN, "failures": gate_failures}}


def run(mode: str = "template", *, live: dict | None = None, only: list[str] | None = None, prepare=None) -> dict:
    """``prepare(state)`` may swap writers in tests; production runs leave it unset."""
    spec = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    scenarios = [s for s in spec["scenarios"] if not only or s["id"] in only]
    with tempfile.TemporaryDirectory(prefix="mt-eval-") as tmp:
        results = [run_scenario(s, Path(tmp), live if mode == "live" else None, prepare) for s in scenarios]
    summary = score(results)
    return {
        "suite": spec["version"], "mode": mode, "model": (live or {}).get("model", "template"),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "human_review": False, **summary,
        "scenarios": [{"id": r.id, "title": r.title, "passed": r.passed,
                       "checks": [c.__dict__ for c in r.checks], "transcript": r.transcript} for r in results],
    }


def render_markdown(report: dict) -> str:
    lines = [f"# 固定多轮辅导评测（{report['suite']}）", "",
             f"- 模式：`{report['mode']}`；模型：`{report['model']}`；生成时间：{report['generated_at']}",
             "- 评分方式：全部自动（规则 + 本地验证器），**没有人工评分**。",
             f"- 场景通过：{report['scenarios_passed']}/{report['scenarios_total']}",
             f"- 发布门：**{'通过' if report['gate']['passed'] else '未通过'}**"
             + ("" if report["gate"]["passed"] else "（" + "；".join(report["gate"]["failures"]) + "）"), "",
             "| 维度 | 通过/总数 | 得分 | 门槛 |", "|---|---|---|---|"]
    for key, row in report["dimensions"].items():
        lines.append(f"| {row['name']} | {row['passed']}/{row['total']} | {row['score']} | {GATE_MIN[key]} |")
    lines += ["", "## 场景", "", "| 场景 | 结果 | 未通过的检查 |", "|---|---|---|"]
    for scenario in report["scenarios"]:
        failed = [c["detail"] for c in scenario["checks"] if not c["passed"]]
        lines.append(f"| {scenario['title']} | {'通过' if scenario['passed'] else '未通过'} | {'；'.join(failed) or '—'} |")
    if report["critical_failures"]:
        lines += ["", "## 关键失败", ""] + [f"- `{c['scenario']}`：{c['detail']}" for c in report["critical_failures"]]
    return "\n".join(lines) + "\n"


__all__ = ["DIMENSIONS", "GATE_MIN", "render_markdown", "run", "run_scenario", "score"]
