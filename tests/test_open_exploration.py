"""Public readings, licensed offline fallback, and private owner-local retrieval."""
import json
import sqlite3
from contextlib import closing
from uuid import uuid4

import httpx
import pytest
from test_document_pipeline import _build_simple_pdf
from test_exploration_api import BASE, PREFIX, body, install
from test_phase5_e2e_offer_flow import _client

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state, reset_product_state
from mathtutor.application.exploration_evidence import safe_source_url
from mathtutor.application.open_readings import OpenReadingSearch
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope


@pytest.fixture(autouse=True)
def reset_state():
    reset_product_state()
    yield
    reset_product_state()


def article(request):
    assert request.method == "GET" and "Authorization" not in request.headers
    assert request.url.host in {"zh.wikipedia.org", "en.wikipedia.org", "zh.wikibooks.org", "en.wikibooks.org"}
    params = request.url.params
    if params["action"] == "parse":
        text = '<p>The paragraph retains the formula <math alttext="x^2"><mi>x</mi></math> under its original conditions.</p>'
        return httpx.Response(200, json={"parse": {"text": text}})
    assert params["gsrnamespace"] == "0"
    book = "wikibooks" in request.url.host
    return httpx.Response(200, json={"batchcomplete": True, "query": {"pages": [
        {"pageid": 17 if book else 13, "lastrevid": 102 if book else 101, "index": 1,
         "title": "Calculus/Derivatives" if book else "Derivative", "snippet": "An <span>example</span> &amp; an equation."}
    ]}})


def forbid(*args, **kwargs):
    pytest.fail("This source or secret store must not be contacted for this action.")


def test_default_entry_retrieves_both_projects_without_credentials_or_forwarding(tmp_path):
    with _client(tmp_path / "open.db") as client:
        service = get_product_state().exploration
        service.client.configuration = service.client.propose = service.client.search = forbid
        calls = []

        def transport(request):
            calls.append((request.url.host, request.url.params["action"]))
            assert "private learner" not in str(request.url)
            return article(request)

        service.open_search = OpenReadingSearch(transport=httpx.MockTransport(transport))
        data = {"inquiry_id": str(uuid4()), "generation": 0, "question": "Can a function be continuous but not differentiable?", "language": "en"}
        resp = client.post(PREFIX + "/inquiries", json=data)
        assert resp.status_code == 200, resp.text
        view = resp.json()
        assert {card["provider"] for card in view["evidence"]["cards"]} == {"wikipedia", "active_calculus"}
        # Identical mocked wiki paragraphs count once, while both attributions remain in the registry.
        sources = view["evidence"]["sources"]
        assert {s["provider"] for s in sources} == {"wikipedia", "wikibooks", "active_calculus"}
        assert all(s["attribution"]["license"] == "CC BY-SA 4.0" for s in sources)
        assert "x^2" in sources[0]["text"] and "<mi>" not in sources[0]["text"]
        assert sources[0]["original_url"] == "https://en.wikipedia.org/w/index.php?oldid=101"
        assert view["mode"] == "open" and [a["status"] for a in view["retrieval_attempts"]] == ["found", "found"]
        path = PREFIX + "/inquiries/" + data["inquiry_id"]
        assert client.get(path).json()["evidence"]["sources"] == sources
        assert client.post(PREFIX + "/inquiries", json=data).json() == view and len(calls) == 4
        assert client.post(path + "/organize", json={"revision": 1}).status_code == 409
        assert client.get(path).json()["organization_attempts"] == 0
        assert client.post(PREFIX + "/inquiries", json={**data, "mode": "zhihu"}).status_code == 409


@pytest.mark.asyncio
async def test_chinese_fallback_keeps_partial_network_receipts_and_does_not_follow_redirects():
    def partial(request):
        if request.url.host == "zh.wikipedia.org":
            return httpx.Response(429, headers={"Retry-After": "90"})
        if "wikibooks" in request.url.host:
            return httpx.Response(302, headers={"Location": "https://other.invalid/secret"})
        return article(request)

    search = OpenReadingSearch(transport=httpx.MockTransport(partial))
    sources, attempts = await search.search("为什么函数连续不一定可导？", "zh")
    assert [(a.provider, a.language, a.status) for a in attempts] == [
        ("wikipedia", "zh", "rate_limited"), ("wikipedia", "en", "found"),
        ("wikibooks", "zh", "unavailable"), ("wikibooks", "en", "unavailable")]
    assert {s.provider for s in sources.sources} == {"wikipedia", "active_calculus"}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,status", [({"batchcomplete": True}, "empty"), ({"wrong": 1}, "unavailable"),
                                             ({"error": {"code": "maxlag"}}, "rate_limited")])
