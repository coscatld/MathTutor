"""Anonymous, bounded public-math retrieval. Queries never include learner records."""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from itertools import zip_longest
from typing import Literal, Protocol
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from mathtutor.application.exploration_evidence import (
    MAX_SOURCES, PUBLIC_PROVIDERS, WIKI_HOSTS, Attribution, PublicProvider, SourceBatch, SourceSnapshot, public_snapshot,
)

Project = Literal["wikipedia", "wikibooks"]
Locale = Literal["zh", "en"]
Access = Literal["online", "bundled"]


class RetrievalAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: PublicProvider
    access: Access = "online"
    language: Locale
    status: Literal["found", "empty", "unavailable", "rate_limited"]
    count: int = Field(default=0, ge=0)


@dataclass(frozen=True)
class ReadingQuery:
    question: str
    language: Locale
    retrieved_at: str


@dataclass(frozen=True)
class AdapterReadings:
    sources: tuple[SourceSnapshot, ...]
    attempts: tuple[RetrievalAttempt, ...]


class ReadingAdapter(Protocol):
    """Retrieve public excerpts without learner identifiers or access to the private library."""

    provider: PublicProvider
    access: Access

    async def retrieve(self, query: ReadingQuery) -> AdapterReadings: ...


# Aliases keep a conversational question searchable in either edition. Unknown
# topics use the user's own words in the corresponding public language edition.
_TOPICS = (
    (("0.999",), "0.999…", "0.999..."),
    (("可导", "不可微", "differentiab", "continuity and differentiability"), "可微函数", "differentiable function"),
    (("导数", "derivative"), "导数", "derivative"),
    (("丢解", "除以 x", "除以x", "dividing both sides", "division by zero"), "除以零", "division by zero"),
    (("平方根", "根式", "square root", "sqrt", "√"), "平方根", "square root"),
    (("中值定理", "mean value theorem"), "中值定理", "mean value theorem"),
    (("鸽巢", "抽屉原理", "pigeonhole", "pigeon hole"), "鸽巢原理", "pigeonhole principle"),
    (("条件概率", "conditional probability"), "条件概率", "conditional probability"),
    (("贝叶斯", "bayes"), "贝叶斯定理", "Bayes' theorem"),
    (("等比级数", "geometric series"), "几何级数", "geometric series"),
    (("一元二次", "quadratic equation", "求根公式"), "一元二次方程", "quadratic equation"),
    (("勾股", "毕达哥拉斯", "pythagor"), "勾股定理", "Pythagorean theorem"),
)


def _queries(question: str, language: Locale):
    folded = question.casefold()
    for aliases, chinese, english in _TOPICS:
        if any(alias in folded for alias in aliases):
            return [("zh", chinese), ("en", english)] if language == "zh" else [("en", english)]
    locale = "zh" if re.search(r"[\u3400-\u9fff]", question) else "en"
    return [(locale, question.strip())]


# The source-language quotations retain their authors' wording. The book/section
# and license are also present in each saved snapshot when the device is offline.
@dataclass(frozen=True)
class TextbookAdapter:
    provider: PublicProvider
    aliases: tuple[str, ...]
    title: str
    author: str
    edition: str
    url: str
    quote: str
    access: Access = "bundled"

    async def retrieve(self, query: ReadingQuery) -> AdapterReadings:
        matches = any(alias in query.question.casefold() for alias in self.aliases)
        sources = (public_snapshot(
            provider=self.provider, content_id=self.url, content_type="open_textbook", title=self.title,
            author=self.author, url=self.url, text=self.quote, scope="textbook_excerpt", retrieved_at=query.retrieved_at,
            attribution=Attribution(language="en", version=self.edition), request_id="bundled-edition",
        ),) if matches else ()
        attempt = RetrievalAttempt(provider=self.provider, access=self.access, language="en",
                                   status="found" if matches else "empty", count=len(sources))
        return AdapterReadings(sources, (attempt,))


