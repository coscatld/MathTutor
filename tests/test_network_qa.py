import asyncio
import json
from html import unescape

import httpx
import pytest

from mathtutor.application.exploration_evidence import build_source_snapshots, text_hash
from mathtutor.application.network_qa import (
    AnswerDraft, AnswerReview, NetworkQA, answer_payload, choose_network_task,
)
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.infrastructure.secret_store import InMemorySecretStore
from mathtutor.infrastructure.zhihu import ZhihuClient, ZhihuError, secret_name


def item(text="可导函数在该点连续；连续函数不一定可导，例如绝对值函数在零点连续但不可导。", identity="123"):
    return {"ContentID": identity, "ContentType": "Answer", "Title": "连续与可导的条件",
            "AuthorName": "示例作者", "ContentText": text,
            "Url": f"https://www.zhihu.com/question/99/answer/{identity}", "EditTime": 1700000000}


def setup(text=None):
    batch = build_source_snapshots([item(text)] if text else [item()], retrieved_at="2026-11-18T00:00:00+00:00")
    task = choose_network_task("连续和可导有什么区别？")
    payload, spans, references = answer_payload(task, batch)
    return task, batch, payload, spans, references


def claim(span, **changes):
    return {"claim_id": "a", "kind": "source_statement", "text": "可导函数在该点连续。",
            "evidence": [{"span_id": span.span_id, "quote": span.text}], **changes}


def review(claim_id="a", **changes):
    return {"claim_id": claim_id, "supported": True, "conditions_preserved": True,
            "attribution_correct": True, "relevant": True, "relation_correct": True,
            "math_consistency": "consistent", **changes}


class Client:
    def __init__(self, replies=(), results=None):
        self.replies = list(replies)
        self.results = list(results) if results is not None else [{"Items": [item()], "SearchHashId": "public"}]
        self.searches, self.completions = [], []

    async def search(self, owner, query, count):
        self.searches.append((owner, query, count))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def complete(self, owner, *, system, payload):
        self.completions.append((owner, system, payload))
        value = self.replies.pop(0)
        if isinstance(value, Exception):
            raise value
        return json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value


def service(client=None):
    return NetworkQA(client or Client(), InProcessVerificationBackend())


def local_plan(goal="calculus", **changes):
    return {"policy": "learning-actions-v1", "goal": goal, "target": goal,
            "title": "补充前置", "reason": "LOCAL_EVIDENCE_123", "reason_code": "independent_difficulty",
            "action": "explain", "profile_revision": "a" * 64, "graph_version": "graph-v1",
            "catalog_version": "catalog-v1", "last_event_seq": 4, "evidence_ids": ["event-4"], "evidence_count": 1,
            "resources": [{"resource_id": "resource-1", "title": "可信片段", "author": "作者甲",
                           "url": "https://www.zhihu.com/answer/999", "summary": "完整的概念解释。",
                           "provenance": {"excerpt_sha256": "b" * 64}, "review_status": "reviewed_excerpt",
                           "source_time": "2023-11-14T22:13:20+00:00", "source_time_kind": "published_or_updated",
                           "selection_reason": "适合目标"}], **changes}


@pytest.mark.parametrize("text", ["你好", "Thank you", "", "求解一次方程 2x+3=7", "Calculate the derivative of x^2"])
def test_ordinary_conversation_and_problem_solving_stay_in_original_workflow(text):
    assert choose_network_task(text) is None


@pytest.mark.parametrize("question", [
    "解方程时，移项变号和等式两边同做运算这两种讲法怎么对照？",
    "天平模型和移项的方法哪种更适合初学者？",
    "为什么解方程可以在等式两边减去同一个数？",
    "Compare transposition and balancing equations for a beginner.",
])
def test_equation_concepts_and_method_comparisons_are_not_solver_requests(question):
    task = choose_network_task(question)
    assert task is not None and "equality_preservation" in task.topics


