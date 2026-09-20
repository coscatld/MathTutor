"""Offline protocol/budget checks; these are never semantic quality evidence."""
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from rag_live_acceptance import RecordedProvider, BudgetExhausted, decision_valid, checker_metrics
from mathtutor.application.tutor_runtime import check_claim_support
from mathtutor.infrastructure.generative_gateway import CompletionResult


@pytest.mark.asyncio
async def test_production_check_sends_only_claim_and_evidence():
    captured = []
    async def invoke(messages, *, tool_enabled):
        captured.extend(messages)
        assert tool_enabled is False
        return CompletionResult(text='{"supported":[true]}', provider_id="offline", model="protocol", finish_reason="stop")
    payload = [{"claim": "synthetic", "evidence": ["synthetic"]}]
    assert await check_claim_support(invoke, payload)
    assert json.loads(captured[1]["content"]) == payload
    assert "reference_label" not in json.dumps(captured)


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ['{"supported":["false"]}', '{"supported":[1]}', '{"supported":[]}', 'not-json'])
async def test_invalid_response_is_not_a_valid_negative(text):
    result = CompletionResult(text=text, provider_id="offline", model="protocol", finish_reason="stop")
    async def invoke(*args, **kwargs):
        return result
    assert await check_claim_support(invoke, [{"claim": "c", "evidence": ["e"]}]) is False
    assert not decision_valid(result)


@pytest.mark.asyncio
async def test_request_limit_prevents_dispatch_and_logs_no_reference(tmp_path):
    class Offline:
        provider_id = "offline"
        model = "protocol"
        calls = 0
        async def complete(self, messages, **kwargs):
            self.calls += 1
            assert kwargs["max_retries"] == 0
            assert kwargs["max_tokens"] == 128
            return CompletionResult(text="ok", provider_id=self.provider_id, model=self.model,
                                    finish_reason="stop", input_tokens=3, output_tokens=1)
    source = Offline()
    wrapped = RecordedProvider(source, dict(max_requests=1, max_total_tokens=10000,
                                           max_output_tokens=128), tmp_path)
    await wrapped.complete([dict(role="user", content="synthetic")], max_tokens=9000, max_retries=99)
    with pytest.raises(BudgetExhausted):
        await wrapped.complete([])
    assert source.calls == 1
    assert wrapped.accounted_tokens > 128
    assert json.loads((tmp_path / "request-001.json").read_text())["execution_status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_token_reservation_blocks_before_dispatch(tmp_path):
    class Forbidden:
        async def complete(self, *args, **kwargs):
            pytest.fail("request must not reach provider")
    wrapped = RecordedProvider(Forbidden(), dict(max_requests=10, max_total_tokens=1,
                                                max_output_tokens=128), tmp_path)
    with pytest.raises(BudgetExhausted):
        await wrapped.complete([])
    assert wrapped.requests == 0


def test_timeouts_remain_in_denominator_without_becoming_valid_negatives():
    plan = [dict(case_id="yes", human_review_status="APPROVED", reference_label="SUPPORTED"),
            dict(case_id="no", human_review_status="APPROVED", reference_label="NOT_SUPPORTED")]
    rows = [dict(case_id="yes", execution_status="COMPLETED", observed_decision="SUPPORTED"),
            dict(case_id="no", execution_status="TIMEOUT", observed_decision=None)]
    result = checker_metrics(rows, plan)
    assert result["valid_coverage"] == dict(numerator=1, denominator=2, rate=.5)
    assert result["supported_pass_rate"]["rate"] == 1
    assert result["unsupported_false_accept_rate"] == dict(numerator=0, denominator=1, rate=0)
