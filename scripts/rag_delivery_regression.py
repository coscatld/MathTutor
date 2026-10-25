"""Bounded continuation of the authorized real development evaluation.

Original evidence is read-only. Each dispatch durably reserves the cumulative
budget before sending. Only new responses with complete usage release a reserve.
"""
from __future__ import annotations
import asyncio
import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import threading

from rag_live_acceptance import ROOT, write, RecordedProvider, BudgetExhausted, route_b

OLD = ROOT / "artifacts/live-acceptance-20260920-v4"
OUT = ROOT / "artifacts/delivery-regression-20260920"


class CumulativeProvider(RecordedProvider):
    def __init__(self, provider, auth, directory):
        super().__init__(provider, auth, directory)
        self.ledger = OUT / "budget.json"
        if self.ledger.exists():
            data = json.loads(self.ledger.read_text(encoding="utf-8"))
            self.requests, self.accounted_tokens = data["requests"], data["charged_tokens"]
        else:
            self.requests, self.accounted_tokens = 24, 169364
        self.persist()

    def persist(self):
        write(self.ledger, dict(requests=self.requests, charged_tokens=self.accounted_tokens,
            request_limit=120, token_limit=300000, historical_charge=169364,
            policy="Old reservations never refunded; new complete usage settles reservation, unknown retains full reserve"))

    async def complete(self, messages, **kwargs):
        kwargs["max_retries"] = 0
        kwargs["max_tokens"] = min(kwargs.get("max_tokens") or 1800, 1800)
        reserved = len(json.dumps(dict(messages=messages, tools=kwargs.get("tools")), ensure_ascii=False).encode()) + 2048 + kwargs["max_tokens"]
        with self.lock:
            if self.requests >= 120 or self.accounted_tokens + reserved > 300000:
                raise BudgetExhausted("Cumulative authorized budget exhausted before dispatch")
            self.requests += 1
            self.accounted_tokens += reserved
            row = dict(request_id=self.requests, case_id=self.case_id, messages=messages,
                parameters=kwargs, reserved_tokens=reserved, charged_tokens=reserved,
                execution_status="STARTED", provider=self.provider_id, model=self.model)
            self.rows.append(row)
            self._save(row)
            self.persist()
        try:
            response = await asyncio.wait_for(self.provider.complete(messages, **kwargs), 60)
            row.update(execution_status="COMPLETED", response=response.model_dump(mode="json"))
            self.settle(row, response.input_tokens, response.output_tokens)
            return response
        except BaseException as exc:
            from mathtutor.infrastructure.gateway_config import classify_gateway_error
            diagnostic = getattr(exc, "diagnostics", {})
            row.update(execution_status="ERROR", error_type=type(exc).__name__,
                error_category=classify_gateway_error(str(exc)), diagnostics=diagnostic)
            usage = diagnostic.get("usage", {})
            self.settle(row, usage.get("prompt_tokens"), usage.get("completion_tokens"))
            raise
        finally:
            self._save(row)
            self.persist()

    def settle(self, row, incoming, outgoing):
        known = all(type(n) is int and n >= 0 for n in (incoming, outgoing))
        row["usage_estimated"] = not known
        if known:
            with self.lock:
                charge = incoming + outgoing
                self.accounted_tokens += charge - row["reserved_tokens"]
                row["charged_tokens"] = charge


def setup(phase):
    from mathtutor.infrastructure.generative_gateway import GenerativeModelGateway, ModelRole
    from mathtutor.infrastructure.gateway_config import GatewayConfigService
    from mathtutor.infrastructure.keychain_secret_store import KeychainSecretStore
    OUT.mkdir(exist_ok=True)
    directory = OUT / phase
    directory.mkdir(exist_ok=False)
    auth = json.loads((OLD / "authorization.json").read_text(encoding="utf-8"))
    assert auth["authorized"] and auth["max_requests"] == 120 and auth["max_total_tokens"] == 300000
    store = KeychainSecretStore()
    gateway = GenerativeModelGateway(store)
    service = GatewayConfigService(gateway, store, Path(auth["gateway_config_path"]))
    base = gateway.provider_for(ModelRole.TUTOR_WRITER)
    assert (base.provider_id, base.model) == (auth["provider"], auth["model"])
    write(directory / "source-digest.json", {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [ROOT / "src/mathtutor/infrastructure/generative_gateway.py",
                  ROOT / "src/mathtutor/infrastructure/tutor_chat.py", Path(__file__)]})
    return CumulativeProvider(base, auth, directory), store, service, directory