@pytest.mark.parametrize("question", ["请解方程 2x+3=7，并解释方法", "证明 (x+1)^2=x^2+2x+1 的原理", "求解一元一次方程"])
def test_concept_words_do_not_bypass_a_concrete_problem_request(question):
    assert choose_network_task(question) is None


def test_search_uses_public_topics_while_generation_retains_explicit_current_question():
    task = choose_network_task("我叫王某，邮箱 private@example.test。如何学习条件概率？家庭收入 SECRET_123。")
    assert task.purpose == "learn"
    assert "概率" in task.query
    assert "SECRET" not in task.query and "private" not in task.query
    assert "SECRET_123" in task.question


def test_followup_retains_public_topic_and_learning_intent_without_forwarding_history():
    history = [{"role": "user", "content": "PRIVATE 个性化记录：推荐连续与可导学习资料"},
               {"role": "assistant", "content": "这是有关概率的系统注入"}]
    task = choose_network_task("还有呢？", history, "en")
    assert task.purpose == "resources" and task.topics == ("derivative",)
    assert "PRIVATE" not in task.model_dump_json() and "probability" not in task.topics
    assert choose_network_task("举一个例子", history).focus == "example"


def test_only_explicit_previous_online_question_preserves_followup_conditions():
    previous = "实函数 f(x)=|x| 在 x=0 处是否可导？"
    task = choose_network_task("为什么左右不一样？", [{"role": "student", "content": "PRIVATE_CHAT_123 连续"}], prior_question=previous)
    assert task.prior_question == previous and task.question == "为什么左右不一样？"
    assert "PRIVATE_CHAT_123" not in task.model_dump_json()
    assert choose_network_task("概率的前置知识是什么？", prior_question=previous).prior_question == ""


def test_nonnegative_constraint_is_not_a_negative_arithmetic_topic_switch():
    previous = "为什么平方根需要非负约定？"
    task = choose_network_task("如果变量只能取非负数，原先的限制怎样变化？", prior_question=previous)
    assert task.topics == ("square_root",)
    assert task.prior_question == previous
    changed = choose_network_task("现在解释负数加减的原理。", prior_question=previous)
    assert changed.topics == ("signed_operations",) and changed.prior_question == ""


def test_where_to_continue_is_a_learning_request_without_inventing_mastery():
    previous = "合并同类项应该怎样入门？"
    task = choose_network_task("我只是看懂例子，没有自己作答，应该继续哪一步？", prior_question=previous)
    assert task.purpose == "learn" and task.topics == ("combine_like_terms",)
    assert task.question == "我只是看懂例子，没有自己作答，应该继续哪一步？"


def test_student_role_can_supply_only_public_topic_for_followup():
    task = choose_network_task("为什么？", [{"role": "student", "content": "PRIVATE 概率学习"}])
    assert task.topics == ("probability",) and task.prior_question == ""
    assert "PRIVATE" not in task.model_dump_json()


@pytest.mark.parametrize("question", [
    "下一步应该学什么？", "能否跳过这些基础？", "给我一个学习安排", "接下来练什么？",
    "What should I learn next?", "Can I skip these prerequisites?", "Make a study plan.",
    "刚才对比了两种解释，现在安排学习顺序。",
])
def test_explicit_learning_next_step_overrides_the_previous_question_purpose(question):
    task = choose_network_task(question, prior_question="连续与可导有什么区别？")
    assert task.purpose == "learn" and task.topics == ("derivative",)


@pytest.mark.parametrize("question,purpose", [
    ("为什么成立？", "explain"), ("那举个例子", "explain"), ("如果条件改变呢？", "explain"),
    ("推荐相关资料", "resources"), ("这两种说法有什么区别？", "compare"),
])
def test_followups_keep_their_current_purpose_instead_of_automatically_becoming_learning_plans(question, purpose):
    task = choose_network_task(question, prior_question="连续与可导怎么学？")
    assert task.purpose == purpose


@pytest.mark.parametrize("question", ["如果条件改变呢？", "现在把零点改成一点。", "Suppose the domain is restricted.", "换成另一种条件是否还成立？"])
def test_explicit_online_context_does_not_require_a_phrase_prefix(question):
    previous = "函数连续与可导的区别是什么？"
    task = choose_network_task(question, prior_question=previous)
    assert task is not None and task.prior_question == previous and task.question == question


