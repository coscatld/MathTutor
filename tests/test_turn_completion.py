import asyncio
import pytest
from mathtutor.application.tutor_runtime import (
    TutorTurnResult, FinishReason, current_turn, complete_tutor, record_turn, loop_health,
)
from mathtutor.infrastructure.generative_gateway import CompletionResult


class Provider:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def result(reason='stop', text='计算结果是 391。'):
    return CompletionResult(text=text, finish_reason=reason, provider_id='fake', model='test', input_tokens=12, output_tokens=8)


async def run(provider, **limits):
    turn = TutorTurnResult(**limits)
    token = current_turn.set(turn)
    try:
        try:
            await complete_tutor(provider, [{'role': 'user', 'content': '17×23=?'}], max_tokens=512, temperature=0.4)
        except (RuntimeError, TimeoutError):
            pass
        return turn
    finally:
        current_turn.reset(token)


@pytest.mark.asyncio
async def test_natural_stop_completes_turn():
    provider = Provider(result())
    turn = await run(provider)
    assert turn.status == 'COMPLETED'
    assert turn.finish_reason == FinishReason.NATURAL_STOP
    assert len(provider.calls) == 1
    assert turn.input_tokens == 12


def test_final_answer_completes_turn():
    turn = TutorTurnResult()
    turn.stop(FinishReason.FINAL_ANSWER, '391')
    assert turn.status == 'COMPLETED'


@pytest.mark.asyncio
async def test_grace_call_before_step_cap():
    provider = Provider(result('length', '先把23拆成'), result('stop', '20+3。'))
    turn = await run(provider)
    assert turn.grace_call_used and turn.steps_used == 2
    assert '先把23拆成' in turn.final_text and turn.final_text.endswith('20+3。')
    assert '续写接缝待核对' in turn.final_text
    assert '最后一次' in provider.calls[1][0][-1]['content']
    assert turn.status == 'PARTIAL'
    assert turn.input_tokens == 24


@pytest.mark.asyncio
async def test_token_limit_returns_partial():
    turn = await run(Provider(result('length'), result('length')))
    assert turn.partial and turn.finish_reason == FinishReason.TOKEN_LIMIT


@pytest.mark.asyncio
async def test_provider_length_not_treated_as_stop():
    turn = await run(Provider(result('length')), max_steps=1)
    assert turn.partial


@pytest.mark.asyncio
async def test_stream_interruption_returns_partial():
    turn = await run(Provider(result('')))
    assert turn.partial and turn.finish_reason == FinishReason.STREAM_INTERRUPTED


@pytest.mark.asyncio
async def test_provider_error_preserves_partial():
    turn = await run(Provider(result('length', '部分'), RuntimeError('unavailable')))
    assert turn.final_text == '部分' and turn.partial
    assert turn.finish_reason == FinishReason.PROVIDER_ERROR


@pytest.mark.asyncio
async def test_timeout_is_distinct():
    turn = await run(Provider(TimeoutError()))
    assert turn.status == 'FAILED' and turn.finish_reason == FinishReason.TIMEOUT


@pytest.mark.asyncio
async def test_budget_blocks_call():
    provider = Provider(result())
    turn = await run(provider, max_total_tokens=1)
    assert not provider.calls and turn.finish_reason == FinishReason.TOKEN_LIMIT


@pytest.mark.asyncio
async def test_tool_call_cannot_execute_in_expression_only_runtime():
    provider = Provider(result('tool_calls'))
    turn = await run(provider)
    assert turn.finish_reason == FinishReason.INVALID_TOOL_SEQUENCE
    assert len(provider.calls) == 1


def test_step_cap_returns_partial():
    turn = TutorTurnResult()
    turn.stop(FinishReason.STEP_CAP, 'partial')
    record_turn(turn)
    assert turn.partial
    assert loop_health()['loop_step_cap_hit_total'] >= 1


@pytest.mark.asyncio
async def test_partial_persistence():
    from mathtutor.repositories.conversation_repository import InMemoryConversationRepository
    repo = InMemoryConversationRepository()
    await repo.append_message('s', 'c', role='tutor', content='部分', status='PARTIAL', finish_reason='TOKEN_LIMIT', turn_id='t')
    message = (await repo.messages('s', 'c'))[0]
    assert message['status'] == 'PARTIAL' and message['turn_id'] == 't'


