"""High-school follow-ups keep the pasted question across WS turns/restarts."""
import asyncio
import json
import pytest
from mathtutor.api.product_state import get_product_state
from mathtutor.application.math_claims import certify
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole
from test_tutor_p0 import client_at, send, summary

QUESTION = r'函数 \(f(x)=2^x-2/x-a\) 的一个零点在 (1,2) 内，实数a的范围是____。'


@pytest.mark.parametrize('text', [
    r'端点值为 \(g(1)=0\)，\(g(2)=3\)。',
    r'第一支定义域 \(x\le1\)，第二支 \(x>1\)。',
    r'考察端点 \(x=1\)、\(x=2\)。',
    r'奇函数有 \(f(0)=0\)。',
    r'分段函数第二支要求 $x>1$。候选根为 $x=1/2$，不符合定义域 $x>1$。所以原函数只有零点 $x=0$。',
])
def test_distinct_conditions_and_function_values_are_not_false_equivalence(text):
    result=asyncio.run(certify(text,InProcessVerificationBackend()))
    assert not result.refuted
    assert result.unchecked>0
    if 'f(0)' in text:
        assert result.verified==0


def test_real_wrong_computation_and_missing_root_still_fail():
    backend=InProcessVerificationBackend()
    assert asyncio.run(certify('$3+4=8$',backend)).refuted
    assert asyncio.run(certify('所以 $x=2$。',backend,anchor=('quadratic','x^2-5x+6=0'))).refuted


class DiscussionTeacher:
    def __init__(self):
        self.seen=[]
    async def respond(self,text,**kwargs):
        self.seen.append((text,kwargs))
        return '把参数单独放一边，是为了把参数范围和函数值域联系起来。卡住时可以从这个联系继续看原题。'


@pytest.mark.parametrize('command, request_phrase', [
    ('request_hint', '起步提示'), ('request_explanation', '关键概念'),
    ('request_example', '同类示例'), ('request_solution', '完整解答'),
])
def test_saved_discussion_support_buttons_answer_same_question_without_grading(tmp_path, command, request_phrase):
    from test_tutor_p0 import count
    db = tmp_path / 'discussion-buttons.db'
    teacher = DiscussionTeacher()
    with client_at(db) as client, client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        state = get_product_state()
        state.learner_settings.update('high', 10)
        state.controller.chat_responder = teacher
        send(ws, 'send_message', 'question', {'text': QUESTION})
        before = summary(client)
        available = {a['command']: a for a in before['allowed_actions']}
        assert all(available[c]['enabled'] for c in (
            'request_hint', 'request_explanation', 'request_example', 'request_solution'))
        events = count(db, 'learning_events')
        frames = send(ws, command, 'help', {}, cycle_id=before['cycle_id'],
                      problem_revision=before['problem_revision'], expected_state_version=before['state_version'])
        assert any(f['event_type'] == 'assistant_complete' for f in frames)
        assert not any(f['event_type'] == 'turn_error' for f in frames)
        text, options = teacher.seen[-1]
        assert request_phrase in text and options['unstructured_math']
        assert json.loads(options['problem_context'])['original_question'] == QUESTION
        after = summary(client)
        assert after['problem_context']['display_text'] == QUESTION
        assert after['problem_context']['lifecycle'] == 'discussion'
        assert (after['cycle_id'], after['state'], after['state_version']) == (
            before['cycle_id'], before['state'], before['state_version'])
        assert count(db, 'learning_events') == events
        assert count(db, 'attempt_assessments') == 0
        calls = len(teacher.seen)
        assert send(ws, command, 'help', {}, cycle_id=before['cycle_id'],
                    problem_revision=before['problem_revision'], expected_state_version=before['state_version']) == frames
        assert len(teacher.seen) == calls
        stale = send(ws, command, 'stale', {}, cycle_id='another-question')
        assert any(f['payload'].get('error_code') == 'PROBLEM_BINDING_STALE' for f in stale)
        assert len(teacher.seen) == calls


def test_pasted_question_and_focus_survive_followups_replay_and_restart(tmp_path):
    db=tmp_path/'discussion.db'
    teacher=DiscussionTeacher()
    with client_at(db) as client,client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        get_product_state().controller.chat_responder=teacher
        send(ws,'send_message','pasted',{'text':QUESTION})
        original=summary(client)['problem_context']
        assert original['display_text']==QUESTION and original['lifecycle']=='discussion'
        assert summary(client)['recovery_problem'] is None
        for index,text in enumerate(['我看不懂','为什么要把a移到一边？','这是专门想出来的吗？','能不能给点提示']):
            frames=send(ws,'send_message',f'why-{index}',{'text':text})
            assert any(f['event_type']=='assistant_complete' for f in frames)
            context=json.loads(teacher.seen[-1][1]['problem_context'])
            assert context['original_question']==QUESTION
            assert summary(client)['problem_context']['problem_id']==original['problem_id']
        before=len(teacher.seen)
        assert send(ws,'send_message','why-3',{'text':'能不能给点提示'})==frames
        assert len(teacher.seen)==before
        assert sum(summary(client)['evidence_summary'][k] for k in ['independent','assisted','post_solution'])==0
    restored_teacher=DiscussionTeacher()
    with client_at(db) as client,client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        get_product_state().controller.chat_responder=restored_teacher
        assert summary(client)['problem_context']['display_text']==QUESTION
        send(ws,'send_message','after-restart',{'text':'为什么不是闭区间？'})
        stored=json.loads(restored_teacher.seen[-1][1]['problem_context'])
        assert stored['original_question']==QUESTION and stored['recent_explanations']
        assert summary(client)['problem_context']['current_subgoal']['prompt_target']=='为什么不是闭区间？'
        # A supported exercise remains a separate verified task.
        send(ws,'send_message','new-equation',{'text':'换题：x^2-5x+6=0'})
        assert summary(client)['problem_context']['lifecycle'].lower()=='active'
        assert 'discussion-' not in summary(client)['problem_context']['problem_id']