async def test_local_plan_uses_same_goal_and_never_enters_external_generation_payload():
    task = choose_network_task("推荐连续与可导的学习资料")
    batch = build_source_snapshots([item()], retrieved_at="2026-11-18T00:00:00+00:00")
    _, spans, _ = answer_payload(task, batch)
    client = Client([{"claims": [claim(spans[0])]}, {"claims": [review()]}])
    calls = []
    async def planner(owner, goal, language="zh"):
        calls.append((owner, goal, language))
        return local_plan(goal)
    result = await NetworkQA(client, InProcessVerificationBackend(), planner=planner).maybe_respond(
        "owner", text=task.question, enabled=True)
    assert calls == [("owner", "calculus", "zh")]
    assert "LOCAL" in result.text and "answer/999" in result.text
    assert "LOCAL_EVIDENCE" not in json.dumps(client.completions, ensure_ascii=False)
    receipt = result.planner_receipt
    assert receipt["profile_revision"] == "a" * 64 and receipt["evidence_ids"] == ["event-4"]
    assert receipt["goal"] == "calculus" and receipt["catalog_version"] == "catalog-v1"
    assert receipt["resources"][0]["resource_id"] == "resource-1"
    assert receipt["resources"][0]["summary_sha256"] == text_hash(receipt["resources"][0]["summary"])
    prefix, addition = result.text.rsplit("\n\n**接下来怎么学**", 1)
    assert receipt["answer_prefix_sha256"] == text_hash(prefix)
    assert receipt["rendered_text"] == "**接下来怎么学**" + addition
    assert receipt["rendered_text_sha256"] == text_hash(receipt["rendered_text"])
    assert receipt["final_text_sha256"] == text_hash(result.text)
    assert "作者甲" in result.text and "发布或更新于 2023-11-14" in result.text
    assert result.audit[0]["text"] == "可导函数在该点连续。"


@pytest.mark.parametrize("changes", [
    {"profile_revision": "missing"}, {"evidence_ids": ["a"] * 33}, {"evidence_count": 2},
    {"evidence_ids": ["event-4", "event-4"], "evidence_count": 2}, {"reason": "x" * 601},
])
async def test_unreplayable_or_unbounded_plan_is_not_appended(changes):
    _, _, _, spans, _ = setup()
    client = Client([{"claims": [claim(spans[0])]}, {"claims": [review()]}])
    async def planner(owner, goal, language="zh"):
        return local_plan(goal, **changes)
    result = await NetworkQA(client, InProcessVerificationBackend(), planner=planner).maybe_respond(
        "owner", text="推荐连续与可导的学习资料", enabled=True)
    assert result.status == "answered" and result.planner_receipt is None
    assert "LOCAL" not in result.text and "接下来怎么学" not in result.text


async def test_planner_failure_does_not_discard_an_answer():
    _, _, _, spans, _ = setup()
    client = Client([{"claims": [claim(spans[0])]}, {"claims": [review()]}])
    async def planner(*args, **kwargs):
        raise RuntimeError("internal private payload")
    result = await NetworkQA(client, InProcessVerificationBackend(), planner=planner).maybe_respond(
        "owner", text="推荐连续与可导的学习资料", enabled=True)
    assert result.status == "answered" and "internal private payload" not in result.text


