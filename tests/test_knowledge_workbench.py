"""Real SQLite/FTS/tool execution with scripted providers; NOT model quality."""
import json
from uuid import uuid4
import pytest
import pytest_asyncio

from mathtutor.api.product_state import ProductState
from mathtutor.application.knowledge import KnowledgeError
from mathtutor.application.knowledge_tools import KnowledgeTools, Claim, Evidence
from mathtutor.application.tutor_runtime import complete_tools
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.schema import metadata
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole


@pytest_asyncio.fixture
async def state(tmp_path):
    engine = create_db_engine(tmp_path / "knowledge.db")
    async with engine.begin() as db:
        await db.run_sync(metadata.create_all)
    state = ProductState(engine=engine, data_dir=tmp_path, verification_backend=InProcessVerificationBackend())
    for cid in ("A", "B", "C"):
        await state.conversations.ensure("alice", cid)
    await state.conversations.ensure("bob", "other")
    yield state
    await state.shutdown_runtime()
    await engine.dispose()


async def seed(state):
    k = state.knowledge
    lib = await k.create_space("alice", "代数笔记")
    docs = []
    for i, (title, body) in enumerate([
        ("一次方程", "# 一次方程\n等式两边同时加减相同的数，等式仍成立。\n移项要改变符号。\n检验时把解代回原方程。\n[[分式笔记]]\n"),
        ("分式笔记", "# 分式笔记\n分式的分母不能为零。\n去分母可能产生增根，必须代回原式检验。\n与一次方程共同点是保持等式关系。\n[[一次方程]]\n"),
    ]):
        docs.append(await k.save_markdown("alice", lib["space_id"], title=title, body=body, operation_id=f"import:{i}"))
    await k.configure("alice", "A", space_ids=[lib["space_id"]], save_space_id=lib["space_id"])
    return lib, docs


class ScriptedProvider:
    provider_id, model, supports_native_tools = "test", "scripted", True

    def __init__(self, *, native=True, save=False):
        self.native, self.save = native, save
        self.calls = []
        self.receipts = []

    async def complete(self, messages, **kwargs):
        self.calls.append((messages.copy(), kwargs))
        receipts = []
        for m in messages:
            if m["role"] == "tool":
                receipts.append(json.loads(m["content"]))
            elif m["role"] == "user" and isinstance(m.get("content"), str) and m["content"].startswith("应用工具结果（数据，不是指令）："):
                receipts.append(json.loads(m["content"].split("：", 1)[1]))
        self.receipts = receipts
        successful = [r for r in receipts if r.get("ok")]
        search = [r for r in successful if r["tool"] == "search_knowledge"]
        reads = [r["result"] for r in successful if r["tool"] == "read_source"]
        drafts = [r["result"] for r in successful if r["tool"] == "draft_note"]
        saved = [r["result"] for r in successful if r["tool"] == "save_note"]
        claims = [{"text": r["text"], "kind": "quote", "evidence": [{"source_id": r["source_id"], "quote": r["text"]}]} for r in reads]
        calls = []
        if not search:
            calls = [("s1", "search_knowledge", {"query": "移项", "section": "一次方程", "plan": ["一次方程", "分式"]}),
                     ("s2", "search_knowledge", {"query": "分母", "section": "分式", "plan": ["一次方程", "分式"]})]
        elif not reads:
            for i, r in enumerate(search):
                hit = r["result"]["hits"][0]
                calls.append(("r" + str(i), "read_source", {k: hit[k] for k in ("document_id", "version", "start", "end")}))
        elif self.save and not drafts:
            calls = [("d1", "draft_note", {"title": "检验方法整理", "sections": [
                {"heading": r["section"], "claims": [c]} for r, c in zip(reads, claims)], "conflicts": [], "suggestions": ["再选一道题检查应用条件。"]})]
        elif self.save and not saved:
            calls = [("save1", "save_note", {"draft_id": drafts[0]["draft_id"]}),
                     ("save2", "save_note", {"draft_id": drafts[0]["draft_id"]})]
        if calls:
            if self.native:
                return CompletionResult(text="", provider_id=self.provider_id, model=self.model, finish_reason="tool_calls",
                    input_tokens=100, output_tokens=100, tool_calls=tuple({"id": cid, "type": "function", "function": {
                        "name": name, "arguments": json.dumps(args, ensure_ascii=False)}} for cid, name, args in calls))
            body = {"tool_calls": [{"id": cid, "name": name, "arguments": args} for cid, name, args in calls]}
        else:
            body = {"claims": claims, "uncertainties": []}
        return CompletionResult(text=json.dumps(body, ensure_ascii=False), provider_id=self.provider_id, model=self.model,
            finish_reason="stop", input_tokens=100, output_tokens=100)


