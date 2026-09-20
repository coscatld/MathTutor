"""Appendix B scenarios: real SQLite and HTTP/WS; scripted generation is protocol-only."""
import importlib.util
import json
from uuid import UUID

import pytest
from sqlalchemy import select
from test_knowledge_workbench import state, seed, ScriptedProvider
from test_tutor_p0 import client_at, send
from test_image_attachments import bind
from test_pdf_classification import _pdf_with_pages
from mathtutor.api.product_state import get_product_state
from mathtutor.application.knowledge_tools import KnowledgeTools
from mathtutor.application.knowledge import KnowledgeError
from mathtutor.application.tutor_runtime import complete_tools
from mathtutor.domain.evidence import EvidencePack
from mathtutor.infrastructure.knowledge_schema import receipts

PREFIX = '/api/v2/math-tutor/desktop'
FACT = 'Quadratic formula x = (-b + sqrt(b^2 - 4ac)) / 2a'


def test_e2e1_pdf_tutor_shared_orchestrator(tmp_path, monkeypatch):
    calls, packs = [], []
    with client_at(tmp_path / 'pdf.db') as client:
        response = client.post(PREFIX + '/documents/import?conversation_id=p0',
            files={'file': ('formula.pdf', _pdf_with_pages([FACT]), 'application/pdf')})
        assert response.status_code == 200, response.text
        assert response.json()['status'] in ('ready', 'ready_with_warnings')
        product = get_product_state()
        original = product.retrieval_orchestrator.retrieve_for_turn
        async def observe(*args, **kwargs):
            pack = await original(*args, **kwargs)
            packs.append(pack)
            return pack
        monkeypatch.setattr(product.retrieval_orchestrator, 'retrieve_for_turn', observe)
        bind(calls)
        with client.websocket_connect('/api/v2/math-tutor/ws') as ws:
            frames = send(ws, 'send_message', 'pdf-e2e', {'text': '请解释资料里的 Quadratic formula'})
        assert any(f['event_type'] == 'assistant_complete' for f in frames)
        assert packs and all(isinstance(p, EvidencePack) for p in packs)
        assert any(p.evidences for p in packs)
        assert 'Quadratic formula' in json.dumps(calls, ensure_ascii=False)


def test_e2e2_conversation_isolation(tmp_path):
    calls = []
    with client_at(tmp_path / 'isolation.db') as client:
        response = client.post(PREFIX + '/documents/import?conversation_id=A',
            files={'file': ('formula.pdf', _pdf_with_pages([FACT]), 'application/pdf')})
        assert response.status_code == 200
        bind(calls)
        with client.websocket_connect('/api/v2/math-tutor/ws') as ws:
            send(ws, 'send_message', 'isolated', {'text': '请解释资料中的 Quadratic formula'}, session='B')
        assert FACT not in json.dumps(calls, ensure_ascii=False)
        assert client.get(PREFIX + '/conversations/B/resources').json()['documents'] == []


async def initial_tools(product, query='移项'):
    await seed(product)
    scope = await product.knowledge.scope('alice', 'A')
    pack = await product.retrieval_orchestrator.retrieve_for_turn('alice', scope, query)
    tools = KnowledgeTools(product, 'alice', 'A', generation=await product.knowledge.generation('alice'))
    await tools.seed_evidence(pack)
    return pack, tools


@pytest.mark.asyncio
async def test_e2e3_initial_evidence_citation_without_search(state):
    pack, tools = await initial_tools(state)
    assert pack.evidences and tools.search_hits
    key = next(iter(tools.search_hits))
    read = await tools.execute('read_source', dict(zip(('document_id', 'version', 'start', 'end'), key)), 'initial-read')
    assert read['ok']
    source = read['result']
    result = await tools.finalize(json.dumps({'claims': [{'text': source['text'], 'kind': 'quote',
        'evidence': [{'source_id': source['source_id'], 'quote': source['text']}]}], 'uncertainties': []}))
    assert 'source=' in result
    assert all(r['tool'] != 'search_knowledge' for r in tools.receipts)


@pytest.mark.asyncio
async def test_e2e4_second_retrieval_hops_and_rate(state):
    pack, tools = await initial_tools(state, 'unmatchedquasarxyz')
    assert not pack.evidences and pack.execution.retrieval_ran
    result = await complete_tools(ScriptedProvider(), [{'role': 'user', 'content': '移项与分母检验'}], executor=tools)
    state.metrics.end_retrieval_turn()
    assert result.turn_result['finish_reason'] == 'FINAL_ANSWER'
    assert any(r['tool'] == 'read_source' and r['ok'] for r in tools.receipts)
    assert tools.retrieval_execution.hop_count == 3
    assert [hop.kind for hop in tools.retrieval_execution.hops] == ['INITIAL', 'AGENT_SEARCH', 'AGENT_SEARCH']
    assert state.metrics.rag()['second_retrieval_rate'] == 1


@pytest.mark.asyncio
async def test_e2e5_no_embedding_real_baseline(state):
    assert importlib.util.find_spec('sentence_transformers') is None
    pack, _ = await initial_tools(state)
    assert pack.evidences
    assert pack.execution.mode == 'lexical'
    assert pack.execution.reranker_used
    assert pack.execution.context_ms is not None
    assert state.retrieval_orchestrator._expander is not None


def test_e2e6_no_text_pdf_needs_ocr(tmp_path):
    with client_at(tmp_path / 'empty-pdf.db') as client:
        response = client.post(PREFIX + '/documents/import?conversation_id=p0',
            files={'file': ('empty.pdf', _pdf_with_pages(['']), 'application/pdf')})
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'needs_ocr'


@pytest.mark.asyncio
async def test_e2e7_disable_then_delete_receipt(state):
    _, tools = await initial_tools(state)
    key = next(iter(tools.search_hits))
    read = await tools.execute('read_source', dict(zip(('document_id', 'version', 'start', 'end'), key)), 'read')
    assert read['ok']
    source = read['result']
    did = UUID(source['document_id'])
    await state.document_repository.set_retrieval_enabled('alice', did, False)
    scope = await state.knowledge.scope('alice', 'A')
    pack = await state.retrieval_orchestrator.retrieve_for_turn('alice', scope, '移项')
    assert all(e.document_id != did for e in pack.evidences)
    again = await state.knowledge.read_citation_receipt('alice', 'A', source['receipt_id'], source['start'], source['end'])
    assert again['text'] == source['text']
    assert await state.data_lifecycle.delete_document('alice', did)
    async with state.knowledge.engine.connect() as connection:
        assert not (await connection.execute(select(receipts.c.receipt_id).where(receipts.c.receipt_id == source['receipt_id']))).all()
    with pytest.raises(KnowledgeError):
        await state.knowledge.read_citation_receipt('alice', 'A', source['receipt_id'], source['start'], source['end'])


@pytest.mark.asyncio
async def test_e2e8_unset_scope_fails_closed(state, monkeypatch):
    from mathtutor.application.conversation_scope import current_document_scope
    assert current_document_scope() is None
    async def forbidden(*args, **kwargs):
        pytest.fail('UNSET scope reached owner-wide retrieval')
    monkeypatch.setattr(state.document_index, 'search', forbidden)
    with pytest.raises(TypeError):
        await state.retrieval_orchestrator.retrieve_for_turn('alice', user_query='移项')
    assert await state.controller.chat_documents.build('alice', '移项') is None
