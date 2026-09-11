import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import MarkdownRenderer from '../components/common/MarkdownRenderer';
import { normalizeMath } from '../components/common/math-normalization';
import { initialMathTutorState, mathTutorReducer } from '../features/math-tutor/lib/reducer';
import { projectStudentFrame } from '../features/math-tutor/lib/protocol';
import { allowedInputsToButtons, buildEnvelope, projectTurnError } from '../features/math-tutor/lib/protocol';
import TutorActionCard from '../features/math-tutor/components/TutorActionCard';

const render = (text: string) => renderToStaticMarkup(<MarkdownRenderer content={text} enableMath />);
for (const role of ['user', 'assistant']) {
  test(`${role}_markdown_rendering`, () => {
    const html = render('# 标题\n\n**重点** *说明*\n\n- 步骤\n\n> 引用\n\n[链接](https://example.com)');
    for (const tag of ['h1', 'strong', 'em', 'li', 'blockquote', 'a']) assert.ok(html.includes(`<${tag}`));
  });
}
test('inline_latex_rendering', () => {
  assert.match(render('答案是 \\(391\\)。'), /class="katex"/);
  assert.match(render('$x^2$'), /class="katex"/);
});
test('block_latex_rendering', () => {
  assert.match(render('\\[17\\times23=391\\]'), /katex-display/);
  assert.match(render('$$\nx^2\n$$'), /katex-display/);
});
test('markdown_code_block', () => {
  const text = '```latex\n\\[x^2\\]\n```';
  assert.equal(normalizeMath(text), text);
  const html = render(text);
  assert.match(html, /<pre><code/);
  assert.ok(!html.includes('class="katex"'));
});
test('renderer_does_not_execute_html', () => {
  const html = render('<script>alert(1)</script>\n\n[x](javascript:alert(1))\n\n<img src=x onerror=alert(1)>');
  assert.ok(!html.includes('<script') && !html.includes('onerror') && !html.includes('javascript:'));
});
test('legacy_math_bracket_normalization_is_conservative', () => {
  for (const text of ['[普通文本]', '[link](https://example.com)', '[a, b]', '`\\(x\\)`', '[this is \\frac{a}{b}]']) assert.equal(normalizeMath(text), text);
  assert.match(render('[ \\frac{0}{0} ]'), /katex-display/);
});
test('completed_message_requires_completion_event', () => {
  let state = initialMathTutorState('c');
  const frame = (event_type: string, payload = {}) => projectStudentFrame({event_type, payload: {turn_id: 't', conversation_id: 'c', ...payload}})!;
  state = mathTutorReducer(state, {type: 'frame', frame: frame('assistant_delta', {student_message: '部分'})});
  assert.equal(state.messages[0].status, 'STREAMING');
  const ended = mathTutorReducer(state, {type: 'frame', frame: frame('turn_end')});
  assert.equal(ended.messages[0].status, 'PARTIAL');
  const complete = mathTutorReducer(state, {type: 'frame', frame: frame('assistant_complete')});
  assert.equal(complete.messages[0].status, 'COMPLETED');
  const partial = mathTutorReducer(state, {type: 'frame', frame: frame('assistant_partial')});
  assert.equal(partial.messages[0].status, 'PARTIAL');
});
test('internal_command_not_rendered', () => {
  const frame = projectStudentFrame({event_type: 'tutor_message', payload: {student_message: '命令 submit_problem 已确认'}})!;
  assert.equal(mathTutorReducer(initialMathTutorState('c'), {type: 'frame', frame}).messages.length, 0);
});
test('deltas_accumulate_in_one_message_and_foreign_turns_are_ignored', () => {
  let state = initialMathTutorState('c');
  for (const text of ['前半', '后半']) {
    const frame = projectStudentFrame({event_type: 'assistant_delta', payload: {turn_id: 't', conversation_id: 'c', student_message: text}})!;
    state = mathTutorReducer(state, {type: 'frame', frame});
  }
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].text, '前半后半');
  const foreign = projectStudentFrame({event_type: 'assistant_complete', payload: {turn_id: 't', conversation_id: 'other'}})!;
  assert.equal(mathTutorReducer(state, {type: 'frame', frame: foreign}), state);
});

