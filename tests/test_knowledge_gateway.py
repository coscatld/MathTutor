"""Actual HTTP gateway wire protocols with mock transport, not model quality."""
import json
import httpx
import pytest
from test_knowledge_workbench import state, seed, ScriptedProvider
from mathtutor.application.knowledge_tools import KnowledgeTools
from mathtutor.application.tutor_runtime import complete_tools
from mathtutor.infrastructure.generative_gateway import OpenAICompatibleProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [True, False])
async def test_http_gateway_executes_and_returns_real_receipts(state, native):
    lib, _ = await seed(state)
    scripted = ScriptedProvider(native=native, save=True)
    requests = []
    async def endpoint(request):
        payload = json.loads(request.content)
        requests.append(payload)
        result = await scripted.complete(payload["messages"])
        message = {"role":"assistant","content":result.text or None}
        if result.tool_calls:
            message["tool_calls"] = list(result.tool_calls)
        return httpx.Response(200,json={"choices":[{"message":message,"finish_reason":result.finish_reason}],
            "usage":{"prompt_tokens":100,"completion_tokens":100}})
    async def key(): return "fixture-not-a-real-key"
    provider = OpenAICompatibleProvider(base_url="https://fixture.invalid/v1",model="scripted",api_key_resolver=key,
        transport=httpx.MockTransport(endpoint))
    executor = KnowledgeTools(state,"alice","A",generation=await state.knowledge.generation("alice"),
        save_space=lib["space_id"],allow_save=True,synthesize=True)
    result = await complete_tools(provider,[{"role":"user","content":"整理并保存笔记"}],max_tokens=2200,
        temperature=0,executor=executor,structured=not native)
    assert "已保存新笔记" in result.text
    assert bool(requests[0].get("tools")) is native
    assert any(r.get("tool")=="read_source" and r.get("result",{}).get("body_hash") for r in scripted.receipts)
    assert len(await state.knowledge.list_notes("alice",lib["space_id"])) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("supported", [True, 1])
async def test_summary_entailment_uses_shared_loop_and_requires_actual_boolean(state, supported):
    from mathtutor.infrastructure.generative_gateway import CompletionResult
    await seed(state)
    class SummaryProvider(ScriptedProvider):
        checks = 0
        async def complete(self,messages,**kwargs):
            if "只做证据蕴含检查" in messages[0].get("content",""):
                self.checks += 1
                claims=json.loads(messages[1]["content"])
                return CompletionResult(text=json.dumps({"supported":[supported]*len(claims)}),provider_id="test",model="scripted",
                    finish_reason="stop",input_tokens=100,output_tokens=100)
            result=await super().complete(messages,**kwargs)
            if not result.tool_calls:
                final=json.loads(result.text)
                for claim in final["claims"]: claim["kind"]="summary"
                result=result.model_copy(update={"text":json.dumps(final,ensure_ascii=False)})
            return result
    provider=SummaryProvider()
    executor=KnowledgeTools(state,"alice","A",generation=await state.knowledge.generation("alice"))
    result=await complete_tools(provider,[{"role":"user","content":"总结资料"}],executor=executor)
    assert provider.checks >= 1
    assert result.turn_result["steps_used"]==len(provider.calls)+provider.checks
    if supported is True:
        assert result.turn_result["finish_reason"]=="FINAL_ANSWER"
        assert "AI 总结" in result.text
    else:
        assert result.turn_result["finish_reason"]=="INVALID_TOOL_SEQUENCE"
        assert "AI 总结" not in result.text


