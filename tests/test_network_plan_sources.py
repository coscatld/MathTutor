import copy
import json
import sqlite3
from contextlib import closing
from html import unescape

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application.exploration_evidence import build_source_snapshots, text_hash
from mathtutor.application.learning_actions import plan_learning_actions
from mathtutor.application.network_plan_sources import choose_current_reading
from mathtutor.application.network_qa import NetworkQA, answer_payload, choose_network_task
from mathtutor.application.verification_backend import InProcessVerificationBackend
from test_learning_plan_conflicts import E02_FIRST, E02_NEXT
from test_network_qa import Client, claim, item, review
from test_tutor_p0 import client_at, send

QUOTE = "同类项的字母及对应指数相同，合并同类项时只对系数求和，字母和指数不变。"
ADJACENT = "去括号时，把括号外的因子乘到括号内每一项。"


def scenario(*, rejected=False, text=QUOTE, question=E02_FIRST, items=None):
    rows = items or [{**item(text), "Title": "入门讲义", "AuthorName": "示例作者"}]
    batch = build_source_snapshots(rows, retrieved_at="2026-11-18T00:00:00+00:00")
    task = choose_network_task(question)
    _, spans, _ = answer_payload(task, batch)
    claims = [claim(span, claim_id=f"c{i}", text=span.text) for i, span in enumerate(spans)]
    checks = [review(row["claim_id"], supported=not rejected, math_consistency="not_assessed") for row in claims]
    provider = Client([{"claims": claims}, {"claims": checks}], [{"Items": rows, "SearchHashId": "synthetic"}])
    async def planner(owner, goal, language="zh", request=""):
        return plan_learning_actions([], goal, {"version": "empty-test-catalog", "resources": []}, language=language, request=request)
    return NetworkQA(provider, InProcessVerificationBackend(), planner=planner), provider, task


async def test_e02_selects_one_current_excerpt_without_adding_a_second_plan_or_provider_call():
    qa, provider, task = scenario(items=[{**item(ADJACENT, "11"), "Title": "合并同类项入门"}, item(QUOTE, "12")])
    result = await qa.maybe_respond("local-admin", text=task.question, enabled=True)
    plan = result.planner_receipt
    assert plan["goal"] == plan["target"] == "combine_like_terms"
    assert [step["minutes"] for step in plan["steps"]] == [2, 5, 3]
    assert len(plan["resources"]) == 1
    selected = plan["resources"][0]
    assert selected["url"].endswith("/12") and selected["origin"] == "current_search_summary"
    assert selected["supporting_claim_ids"] == ["c1"] and selected["summary"] == QUOTE
    source = next(s for s in result.sources if s["source_id"] == selected["source_id"])
    assert source["text"][selected["quote_start"]:selected["quote_end"]] == QUOTE
    assert selected["summary_sha256"] == text_hash(QUOTE) and selected["excerpt_sha256"] == source["text_sha256"]
    assert "本次选读" in result.text and "未加入初审资料库" in result.text
    assert "合并同类项" in unescape(selected["selection_reason"])
    assert result.text.count("**接下来怎么学**") == 1
    assert plan["final_text_sha256"] == text_hash(result.text)
    assert plan["rendered_text_sha256"] == text_hash(plan["rendered_text"])
    assert plan["evidence_ids"] == []
    assert len(provider.searches) == 1 and len(provider.completions) == 2
    assert "current_search_summary" not in json.dumps(provider.completions)


@pytest.mark.parametrize("text,rejected", [(ADJACENT, False), (QUOTE, True)])
async def test_nearby_topic_or_rejected_claim_does_not_become_selected_introductory_reading(text, rejected):
    qa, _, task = scenario(text=text, rejected=rejected)
    result = await qa.maybe_respond("local-admin", text=task.question, enabled=True)
    assert result.planner_receipt["resources"] == []
    assert "暂不指定文章" in result.text
    assert "本次选读：" not in result.text