test('solution_button_emits_public_command_even_for_legacy_server_name', () => {
  const buttons = allowedInputsToButtons(['solution_shown_permitted', 'request_solution']);
  assert.equal(buttons.length, 1);
  assert.equal(buttons[0].command, 'request_solution');
  const wire = JSON.parse(buildEnvelope(buttons[0].command, {}, 'c', {requestId: 'r', idempotencyKey: 'r'}));
  assert.equal(wire.protocol_version, 2);
  assert.equal(wire.request_id, 'r');
  assert.equal(wire.command, 'request_solution');
});

const turnFrame = (event_type: string, payload: Record<string, unknown> = {}) => projectStudentFrame({event_type, payload: {turn_id: 't', message_id: 'result-t', conversation_id: 'c', ...payload}})!;

test('same_turn_error_and_terminal_error_share_one_result_and_one_recovery', () => {
  let state = initialMathTutorState('c');
  for (const event_type of ['turn_error', 'turn_error', 'assistant_error', 'assistant_error']) {
    state = mathTutorReducer(state, {type: 'frame', frame: turnFrame(event_type, {error: '请补充题目。'})});
  }
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].turnId, 't');
  const html = renderToStaticMarkup(<TutorActionCard message={state.messages[0]} onRecover={() => {}} />);
  assert.equal(html.split('请补充题目。').length - 1, 1);
  assert.equal(html.split('重新同步').length - 1, 1);
  assert.ok(!html.includes('border-red') && !html.includes('这次回答未能生成'));
});

test('error_after_content_remains_inside_the_same_turn_container', () => {
  let state = mathTutorReducer(initialMathTutorState('c'), {type: 'frame', frame: turnFrame('assistant_delta', {student_message: '已完成第一步。'})});
  for (const event_type of ['turn_error', 'turn_error', 'assistant_partial']) {
    state = mathTutorReducer(state, {type: 'frame', frame: turnFrame(event_type, {error: '服务中断。', final_text: '已完成第一步。\n\n服务中断。'})});
  }
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].text, '已完成第一步。\n\n服务中断。');
});

test('snapshot_replay_after_hydration_does_not_duplicate_text_or_message', () => {
  let state = mathTutorReducer(initialMathTutorState('c'), {type: 'restore', summary: {
    messages: [{message_id: 'result-t', turn_id: 't', role: 'tutor', content: '完整答案', status: 'COMPLETED'}],
  }});
  for (let replay = 0; replay < 2; replay++) {
    state = mathTutorReducer(state, {type: 'frame', frame: turnFrame('assistant_delta', {student_message: '完整答案', content_mode: 'snapshot'})});
    state = mathTutorReducer(state, {type: 'frame', frame: turnFrame('assistant_complete')});
  }
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].text, '完整答案');
  assert.equal(state.messages[0].status, 'COMPLETED');
});

test('restore_with_no_allowed_actions_clears_old_capabilities', () => {
  const old = {...initialMathTutorState('c'), allowedNextInputs: ['request_hint'], problemActive: true};
  const state = mathTutorReducer(old, {type: 'restore', summary: {state: '', allowed_next_inputs: []}});
  assert.deepEqual(state.allowedNextInputs, []);
  assert.equal(state.problemActive, false);
});

test('assistance_level_restores_from_server_ledger_after_restart', () => {
  const state = mathTutorReducer(initialMathTutorState('c'), {type: 'restore', summary: {state: 'practice_offered', effective_assistance_level: 5}});
  assert.equal(state.assistanceLevel, 5);
});

test('legacy_unknown_command_and_internal_exception_are_not_student_copy', () => {
  for (const text of ['未知命令：solution_shown_permitted', '内部错误: secret exception']) {
    const projected = projectTurnError(text);
    assert.ok(!projected.includes('solution_shown_permitted') && !projected.includes('secret'));
  }
});
