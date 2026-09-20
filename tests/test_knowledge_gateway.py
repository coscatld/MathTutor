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