async def test_no_evidence_keeps_the_local_plan_and_explicitly_leaves_reading_unassigned():
    qa, provider, task = scenario()
    provider.results = [{"Items": [], "SearchHashId": "a"}, {"Items": [], "SearchHashId": "b"}]
    result = await qa.maybe_respond("local-admin", text=task.question, enabled=True)
    assert result.planner_receipt["resources"] == [] and result.status == "local_plan"
    assert "暂不指定文章" in result.text and len(provider.completions) == 0
    assert len(provider.searches) == 2  # Existing bounded retrieval; selection adds no call.


async def test_viewed_without_attempt_does_not_reassign_reading_automatically():
    qa, _, task = scenario(question=E02_NEXT)
    result = await qa.maybe_respond("local-admin", text=task.question, enabled=True)
    assert result.planner_receipt["reason_code"] == "viewed_unchecked"
    assert result.planner_receipt["resources"] == []
    assert "本次选读" not in result.text and "暂不指定文章" not in result.text


@pytest.mark.parametrize("failure", ["removed_claim", "rejected_claim", "removed_source", "changed_quote", "changed_snapshot"])
async def test_deleted_or_changed_premise_invalidates_a_dependent_reading_choice(failure):
    qa, _, task = scenario(items=[item(ADJACENT, "11"), item(QUOTE, "12")])
    reply = await qa.respond("local-admin", task)
    sources, claims = copy.deepcopy(list(reply.sources)), copy.deepcopy(list(reply.audit))
    claims[1]["dependencies"] = ["c0"]
    selected = choose_current_reading(sources, claims, ["c0", "c1"], target="combine_like_terms", language="zh")
    assert selected["supporting_claim_ids"] == ["c1", "c0"]
    if failure == "removed_claim":
        claims.pop(0)
    elif failure == "rejected_claim":
        claims[0]["accepted"] = False
    elif failure == "removed_source":
        sources.pop(0)
    elif failure == "changed_quote":
        claims[0]["evidence"][0]["quote"] += "已变更"
    else:
        sources[0]["text"] += "已变更"
    assert choose_current_reading(sources, claims, ["c0", "c1"], target="combine_like_terms", language="zh") is None


async def test_other_goal_and_suppressed_claims_cannot_supply_a_reading_choice():
    qa, _, task = scenario()
    reply = await qa.respond("local-admin", task)
    assert choose_current_reading(reply.sources, reply.audit, ["c0"], target="linear_algebra", language="zh") is None
    assert choose_current_reading(reply.sources, reply.audit, [], target="combine_like_terms", language="zh") is None


def test_selected_excerpt_is_durable_replays_once_and_cannot_return_after_conversation_purge(tmp_path):
    database = tmp_path / "current-reading.db"
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        qa, provider, task = scenario()
        get_product_state().controller.network_qa = qa
        payload = {"text": task.question, "network_search": True}
        send(ws, "send_message", "reading", payload)
        with closing(sqlite3.connect(database)) as conn:
            content, context = conn.execute("SELECT content, continuation_context FROM conversation_messages WHERE role='tutor' AND turn_id='reading'").fetchone()
            assert conn.execute("SELECT count(*) FROM learning_events").fetchone()[0] == 0
        evidence = json.loads(context)["network_evidence"]
        assert evidence["planner"]["resources"][0]["origin"] == "current_search_summary"
        assert evidence["network_text"] == content
        assert evidence["planner"]["final_text_sha256"] == text_hash(content)
        replay = send(ws, "send_message", "reading", payload)
        assert len(provider.searches) == 1 and len(provider.completions) == 2
        assert any(frame.get("payload", {}).get("final_text") == content for frame in replay)
        assert client.delete("/api/v2/math-tutor/sessions/p0").status_code == 200
        response = client.delete("/api/v2/math-tutor/trash/p0")
        assert response.status_code == 200, response.text
        with closing(sqlite3.connect(database)) as conn:
            assert conn.execute("SELECT count(*) FROM conversation_messages").fetchone()[0] == 0
        replay = send(ws, "send_message", "reading", payload)
        assert not any(content in json.dumps(frame, ensure_ascii=False) for frame in replay)
        assert len(provider.searches) == 1