TEXTBOOK_ADAPTERS = (
    TextbookAdapter("active_calculus",
        ("连续函数", "函数连续", "可导", "不可微", "continuous function", "function be continuous", "differentiab"),
        "Active Calculus · 1.7 Limits, continuity, and differentiability", "Matthew Boelkins",
        "2nd ed. (2025), §1.7.4", "https://activecalculus.org/single/sec-1-7-lim-cont-diff.html",
        "A function can be continuous at a point, but not be differentiable there."),
    TextbookAdapter("open_math_books", ("鸽巢", "抽屉原理", "pigeonhole", "pigeon hole"),
        "Discrete Mathematics: An Open Introduction · 3.2 Proofs", "Oscar Levin",
        "3rd ed., §3.2", "https://discrete.openmathbooks.org/dmoi3/sec_logic-proofs.html",
        "If more than n pigeons fly into n pigeon holes, then at least one pigeon hole will contain at least two pigeons."),
)


class _VisibleText(HTMLParser):
    """Read rendered paragraphs or snippets, keeping the one TeX alternative per formula."""

    def __init__(self, paragraphs=False):
        super().__init__(convert_charrefs=True)
        self.paragraphs = paragraphs
        self.in_paragraph = not paragraphs
        self.skip = ""
        self.chunks = []
        self.paragraph_text = []
        self.omitted_math = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self.skip:
            return
        if tag in {"style", "script", "annotation"} or tag == "sup" and "reference" in (attrs.get("class") or ""):
            self.skip = tag
        elif tag in {"sub", "sup"} and self.in_paragraph:
            self.paragraph_text.append("_" if tag == "sub" else "^")
        elif tag == "p" and self.paragraphs:
            self.in_paragraph = True
            self.paragraph_text = []
        elif tag == "math":
            tex = attrs.get("alttext")
            if tex and self.in_paragraph:
                self.paragraph_text.append(tex)
            elif self.in_paragraph:
                self.omitted_math = True
            self.skip = "math"
        elif tag == "br" and self.in_paragraph:
            self.paragraph_text.append(" ")

    def handle_endtag(self, tag):
        if self.skip:
            if self.skip == tag:
                self.skip = ""
        elif tag == "p" and self.paragraphs:
            paragraph = " ".join("".join(self.paragraph_text).split())
            if len(paragraph) >= 35 and not _navigation(paragraph):
                self.chunks.append(paragraph)
            self.in_paragraph = False

    def handle_data(self, data):
        if self.in_paragraph and not self.skip:
            self.paragraph_text.append(data)

    @classmethod
    def read(cls, markup, *, paragraphs=False):
        reader = cls(paragraphs)
        reader.feed(markup)
        reader.close()
        value = "\n".join(reader.chunks[:2]) if paragraphs else " ".join("".join(reader.paragraph_text).split())
        return value, reader.omitted_math


class _Unavailable(Exception):
    def __init__(self, status="unavailable"):
        self.status = status


def _navigation(text: str) -> bool:
    return bool(re.search(r"章[节節][导導]航|返回目[录錄]|chapter navigation|table of contents", text, re.I))


def _retry_seconds(value: str) -> float:
    if value.isdigit() and len(value) < 12:
        return int(value)
    try:
        return max(0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError, OverflowError):
        return 60


