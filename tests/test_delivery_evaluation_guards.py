"""Accounting and review-integrity checks; never substitutes for live quality."""
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rag_delivery_regression as run
from mathtutor.infrastructure.generative_gateway import CompletionResult, GenerativeProviderError


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["known", "unknown", "known_error", "unknown_error"])
async def test_new_usage_settlement_never_refunds_historical_unknowns(tmp_path, monkeypatch, outcome):
    monkeypatch.setattr(run, "OUT", tmp_path)
    output = tmp_path / "requests"
    output.mkdir()
    class Provider:
        provider_id, model = "offline", "fixture"
        async def complete(self, messages, **kwargs):
            assert kwargs["max_retries"] == 0
            if "error" in outcome:
                raise GenerativeProviderError("empty content", diagnostics={"usage":
                    {"prompt_tokens": 100, "completion_tokens": 512} if outcome == "known_error" else {}})
            return CompletionResult(text="ok", provider_id=self.provider_id, model=self.model, finish_reason="stop",
                input_tokens=100 if outcome == "known" else None, output_tokens=512 if outcome == "known" else None)
    provider = run.CumulativeProvider(Provider(), {}, output)
    try:
        await provider.complete([{"role": "user", "content": "synthetic"}], max_tokens=512, max_retries=99)
    except GenerativeProviderError:
        assert "error" in outcome
    row = json.loads((output / "request-025.json").read_text(encoding="utf-8"))
    expected = 612 if outcome in {"known", "known_error"} else row["reserved_tokens"]
    assert provider.accounted_tokens == 169364 + expected
    assert row["charged_tokens"] == expected > 0
    restarted = run.CumulativeProvider(Provider(), {}, output)
    assert restarted.requests == 25
    assert restarted.accounted_tokens == provider.accounted_tokens


def test_saved_semantic_review_keeps_errors_and_original_denominator():
    result = json.loads((Path(__file__).parent / "fixtures/sanitized_rag_release/review/original-B-atomic-review.json").read_text(encoding="utf-8"))
    assert result["human_review_status"] == "PENDING"
    rows = {r["case_id"]: r for r in result["rows"]}
    assert len(rows) == 14
    for row in rows.values():
        if row["task_completion"] == "NOT_ANSWERED_TEMPLATE":
            assert row["faithfulness_score"] == 0
            assert row["required_content_coverage"] == 0
    mixed = rows["easy:mixed_cjk_latex"]
    assert "这已经是" in mixed["final_answer"]
    assert any(c["mathematical_correctness"] == "INCORRECT" and "b≠0" in c["rationale"] for c in mixed["claims"])
    assert rows["easy:discriminant"]["task_completion"] == "INCOMPLETE_DELIVERY"


def test_degenerate_final_prose_is_not_certified_by_correct_equations():
    result = json.loads((Path(__file__).parent / "fixtures/sanitized_rag_release/review/final-review.json").read_text(encoding="utf-8"))
    rows = {r["case_id"]: r for r in result["degenerate"]}
    assert len(rows) == 3
    row = rows["degenerate:c0"]
    assert "一正一负" in row["final_answer"]
    assert row["delivery"] == "NATURAL_STOP"
    assert row["math_correctness"] == "FAIL"
    assert "0,-1" in row["entire_prose_review"]


def test_knowledge_records_actual_contract_paths():
    result = json.loads((Path(__file__).parent / "fixtures/sanitized_rag_release/review/final-review.json").read_text(encoding="utf-8"))
    rows = {r["case_id"]: r for r in result["knowledge"]}
    assert rows["K1_summary"]["support_checks"][0]["result"] is True
    assert rows["K1_summary"]["direct_seed_read_without_search"]
    assert not rows["K1_summary"]["agent_search_hops"]
    assert not rows["K2_quote"]["support_checks"]
    assert rows["K3_absent"]["agent_search_hops"][0]["kind"] == "AGENT_SEARCH"
    assert not rows["K4_hint"]["request_record_ids"]
