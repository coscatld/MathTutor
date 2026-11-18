import copy

import pytest

from mathtutor.application.exploration_evidence import text_hash
from mathtutor.application.learning_actions import load_catalog, plan_learning_actions
from mathtutor.application.math_verification import verify_math
from mathtutor.application.network_qa import NetworkQA, NetworkReply
from mathtutor.application.recommendations import RecommendationsService
from mathtutor.application.verification_backend import InProcessVerificationBackend
from test_learning_actions import service
from test_learning_plan_conflicts import E02_FIRST

URL = "https://zhuanlan.zhihu.com/p/91571883"


def reviewed_like_terms(catalog):
    matches = [row for row in catalog["resources"] if row["url"] == URL]
    assert len(matches) == 1
    return matches[0]


def test_like_terms_admission_is_bounded_and_keeps_the_real_date_and_two_retrieval_witnesses():
    catalog = load_catalog()
    row = reviewed_like_terms(catalog)
    assert len(catalog["resources"]) == len({r["url"] for r in catalog["resources"]}) == 24
    assert catalog["version"] == "zhihu-curated-20261118-r2"
    assert row["title"] == "初中数学基础知识 第四章 整式" and row["author"] == "阿巴酱"
    assert row["published_at"] is None and row["source_time"] == "2019-11-13T03:13:17+00:00"
    assert row["source_time_kind"] == "published_or_updated"
    assert row["knowledge_points"] == ["combine_like_terms"] and row["prerequisites"] == []
    assert row["review"]["method"] == "ai_assisted" and row["review"]["scope"] == "search_excerpt"
    assert row["review"]["full_article_reviewed"] is row["review"]["human_expert_reviewed"] is False
    proof = row["provenance"]
    assert proof["start"] == 226 and proof["end"] == 406
    assert proof["excerpt"].startswith("考点一：同类项") and "两者缺一不可" in proof["excerpt"]
    assert proof["excerpt"].endswith("字母和字母的指数保持不变")
    assert "幂的乘方" not in proof["excerpt"] and "幂的乘方" in row["review"]["notes"]
    assert proof["excerpt_sha256"] == text_hash(proof["excerpt"])
    assert len({w["request_id"] for w in proof["corroborating_retrievals"]}) == 2
    assert all(w["provider_summary_sha256"] == proof["provider_summary_sha256"] for w in proof["corroborating_retrievals"])
    assert proof["raw_response_sha256"] is None and len(proof["snapshot_file_sha256"]) == 64
    assert proof["provider_create_time"] is None and proof["provider_edit_time"] == 1573614797


def test_identity_definition_is_not_labeled_as_a_like_terms_lesson():
    row = next(row for row in load_catalog()["resources"] if row["resource_id"] == "zhihu-a295cb0b6a952d64")
    assert "combine_like_terms" not in row["knowledge_points"] + row["tags"]
    assert "公共定义域" in row["provenance"]["excerpt"]


async def test_visible_positive_examples_are_locally_checked_without_losing_the_like_terms_condition():
    backend = InProcessVerificationBackend()
    for expression, answer in [("-5a+3a", "-2a"), ("-4+5", "1")]:
        assert (await verify_math(backend, expression, answer)).status == "verified"
    assert (await verify_math(backend, "a+a^2", "2a")).status == "refuted"


async def test_introductory_catalog_reading_does_not_resurrect_rejected_network_claims():
    catalog = load_catalog()
    async def planner(owner, goal, language="zh", request=""):
        return plan_learning_actions([], goal, catalog, language=language, request=request)
    qa = NetworkQA(None, InProcessVerificationBackend(), planner=planner)
    rejected = {"claim_id": "c1", "accepted": False, "reasons": ["invalid_evidence_binding"],
                "text": "不得复活这段模型声明", "dependencies": []}
    async def response(owner, task):
        return NetworkReply("本次解释证据不足。", "unsupported", task.query, audit=(rejected,))
    qa.respond = response
    reply = await qa.maybe_respond("local-admin", text=E02_FIRST, enabled=True)
    plan = reply.planner_receipt
    selected = plan["resources"]
    assert plan["goal"] == plan["target"] == "combine_like_terms" and plan["evidence_ids"] == []
    assert [step["minutes"] for step in plan["steps"]] == [2, 5, 3]
    assert len(selected) == 1 and selected[0]["url"] == URL
    assert selected[0]["origin"] == "reviewed_catalog" and selected[0]["supporting_claim_ids"] == []
    assert "两个判断条件" in selected[0]["selection_reason"]
    assert "初审片段选读" in reply.text and "AI 审核，未审核全文" in reply.text
    assert "发布或更新于 2019-11-13" in reply.text
    assert reply.audit == (rejected,) and "不得复活" not in reply.text
    assert plan["network_answer_available"] is False and plan["retained_context_ids"] == []


async def test_catalog_revision_changes_cache_identity_without_changing_owner_or_profile(service):
    new = load_catalog()
    old = copy.deepcopy(new)
    old["version"] = "zhihu-curated-20261118"
    old["resources"] = [row for row in old["resources"] if row["url"] != URL]
    for row in old["resources"]:
        if row["resource_id"] == "zhihu-a295cb0b6a952d64":
            row["knowledge_points"].append("combine_like_terms")
            row["tags"].append("combine_like_terms")
    before = RecommendationsService(service.repository.engine, service.student_state, service.client, catalog=old)
    after = RecommendationsService(service.repository.engine, service.student_state, service.client, catalog=new)
    try:
        await service.configure("alice", enabled=False, goal="combine_like_terms")
        state = await service.repository.get("alice")
        old_plan, new_plan = (await before.get("alice"))["plan"], (await after.get("alice"))["plan"]
        assert old_plan["profile_revision"] == new_plan["profile_revision"]
        assert old_plan["goal"] == new_plan["goal"] == "combine_like_terms"
        assert not old_plan["resources"] and len(new_plan["resources"]) == 1
        assert before._cache_key("alice", state, old_plan) != after._cache_key("alice", state, new_plan)
        assert await service.student_state.events("alice") == [] and not service.client.calls
    finally:
        await before.close()
        await after.close()