async def test_no_hits_and_failed_sources_do_not_create_unrelated_textbooks(payload, status):
    search = OpenReadingSearch(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    none, attempts = await search.search("unrelated occultation catalogue", "en")
    assert not none.sources
    assert [a.status for a in attempts] == [status, status]
    relevant, _ = await search.search("Pigeonhole principle", "en")
    assert len(relevant.sources) == 1 and relevant.sources[0].scope == "textbook_excerpt"
    assert relevant.sources[0].provider == "open_math_books" and relevant.sources[0].author == "Oscar Levin"


@pytest.mark.parametrize(("url","provider","allowed"), [
    ("https://en.wikipedia.org/w/index.php?oldid=42", "wikipedia", True),
    ("https://en.wikipedia.org/w/index.php?oldid=42", "wikibooks", False),
    ("https://en.wikipedia.org/w/index.php?oldid=42&returnto=foo", "wikipedia", False),
    ("https://user@zh.wikibooks.org/w/index.php?oldid=3", "wikibooks", False),
    ("https://en.wikipedia.org.evil.invalid/w/index.php?oldid=42", "wikipedia", False),
    ("https://activecalculus.org/single/sec-1-7-lim-cont-diff.html", "active_calculus", True),
    ("https://activecalculus.org/other", "active_calculus", False),
])
def test_provider_link_boundaries(url, provider, allowed):
    assert bool(safe_source_url(url, provider)) is allowed


def test_premigration_zhihu_record_replays_and_organizes_without_source_selection(tmp_path):
    path = tmp_path / "legacy.db"
    old = body()
    with _client(path) as client:
        install(client)
        assert client.post(PREFIX + "/inquiries", json=old).status_code == 200
    # The saved payload simulates the schema that shipped before open readings.
    with closing(sqlite3.connect(path)) as conn:
        saved = json.loads(conn.execute("SELECT payload FROM exploration_inquiries").fetchone()[0])
        for key in ("mode", "retrieval_attempts"):
            saved.pop(key)
        for source in saved["evidence"]["sources"]:
            source.pop("attribution")
        for card in saved["evidence"]["cards"]:
            card.pop("provider")
            card.pop("attribution")
        conn.execute("UPDATE exploration_inquiries SET payload=?", (json.dumps(saved),))
        conn.commit()
    reset_product_state()
    with _client(path) as client:
        calls = install(client)
        get_product_state().exploration.open_search.search = forbid
        old.pop("mode")
        restored = client.post(PREFIX + "/inquiries", json=old).json()
        assert restored["mode"] == "zhihu" and not calls
        organized = client.post(PREFIX + "/inquiries/" + old["inquiry_id"] + "/organize", json={"revision": 1})
        assert organized.status_code == 200
        assert organized.json()["ai_status"] == "ready" and len(calls) == 1


def test_local_pdf_is_read_from_page_obeys_owner_and_toggle_and_stays_off_network(tmp_path):
    with _client(tmp_path / "library.db") as client:
        service = get_product_state().exploration
        service.open_search.search = service.client.search = service.client.propose = forbid
        document = _build_simple_pdf(["Preface for a locally stored handout.", "Private ellipticcurve example with parameter 973."])
        loaded = client.post(BASE + "/documents/import", files={"file": ("math-handout.pdf", document, "application/pdf")})
        assert loaded.status_code == 200, loaded.text
        doc_id = loaded.json()["document_id"]

        def query():
            response = client.post(PREFIX + "/library", json={"question": "ellipticcurve"})
            assert response.status_code == 200, response.text
            return response.json()

        found = query()
        assert len(found) == 1 and found[0]["document_id"] == doc_id
        assert found[0]["page"] <= 2 <= (found[0]["page_end"] or found[0]["page"])
        assert found[0]["filename"] == "math-handout.pdf" and "973" in found[0]["text"]
        assert not client.get(PREFIX + "/inquiries").json()["items"]
        client.app.dependency_overrides[require_student_owner] = lambda: StudentOwnerScope(
            principal=PrincipalScope(user_id="bob", username="bob", role="student"), student_id="bob")
        assert query() == []
        client.app.dependency_overrides.clear()
        assert client.patch(BASE + f"/documents/{doc_id}/retrieval", json={"enabled": False}).status_code == 200
        assert query() == []
        assert client.patch(BASE + f"/documents/{doc_id}/retrieval", json={"enabled": True}).status_code == 200
        assert query() == found
        assert client.delete(BASE + f"/documents/{doc_id}").status_code in (200, 204)
        assert query() == []