class MediaWikiAdapter:
    access: Access = "online"

    def __init__(self, project: Project, *, transport=None):
        if project not in WIKI_HOSTS:
            raise ValueError("Unknown MediaWiki project.")
        self.provider = project
        self.transport = transport
        self.retry_after = {}

    async def _request(self, client, endpoint, params):
        if self.retry_after.get(endpoint, 0) > time.monotonic():
            raise _Unavailable("rate_limited")
        async with client.stream("GET", endpoint, params={"format": "json", "formatversion": "2", **params}) as response:
            if response.status_code == 429:
                self.retry_after[endpoint] = time.monotonic() + _retry_seconds(response.headers.get("Retry-After", ""))
                raise _Unavailable("rate_limited")
            if response.status_code != 200:
                raise _Unavailable()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 512_000:
                    raise _Unavailable()
        try:
            data = json.loads(body)
        except (ValueError, RecursionError):
            raise _Unavailable() from None
        if not isinstance(data, dict):
            raise _Unavailable()
        if "error" in data:
            code = data["error"].get("code") if isinstance(data["error"], dict) else None
            if code in {"ratelimited", "maxlag"}:
                self.retry_after[endpoint] = time.monotonic() + _retry_seconds(response.headers.get("Retry-After", ""))
                raise _Unavailable("rate_limited")
            raise _Unavailable()
        return data

    async def _edition(self, client, language, query, stamp):
        project = self.provider
        host = f"{language}.{project}.org"
        endpoint = f"https://{host}/w/api.php"
        if project == "wikibooks" and query in {"可微函数", "differentiable function"}:
            query = "intitle:导数" if language == "zh" else "intitle:derivatives calculus"
        found = await self._request(client, endpoint, {
            "action": "query", "generator": "search", "gsrsearch": query, "gsrnamespace": 0,
            "gsrlimit": 4, "gsrprop": "snippet", "prop": "info",
        })
        # MediaWiki omits query entirely on a successful zero-hit generator.
        if "query" not in found and not found.get("batchcomplete"):
            raise _Unavailable()
        pages = found.get("query", {}).get("pages", [])
        if not isinstance(pages, list):
            raise _Unavailable()
        results = []
        request_id = str(uuid4())
        candidates = [page for page in pages if isinstance(page, dict) and type(page.get("index")) is int]
        for page in sorted(candidates, key=lambda item: item["index"]):
            revision, page_id, title, snippet = (page.get(key) for key in ("lastrevid", "pageid", "title", "snippet"))
            if (type(revision) is not int or revision < 1 or type(page_id) is not int or page_id < 1
                    or not isinstance(title, str) or not title.strip() or not isinstance(snippet, str)):
                continue
            if project == "wikibooks" and "/" not in title and any(
                isinstance(p, dict) and "/" in str(p.get("title", "")) for p in pages
            ):
                continue
            if re.search(r"\((?:finance|film|album|disambiguation)\)|消歧|消歧義|电影", title, re.I):
                continue
            text, missing_math = _VisibleText.read(snippet)
            scope = "search_excerpt"
            if not results:
                # The search snippet is still usable if the revision's lead is
                # empty, too large, rate-limited, or contains only navigation.
                try:
                    parsed = await self._request(client, endpoint, {
                        "action": "parse", "oldid": revision, "section": 0, "prop": "text",
                        "disableeditsection": 1, "disablelimitreport": 1,
                    })
                    markup = parsed.get("parse", {}).get("text", "")
                    if isinstance(markup, str):
                        paragraph, omitted = _VisibleText.read(markup, paragraphs=True)
                        if paragraph:
                            text, missing_math, scope = paragraph, omitted, "page_excerpt"
                except (_Unavailable, httpx.HTTPError):
                    pass
            if not text.strip() or _navigation(text):
                continue
            warnings = []
            if missing_math:
                warnings.append("possible_missing_formula")
            if len(text) > 1000:
                warnings.append("excerpt_truncated")
            results.append(public_snapshot(
                provider=project, content_id=f"{host}:{page_id}", content_type="encyclopedia" if project == "wikipedia" else "wikibook",
                title=title[:300], author=f"{'Wikipedia' if project == 'wikipedia' else 'Wikibooks'} contributors",
                url=f"https://{host}/w/index.php?oldid={revision}", text=text, scope=scope, retrieved_at=stamp,
                request_id=request_id, attribution=Attribution(language=language, version=str(revision)), warnings=tuple(warnings),
            ))
            if len(results) == 2:
                break
        return results

    async def _editions(self, client, query):
        attempts = []
        for language, term in _queries(query.question, query.language):
            try:
                async with asyncio.timeout(9):
                    sources = await self._edition(client, language, term, query.retrieved_at)
                status = "found" if sources else "empty"
            except (_Unavailable, httpx.HTTPError, TimeoutError, ValueError, AttributeError, TypeError) as error:
                status = error.status if isinstance(error, _Unavailable) else "unavailable"
                sources = []
            attempts.append(RetrievalAttempt(provider=self.provider, language=language, status=status, count=len(sources)))
            if sources:
                return AdapterReadings(tuple(sources), tuple(attempts))
        return AdapterReadings((), tuple(attempts))

    async def retrieve(self, query: ReadingQuery) -> AdapterReadings:
        async with httpx.AsyncClient(transport=self.transport, timeout=5, follow_redirects=False,
                headers={"User-Agent": "MathTutor/1.0 (https://github.com/coscatld/MathTutor)",
                         "Accept": "application/json"}) as client:
            return await self._editions(client, query)