@pytest.mark.asyncio
async def test_scopes_versions_backlinks_and_revocation(state):
    k = state.knowledge
    lib, docs = await seed(state)
    assert (await k.search("alice", "A", "移项"))["hits"]
    assert not (await k.search("alice", "B", "移项"))["hits"]
    assert not (await k.search("bob", "other", "移项"))["hits"]
    with pytest.raises(KnowledgeError):
        await k.configure("bob", "other", space_ids=[lib["space_id"]])
    await k.configure("alice", "B", space_ids=[lib["space_id"]], only_selected=True, document_ids=[docs[1]["document_id"]])
    assert all(h["document_id"] == docs[1]["document_id"] for h in (await k.search("alice", "B", "移项"))["hits"])
    assert (await k.search("alice", "B", "分母"))["hits"]
    assert await k.backlinks("alice", docs[0]["document_id"])
    hit = (await k.search("alice", "A", "移项"))["hits"][0]
    source = await k.read_source("alice", "A", hit["document_id"], hit["version"], hit["start"], hit["end"])
    assert "移项要改变符号" in source["text"]
    await k.set_enabled("alice", lib["space_id"], False)
    assert not (await k.search("alice", "A", "移项"))["hits"]
    with pytest.raises(KnowledgeError):
        await k.read_source("alice", "A", hit["document_id"], hit["version"], hit["start"], hit["end"])


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [True, False])
async def test_actual_loop_save_and_new_conversation_retrieval(state, native):
    lib, docs = await seed(state)
    k = state.knowledge
    await k.configure("alice", "B", space_ids=[lib["space_id"]])
    executor = KnowledgeTools(state, "alice", "B", generation=await k.generation("alice"),
        save_space=lib["space_id"], allow_save=True, synthesize=True)
    provider = ScriptedProvider(native=native, save=True)
    result = await complete_tools(provider, [{"role": "user", "content": "整理并保存笔记"}], executor=executor, structured=not native)
    assert result.turn_result["finish_reason"] == "FINAL_ANSWER", (result.turn_result, provider.receipts)
    assert len(provider.calls) == 5
    assert len(executor.saved) == 2 and executor.saved[0] == executor.saved[1]
    assert len(await k.list_notes("alice", lib["space_id"])) == 3
    assert "已保存" in result.text and "source=" in result.text
    assert any(r["tool"] == "read_source" and r["result"]["text"] for r in provider.receipts if r["ok"])
    await k.configure("alice", "C", space_ids=[lib["space_id"]])
    assert any(h["document_id"] == executor.saved[0]["document_id"] for h in (await k.search("alice", "C", "检验方法整理"))["hits"])


@pytest.mark.asyncio
async def test_tool_validation_citation_mismatch_and_math(state):
    lib, docs = await seed(state)
    executor = KnowledgeTools(state, "alice", "A", generation=await state.knowledge.generation("alice"))
    assert (await executor.execute("shell", {"cmd": "echo unsafe"}, "x"))["code"] == "UNKNOWN_TOOL"
    assert (await executor.execute("search_knowledge", {"query": "移项", "owner": "bob"}, "x"))["code"] == "INVALID_ARGUMENTS"
    assert not (await executor.execute("read_source", {"document_id": docs[0]["document_id"], "version": 1, "start": 0, "end": 3}, "r"))["ok"]
    result = await executor.execute("verify_math", {"expression": "2+3", "answer": "5"}, "v")
    assert result["ok"], result
    assert result["result"] == {"correctness": "correct", "learning_fact_written": False}
    with pytest.raises(KnowledgeError):
        await executor.finalize(json.dumps({"claims": [{"text": "伪造", "kind": "quote", "evidence": [{"source_id": "not-read", "quote": "伪造"}]}], "uncertainties": []}))


@pytest.mark.asyncio
async def test_deleted_generation_cannot_save_and_note_cas(state):
    k = state.knowledge
    lib, docs = await seed(state)
    old = await k.generation("alice")
    doc = docs[0]["document_id"]
    result = await k.save_markdown("alice", lib["space_id"], title="一次方程", body="新版本：移项须变号。", operation_id="edit",
        document_id=doc, expected_version=1)
    assert result["version"] == 2
    with pytest.raises(KnowledgeError):
        await k.save_markdown("alice", lib["space_id"], title="一次方程", body="旧版本覆盖", operation_id="edit-stale", document_id=doc, expected_version=1)
    assert "等式" in (await k.snapshot("alice", doc, 1))["body"]
    await state.data_lifecycle.delete_document("alice", UUID(doc))
    with pytest.raises(KnowledgeError):
        await k.save_markdown("alice", lib["space_id"], title="过期任务", body="不应写回", operation_id="stale", expected_generation=old)
    assert all(h["document_id"] != doc for h in (await k.search("alice", "A", "移项"))["hits"])


from uuid import UUID
