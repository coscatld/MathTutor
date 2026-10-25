"""Opt-in development measurement using the production gateway and application.

prepare never reads credentials or calls a provider. run requires an explicit
authorization JSON and an already prepared plan. No labels reach model inputs.
This runner does not certify quality: independent human review remains required.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import hashlib
import inspect
import json
import re
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import rag_hard_set_probe as fixtures
from mathtutor.application.tutor_runtime import check_claim_support


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def preview_evidence(tmp):
    env = await fixtures.build_knowledge_harness(tmp)
    try:
        tools = await fixtures._tools(env["state"], "conv-a")
        return {key: await fixtures._surface(tools, query=query, title=title,
                    needle=fixtures._FACT_QUOTES[key], call_id="preview-"+key)
                for key, (query, title) in fixtures._SURFACE_SPECS.items()}
    finally:
        await env["state"].shutdown_runtime()
        await env["engine"].dispose()


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=False)
    easy = fixtures.official()
    # Existing citation expectations are NOT semantic reference labels.
    claims = [
        dict(case_id=c.key, claim=c.quotes[0][1], evidence_keys=list(c.cited),
             original_citation_case=asdict(c), reference_label=None,
             reference_reason=None, human_review_status="PENDING")
        for c in fixtures.CLAIM_CASES
    ]
    # These exercise absent information and partial support using the same docs.
    claims.extend([
        dict(case_id="S_missing_author", claim="这份判别式讲义的作者是张老师。",
             evidence_keys=["disc"], reference_label=None, reference_reason=None,
             human_review_status="PENDING"),
        dict(case_id="S_added_positive_roots", claim="判别式大于零时有两个不同实根，而且两根均为正数。",
             evidence_keys=["disc"], reference_label=None, reference_reason=None,
             human_review_status="PENDING"),
        dict(case_id="S_wrong_source", claim=fixtures._FACT_QUOTES["disc"],
             evidence_keys=["weida"], reference_label=None, reference_reason=None,
             human_review_status="PENDING"),
    ])
    with tempfile.TemporaryDirectory(prefix="mathtutor-eval-preview-") as tmp:
        evidence = asyncio.run(preview_evidence(Path(tmp)))
    for case in claims:
        case["prepared_evidence"] = [evidence[k] for k in case["evidence_keys"]]
    questions = [dict(case_id="easy:"+q.key, question=q.text, corpus="easy",
                      mode="send_message", reference=asdict(q)) for q in easy.QUERIES]
    questions += [dict(case_id="hard:"+q.key, question=q.text, corpus="hard",
                       mode="send_message", reference=asdict(q)) for q in fixtures.QUERY_CASES]
    plan = dict(schema="mathtutor.live-acceptance/1", cohort="DEVELOPMENT_REGRESSION",
                repetitions=1, claims=claims, questions=questions,
                source=fixtures.source_fingerprint(),
                runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                prompt_sha256=hashlib.sha256(inspect.getsource(check_claim_support).encode()).hexdigest(),
                quality_threshold_status="PROPOSED_NOT_FORMAL_ACCEPTANCE",
                proposed_thresholds=dict(valid_coverage_min=.95, supported_pass_min=.95,
                    unsupported_false_accept_max=.05, answer_faithfulness_macro_min=.95,
                    answerable_content_coverage_min=.90, severe_errors_max=0),
                review_required=["evidence_support", "math_correctness", "citation_attribution",
                                 "required_content_coverage", "teaching_compliance"],
                limitations=["Existing citation labels are not semantic gold labels",
                    "No independent holdout; no formal quality PASS permitted",
                    "14 existing questions do not cover every teaching mode",
                    "Repeated measurements must not inflate independent case count"])
    write(directory / "plan.json", plan)
    write(directory / "plan-digest.json", dict(sha256=fingerprint(plan)))
    write(directory / "authorization.example.json", dict(authorized=False, provider=None,
        model=None, gateway_config_path=None, max_requests=120, max_total_tokens=300000,
        max_output_tokens=1800, max_retries=0, monetary_limit=None,
        allowed_data="synthetic evaluation documents, questions and answers only"))
    write(directory / "status.json", dict(SEMANTIC_MEASUREMENT="BLOCKED",
        SEMANTIC_QUALITY="INSUFFICIENT_EVIDENCE", blocker="Provider/model authorization pending",
        real_requests=0, A="NOT_RUN", B="NOT_RUN", human_review="PENDING"))


class BudgetExhausted(RuntimeError):
    pass


class RecordedProvider:
    """Accounting/recording decorator; HTTP and credentials stay in the gateway."""
    def __init__(self, provider, authorization, directory):
        self.provider = provider
        self.authorization = authorization
        self.directory = directory
        self.requests = 0
        self.accounted_tokens = 0
        self.rows = []
        self.case_id = "connectivity"
        self.lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.provider, name)

    async def complete(self, messages, **kwargs):
        kwargs["max_retries"] = 0
        kwargs["max_tokens"] = min(kwargs.get("max_tokens") or 1800,
                                   self.authorization["max_output_tokens"])
        # UTF-8 bytes plus framing reserve: conservative proxy, not an exact tokenizer.
        input_reserve = len(json.dumps(dict(messages=messages, tools=kwargs.get("tools")),
                                       ensure_ascii=False).encode()) + 2048
        reserved = input_reserve + kwargs["max_tokens"]
        with self.lock:
            if (self.requests >= self.authorization["max_requests"] or
                self.accounted_tokens + reserved > self.authorization["max_total_tokens"]):
                raise BudgetExhausted("Authorized request/token reservation exhausted")
            self.requests += 1
            self.accounted_tokens += reserved
            row = dict(request_id=self.requests, case_id=self.case_id,
                       provider=self.provider_id, model=self.model, messages=messages,
                       parameters=kwargs, reserved_tokens=reserved, execution_status="STARTED")
            self.rows.append(row)
            self._save(row)
        try:
            response = await asyncio.wait_for(self.provider.complete(messages, **kwargs), 60)
            observed = (response.input_tokens or 0) + (response.output_tokens or 0)
            with self.lock:
                # Never refund uncertain or failed requests. Retain actual overshoots.
                self.accounted_tokens += max(0, observed - reserved)
            row.update(execution_status="COMPLETED", response=response.model_dump(mode="json"),
                       usage_estimated=response.input_tokens is None or response.output_tokens is None)
            return response
        except BaseException as error:
            from mathtutor.infrastructure.gateway_config import classify_gateway_error
            http_status = re.search(r"\bHTTP (\d{3})\b", str(error))
            row.update(execution_status="TIMEOUT" if is_timeout(error) else "ERROR",
                       error_type=type(error).__name__, error_category=classify_gateway_error(str(error)),
                       http_status=int(http_status[1]) if http_status else None)
            raise
        finally:
            self._save(row)

    def _save(self, row):
        write(self.directory / f"request-{row['request_id']:03}.json", row)


def is_timeout(error):
    import httpx
    return isinstance(error, (TimeoutError, httpx.TimeoutException)) or isinstance(error.__cause__, httpx.TimeoutException)


def decision_valid(response, count=1):
    try:
        data = json.loads(response.text)
        return (not response.tool_calls and response.finish_reason in {"stop", "end_turn"}
                and isinstance(data, dict) and set(data) == {"supported"}
                and isinstance(data["supported"], list) and len(data["supported"]) == count
                and all(type(x) is bool for x in data["supported"]))
    except (TypeError, ValueError):
        return False


def checker_metrics(rows, planned):
    """Fixed denominators; errors never masquerade as valid negative decisions."""
    valid = sum(x.get("execution_status") == "COMPLETED" for x in rows)
    result = dict(valid_coverage=dict(numerator=valid, denominator=len(planned),
                                     rate=valid / len(planned) if planned else None))
    if any(x.get("human_review_status") != "APPROVED" or
           x.get("reference_label") not in {"SUPPORTED", "NOT_SUPPORTED"} for x in planned):
        result.update(supported_pass_rate=None, unsupported_false_accept_rate=None,
                      reason="Reference labels await independent human review")
        return result
    by_id = {x["case_id"]: x for x in rows}
    for key, label in (("supported_pass_rate", "SUPPORTED"),
                       ("unsupported_false_accept_rate", "NOT_SUPPORTED")):
        cases = [x for x in planned if x["reference_label"] == label]
        passed = sum(by_id.get(x["case_id"], {}).get("observed_decision") == "SUPPORTED"
                     and by_id[x["case_id"]].get("execution_status") == "COMPLETED" for x in cases)
        result[key] = dict(numerator=passed, denominator=len(cases),
                           rate=passed / len(cases) if cases else None)
    return result


async def route_a(plan, provider, directory, tmp):
    env = await fixtures.build_knowledge_harness(tmp)
    rows = []
    try:
        tools = await fixtures._tools(env["state"], "conv-a")
        surfaced = {}
        for key, (query, title) in fixtures._SURFACE_SPECS.items():
            surfaced[key] = await fixtures._surface(tools, query=query, title=title,
                needle=fixtures._FACT_QUOTES[key], call_id="live-"+key)
        for case in plan["claims"]:
            provider.case_id = "A:" + case["case_id"]
            evidence = [surfaced[k] for k in case["evidence_keys"]]
            assert [x["text"] for x in evidence] == [x["text"] for x in case["prepared_evidence"]], "Frozen evidence changed"
            row = dict(case_id=case["case_id"], reference_label=case["reference_label"],
                       reference_reason=case["reference_reason"], human_review_status=case["human_review_status"],
                       claim=case["claim"], evidence_reference=evidence,
                       observed_decision=None, production_allowed=None,
                       provider=provider.provider_id, model=provider.model,
                       prompt_version=plan["prompt_sha256"])
            response = None
            async def invoke(messages, *, tool_enabled):
                nonlocal response
                assert tool_enabled is False
                response = await provider.complete(messages, temperature=.2, max_tokens=1800)
                return response
            try:
                allowed = await check_claim_support(invoke, [dict(claim=case["claim"],
                    evidence=[x["text"] for x in evidence])])
                row["production_allowed"] = allowed
                if decision_valid(response):
                    row.update(observed_decision="SUPPORTED" if allowed else "NOT_SUPPORTED",
                               execution_status="COMPLETED")
                else:
                    row.update(execution_status="INVALID_RESPONSE")
            except Exception as error:
                row.update(execution_status="BUDGET_EXHAUSTED" if isinstance(error, BudgetExhausted)
                    else "TIMEOUT" if is_timeout(error) else "ERROR", error_type=type(error).__name__)
            rows.append(row)
            write(directory / "A-results.json", rows)
    finally:
        await env["state"].shutdown_runtime()
        await env["engine"].dispose()
    return rows


def route_b(plan, provider, store, config, directory, tmp):
    import secrets
    from fastapi.testclient import TestClient
    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import get_product_state, reset_product_state
    from mathtutor.infrastructure.generative_gateway import ModelRole
    from mathtutor.security.settings import MathTutorSecuritySettings
    tmp.mkdir()
    write(tmp / "gateway.json", config)
    reset_product_state()
    rows = []
    try:
        with patch("mathtutor.api.product_state._default_secret_store", return_value=store):
            settings = MathTutorSecuritySettings(
                environment="development", host="127.0.0.1",
                allowed_hosts=("testserver",), allowed_origins=(),
                bridge_secret=secrets.token_hex(32),
            )
            app = create_math_tutor_app(settings, auth_enabled=False, db_path=str(tmp / "isolated.db"))
        state = get_product_state()
        for role in ModelRole:
            state.gateway.register_provider(role, provider)
        with TestClient(app, headers={"X-MathTutor-Bridge": settings.bridge_secret}) as client:
            for case in plan["questions"]:
                cid = case["case_id"].replace(":", "-")
                provider.case_id = "B:" + case["case_id"]
                before = provider.requests
                corpus = fixtures.official().CORPUS if case["corpus"] == "easy" else fixtures.HARD_DOCS
                row = dict(case_id=case["case_id"], question=case["question"], mode=case["mode"],
                           human_review={key: None for key in plan["review_required"]},
                           human_review_status="PENDING", frames=[], execution_status="STARTED")
                try:
                    for doc in corpus:
                        imported = client.post("/api/v2/math-tutor/desktop/documents/import",
                            params={"conversation_id": cid},
                            files={"file": (doc.filename, doc.body.encode(), "text/markdown")})
                        imported.raise_for_status()
                        if imported.json()["status"] not in {"ready", "ready_with_warnings"}:
                            raise RuntimeError("Synthetic corpus ingestion failed")
                    with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
                        ws.send_json(dict(protocol_version=2, request_id=cid, idempotency_key=cid,
                            session_id=cid, command="send_message", payload=dict(text=case["question"])))
                        while True:
                            frame = ws.receive_json()
                            row["frames"].append(frame)
                            if frame["event_type"] == "turn_end":
                                break
                    row.update(execution_status="COMPLETED", actual_requests=provider.requests-before,
                        real_call_observed=provider.requests > before,
                        final_frames=[f for f in row["frames"] if f["event_type"] in
                                      {"assistant_complete", "assistant_partial", "assistant_error"}],
                        fallback_review_status="REVIEW_FRAMES_AND_CALL_RECORDS")
                    terminal = row["final_frames"][-1]["payload"] if row["final_frames"] else {}
                    row.update(final_answer=terminal.get("final_text"),
                               application_status=terminal.get("status"),
                               finish_reason=terminal.get("finish_reason"),
                               token_usage=terminal.get("usage"),
                               request_record_ids=list(range(before+1, provider.requests+1)),
                               refusal_review=None, template_fallback_review=None)
                except Exception as error:
                    row.update(execution_status="ERROR", error_type=type(error).__name__,
                               actual_requests=provider.requests-before)
                rows.append(row)
                write(directory / "B-results.json", rows)
    finally:
        reset_product_state()
    return rows


def run(directory, authorization_path):
    from mathtutor.infrastructure.generative_gateway import GenerativeModelGateway, ModelRole
    from mathtutor.infrastructure.gateway_config import GatewayConfigService
    from mathtutor.infrastructure.keychain_secret_store import KeychainSecretStore
    plan = json.loads((directory / "plan.json").read_text(encoding="utf-8"))
    assert fingerprint(plan) == json.loads((directory / "plan-digest.json").read_text())["sha256"]
    auth = json.loads(authorization_path.read_text(encoding="utf-8"))
    assert auth["authorized"] is True and auth["max_retries"] == 0
    assert 0 < auth["max_requests"] <= 120 and 0 < auth["max_total_tokens"] <= 300000
    assert 0 < auth["max_output_tokens"] <= 1800 and auth["monetary_limit"] is None
    assert plan["prompt_sha256"] == hashlib.sha256(inspect.getsource(check_claim_support).encode()).hexdigest()
    assert plan["source"] == fixtures.source_fingerprint(), "Prepare again if code changed"
    assert plan["runner_sha256"] == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    output = directory / "execution"
    output.mkdir(exist_ok=False)
    store = KeychainSecretStore()
    gateway = GenerativeModelGateway(store)
    service = GatewayConfigService(gateway, store, Path(auth["gateway_config_path"]))
    base = gateway.provider_for(ModelRole.TUTOR_WRITER)
    if base is None or (base.provider_id, base.model) != (auth["provider"], auth["model"]):
        raise ValueError("Explicitly authorized provider/model must match existing settings")
    provider = RecordedProvider(base, auth, output)
    write(output / "authorization.json", auth)
    # Only production provider code resolves the one named SecretStore credential.
    # No discovery, fallback provider selection, or custom HTTP client.
    status = dict(SEMANTIC_MEASUREMENT="BLOCKED", SEMANTIC_QUALITY="INSUFFICIENT_EVIDENCE",
                  human_review="PENDING", connectivity="NOT_RUN")
    try:
        response = asyncio.run(provider.complete([dict(role="user", content="只回复：连接成功")],
                                                temperature=0, max_tokens=128))
        if not response.text.strip():
            raise RuntimeError("Empty connectivity response")
        status["connectivity"] = "REAL_RESPONSE_OBSERVED_NOT_QUALITY_PASS"
        with tempfile.TemporaryDirectory(prefix="mathtutor-live-eval-") as folder:
            tmp = Path(folder)
            a = asyncio.run(route_a(plan, provider, output, tmp / "A"))
            b = route_b(plan, provider, store, service.current_config(), output, tmp / "B")
        completed = sum(x["execution_status"] == "COMPLETED" for x in a)
        status.update(A=dict(planned=len(plan["claims"]), valid_decisions=completed,
            **checker_metrics(a, plan["claims"])),
            B=dict(planned=len(b), actual_call_cases=sum(x.get("real_call_observed", False) for x in b)))
        if (len(a) == len(plan["claims"]) and len(b) == len(plan["questions"])
            and all(x["execution_status"] != "BUDGET_EXHAUSTED" for x in a)
            and all(x.get("real_call_observed") for x in b)):
            status["SEMANTIC_MEASUREMENT"] = "COMPLETE"
        else:
            status["blocker"] = "Incomplete/invalid executions; every planned case retained"
    except Exception as error:
        status.update(blocker=type(error).__name__)
    finally:
        for route, cases in (("A", plan["claims"]), ("B", plan["questions"])):
            target = output / f"{route}-results.json"
            observed = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
            by_id = {row["case_id"]: row for row in observed}
            write(target, [by_id.get(case["case_id"], dict(case_id=case["case_id"],
                execution_status="NOT_RUN", observed_decision=None, human_review_status="PENDING"))
                for case in cases])
        status.update(real_requests=provider.requests, accounted_token_reservations=provider.accounted_tokens)
        write(output / "status.json", status)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--authorization", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare(args.out)
    else:
        if args.authorization is None:
            parser.error("run requires --authorization")
        run(args.out, args.authorization)