class OpenReadingSearch:
    def __init__(self, *, adapters: Iterable[ReadingAdapter] | None = None, transport=None):
        self.adapters: dict[PublicProvider, ReadingAdapter] = {}
        if adapters is None:
            adapters = (MediaWikiAdapter("wikipedia", transport=transport),
                        MediaWikiAdapter("wikibooks", transport=transport), *TEXTBOOK_ADAPTERS)
        for adapter in adapters:
            self.register(adapter)

    def register(self, adapter: ReadingAdapter) -> None:
        if adapter.provider not in PUBLIC_PROVIDERS or adapter.access not in {"online", "bundled"}:
            raise ValueError("Public adapters require a registered provider URL policy and access type.")
        if adapter.provider in self.adapters:
            raise ValueError(f"Duplicate reading adapter for {adapter.provider}.")
        self.adapters[adapter.provider] = adapter

    async def _retrieve(self, adapter: ReadingAdapter, query: ReadingQuery) -> AdapterReadings:
        try:
            async with asyncio.timeout(20):
                result = await adapter.retrieve(query)
            if not result.attempts or any(a.provider != adapter.provider or a.access != adapter.access for a in result.attempts):
                raise ValueError("Adapter returned a receipt for a different collection.")
            validated = []
            for source in result.sources:
                if source.provider != adapter.provider:
                    raise ValueError("Adapter returned another provider's source.")
                # Check the URL, hashes and field types even for a custom adapter
                # that returned an unchecked model copy.
                validated.append(SourceSnapshot.model_validate(source.model_dump()))
            return AdapterReadings(tuple(validated), result.attempts)
        except Exception:
            # An external adapter's failure must not cancel other sources.
            # asyncio.CancelledError still propagates when the learner cancels.
            attempt = RetrievalAttempt(provider=adapter.provider, access=adapter.access, language=query.language,
                                       status="unavailable")
            return AdapterReadings((), (attempt,))

    async def search(self, question: str, language: Locale):
        query = ReadingQuery(question, language, datetime.now(UTC).isoformat())
        results = await asyncio.gather(*(self._retrieve(adapter, query) for adapter in self.adapters.values()))
        sources = []
        ids = set()
        seen = {}
        for row in zip_longest(*(result.sources for result in results)):
            for item in row:
                if item is None or item.source_id in ids:
                    continue
                ids.add(item.source_id)
                if len(sources) < MAX_SOURCES:
                    previous = seen.setdefault(" ".join(item.text.split()), item.source_id)
                    duplicate = None if previous == item.source_id else previous
                    sources.append(item if item.duplicate_of == duplicate else item.model_copy(update={"duplicate_of": duplicate}))
        batch = SourceBatch(sources=tuple(sources), input_limited=len(ids) > MAX_SOURCES)
        return batch, [attempt for result in results for attempt in result.attempts]