def test_unsupported_exponential_is_taught_and_preserved_without_elementary_replacement(tmp_path):
    with client_at(tmp_path/'exp.db') as client,client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        get_product_state().controller.chat_responder=DiscussionTeacher()
        frames=send(ws,'send_message','exponential',{'text':'2^x+x-2=0'})
        assert any(f['event_type']=='assistant_complete' for f in frames)
        assert summary(client)['problem_context']['display_text']=='2^x+x-2=0'
        assert summary(client)['recovery_problem'] is None


def test_real_gateway_receives_saved_question_as_data_and_current_stage(tmp_path):
    class Provider:
        provider_id,model='offline','teacher-test'
        def __init__(self): self.calls=[]
        async def complete(self,messages,**kwargs):
            self.calls.append((messages,kwargs))
            return CompletionResult(text='先把零点条件看成函数与水平线的交点，再讨论函数在这段区间的取值。',provider_id=self.provider_id,model=self.model,finish_reason='stop',input_tokens=10,output_tokens=10)
    provider=Provider()
    with client_at(tmp_path/'gateway.db') as client,client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        state=get_product_state()
        state.learner_settings.update('high',10)
        state.gateway.register_provider(ModelRole.TUTOR_WRITER,provider)
        send(ws,'send_message','original',{'text':QUESTION})
        send(ws,'send_message','why',{'text':'这是专门想出来的吗？'})
        messages,kwargs=provider.calls[-1]
        assert '高一' in messages[0]['content']
        assert '不用反问' in messages[0]['content'] or '不要把同一个疑问反问' in messages[0]['content']
        lesson=next(m['content'] for m in messages if m['role']=='user' and str(m['content']).startswith('已保存的原题'))
        assert json.loads(lesson.split('\n',1)[1])['original_question']==QUESTION
        assert kwargs['max_tokens']==4096


def test_high_school_paste_is_agent_led_but_explicit_practice_is_verified(tmp_path):
    with client_at(tmp_path/'modes.db') as client,client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        state=get_product_state()
        state.learner_settings.update('high',10)
        state.controller.chat_responder=DiscussionTeacher()
        send(ws,'send_message','paste',{'text':'x^2-5x+6>0'})
        assert summary(client)['problem_context']['lifecycle']=='discussion'
        send(ws,'submit_problem','practice',{'text':'x^2-5x+6>0'},session='practice')
        assert summary(client,'practice')['problem_context']['lifecycle']=='active'
        send(ws,'submit_attempt','answer',{'answer':'x<2或x>3'},session='practice')
        assert summary(client,'practice')['evidence_summary']['independent']==1


def test_short_student_formula_does_not_replace_saved_question(tmp_path):
    with client_at(tmp_path/'student-step.db') as client,client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        state=get_product_state()
        state.learner_settings.update('high',10)
        state.controller.chat_responder=DiscussionTeacher()
        send(ws,'send_message','question',{'text':QUESTION})
        for index,text in enumerate(['a=2','g(1)=0','0<a<3','函数为什么在这段递增？']):
            send(ws,'send_message',f'step-{index}',{'text':text})
            assert summary(client)['problem_context']['display_text']==QUESTION
        next_question='已知f(x)=2^x-1，求它的零点。'
        send(ws,'send_message','next-question',{'text':next_question})
        assert summary(client)['problem_context']['display_text']==next_question


def test_graph_followup_uses_saved_original_without_requiring_formula_again(tmp_path, monkeypatch):
    from mathtutor.application.scene import build_scene
    seen=[]
    async def author(gateway, text):
        seen.append(text)
        return build_scene({'title':'原题函数', 'objects':[{'id':'f','type':'function','expr':'2^x-2/x','domain':[1,2]}]}, source='model', reveal=False)
    monkeypatch.setattr('mathtutor.application.scene.author_scene', author)
    with client_at(tmp_path/'graph.db') as client,client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        get_product_state().controller.chat_responder=DiscussionTeacher()
        send(ws,'send_message','original',{'text':QUESTION})
        frames=send(ws,'send_message','graph',{'text':'能画个图看看吗？我还是看不懂。'})
        assert any(f['event_type']=='assistant_complete' for f in frames)
        assert QUESTION in seen[-1]
        assert 'mathtutor-scene' in summary(client)['messages'][-1]['content']
        assert summary(client)['problem_context']['display_text']==QUESTION
