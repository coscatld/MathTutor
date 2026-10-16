"""Real request boundaries, unrelated recovery and graph noun regressions."""
import pytest
from mathtutor.application.teaching_intent import explicit_solution_request
from mathtutor.application.function_graph import is_graph_request
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole
from mathtutor.api.product_state import get_product_state
from test_tutor_p0 import client_at, send, summary

@pytest.mark.parametrize('text',[
    'Please give me the complete solution.',
    'Solve this equation step by step. Provide your final answer.',
    'Provide a complete correct solution.\nConversation:\nTeacher: How did you try it?\nStudent: I guessed.',
])
def test_explicit_english_requests_allow_solution(text):
    assert explicit_solution_request(text)

@pytest.mark.parametrize('text',[
    "Don't give me the answer, only a hint.",
    'Please show the final answer, but do not reveal the answer yet.',
    'Respond to the student.\nConversation:\nTutor: Please provide the final answer.\nStudent: Can you explain this step?',
    'Problem: Solve the problem step-by-step.\nStudent’s latest message:\nPlease do not give me the answer.',
    'What does "show the final answer" mean?',
])
def test_negation_and_quoted_historical_requests_do_not_grant_disclosure(text):
    assert not explicit_solution_request(text)

@pytest.mark.parametrize('text',[
    'Find the area bounded by the graphs of y=3x and y=x^2.',
    'The graph crosses the axis. Why does that happen?',
    'Explain this paragraph about a plot of velocity.',
])
def test_english_graph_nouns_are_not_drawing_commands(text):
    assert not is_graph_request(text)

@pytest.mark.parametrize('text',['Plot y=x^3.','Please graph y=x^2.','Could you plot y=3x?','Show me the graph of y=x^2.'])
def test_english_graph_commands_still_work(text):
    assert is_graph_request(text)

class Teacher:
    provider_id,model='fixed','offline'
    def __init__(self):self.calls=[]
    async def complete(self,messages,**kwargs):
        self.calls.append((messages,kwargs))
        return CompletionResult(text='No',provider_id=self.provider_id,model=self.model,finish_reason='stop')

def test_successful_current_answer_is_not_followed_by_unrelated_recovery(tmp_path):
    provider=Teacher()
    with client_at(tmp_path/'requests.db') as client,client.websocket_connect('/api/v2/math-tutor/ws') as ws:
        state=get_product_state();state.learner_settings.update('middle',8)
        state.gateway.register_provider(ModelRole.TUTOR_WRITER,provider)
        send(ws,'send_message','check',{'text':'Check this student solution.\nProblem: A box has 9 red and 8 blue balls. How many balls?\nStudent: 9+8=17.\nIs it incorrect? Write only Yes or No.'})
        text=summary(client)['messages'][-1]['content']
        assert text.endswith('No') and '相关基础题' not in text
        prompt=provider.calls[0][0][0]['content']
        assert '默认跟随学生当前请求的语言' in prompt
        assert '首次接触' not in prompt
