"""Exercise production chat wiring, including its default extension registry.

All HTTP is intercepted locally. These test delivery and budgets, not live
model quality, and never access a real API key or the user's database.
"""
import json

import httpx
import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application import tutor_runtime
from mathtutor.infrastructure.generative_gateway import ModelRole, OpenAICompatibleProvider
from mathtutor.infrastructure.vision import content_token_estimate
from test_tutor_p0 import client_at, send, summary


QUESTION = (r'我想问一下“若集合 $A = \{(x, y) \mid y = x^2 - 2x,\ x \in \mathbb{R}\}$，'
            r'$B = \{(x, y) \mid y = -x^2 + 2x + 6,\ x \in \mathbb{R}\}$，'
            r'则 $A \cap B =$”这道题怎么做')
GUIDANCE = '交集中的点要同时满足两个方程。令两个表达式相等，解出横坐标，再代回求纵坐标。'


def bind(transport):
    async def key():
        return 'test-key-not-real'

    state = get_product_state()
    state.gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(
        base_url='https://example.invalid/v1', model='local-fixture',
        api_key_resolver=key, transport=httpx.MockTransport(transport)))
    # Deliberately keep state.controller.chat_responder as built by ProductState.
    # Replacing it with TutorChatResponder(gateway) hides the extension budgets.
    return state


@pytest.mark.parametrize('grade', [10, 11, 12])
def test_short_intersection_question_reaches_model_and_completes(tmp_path, grade):
    calls = []

    def transport(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={
            'choices': [{'message': {'content': GUIDANCE}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50}})

    with client_at(tmp_path / 'question.db') as client, client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        state = bind(transport)
        state.learner_settings.update('high' if grade >= 10 else 'middle', grade)
        frames = send(ws, 'send_message', 'intersection', {'text': QUESTION})
        assert summary(client)['problem_context']['display_text'] == QUESTION
        assert sum(summary(client)['evidence_summary'][k]
                   for k in ('independent', 'assisted', 'post_solution')) == 0
    assert len(calls) == 1
    names = [t['function']['name'] for t in calls[0]['tools']]
    assert 'verify_math' in names and 'ext_length_convert' in names
    assert 'draw_scene' not in names
    final = next(f['payload'] for f in frames if f['event_type'] == 'assistant_complete')
    assert final['status'] == 'COMPLETED' and final['steps_used'] == 1
    assert GUIDANCE in final['final_text']
    assert not any(f['event_type'] in ('assistant_error', 'turn_error') for f in frames)


def test_drawing_still_fits_default_budget_with_production_extensions(tmp_path):
    calls = []

    def transport(request):
        body = json.loads(request.content)
        calls.append(body)
        assert sum(content_token_estimate(m.get('content', '')) + 16 for m in body['messages']) + \
            content_token_estimate(json.dumps(body['tools'], ensure_ascii=False)) + body['max_tokens'] <= 16384
        message = {'content': '看图中的曲线，横坐标确定后，纵坐标由函数关系确定。'}
        if len(calls) == 1:
            message = {'content': '', 'tool_calls': [{'id': 'drawing', 'type': 'function', 'function': {
                'name': 'draw_scene', 'arguments': json.dumps({'title': '抛物线', 'objects': [
                    {'id': 'f', 'type': 'function', 'expr': 'x^2-2x'}]})}}]}
        return httpx.Response(200, json={
            'choices': [{'message': message, 'finish_reason': 'tool_calls' if len(calls) == 1 else 'stop'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 50}})

    with client_at(tmp_path / 'draw.db') as client, client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        state = bind(transport)
        state.learner_settings.update('high', 10)
        frames = send(ws, 'send_message', 'drawing', {'text': '为什么椭圆的焦点在长轴上？配个图讲讲'})
    assert len(calls) == 2
    assert any(t['function']['name'] == 'draw_scene' for t in calls[0]['tools'])
    final = next(f['payload'] for f in frames if f['event_type'] == 'assistant_complete')
    assert '```mathtutor-scene' in final['final_text']


@pytest.mark.parametrize('failure', ['provider', 'budget'])
def test_failure_has_true_reason_no_misleading_solver_fallback(tmp_path, monkeypatch, failure, caplog):
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(503, text='private provider response test-key-not-real')

    if failure == 'budget':
        original = tutor_runtime.complete_math_tools

        async def limited(*args, **kwargs):
            tutor_runtime.current_turn.get().max_total_tokens = 1
            return await original(*args, **kwargs)

        monkeypatch.setattr(tutor_runtime, 'complete_math_tools', limited)
    with client_at(tmp_path / 'failed.db') as client, client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        bind(transport)
        frames = send(ws, 'send_message', 'failed', {'text': QUESTION})
        traces = client.get('/api/v2/math-tutor/desktop/diagnostics/turns').json()['turns']
        # Replaying an identical failed request does not call the model again.
        before = len(calls)
        send(ws, 'send_message', 'failed', {'text': QUESTION})
        assert len(calls) == before
    reason, code, notice = (('TOKEN_LIMIT', 'TUTOR_TOKEN_LIMIT', '处理长度达到上限') if failure == 'budget'
                            else ('PROVIDER_ERROR', 'MODEL_UNAVAILABLE', '模型服务暂时不可用'))
    final = next(f['payload'] for f in frames if f['event_type'] == 'assistant_error')
    assert final['status'] == 'FAILED' and final['finish_reason'] == reason
    assert final['error_code'] == code and notice in final['error']
    assert traces[0]['finish_reason'] == reason and traces[0]['error_code'] == code
    assert len(calls) == (0 if failure == 'budget' else 1)
    rendered = json.dumps(frames, ensure_ascii=False) + caplog.text
    assert 'test-key-not-real' not in rendered and 'private provider response' not in rendered
    assert '结构化求解器没有把它编成标准计算题' not in rendered