def diagnose(phase):
    numbers = [13, 15] if phase == "diagnose" else [18, 20, 21, 22, 24]
    provider, _, _, directory = setup("diagnostic-baseline" if phase == "diagnose" else "diagnostic-failures")
    write(directory / "plan.json", dict(original_request_ids=numbers,
        change="Metadata capture only; identical saved messages, temperature, output cap, model; no retries",
        caveat="New samples diagnose reproducibility; missing old raw HTTP cannot be reconstructed"))
    async def calls():
        for number in numbers:
            old = json.loads((OLD / "execution" / f"request-{number:03}.json").read_text(encoding="utf-8"))
            provider.case_id = f"diagnostic:original-{number:03}"
            try:
                await provider.complete(old["messages"], **old["parameters"])
            except Exception:
                pass
    asyncio.run(calls())


def expressions(phase):
    provider, store, service, directory = setup(phase)
    plan = json.loads((OLD / "plan.json").read_text(encoding="utf-8"))
    if phase == "degenerate-fixed":
        plan["questions"] = [dict(case_id=key, question=question, corpus="easy", mode="send_message", reference=reference)
            for key, question, reference in [
                ("degenerate:a0", "请解释 ax^2+bx+c=0 在 a=0 时是否一定是一次方程。分别讨论 b不等于0、b=0且c不等于0、b=c=0 的方程类型和解集。", ["b!=0: linear, x=-c/b", "b=0,c!=0: contradiction, no roots", "b=c=0: identity, all real roots"]),
                ("degenerate:b0", "请解释 ax^2+bx+c=0 在 a不等于0、b=0 时仍是什么方程，并讨论 -c/a 为正、零、负的实根情况。", ["quadratic", "-c/a>0: two roots", "=0: repeated zero", "<0: no real roots"]),
                ("degenerate:c0", "请解释 ax^2+bx+c=0 在 a不等于0、c=0 时的因式分解和实根，并单独说明 b=0 时会怎样。", ["x(ax+b)=0", "0 and -b/a", "b=0: repeated zero, still quadratic"]),
            ]]
        plan["reference_status"] = "PROVISIONAL_AI_NOT_HUMAN_REVIEWED"
    write(directory / "plan.json", plan)
    with tempfile.TemporaryDirectory(prefix="mathtutor-delivery-") as folder:
        route_b(plan, provider, store, service.current_config(), directory, Path(folder) / "B")