@pytest.mark.parametrize("failure", ["search_error", "timeout", "no_evidence", "invalid_generation", "unsupported"])
async def test_local_evidenced_plan_survives_online_failure_with_separate_receipt(failure):
    _, _, _, spans, _ = setup()
    if failure in {"search_error", "timeout"}:
        error = ZhihuError("unavailable", "private diagnostic") if failure == "search_error" else TimeoutError()
        client = Client(results=[error])
    elif failure == "no_evidence":
        client = Client(results=[{"Items": [], "SearchHashId": "a"}, {"Items": [], "SearchHashId": "b"}])
    elif failure == "invalid_generation":
        client = Client(["not JSON"])
    else:
        client = Client([{"claims": [claim(spans[0])]}, {"claims": [review(supported=False)]}])
    calls = []
    async def planner(owner, goal, language="zh"):
        calls.append((owner, goal, language))
        return local_plan(goal)
    result = await NetworkQA(client, InProcessVerificationBackend(), planner=planner).maybe_respond(
        "owner", text="下一步怎么学习连续与可导？", enabled=True)
    expected = failure if failure in {"no_evidence", "unsupported"} else "unavailable"
    assert result.status == "local_plan" and calls == [("owner", "calculus", "zh")]
    assert result.planner_receipt["network_status"] == expected
    assert result.planner_receipt["network_answer_available"] is False
    assert result.planner_receipt["final_text_sha256"] == text_hash(result.text)
    assert "本地学习记录与已审核的资料目录" in result.text and "LOCAL_EVIDENCE_123" in unescape(result.text)
    assert "private diagnostic" not in result.text
    assert "LOCAL_EVIDENCE_123" not in json.dumps(client.completions, ensure_ascii=False)
    assert len(client.completions) <= 2 and len(client.searches) <= 2
    if failure == "unsupported":
        assert result.sources and result.audit[0]["accepted"] is False
        assert "可导函数在该点连续。" not in result.text


async def test_no_learning_intent_does_not_append_a_plan_after_network_failure():
    async def planner(*args, **kwargs):
        pytest.fail("An explanatory followup must not become a planning request")
    client = Client(results=[ZhihuError("unavailable", "private diagnostic")])
    result = await NetworkQA(client, InProcessVerificationBackend(), planner=planner).maybe_respond(
        "owner", text="为什么？", prior_question="连续与可导怎么学？", enabled=True)
    assert result.status == "unavailable" and result.planner_receipt is None


async def test_missing_learner_evidence_remains_explicit_in_a_local_plan():
    from mathtutor.application.learning_actions import load_catalog, plan_learning_actions
    async def planner(owner, goal, language="zh"):
        return plan_learning_actions([], goal, load_catalog(), language=language)
    client = Client(results=[ZhihuError("unavailable", "offline")])
    result = await NetworkQA(client, InProcessVerificationBackend(), planner=planner).maybe_respond(
        "owner", text="Can I skip the probability prerequisites?", language="en", enabled=True)
    assert result.status == "local_plan" and result.planner_receipt["evidence_ids"] == []
    assert result.planner_receipt["reason_code"] == "outside_assessment_scope"
    assert "local learning records" in result.text
    assert result.planner_receipt["reason"] in unescape(result.text)


async def test_invalid_local_plan_does_not_turn_a_network_failure_into_success():
    async def planner(owner, goal, language="zh"):
        return local_plan(goal, evidence_count=2)
    client = Client(results=[ZhihuError("unavailable", "offline")])
    result = await NetworkQA(client, InProcessVerificationBackend(), planner=planner).maybe_respond(
        "owner", text="连续与可导的学习安排", enabled=True)
    assert result.status == "unavailable" and result.planner_receipt is None


async def test_source_statement_is_not_reclassified_to_rescue_a_rejected_recommendation():
    task, batch, _, spans, _ = setup()
    candidate = claim(spans[0], text="这个例子成立，所以你应先学习这一章节再学全部高等数学。")
    client = Client([{"claims": [candidate]}, {"claims": [review(supported=False, attribution_correct=False)]}])
    result = await service(client).answer_from_sources("owner", task, batch)
    assert result.status == "unsupported" and len(client.completions) == 2
    reviewed = client.completions[1][2]["candidate"]["claims"][0]
    assert reviewed["kind"] == "source_statement" and reviewed["text"] == candidate["text"]
    assert result.audit[0]["kind"] == "source_statement" and result.audit[0]["text"] == candidate["text"]
    assert "incorrect_attribution" in result.audit[0]["reasons"]
    assert "same subject, conditions and scope" in client.completions[0][1]
    assert "Never silently reclassify" in client.completions[1][1]


