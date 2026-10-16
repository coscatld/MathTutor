"""General failures found in real K12 runs; no benchmark answer lookup."""
import asyncio
import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application.math_claims import certify, certify_and_annotate
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole
from test_tutor_p0 import client_at, send


@pytest.mark.parametrize('stage,grade,label', [('primary',1,'小学1年级'),('primary',5,'小学5年级'),('middle',8,'8年级'),('high',11,'高二')])
def test_saved_grade_reaches_actual_teacher_request(tmp_path,stage,grade,label):
    calls=[]
    class Provider:
        provider_id,model='regression','teacher'
        async def complete(self,messages,**kwargs):
            calls.append(messages)
            return CompletionResult(text='两堆苹果交换位置，合起来仍然同样多。',provider_id=self.provider_id,model=self.model,finish_reason='stop',input_tokens=20,output_tokens=20)
    with client_at(tmp_path/'grade.db') as client,client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        assert client.put('/api/v2/math-tutor/desktop/settings/learner',json={'stage':stage,'grade':grade}).status_code==200
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER,Provider())
        frames=send(ws,'send_message','explain',{'text':'加法交换律为什么成立？'})
        assert any(f['event_type']=='assistant_complete' for f in frames)
    system=calls[-1][0]['content']
    assert label in system
    if stage=='primary':assert 'ax²+bx+c' not in system


@pytest.mark.parametrize('anchor,branches,ok', [
    ('(2x-5)(3x+1)=0',r'\(2x-5=0\) 或 \(3x+1=0\)',True),
    ('(2x-5)(3x+1)=0',r'\(2x-4=0\) 或 \(3x+1=0\)',False),
    ('(2x-5)(3x+1)=0',r'\(2x-5=0\)',False),
])
def test_alternative_factor_equations_are_checked_as_one_solution_set(anchor,branches,ok):
    r=asyncio.run(certify('所以 '+branches+'。',InProcessVerificationBackend(),anchor=('quadratic',anchor)))
    assert bool(r.refuted) is not ok
    if ok:assert r.verified==1


def test_unbound_domain_constraints_and_function_definitions_are_not_equivalence_claims():
    backend=InProcessVerificationBackend()
    for text in [r'已知 \(r>0\)，\(r^2=16\)，所以 \(r=4\)。',
                 r'配方得 \(y=x^2-6x+12=(x-3)^2+3\)。',
                 r'化简后直线为 \(y=2x\)。']:
        result=asyncio.run(certify(text,backend))
        assert not result.refuted and result.unchecked>0
    # An invented sign assumption cannot bypass the trusted exercise anchor.
    result=asyncio.run(certify(r'设 \(x>0\)，所以 \(x=4\)。',backend,anchor=('quadratic','x^2-16=0')))
    assert result.refuted
    assert asyncio.run(certify(r'展开 \((x+2)^2=x^2+4\)。',backend)).refuted


def test_empty_formula_free_repair_is_not_accepted_as_a_mathematical_fix():
    async def fallback(_):return '服务暂不可用，你可以继续补充想法。'
    text,result=asyncio.run(certify_and_annotate('先算 $8+9=18$。',InProcessVerificationBackend(),regenerate=fallback))
    assert result.refuted and '8+9=18' in text and '核验未通过' in text
    assert '服务暂不可用' not in text


def test_inequality_or_and_unsupported_higher_degree_union_are_not_polynomial_equalities():
    from mathtutor.application.math_claims import extract_statements
    for text in [r'\(x\ne1\) 或 \(x=2\)',r'\(x^2=4\) 或 \(x=0\)']:
        statements=extract_statements(text)
        assert not any(')*((' in s.text for s in statements)
    # A context constraint still cannot hide a wrong polynomial identity.
    r=asyncio.run(certify('已知 $x>0$，展开得 $(x+3)^2=x^2+9$。',InProcessVerificationBackend()))
    assert r.refuted


@pytest.mark.parametrize('text,allowance',[('解释一下加法交换律。',2048),('请给我完整解答：为什么加法交换律成立？',4096)])
def test_full_solution_has_room_for_reasoning_and_visible_answer(tmp_path,text,allowance):
    calls=[]
    class Provider:
        provider_id,model='regression','teacher'
        async def complete(self,messages,**kwargs):
            calls.append(kwargs)
            return CompletionResult(text='交换两堆苹果的位置，总个数没有变。',provider_id=self.provider_id,model=self.model,finish_reason='stop',input_tokens=20,output_tokens=20)
    with client_at(tmp_path/'allowance.db') as client,client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        state=get_product_state();state.learner_settings.update('primary',2)
        state.gateway.register_provider(ModelRole.TUTOR_WRITER,Provider())
        send(ws,'send_message','explain',{'text':text})
    assert calls[-1]['max_tokens']==allowance
