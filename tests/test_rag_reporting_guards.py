import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rag_hard_set_probe as probe
from test_rag_production_benchmark import bench, OWNER


@pytest.mark.asyncio
async def test_valid_known_answer_empty_ranking_is_scored_miss(bench, monkeypatch):
    async def empty(*args, **kwargs):
        return None, []
    monkeypatch.setattr(probe.official(), "_rank", empty)
    result = await probe.official_retrieval_metrics(
        bench, [("miss", "query", (("linear", 0),))], owner=OWNER)
    assert result["eligible_queries"] == 1
    assert result["aggregate"]["recall@5"] == 0


@pytest.mark.asyncio
async def test_empty_scope_no_answer_remains_in_denominator(bench):
    bench["scope"] = []
    result = await probe.official_retrieval_metrics(bench, [("empty", "query", ())], owner=OWNER)
    assert result["eligible_queries"] == 1
    assert result["per_query"]["empty"]["counts"]["ranked_returned"] == 0


@pytest.mark.asyncio
async def test_wrong_owner_is_invalid_before_ranking(bench):
    with pytest.raises(probe.BenchmarkInvalid, match="owner"):
        await probe.official_retrieval_metrics(bench, [("invalid", "query", ())], owner="wrong")


@pytest.mark.asyncio
async def test_missing_bound_reference_is_invalid(bench):
    with pytest.raises(probe.BenchmarkInvalid, match="reference"):
        await probe.official_retrieval_metrics(
            bench, [("invalid", "query", (("linear", 999),))], owner=OWNER)
