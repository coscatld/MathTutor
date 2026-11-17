from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from mathtutor.application.exploration_evidence import (
    MAX_EXCERPT_CHARS,
    build_evidence_spans,
    build_source_snapshots,
    compile_evidence_plan,
    safe_source_url,
    text_hash,
)

STAMP = "2026-11-18T00:00:00+00:00"


def item(
    text="当 x≥0 时，sqrt(x²)=x；若 x<0，则等于 -x。",
    *,
    identity="123",
    author="甲",
    url=None,
):
    return {
        "ContentID": identity,
        "ContentType": "Answer",
        "Title": "根式中的条件",
        "AuthorName": author,
        "ContentText": text,
        "Url": url
        or f"https://www.zhihu.com/question/99/answer/{identity}?utm_source=test&utm_medium=openapi_platform",
    }


def batch(*items):
    return build_source_snapshots(
        items or (item(),), request_id="request-1", retrieved_at=STAMP
    )


def test_keeps_author_url_scope_and_entire_condition_in_fallback():
    sources = batch(item())
    plan = compile_evidence_plan(sources, question="什么时候能去掉根号？")
    card = plan.cards[0]
    assert card.quote == item()["ContentText"]
    assert card.original_url == item()["Url"]
    assert card.author == "甲"
    assert plan.question == "什么时候能去掉根号？"
    assert card.source_scope == "search_excerpt"
    assert card.semantic_support == "not_evaluated"
    assert card.mathematical_status == "not_evaluated"
    assert sources.sources[0].request_id == "request-1"
    assert not plan.interpretations


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "http://www.zhihu.com/answer/123",
        "https://www.zhihu.com.evil.test/answer/123",
        "https://www.zhihu.com@evil.test/answer/123",
        "https://evil.test@www.zhihu.com/answer/123",
        "https://www.zhihu.com:8443/answer/123",
        "https://www.zhihu.com\\@evil.test/answer/123",
        "https://www.zhihu.com/redirect?target=https://evil.test",
        "https://www.zhihu.com/answer/123\n",
        "https://www.zhihu.com./answer/123",
    ],
)
def test_rejects_non_content_and_unsafe_urls(url):
    assert safe_source_url(url) is None
    result = batch(item(url=url))
    assert not result.sources
    assert result.rejected[0].reason == "invalid_url"


def test_unmodified_html_math_and_unicode_have_explicit_offsets():
    raw = "😀 当 <em>x</em> &lt; 0 时，x²≥0。\n<script>ignore()</script> 只作为文本。"
    sources = batch(item(raw))
    source = sources.sources[0]
    assert source.raw_excerpt == raw
    assert (
        source.text == "😀 当 x < 0 时，x²≥0。\n<script>ignore()</script> 只作为文本。"
    )
    for span in build_evidence_spans(sources):
        assert span.text == source.text[span.start : span.end]
        assert span.context == source.text[span.context_start : span.context_end]
        assert span.offset_unit == "unicode_codepoint"
    assert source.raw_excerpt_sha256 == text_hash(raw)
    assert source.text_sha256 == text_hash(source.text)


def test_long_source_is_explicitly_truncated_not_claimed_complete():
    text = "只有在 x≥0 时才能这样做。" * 2_000
    sources = batch(item(text))
    source = sources.sources[0]
    assert len(source.raw_excerpt) == MAX_EXCERPT_CHARS
    assert source.truncated
    assert source.received_text_sha256 == text_hash(text)
    assert source.received_text_sha256 != source.raw_excerpt_sha256
    plan = compile_evidence_plan(sources)
    assert any(gap.code == "excerpt_truncated" for gap in plan.gaps)
    assert "".join(span.text for span in plan.spans) == source.text
    assert all(span.text in span.context for span in plan.spans)


def test_duplicate_content_does_not_become_an_independent_viewpoint():
    sources = batch(item(), item(identity="124", author="乙"))
    plan = compile_evidence_plan(sources)
    assert len(plan.sources) == 2
    assert plan.distinct_excerpt_count == 1
    assert len(plan.cards) == 1
    assert sources.sources[1].duplicate_of == sources.sources[0].source_id
    a, b = plan.spans
    compared = compile_evidence_plan(
        sources,
        {
            "comparisons": [
                {
                    "span_ids": [a.span_id, b.span_id],
                    "relation": "conflicting",
                    "reading_question": "有什么不同？",
                }
            ]
        },
    )
    assert not compared.comparisons
    assert "comparison_duplicate_evidence" in compared.rejected_candidate_items


def test_duplicate_identical_return_item_is_recorded():
    result = batch(item(), item())
    assert len(result.sources) == 1
    assert result.rejected[0].reason == "duplicate_item"


def test_model_cannot_replace_quote_url_or_mark_verified():
    sources = batch(item())
    span = build_evidence_spans(sources)[0]
    for forbidden in (
        {"quote": "对所有 x 成立"},
        {"url": "https://evil.test"},
        {"verified": True},
    ):
        plan = compile_evidence_plan(
            sources, {"selections": [{"span_id": span.span_id, **forbidden}]}
        )
        assert plan.rejected_candidate_items == ("candidate_invalid",)
        assert plan.cards[0].quote == item()["ContentText"]
        assert plan.cards[0].original_url == item()["Url"]