def knowledge(phase):
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import get_product_state, reset_product_state
    from mathtutor.security.settings import MathTutorSecuritySettings
    from mathtutor.infrastructure.generative_gateway import ModelRole
    from mathtutor.application.knowledge_tools import KnowledgeTools
    from mathtutor.application import tutor_runtime
    provider, store, _, directory = setup(phase)
    cases = [
        dict(case_id="K1_summary", question="请用自己的话解释资料中移项为什么要变号，并给出依据。", expected="seed read_source allowed without repeated search; summary invokes support_check"),
        dict(case_id="K2_quote", question="请逐字引用资料中关于移项依据的原句。", expected="read_source and verbatim quote; support_check not required for quote"),
        dict(case_id="K3_absent", question="这份移项资料的作者姓名和出生日期是什么？", expected="acknowledge missing information; no invented claim"),
        dict(case_id="K4_hint", question="只要提示，不要直接答案：移项为什么要变号？", expected="hints_only gate; zero retrieval/tool/model calls"),
    ]
    corpus = "# 移项依据\n移项的依据是等式的基本性质。等式两边同时加上或减去同一个数，等式仍然成立。把等式一边的某项移到另一边时，该项的符号改变。\n"
    if phase == "knowledge-ranges":
        cases = cases[:1]
    write(directory / "plan.json", dict(cases=cases, corpus=corpus, mode="knowledge", tool_mode="native",
        reference_status="PROVISIONAL_AI_NOT_HUMAN_REVIEWED", forced_search=False))
    rows, events = [], []
    original_execute, original_seed = KnowledgeTools.execute, KnowledgeTools.seed_evidence
    original_check = tutor_runtime.check_claim_support
    async def execute(executor, name, arguments, call_id):
        result = await original_execute(executor, name, arguments, call_id)
        events.append(dict(event="tool_executed", tool=name, arguments=arguments, call_id=call_id, receipt=result))
        return result
    async def seed(executor, pack):
        result = await original_seed(executor, pack)
        events.append(dict(event="initial_evidence", pack=pack.public_projection() if pack else None,
                           readable_seed_ranges=len(executor.search_hits)))
        return result
    async def check(invoke, claims):
        before = provider.requests
        result = await original_check(invoke, claims)
        events.append(dict(event="support_check", claims=claims, result=result,
                           request_record_ids=list(range(before+1, provider.requests+1))))
        return result
    with tempfile.TemporaryDirectory(prefix="mathtutor-knowledge-live-") as folder:
        import secrets
        reset_product_state()
        try:
            with patch("mathtutor.api.product_state._default_secret_store", return_value=store):
                settings = MathTutorSecuritySettings(
                    environment="development", host="127.0.0.1",
                    allowed_hosts=("testserver",), allowed_origins=(),
                    bridge_secret=secrets.token_hex(32),
                )
                app = create_math_tutor_app(settings, auth_enabled=False, db_path=str(Path(folder) / "knowledge.db"))
            state = get_product_state()
            for role in ModelRole:
                state.gateway.register_provider(role, provider)
            with patch.object(KnowledgeTools, "execute", execute), patch.object(KnowledgeTools, "seed_evidence", seed), \
                 patch.object(tutor_runtime, "check_claim_support", check), \
                 TestClient(app, headers={"X-MathTutor-Bridge": settings.bridge_secret}) as client:
                for case in cases:
                    cid = case["case_id"]
                    provider.case_id = cid
                    events = []
                    before = provider.requests
                    row = dict(**case, mode="knowledge", events=events, frames=[], human_review_status="PENDING")
                    try:
                        imported = client.post("/api/v2/math-tutor/desktop/documents/import", params={"conversation_id": cid},
                            files={"file": ("移项依据.md", corpus.encode(), "text/markdown")})
                        imported.raise_for_status()
                        mounted = client.put("/api/v2/math-tutor/desktop/knowledge/conversations/"+cid,
                            json=dict(mode="knowledge", tool_mode="native"))
                        mounted.raise_for_status()
                        row["actual_mount"] = mounted.json()
                        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
                            ws.send_json(dict(protocol_version=2, request_id=cid, idempotency_key=cid, session_id=cid,
                                command="send_message", payload=dict(text=case["question"])))
                            while True:
                                frame = ws.receive_json()
                                row["frames"].append(frame)
                                if frame["event_type"] == "turn_end":
                                    break
                        finals = [f["payload"] for f in row["frames"] if f["event_type"] in
                                  {"assistant_complete", "assistant_partial", "assistant_error"}]
                        terminal = finals[-1] if finals else {}
                        row.update(execution_status="COMPLETED", final_answer=terminal.get("final_text"),
                            application_status=terminal.get("status"), finish_reason=terminal.get("finish_reason"))
                    except Exception as exc:
                        row.update(execution_status="ERROR", error_type=type(exc).__name__, error=str(exc)[:400])
                    row["request_record_ids"] = list(range(before+1, provider.requests+1))
                    rows.append(row)
                    write(directory / "K-results.json", rows)
        finally:
            reset_product_state()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("phase", choices=["diagnose", "diagnose-failures", "expression-fixed", "degenerate-fixed", "knowledge-ranges", "knowledge-final"])
    args = parser.parse_args()
    if args.phase.startswith("diagnose"):
        diagnose(args.phase)
    elif args.phase.startswith("knowledge"):
        knowledge(args.phase)
    else:
        expressions(args.phase)