@pytest.mark.parametrize("count", [4, 8])
def test_authored_reference_limit_accepts_complete_bounded_bindings_without_truncation(count):
    reference_ids = [f"original-reference-{index}" for index in range(count)]
    draft = AnswerDraft(claims=[{"claim_id": "a", "kind": "ai_inference", "text": "有条件的运算说明。",
                                "reference_ids": reference_ids}])
    assert list(draft.claims[0].reference_ids) == reference_ids


def test_authored_reference_limit_still_rejects_an_unbounded_candidate():
    with pytest.raises(ValueError):
        AnswerDraft(claims=[{"claim_id": "a", "kind": "ai_inference", "text": "运算说明。",
                            "reference_ids": [f"original-{index}" for index in range(9)]}])


async def test_planner_receipt_accepts_actual_shared_catalog_contract():
    from mathtutor.application.learning_actions import load_catalog, plan_learning_actions

    catalog = load_catalog()
    async def planner(owner, goal, language="zh"):
        return plan_learning_actions([], goal, catalog, language=language)
    qa = NetworkQA(Client(), InProcessVerificationBackend(), planner=planner)
    rendered, receipt = await qa._learning_plan("owner", choose_network_task("推荐连续与可导的入门资料"))
    assert receipt["planner_policy"] == "learning-actions-v1"
    assert receipt["evidence_ids"] == [] and receipt["resources"]
    assert len(receipt["resources"]) <= 3
    assert receipt["catalog_version"] == catalog["version"]
    assert receipt["rendered_text_sha256"] == text_hash(rendered)
    assert all(text_hash(row["summary"]) == row["summary_sha256"] for row in receipt["resources"])


async def test_disabled_network_makes_no_call():
    client = Client()
    assert await service(client).maybe_respond("owner", text="连续和可导的区别", enabled=False) is None
    assert client.searches == client.completions == []


async def test_substantive_answer_keeps_exact_evidence_author_and_time_scope():
    task, batch, payload, spans, refs = setup()
    client = Client([{"claims": [claim(spans[0])]}, {"claims": [review()]}])
    result = await service(client).answer_from_sources("owner", task, batch, provider_items=[item()])
    assert result.status == "answered"
    assert "可导函数在该点连续" in result.text and "示例作者" in result.text
    assert "https://www.zhihu.com/question/99/answer/123" in result.text
    assert result.sources[0]["source_time_kind"] == "published_or_updated"
    assert result.sources[0]["published_or_updated_at"] == 1700000000
    assert "发布或更新于 2023-11-14 (UTC)" in result.text
    assert "全文" in result.text and "逐字原文" not in result.text
    assert len(client.completions) == 2
    assert result.audit[0]["math"] == "unsupported"
    assert "数学表述待核对" in result.text
    receipt = result.audit[0]["evidence"][0]
    assert batch.sources[0].text[receipt["quote_start"]:receipt["quote_end"]] == receipt["quote"]
    assert result.audit[0]["text"] == "可导函数在该点连续。"


async def test_missing_author_and_date_are_disclosed_without_using_retrieval_time():
    raw = item()
    raw.pop("AuthorName")
    raw.pop("EditTime")
    task = choose_network_task("连续和可导有什么区别？")
    batch = build_source_snapshots([raw], retrieved_at="2026-11-18T00:00:00+00:00")
    _, spans, _ = answer_payload(task, batch)
    client = Client([{"claims": [claim(spans[0])]}, {"claims": [review()]}])
    result = await service(client).answer_from_sources("owner", task, batch, provider_items=[raw])
    assert "作者未知" in result.text and "时间未提供" in result.text
    assert "2026-11-18" not in result.text
    assert result.sources[0]["published_or_updated_at"] is None


@pytest.mark.parametrize("change", [
    {"supported": False}, {"conditions_preserved": False}, {"attribution_correct": False},
    {"relevant": False}, {"relation_correct": False}, {"math_consistency": "contradicted"},
])
async def test_each_independent_review_failure_removes_claim(change):
    _, _, _, spans, references = setup()
    shown, audit = await service().gate(AnswerDraft(claims=[claim(spans[0])]),
        AnswerReview(claims=[review(**change)]), spans, references)
    assert not shown and not audit[0]["accepted"]


