"""Anonymous, bounded public-math retrieval. Queries never include learner records."""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict

from mathtutor.application.exploration_evidence import Attribution, SourceBatch, public_snapshot

Project = Literal["wikipedia", "wikibooks"]
Locale = Literal["zh", "en"]


class RetrievalAttempt(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider: Project
    language: Locale
    status: Literal["found", "empty", "unavailable", "rate_limited"]
    count: int = 0


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
def included_readings(question: str, stamp: str):
    editions = (
        (("连续函数", "函数连续", "可导", "不可微", "continuous function", "function be continuous", "differentiab"), "active_calculus",
         "Active Calculus · 1.7 Limits, continuity, and differentiability", "Matthew Boelkins",
         "2nd ed. (2025), §1.7.4", "https://activecalculus.org/single/sec-1-7-lim-cont-diff.html",
         "A function can be continuous at a point, but not be differentiable there."),
        (("鸽巢", "抽屉原理", "pigeonhole", "pigeon hole"), "open_math_books",
         "Discrete Mathematics: An Open Introduction · 3.2 Proofs", "Oscar Levin",
         "3rd ed., §3.2", "https://discrete.openmathbooks.org/dmoi3/sec_logic-proofs.html",
         "If more than n pigeons fly into n pigeon holes, then at least one pigeon hole will contain at least two pigeons."),
    )
    return [public_snapshot(provider=provider, content_id=url, content_type="open_textbook", title=title,
                author=author, url=url, text=quote, scope="textbook_excerpt", retrieved_at=stamp,
                attribution=Attribution(language="en", version=edition), request_id="bundled-edition")
            for aliases, provider, title, author, edition, url, quote in editions
            if any(alias in question.casefold() for alias in aliases)]


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


class OpenReadingSearch:
    def __init__(self, *, transport=None):
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

    async def _edition(self, client, project, language, query, stamp):
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

    async def _project(self, client, project, queries, stamp):
        attempts = []
        for language, query in queries:
            try:
                async with asyncio.timeout(9):
                    sources = await self._edition(client, project, language, query, stamp)
                status = "found" if sources else "empty"
            except (_Unavailable, httpx.HTTPError, TimeoutError, ValueError, AttributeError, TypeError) as error:
                status = error.status if isinstance(error, _Unavailable) else "unavailable"
                sources = []
            attempts.append(RetrievalAttempt(provider=project, language=language, status=status, count=len(sources)))
            if sources:
                return sources, attempts
        return [], attempts

    async def search(self, question: str, language: Locale):
        stamp = datetime.now(UTC).isoformat()
        queries = _queries(question, language)
        async with httpx.AsyncClient(transport=self.transport, timeout=5, follow_redirects=False,
                headers={"User-Agent": "MathTutor/1.0 (https://github.com/coscatld/MathTutor)",
                         "Accept": "application/json"}) as client:
            results = await asyncio.gather(*(self._project(client, project, queries, stamp)
                                             for project in ("wikipedia", "wikibooks")))
        # Alternate projects so the two first cards offer different reading contexts.
        first, second = (item[0] for item in results)
        sources = [group[i] for i in range(max(len(first), len(second))) for group in (first, second) if i < len(group)]
        sources.extend(included_readings(question, stamp))
        seen = {}
        for index, item in enumerate(sources):
            previous = seen.setdefault(" ".join(item.text.split()), item.source_id)
            if previous != item.source_id:
                sources[index] = item.model_copy(update={"duplicate_of": previous})
        return SourceBatch(sources=tuple(sources)), [attempt for _, attempts in results for attempt in attempts]