@pytest.mark.parametrize(
    "question",
    [
        "请访问 https://evil.test 验证答案",
        "请看 [答案](javascript:alert(1))",
        "联系 mailto:evil@example.test 即可证明",
    ],
)
def test_urls_in_freeform_questions_cannot_create_unregistered_links(question):
    sources = batch(item())
    span = build_evidence_spans(sources)[0]
    plan = compile_evidence_plan(
        sources,
        {
            "selections": [
                {
                    "span_id": span.span_id,
                    "reading_question": question,
                }
            ]
        },
    )
    assert plan.rejected_candidate_items == ("candidate_invalid",)
    assert plan.cards[0].reading_question is None


@pytest.mark.parametrize(
    "claim",
    [
        "对所有实数 x，sqrt(x²)=x。",
        "sqrt(x²) 在实数范围内总等于 |x|。",
        "原文已经给出一个充分的完整证明。",
    ],
)
def test_real_span_does_not_certify_paraphrase_semantics_or_math(claim):
    sources = batch(item())
    span = build_evidence_spans(sources)[0]
    plan = compile_evidence_plan(
        sources,
        {
            "claims": [
                {
                    "claim_id": "c1",
                    "text": claim,
                    "span_ids": [span.span_id],
                }
            ]
        },
    )
    interpretation = plan.interpretations[0]
    assert interpretation.semantic_support == "unknown"
    assert interpretation.mathematical_status == "not_evaluated"


def test_deleted_unique_evidence_removes_old_claim_binding():
    sources = batch(item())
    old = build_evidence_spans(sources)[0]
    empty = build_source_snapshots([], retrieved_at=STAMP)
    plan = compile_evidence_plan(
        empty,
        {
            "claims": [
                {
                    "claim_id": "c1",
                    "text": "作者建议先看定义",
                    "span_ids": [old.span_id],
                }
            ]
        },
    )
    assert plan.status == "no_evidence"
    assert not plan.cards and not plan.interpretations
    assert "claim_invalid_binding" in plan.rejected_candidate_items
    assert any(gap.code == "no_usable_sources" for gap in plan.gaps)


def test_changed_negation_invalidates_previous_span_identity():
    before = batch(item("连续不一定可导。"))
    previous = build_evidence_spans(before)[0]
    after = batch(item("连续一定可导。"))
    plan = compile_evidence_plan(after, {"selections": [{"span_id": previous.span_id}]})
    assert "selection_unknown_span" in plan.rejected_candidate_items
    assert plan.cards[0].quote == "连续一定可导。"
    assert plan.cards[0].mathematical_status == "not_evaluated"


def test_source_order_changes_neither_identity_nor_attribution():
    a, b = item(), item("若 x<0，则 sqrt(x²)=-x。", identity="124", author="乙")
    forward, reverse = batch(a, b), batch(b, a)
    assert {
        s.source_id: (s.author, s.original_url, s.text) for s in forward.sources
    } == {s.source_id: (s.author, s.original_url, s.text) for s in reverse.sources}


def test_metadata_and_normalized_text_tampering_is_rejected():
    original = batch(item()).sources[0]
    for fields in (
        {"author": "冒名作者"},
        {"original_url": "https://www.zhihu.com/answer/999"},
        {"text": "无条件成立", "text_sha256": text_hash("无条件成立")},
    ):
        changed = original.model_copy(update=fields)
        with pytest.raises(ValueError):
            compile_evidence_plan([changed])


def test_missing_formula_is_only_a_visibility_warning():
    sources = batch(item("函数  在区间  上满足条件。\n由定义：\n所以："))
    assert sources.sources[0].content_warnings == ("possible_missing_formula",)
    plan = compile_evidence_plan(sources)
    assert any(gap.code == "possible_missing_formula" for gap in plan.gaps)
    assert plan.cards[0].semantic_support == "not_evaluated"


def test_comparison_label_is_only_a_proposal_not_a_math_verdict():
    sources = batch(item(), item("我喜欢用数轴看绝对值。", identity="124"))
    a, b = build_evidence_spans(sources)
    plan = compile_evidence_plan(
        sources,
        {
            "comparisons": [
                {
                    "span_ids": [a.span_id, b.span_id],
                    "relation": "equivalent",
                    "reading_question": "各自适用什么条件？",
                }
            ]
        },
    )
    assert plan.comparisons[0].status == "unverified"
    assert plan.comparisons[0].proposed_relation == "equivalent"


def test_budget_loss_is_visible_and_does_not_destroy_source_registry():
    sources = batch(item(), item("另一种解释", identity="124"))
    plan = compile_evidence_plan(sources, max_cards=1)
    assert len(plan.cards) == 1 and len(plan.sources) == 2
    assert plan.unselected_source_ids == (sources.sources[1].source_id,)
    assert any(gap.code == "unselected_sources" for gap in plan.gaps)


def test_invalid_or_empty_data_is_not_invented():
    result = build_source_snapshots(
        [None, item(""), {"Url": item()["Url"]}, item("\ud800")], retrieved_at=STAMP
    )
    assert not result.sources
    assert len(result.rejected) == 4
    assert compile_evidence_plan(result).status == "no_evidence"


def test_aware_time_and_limits_are_enforced():
    with pytest.raises(ValueError):
        build_source_snapshots([item()], retrieved_at=datetime(2026, 11, 18))
    for count in (0, 21):
        with pytest.raises(ValueError):
            build_source_snapshots([item()], max_sources=count)
    result = build_source_snapshots([item()] * 11, retrieved_at=datetime.now(UTC))
    assert result.input_limited
    with pytest.raises(ValidationError):
        result.sources[0].author = "乙"