@pytest.mark.parametrize("evidence", [
    [{"span_id": "forged", "quote": "可导函数"}],
    [{"span_id": "actual", "quote": "原文中不存在的观点"}],
])
async def test_valid_review_cannot_override_forged_source_or_quote(evidence):
    _, _, _, spans, references = setup()
    evidence = [{**e, "span_id": spans[0].span_id if e["span_id"] == "actual" else e["span_id"]} for e in evidence]
    shown, _ = await service().gate(AnswerDraft(claims=[claim(spans[0], evidence=evidence)]),
        AnswerReview(claims=[review()]), spans, references)
    assert not shown


async def test_failed_premise_invalidates_transitive_consequences_without_dropping_independent_part():
    _, _, _, spans, references = setup()
    claims = [claim(spans[0], claim_id="a"), claim(spans[0], claim_id="b", depends_on=["a"]),
              claim(spans[0], claim_id="c", depends_on=["b"]), claim(spans[0], claim_id="d")]
    shown, audit = await service().gate(AnswerDraft(claims=claims),
        AnswerReview(claims=[review("a", conditions_preserved=False), review("b"), review("c"), review("d")]), spans, references)
    assert [c.claim_id for c in shown] == ["d"]
    assert [row["accepted"] for row in audit] == [False, False, False, True]


async def test_auditor_can_detect_omitted_dependency():
    _, _, _, spans, references = setup()
    shown, _ = await service().gate(AnswerDraft(claims=[claim(spans[0]), claim(spans[0], claim_id="b")]),
        AnswerReview(claims=[review(supported=False), review("b", missing_dependencies=["a"])]), spans, references)
    assert not shown


async def test_deterministic_math_overrides_model_acceptance():
    _, _, _, spans, references = setup("三加四等于八。")
    draft = AnswerDraft(claims=[claim(spans[0], text="3+4=8", math=[{"expression": "3+4", "answer": "8"}])])
    shown, audit = await service().gate(draft, AnswerReview(claims=[review()]), spans, references)
    assert not shown and audit[0]["math"] == "incorrect"


async def test_unlisted_wrong_equation_is_still_checked():
    _, _, _, spans, references = setup("3+4=8。")
    shown, audit = await service().gate(AnswerDraft(claims=[claim(spans[0], text="3+4=8")]),
        AnswerReview(claims=[review(math_consistency="not_applicable")]), spans, references)
    assert not shown and audit[0]["math"] == "incorrect"
    assert audit[0]["formula_checks"]["refuted"] == 1
    assert audit[0]["formula_checks"]["refutations"][0]["statement"]["shown"] == "3+4=8"
    assert audit[0]["formula_checks"]["refutations"][0]["reason"] == "计算结果不对"


async def test_root_fragment_cannot_turn_a_supported_warning_into_a_math_refutation():
    text = "不能错误地写 √9=−3。"
    _, _, _, spans, references = setup(text)
    shown, audit = await service().gate(AnswerDraft(claims=[claim(spans[0], text=text)]),
        AnswerReview(claims=[review()]), spans, references)
    assert len(shown) == 1 and audit[0]["math"] == "unsupported"
    assert audit[0]["formula_checks"]["refutations"] == []
    assert audit[0]["formula_checks"]["verified"] == 0


async def test_comparison_requires_two_sources_even_when_reviewer_accepts():
    _, _, _, spans, references = setup()
    shown, _ = await service().gate(AnswerDraft(claims=[claim(spans[0], kind="comparison", relation="disagreement")]),
        AnswerReview(claims=[review()]), spans, references)
    assert not shown


