"""Bounded, source-bound reading plans; quote integrity is not entailment."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

MAX_SOURCES = 20
MAX_EXCERPT_CHARS = 16_000
SPAN_TARGET_CHARS = 1_200
MAX_CANDIDATE_CHARS = 32_000
_HIGHLIGHT = re.compile(r"</?em\s*>", re.IGNORECASE)
_CONTENT_PATH = re.compile(
    r"/(?:question/\d+(?:/answer/\d+)?|(?:en/)?answer/\d+|p/\d+)/?$"
)
_ALLOWED_HOSTS = frozenset({"zhihu.com", "www.zhihu.com", "zhuanlan.zhihu.com"})
SpanId = Annotated[str, Field(min_length=1, max_length=80)]
SourceProvider = Literal["zhihu", "wikipedia", "wikibooks", "active_calculus", "open_math_books"]
ExcerptScope = Literal["search_excerpt", "page_excerpt", "textbook_excerpt"]


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _normalize(text: str) -> str:
    return html.unescape(_HIGHLIGHT.sub("", text))[:MAX_EXCERPT_CHARS]


def _source_id(
    content_id: str,
    content_type: str,
    url: str,
    title: str,
    author: str | None,
    raw_hash: str,
    provenance: tuple[str, ...] = (),
) -> str:
    payload = json.dumps(
        [content_id, content_type, url, title, author, raw_hash, *provenance], ensure_ascii=False
    )
    return "S-" + text_hash(payload)[:24]


def safe_source_url(value: object, provider: SourceProvider = "zhihu") -> str | None:
    if not isinstance(value, str) or len(value) > 2_048 or not value:
        return None
    if any(ord(char) < 33 or ord(char) == 127 for char in value) or "\\" in value:
        return None
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
        ):
            return None
        if provider == "zhihu":
            allowed = parsed.hostname in _ALLOWED_HOSTS and _CONTENT_PATH.fullmatch(parsed.path)
        elif provider in ("wikipedia", "wikibooks"):
            allowed = (parsed.hostname in {f"en.{provider}.org", f"zh.{provider}.org"}
                       and parsed.path == "/w/index.php" and re.fullmatch(r"oldid=[1-9][0-9]*", parsed.query)
                       and not parsed.fragment)
        else:
            allowed = value in {
                "active_calculus": {"https://activecalculus.org/single/sec-1-7-lim-cont-diff.html"},
                "open_math_books": {"https://discrete.openmathbooks.org/dmoi3/sec_logic-proofs.html"},
            }.get(provider, set())
        if not allowed:
            return None
    except ValueError:
        return None
    return value


class Attribution(Frozen):
    language: Literal["en", "zh"]
    version: str = Field(min_length=1, max_length=120)
    license: Literal["CC BY-SA 4.0"] = "CC BY-SA 4.0"


class SourceSnapshot(Frozen):
    source_id: str
    provider: SourceProvider = "zhihu"
    attribution: Attribution | None = None
    content_id: str
    content_type: str
    title: str
    author: str | None
    original_url: str
    request_id: str
    retrieved_at: str
    scope: ExcerptScope = "search_excerpt"
    raw_excerpt: str = Field(max_length=MAX_EXCERPT_CHARS)
    raw_excerpt_sha256: str
    received_text_sha256: str
    text: str = Field(max_length=MAX_EXCERPT_CHARS)
    text_sha256: str
    normalization: Literal["zhihu-highlight-v1", "public-text-v1"] = "zhihu-highlight-v1"
    truncated: bool = False
    duplicate_of: str | None = None
    content_warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_snapshot(self) -> SourceSnapshot:
        if safe_source_url(self.original_url, self.provider) is None:
            raise ValueError("invalid source URL")
        legacy = self.provider == "zhihu"
        if legacy != (self.attribution is None) or legacy != (self.normalization == "zhihu-highlight-v1"):
            raise ValueError("invalid provider attribution")
        if self.raw_excerpt_sha256 != text_hash(
            self.raw_excerpt
        ) or self.text_sha256 != text_hash(self.text):
            raise ValueError("snapshot hash mismatch")
        if self.text != (_normalize(self.raw_excerpt) if legacy else self.raw_excerpt):
            raise ValueError("snapshot normalization mismatch")
        if not self.truncated and self.received_text_sha256 != self.raw_excerpt_sha256:
            raise ValueError("untruncated snapshot must contain the received text")
        expected = _source_id(
            self.content_id,
            self.content_type,
            self.original_url,
            self.title,
            self.author,
            self.raw_excerpt_sha256,
            self.provenance_key(),
        )
        if self.source_id != expected:
            raise ValueError("source identity mismatch")
        _retrieved_time(self.retrieved_at)
        return self

    def provenance_key(self) -> tuple[str, ...]:
        if self.attribution is None:
            return ()
        return (self.provider, self.scope, self.attribution.language, self.attribution.version, self.attribution.license)


def public_snapshot(*, provider: SourceProvider, content_id: str, content_type: str, title: str, author: str,
                    url: str, text: str, scope: ExcerptScope, attribution: Attribution, retrieved_at: str,
                    request_id: str, warnings: tuple[str, ...] = ()) -> SourceSnapshot:
    excerpt = text[:1000]
    digest = text_hash(excerpt)
    provenance = (provider, scope, attribution.language, attribution.version, attribution.license)
    return SourceSnapshot(
        source_id=_source_id(content_id, content_type, url, title, author, digest, provenance),
        provider=provider, content_id=content_id, content_type=content_type, title=title, author=author,
        original_url=url, request_id=request_id, retrieved_at=retrieved_at, scope=scope, attribution=attribution,
        raw_excerpt=excerpt, text=excerpt, raw_excerpt_sha256=digest, received_text_sha256=text_hash(text), text_sha256=digest,
        normalization="public-text-v1", content_warnings=warnings, truncated=len(excerpt) < len(text),
    )


class SourceRejection(Frozen):
    item_index: int
    reason: Literal[
        "invalid_item",
        "invalid_url",
        "missing_identity",
        "empty_excerpt",
        "duplicate_item",
    ]


class SourceBatch(Frozen):
    sources: tuple[SourceSnapshot, ...]
    rejected: tuple[SourceRejection, ...] = ()
    input_limited: bool = False


class EvidenceSpan(Frozen):
    span_id: str
    source_id: str
    start: int
    end: int
    text: str
    context_start: int
    context_end: int
    context: str
    offset_unit: Literal["unicode_codepoint"] = "unicode_codepoint"


class SpanSelection(Frozen):
    span_id: SpanId
    reading_question: str | None = Field(default=None, min_length=1, max_length=240)


class ClaimProposal(Frozen):
    claim_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=600)
    span_ids: tuple[SpanId, ...] = Field(min_length=1, max_length=4)


class ComparisonProposal(Frozen):
    span_ids: tuple[SpanId, SpanId]
    relation: Literal[
        "unresolved",
        "different_conditions",
        "complementary",
        "equivalent",
        "conflicting",
    ] = "unresolved"
    reading_question: str = Field(min_length=1, max_length=240)


class EvidenceCandidate(Frozen):
    selections: tuple[SpanSelection, ...] = Field(default=(), max_length=20)
    claims: tuple[ClaimProposal, ...] = Field(default=(), max_length=12)
    comparisons: tuple[ComparisonProposal, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def only_registered_links(self) -> EvidenceCandidate:
        texts = [
            item.reading_question for item in self.selections if item.reading_question
        ]
        texts += [item.text for item in self.claims]
        texts += [item.reading_question for item in self.comparisons]
        if any(
            re.search(
                r"(?i)(?:[a-z][a-z0-9+.-]*://|(?:javascript|data|file|mailto|tel):|www\.)",
                item,
            )
            for item in texts
        ):
            raise ValueError(
                "candidate text must refer to registered spans instead of URLs"
            )
        if sum(map(len, texts)) > MAX_CANDIDATE_CHARS:
            raise ValueError("candidate text too large")
        return self


class EvidenceCard(Frozen):
    source_id: str
    provider: SourceProvider = "zhihu"
    attribution: Attribution | None = None
    span_id: str
    title: str
    author: str | None
    original_url: str
    quote: str
    context: str
    quote_integrity: Literal["exact_snapshot_text"] = "exact_snapshot_text"
    source_scope: ExcerptScope = "search_excerpt"
    semantic_support: Literal["not_evaluated"] = "not_evaluated"
    mathematical_status: Literal["not_evaluated"] = "not_evaluated"
    reading_question: str | None = None


class UnverifiedInterpretation(Frozen):
    claim_id: str
    text: str
    span_ids: tuple[str, ...]
    semantic_support: Literal["unknown"] = "unknown"
    mathematical_status: Literal["not_evaluated"] = "not_evaluated"
    kind: Literal["model_interpretation"] = "model_interpretation"


class UnverifiedComparison(Frozen):
    span_ids: tuple[str, str]
    proposed_relation: str
    reading_question: str
    status: Literal["unverified"] = "unverified"


class EvidenceGap(Frozen):
    code: str
    source_ids: tuple[str, ...] = ()


class EvidencePlan(Frozen):
    question: str
    sources: tuple[SourceSnapshot, ...]
    spans: tuple[EvidenceSpan, ...]
    cards: tuple[EvidenceCard, ...]
    interpretations: tuple[UnverifiedInterpretation, ...]
    comparisons: tuple[UnverifiedComparison, ...]
    gaps: tuple[EvidenceGap, ...]
    rejected_candidate_items: tuple[str, ...]
    source_rejections: tuple[SourceRejection, ...]
    unselected_source_ids: tuple[str, ...]
    distinct_excerpt_count: int
    status: Literal["evidence_available", "no_evidence"]


def _small_text(value: object, limit: int) -> str:
    return value[:limit] if isinstance(value, str) else ""


def _retrieved_time(value: str | datetime | None) -> str:
    if value is None:
        value = datetime.now(UTC)
    elif isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("retrieved_at requires a timezone")
    return value.astimezone(UTC).isoformat()


def build_source_snapshots(
    items: Sequence[object],
    *,
    request_id: str = "",
    retrieved_at: str | datetime | None = None,
    max_sources: int = 10,
) -> SourceBatch:
    if not 1 <= max_sources <= MAX_SOURCES:
        raise ValueError("max_sources must be between 1 and 20")
    timestamp = _retrieved_time(retrieved_at)
    sources: list[SourceSnapshot] = []
    rejected: list[SourceRejection] = []
    identities: set[str] = set()
    content_groups: dict[str, str] = {}
    for index, item in enumerate(items[:max_sources]):
        if not isinstance(item, Mapping):
            rejected.append(SourceRejection(item_index=index, reason="invalid_item"))
            continue
        url = safe_source_url(item.get("Url"))
        if url is None:
            rejected.append(SourceRejection(item_index=index, reason="invalid_url"))
            continue
        content_id = _small_text(item.get("ContentID"), 160)
        content_type = _small_text(item.get("ContentType"), 80)
        if not content_id or not content_type:
            rejected.append(
                SourceRejection(item_index=index, reason="missing_identity")
            )
            continue
        received = item.get("ContentText")
        if not isinstance(received, str) or not received.strip():
            rejected.append(SourceRejection(item_index=index, reason="empty_excerpt"))
            continue
        try:
            received.encode("utf-8")
        except UnicodeEncodeError:
            rejected.append(SourceRejection(item_index=index, reason="invalid_item"))
            continue
        raw = received[:MAX_EXCERPT_CHARS]
        text = _normalize(raw)
        if not text.strip():
            rejected.append(SourceRejection(item_index=index, reason="empty_excerpt"))
            continue
        raw_hash = text_hash(raw)
        title = _small_text(item.get("Title"), 300) or "知乎内容"
        author = _small_text(item.get("AuthorName"), 120) or None
        source_id = _source_id(content_id, content_type, url, title, author, raw_hash)
        if source_id in identities:
            rejected.append(SourceRejection(item_index=index, reason="duplicate_item"))
            continue
        identities.add(source_id)
        fingerprint = text_hash(re.sub(r"\s+", " ", text).strip())
        duplicate_of = content_groups.setdefault(fingerprint, source_id)
        warnings = []
        if len(received) > len(raw):
            warnings.append("excerpt_truncated")
        if re.search(r"[\u4e00-\u9fff]\s{2,}[\u4e00-\u9fff，。；：]", text):
            warnings.append("possible_missing_formula")
        sources.append(
            SourceSnapshot(
                source_id=source_id,
                content_id=content_id,
                content_type=content_type,
                title=title,
                author=author,
                original_url=url,
                request_id=_small_text(request_id, 160),
                retrieved_at=timestamp,
                raw_excerpt=raw,
                raw_excerpt_sha256=raw_hash,
                received_text_sha256=text_hash(received),
                text=text,
                text_sha256=text_hash(text),
                truncated=len(received) > len(raw),
                duplicate_of=None if duplicate_of == source_id else duplicate_of,
                content_warnings=tuple(warnings),
            )
        )
    return SourceBatch(
        sources=tuple(sources),
        rejected=tuple(rejected),
        input_limited=len(items) > max_sources,
    )


def _sources(
    value: SourceBatch | Sequence[SourceSnapshot],
) -> tuple[SourceSnapshot, ...]:
    sources = value.sources if isinstance(value, SourceBatch) else tuple(value)
    if len(sources) > MAX_SOURCES or len({item.source_id for item in sources}) != len(
        sources
    ):
        raise ValueError("invalid source collection")
    for source in sources:
        source.validate_snapshot()
    registry = {source.source_id: source for source in sources}
    for source in sources:
        if source.duplicate_of is not None:
            target = registry.get(source.duplicate_of)
            if target is None or target is source or target.duplicate_of is not None:
                raise ValueError("invalid duplicate reference")
            if (
                re.sub(r"\s+", " ", target.text).strip()
                != re.sub(r"\s+", " ", source.text).strip()
            ):
                raise ValueError("duplicate content mismatch")
    return sources


def _ranges(text: str) -> list[tuple[int, int]]:
    ranges = []
    start = 0
    while start < len(text):
        target = min(start + SPAN_TARGET_CHARS, len(text))
        end = target
        if target < len(text):
            boundaries = list(
                re.finditer(r"[。！？!?](?:[”’）\)]|\s)*|\n", text[start:target])
            )
            if boundaries and boundaries[-1].end() > SPAN_TARGET_CHARS // 2:
                end = start + boundaries[-1].end()
        ranges.append((start, end))
        start = end
    return ranges


def build_evidence_spans(
    sources: SourceBatch | Sequence[SourceSnapshot],
) -> tuple[EvidenceSpan, ...]:
    spans = []
    for source in _sources(sources):
        ranges = _ranges(source.text)
        for index, (start, end) in enumerate(ranges):
            context_start = ranges[max(0, index - 1)][0]
            context_end = ranges[min(len(ranges) - 1, index + 1)][1]
            spans.append(
                EvidenceSpan(
                    span_id=f"{source.source_id}:{start}:{end}",
                    source_id=source.source_id,
                    start=start,
                    end=end,
                    text=source.text[start:end],
                    context_start=context_start,
                    context_end=context_end,
                    context=source.text[context_start:context_end],
                )
            )
    return tuple(spans)


def _parse_candidate(
    candidate: EvidenceCandidate | Mapping | None,
) -> tuple[EvidenceCandidate, tuple[str, ...]]:
    if candidate is None:
        return EvidenceCandidate(), ()
    if isinstance(candidate, EvidenceCandidate):
        return candidate, ()
    try:
        return EvidenceCandidate.model_validate(candidate), ()
    except (ValidationError, TypeError, ValueError):
        return EvidenceCandidate(), ("candidate_invalid",)


def compile_evidence_plan(
    sources: SourceBatch | Sequence[SourceSnapshot],
    candidate: EvidenceCandidate | Mapping | None = None,
    *,
    question: str = "",
    max_cards: int = 10,
) -> EvidencePlan:
    if not 1 <= max_cards <= MAX_SOURCES:
        raise ValueError("max_cards must be between 1 and 20")
    if not isinstance(question, str) or len(question) > 1_000:
        raise ValueError("question must contain at most 1000 characters")
    snapshots = _sources(sources)
    spans = build_evidence_spans(snapshots)
    registry = {span.span_id: span for span in spans}
    source_map = {source.source_id: source for source in snapshots}
    proposal, errors = _parse_candidate(candidate)
    rejected = list(errors)
    selected: dict[str, SpanSelection] = {}
    for item in proposal.selections:
        span = registry.get(item.span_id)
        if span is None:
            rejected.append("selection_unknown_span")
        elif source_map[span.source_id].duplicate_of is None:
            selected.setdefault(span.source_id, item)
    by_source = {source.source_id: [] for source in snapshots}
    for span in spans:
        by_source[span.source_id].append(span)
    cards = []
    for source in snapshots:
        if source.duplicate_of is not None or len(cards) >= max_cards:
            continue
        selection = selected.get(source.source_id)
        span = (
            registry[selection.span_id] if selection else by_source[source.source_id][0]
        )
        cards.append(
            EvidenceCard(
                source_id=source.source_id,
                provider=source.provider,
                attribution=source.attribution,
                source_scope=source.scope,
                span_id=span.span_id,
                title=source.title,
                author=source.author,
                original_url=source.original_url,
                quote=span.text,
                context=span.context,
                reading_question=selection.reading_question if selection else None,
            )
        )
    interpretations = []
    seen_claims: set[str] = set()
    for claim in proposal.claims:
        if claim.claim_id in seen_claims or any(
            ref not in registry for ref in claim.span_ids
        ):
            rejected.append("claim_invalid_binding")
            continue
        seen_claims.add(claim.claim_id)
        interpretations.append(
            UnverifiedInterpretation(
                claim_id=claim.claim_id,
                text=claim.text,
                span_ids=tuple(dict.fromkeys(claim.span_ids)),
            )
        )
    comparisons = []
    for comparison in proposal.comparisons:
        left, right = (registry.get(ref) for ref in comparison.span_ids)
        if left is None or right is None:
            rejected.append("comparison_unknown_span")
            continue
        a, b = source_map[left.source_id], source_map[right.source_id]
        if (
            (a.duplicate_of or a.source_id) == (b.duplicate_of or b.source_id)
            or (a.content_type, a.content_id) == (b.content_type, b.content_id)
            or urlsplit(a.original_url)._replace(query="", fragment="")
            == urlsplit(b.original_url)._replace(query="", fragment="")
        ):
            rejected.append("comparison_duplicate_evidence")
            continue
        comparisons.append(
            UnverifiedComparison(
                span_ids=comparison.span_ids,
                proposed_relation=comparison.relation,
                reading_question=comparison.reading_question,
            )
        )
    selected_ids = {card.source_id for card in cards}
    unselected = tuple(
        source.source_id
        for source in snapshots
        if source.duplicate_of is None and source.source_id not in selected_ids
    )
    gaps = [] if snapshots else [EvidenceGap(code="no_usable_sources")]
    excerpt_ids = tuple(source.source_id for source in snapshots if source.scope == "search_excerpt")
    if excerpt_ids:
        gaps.append(EvidenceGap(code="search_excerpt_scope", source_ids=excerpt_ids))
    for source in snapshots:
        gaps.extend(
            EvidenceGap(code=warning, source_ids=(source.source_id,))
            for warning in source.content_warnings
        )
    if unselected:
        gaps.append(EvidenceGap(code="unselected_sources", source_ids=unselected))
    if isinstance(sources, SourceBatch) and sources.input_limited:
        gaps.append(EvidenceGap(code="source_limit_reached"))
    return EvidencePlan(
        question=question,
        sources=snapshots,
        spans=spans,
        cards=tuple(cards),
        interpretations=tuple(interpretations),
        comparisons=tuple(comparisons),
        gaps=tuple(gaps),
        rejected_candidate_items=tuple(rejected),
        source_rejections=sources.rejected if isinstance(sources, SourceBatch) else (),
        unselected_source_ids=unselected,
        distinct_excerpt_count=sum(source.duplicate_of is None for source in snapshots),
        status="evidence_available" if cards else "no_evidence",
    )