@pytest.mark.asyncio
async def test_twelve_summaries_use_one_batch_support_check(state):
    from mathtutor.infrastructure.generative_gateway import CompletionResult
    await seed(state)

    class Twelve(ScriptedProvider):
        checks = 0
        generate = 0
        retrieve = 0
        flags = None

        async def complete(self, messages, **kwargs):
            if "只做证据蕴含检查" in messages[0].get("content", ""):
                self.checks += 1
                claims = json.loads(messages[1]["content"])
                assert len(claims) == 12
                flags = self.flags if self.flags is not None else [True] * len(claims)
                return CompletionResult(
                    text=json.dumps({"supported": flags}), provider_id="test", model="scripted",
                    finish_reason="stop", input_tokens=10, output_tokens=10)
            result = await super().complete(messages, **kwargs)
            if result.tool_calls:
                self.retrieve += 1
                return result
            self.generate += 1
            final = json.loads(result.text)
            quote = final["claims"][0]
            final["claims"] = [
                {**quote, "kind": "summary", "text": f"总结要点{index}：{quote['text']}"}
                for index in range(12)
            ]
            return result.model_copy(update={"text": json.dumps(final, ensure_ascii=False)})

    provider = Twelve()
    executor = KnowledgeTools(state, "alice", "A", generation=await state.knowledge.generation("alice"))
    result = await complete_tools(provider, [{"role": "user", "content": "总结资料"}], executor=executor)
    assert provider.checks == 1 and provider.generate == 1 and provider.retrieve >= 1
    assert result.turn_result["finish_reason"] == "FINAL_ANSWER"
    assert "总结要点0" in result.text and "总结要点11" in result.text

    provider = Twelve()
    provider.flags = [True] * 11 + [False]
    executor = KnowledgeTools(state, "alice", "A", generation=await state.knowledge.generation("alice"))
    result = await complete_tools(provider, [{"role": "user", "content": "总结资料"}], executor=executor)
    assert provider.checks == 1
    assert result.turn_result["finish_reason"] == "FINAL_ANSWER"
    assert "总结要点0" in result.text and "总结要点11" not in result.text
    assert "证据不足的总结" in result.text

    provider = Twelve()
    provider.flags = [True, False]
    executor = KnowledgeTools(state, "alice", "A", generation=await state.knowledge.generation("alice"))
    result = await complete_tools(provider, [{"role": "user", "content": "总结资料"}], executor=executor)
    assert provider.checks >= 1
    assert result.turn_result["finish_reason"] == "INVALID_TOOL_SEQUENCE"


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [True, False])
async def test_tools_off_rejects_calls_without_executing(state, native):
    from mathtutor.application.tutor_runtime import current_turn
    from mathtutor.domain.turn_result import FinishReason, TutorTurnResult
    from mathtutor.infrastructure.generative_gateway import CompletionResult
    await seed(state)
    executed = []

    class LastStep(ScriptedProvider):
        async def complete(self, messages, **kwargs):
            if native:
                assert kwargs.get("tools") is None
                calls = ({"id": "x", "type": "function",
                          "function": {"name": "search_knowledge", "arguments": json.dumps({"query": "移项"})}},)
                return CompletionResult(text="伴随文字", finish_reason="stop", tool_calls=calls,
                                        provider_id="test", model="scripted", input_tokens=1, output_tokens=1)
            body = {"tool_calls": [{"id": "x", "name": "search_knowledge", "arguments": {"query": "移项"}}]}
            return CompletionResult(text=json.dumps(body, ensure_ascii=False), finish_reason="stop",
                                    provider_id="test", model="scripted", input_tokens=1, output_tokens=1)

    turn = TutorTurnResult(steps_used=6)
    token = current_turn.set(turn)
    executor = KnowledgeTools(state, "alice", "A", generation=await state.knowledge.generation("alice"))
    original = executor.execute

    async def counted(name, arguments, call_id):
        executed.append(name)
        return await original(name, arguments, call_id)
    executor.execute = counted
    try:
        result = await complete_tools(LastStep(native=native), [{"role": "user", "content": "总结"}],
                                      executor=executor, structured=not native)
    finally:
        current_turn.reset(token)
    assert executed == []
    assert result.turn_result["finish_reason"] == FinishReason.INVALID_TOOL_SEQUENCE.value
    assert result.turn_result["status"] != "COMPLETED"


@pytest.mark.asyncio
async def test_tools_off_pure_text_still_completes(state):
    from mathtutor.application.tutor_runtime import current_turn
    from mathtutor.domain.turn_result import FinishReason, TutorTurnResult
    from mathtutor.infrastructure.generative_gateway import CompletionResult
    await seed(state)
    turn = TutorTurnResult(steps_used=6)
    token = current_turn.set(turn)
    executor = KnowledgeTools(state, "alice", "A", generation=await state.knowledge.generation("alice"))
    try:
        found = await executor.execute("search_knowledge", {"query": "移项"}, "s")
        hit = found["result"]["hits"][0]
        await executor.execute("read_source", {k: hit[k] for k in ("document_id", "version", "start", "end")}, "r")
        reads = list(executor.reads.values())
        claims = [{"text": row["text"], "kind": "quote",
                   "evidence": [{"source_id": row["source_id"], "quote": row["text"]}]} for row in reads]

        class FinalOnly:
            provider_id, model, supports_native_tools = "test", "scripted", True

            async def complete(self, messages, **kwargs):
                return CompletionResult(
                    text=json.dumps({"claims": claims, "uncertainties": []}, ensure_ascii=False),
                    finish_reason="stop", provider_id="test", model="scripted",
                    input_tokens=1, output_tokens=1)

        result = await complete_tools(FinalOnly(), [{"role": "user", "content": "总结"}], executor=executor)
    finally:
        current_turn.reset(token)
    assert result.turn_result["finish_reason"] == FinishReason.FINAL_ANSWER.value
    assert result.turn_result["status"] == "COMPLETED"
