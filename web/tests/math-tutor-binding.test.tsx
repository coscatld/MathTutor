import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { buildEnvelope, projectAllowedActions, projectStudentFrame } from '../features/math-tutor/lib/protocol';
import { initialMathTutorState, mathTutorReducer } from '../features/math-tutor/lib/reducer';
import ActionBar from '../features/math-tutor/components/ActionBar';
import type { AllowedAction } from '../features/math-tutor/types';

const disabledSolution: AllowedAction = {command: 'request_solution', enabled: false, reason_code: 'NO_VERIFIED_SOLUTION', description: '请补充完整题目。', label: ''};

test('main_input_carries_cycle_revision_and_state_version', () => {
  const wire = JSON.parse(buildEnvelope('send_message', {text: 'x=2'}, 'c', {requestId: 'r', cycleId: 'cycle', problemRevision: 'revision', expectedCycleVersion: 3}));
  assert.equal(wire.cycle_id, 'cycle');
  assert.equal(wire.problem_revision, 'revision');
  assert.equal(wire.expected_state_version, 3);
  assert.equal(wire.protocol_version, 2);
});

test('capability_projection_is_default_deny_for_malformed_or_internal_commands', () => {
  const projected = projectAllowedActions([disabledSolution, {command: 'request_hint', enabled: 'false'}, {command: 'solution_shown_permitted', enabled: true}, {command: 'shell', enabled: true}]);
  assert.deepEqual(projected, [disabledSolution]);
});

test('action_button_obeys_backend_enabled_reason_and_review_label', () => {
  const html = renderToStaticMarkup(<ActionBar allowed={['request_solution']} actions={[disabledSolution]} busy={false} disabled={false} onCommand={() => {}} />);
  assert.match(html, /disabled=""/);
  assert.match(html, /aria-describedby="action-reason-NO_VERIFIED_SOLUTION"/);
  assert.equal(html.split('请补充完整题目。').length - 1, 1);
  const review = renderToStaticMarkup(<ActionBar allowed={[]} actions={[{...disabledSolution, enabled: true, description: '', label: '重新查看答案'}]} busy={false} disabled={false} onCommand={() => {}} />);
  assert.match(review, /重新查看答案/);
  assert.ok(!review.includes('disabled=""'));
});

test('new_cycle_low_version_does_not_get_dropped_as_a_stale_old_cycle', () => {
  const old = {...initialMathTutorState('c'), cycleId: 'old', problemRevision: 'old-rev', seenVersion: 20};
  const frame = projectStudentFrame({event_type: 'tutor_action_committed', cycle_id: 'new', cycle_state: 'awaiting_attempt', cycle_state_version: 3, payload: {action: 'verified', student_message: '题目已解析并验证：3x=9'}})!;
  const state = mathTutorReducer(old, {type: 'frame', frame});
  assert.equal(state.cycleId, 'new');
  assert.equal(state.seenVersion, 3);
  assert.equal(state.problemRevision, '');
  const restored = mathTutorReducer(state, {type: 'restore', summary: {cycle_id: 'new', problem_revision: 'new-rev', state_version: 3}});
  assert.equal(restored.problemRevision, 'new-rev');
});

test('terminal_capabilities_override_legacy_allowed_inputs', () => {
  const frame = projectStudentFrame({event_type: 'assistant_complete', cycle_id: 'cycle', problem_revision: 'rev', cycle_state_version: 3,
    allowed_next_inputs: ['request_solution'], allowed_actions: [disabledSolution], payload: {conversation_id: 'c'}})!;
  const state = mathTutorReducer(initialMathTutorState('c'), {type: 'frame', frame});
  assert.deepEqual(state.allowedNextInputs, []);
  assert.equal(state.problemRevision, 'rev');
  assert.deepEqual(state.allowedActions, [disabledSolution]);
});

test('late_old_summary_cannot_roll_back_the_same_cycle', () => {
  const state = {...initialMathTutorState('c'), cycleId: 'cycle', seenVersion: 8};
  assert.equal(mathTutorReducer(state, {type: 'restore', summary: {cycle_id: 'cycle', state_version: 3}}), state);
});