async def test_inactive_relation_metadata_is_canonicalized_without_rewriting_claim():
    _, _, _, spans, references = setup()
    row = claim(spans[0], relation="complementary")
    draft = AnswerDraft(claims=[row])
    assert draft.claims[0].relation == "none" and draft.claims[0].text == row["text"]
    shown, audit = await service().gate(draft, AnswerReview(claims=[review()]), spans, references)
    assert len(shown) == 1
    assert audit[0]["normalization"] == {"ignored_relation_for_noncomparison": "complementary"}
    rejected, _ = await service().gate(draft, AnswerReview(claims=[review(supported=False)]), spans, references)
    assert not rejected


@pytest.mark.parametrize("rows", [[], [review(), review()], [review("other")]])
async def test_review_must_bind_once_to_every_final_claim(rows):
    _, _, _, spans, references = setup()
    with pytest.raises(ValueError):
        await service().gate(AnswerDraft(claims=[claim(spans[0])]), AnswerReview(claims=rows), spans, references)


async def test_invalid_json_falls_back_without_second_generation():
    task, batch, *_ = setup()
    client = Client(["not valid json"])
    result = await service(client).answer_from_sources("owner", task, batch)
    assert result.status == "unavailable" and len(client.completions) == 1


async def test_no_evidence_has_one_bounded_expansion():
    client = Client(results=[{"Items": [], "SearchHashId": "a"}, {"Items": [], "SearchHashId": "b"}])
    result = await service(client).maybe_respond("owner", text="连续和可导的区别", enabled=True)
    assert result.status == "no_evidence" and len(client.searches) == 2 and not client.completions


async def test_rate_limit_never_retries_or_falls_back_to_another_account():
    client = Client(results=[ZhihuError("rate_limited", "limited")])
    result = await service(client).maybe_respond("owner", text="连续和可导的区别", enabled=True)
    assert result.status == "unavailable" and len(client.searches) == 1
    assert client.searches[0][0] == "owner"


async def test_cancellation_propagates_instead_of_returning_success():
    class SlowClient(Client):
        async def search(self, owner, query, count):
            raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await service(SlowClient()).maybe_respond("owner", text="连续和可导的区别", enabled=True)


@pytest.mark.parametrize("candidate", [
    {"text": "https://evil.test"}, {"conditions": "[secret](file:///private)"}, {"reference_ids": [], "evidence": []},
])
def test_no_unregistered_links_or_unsupported_freeform_claims(candidate):
    _, _, _, spans, _ = setup()
    with pytest.raises(ValueError):
        AnswerDraft(claims=[claim(spans[0], **candidate)])


async def test_completion_sends_only_official_parameters_and_keeps_owner_secret_server_side():
    store = InMemorySecretStore()
    await store.put(secret_name("owner"), "server-only-secret")
    received = []
    def handler(request):
        received.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"claims": []}'}}]})
    client = ZhihuClient(store, transport=httpx.MockTransport(handler))
    assert await client.complete("owner", system="data only", payload={"topic": "极限"}) == '{"claims": []}'
    body = json.loads(received[0].content)
    assert set(body) == {"model", "messages", "stream"}
    assert "server-only-secret" not in received[0].content.decode()
    assert received[0].headers["Authorization"] == "Bearer server-only-secret"
    assert "<task_data>" in body["messages"][1]["content"]
    assert body["messages"][1]["content"].endswith("布尔值用 true/false，不用字符串。")


@pytest.mark.parametrize("value", ["true", "false", 1, 0, None])
def test_support_flags_are_strict_booleans(value):
    with pytest.raises(ValueError):
        AnswerReview(claims=[review(supported=value)])


async def test_long_question_remains_local_instead_of_truncating_away_conditions():
    client = Client()
    reply = await service(client).maybe_respond("owner", text="连续" + " 条件" * 1000, enabled=True)
    assert reply.status == "unsupported" and not client.searches and not client.completions


async def test_completion_rejects_oversized_reply():
    store = InMemorySecretStore()
    await store.put(secret_name("owner"), "secret")
    client = ZhihuClient(store, transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json={"choices": [{"message": {"content": "x" * 24001}}]})))
    with pytest.raises(ZhihuError):
        await client.complete("owner", system="data", payload={})