def test_partial_message_can_continue(tmp_path):
    import json
    from fastapi.testclient import TestClient
    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import reset_product_state, get_product_state
    from mathtutor.security.settings import MathTutorSecuritySettings
    from mathtutor.infrastructure.generative_gateway import ModelRole
    reset_product_state()
    app = create_math_tutor_app(MathTutorSecuritySettings(environment='development', host='127.0.0.1'), auth_enabled=False, db_path=str(tmp_path / 'turn.db'))
    provider = Provider(result('length', '第一部分。'), result('length', '第二部分。'), result('stop', '接下来的结论。'))
    provider.model = 'test'
    provider.provider_id = 'fake'
    def collect(ws):
        frames = []
        while True:
            frame = ws.receive_json()
            frames.append(frame)
            if frame['event_type'] == 'turn_end':
                return frames
    with TestClient(app) as client:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        with client.websocket_connect('/api/v2/math-tutor/ws') as ws:
            ws.send_json({'command': 'send_message', 'payload': {'text': '你好'}, 'session_id': 'c'})
            first = collect(ws)
            assert first[0]['event_type'] == 'assistant_start'
            assert first[-2]['event_type'] == 'assistant_partial'
            rows = client.get('/api/v2/math-tutor/sessions/c').json()['messages']
            assert rows[-1]['status'] == 'PARTIAL'
            assert rows[-1]['content'] == '第一部分。\n\n第二部分。'
            ws.send_json({'command': 'send_message', 'payload': {'text': '继续'}, 'session_id': 'c'})
            second = collect(ws)
            assert second[-2]['event_type'] == 'assistant_complete'
            assert second[-2]['payload']['final_text'].strip() == '接下来的结论。'
            assert any(m['content'] == '第一部分。\n\n第二部分。' for m in provider.calls[-1][0])
    reset_product_state()


def test_user_cancel_during_provider_call(tmp_path):
    from fastapi.testclient import TestClient
    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import reset_product_state, get_product_state
    from mathtutor.security.settings import MathTutorSecuritySettings
    from mathtutor.infrastructure.generative_gateway import ModelRole
    import threading
    started = threading.Event()
    class Slow:
        provider_id = 'slow'
        model = 'fake'
        async def complete(self, *args, **kwargs):
            started.set()
            await asyncio.sleep(30)
    reset_product_state()
    app = create_math_tutor_app(MathTutorSecuritySettings(environment='development', host='127.0.0.1'), auth_enabled=False, db_path=str(tmp_path / 'cancel.db'))
    with TestClient(app) as client:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, Slow())
        with client.websocket_connect('/api/v2/math-tutor/ws') as ws:
            ws.send_json({'command': 'send_message', 'payload': {'text': '你好'}, 'session_id': 'c'})
            assert ws.receive_json()['event_type'] == 'assistant_start'
            assert started.wait(3)
            ws.send_json({'command': 'cancel_turn', 'payload': {}, 'session_id': 'c'})
            terminal = ws.receive_json()
            assert terminal['event_type'] == 'assistant_error'
            assert terminal['payload']['status'] == 'CANCELLED'
            assert terminal['payload']['finish_reason'] == 'USER_CANCELLED'
            assert ws.receive_json()['event_type'] == 'turn_end'
    reset_product_state()


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['stop', 'length'])
async def test_provider_stop_reason_preserved(reason):
    import httpx
    from mathtutor.infrastructure.generative_gateway import OpenAICompatibleProvider
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={
        'choices': [{'message': {'content': '答案'}, 'finish_reason': reason}],
        'usage': {'prompt_tokens': 30, 'completion_tokens': 10},
    }))
    async def resolve_key():
        return 'test'
    provider = OpenAICompatibleProvider(provider_id='fake', base_url='https://example.test/v1',
        model='fake', api_key_resolver=resolve_key, transport=transport)
    completion = await provider.complete([{'role': 'user', 'content': '题目'}])
    assert completion.finish_reason == reason
    assert completion.input_tokens == 30 and completion.output_tokens == 10


@pytest.mark.asyncio
async def test_exhausted_step_budget_retains_text_without_call():
    turn = TutorTurnResult(steps_used=2, final_text='已有的可靠输出')
    token = current_turn.set(turn)
    provider = Provider()
    try:
        with pytest.raises(RuntimeError):
            await complete_tutor(provider, [], max_tokens=512, temperature=0.4)
        assert turn.partial and turn.finish_reason == FinishReason.STEP_CAP
        assert turn.final_text == '已有的可靠输出' and not provider.calls
    finally:
        current_turn.reset(token)
