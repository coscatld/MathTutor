import assert from 'node:assert/strict';
import test from 'node:test';
import { checkPractice, practiceExamples } from '../lib/practice.ts';

const [positive, fraction, negative] = practiceExamples;
const grades = (draft, problem = positive) => checkPractice(draft, problem).map(row => row.status);

test('all three examples accept exact values and equivalent intermediate steps', () => {
  assert.deepEqual(grades('x+1=3\n2x=x+2\n2=x'), ['equivalent', 'equivalent', 'solved']);
  assert.deepEqual(grades('3x=2\nx=4/6', fraction), ['equivalent', 'solved']);
  assert.deepEqual(grades('−2x=6\n−3=x', negative), ['equivalent', 'solved']);
  assert.deepEqual(grades('0.666667', fraction), ['changed']);
  assert.deepEqual(grades('4/2'), ['solved']);
});

test('feedback stops at the first wrong or unsupported line', () => {
  assert.deepEqual(checkPractice('\n2x=4\n2x=10\nx=2', positive).map(({ line, status }) => [line, status]), [[2, 'equivalent'], [3, 'changed']]);
  for (const input of ['x=x', '1=0', 'x=3', '1/2']) assert.deepEqual(grades(input), ['changed'], input);
  for (const input of ['1/0', 'x/x=1', 'x²=4', 'x1=2', '2 3', 'x=>2', 'x=1=2', 'x+', 'x=2+']) assert.deepEqual(grades(input), ['unreadable'], input);
  assert.deepEqual(grades('x/2=1'), ['equivalent']);
  assert.deepEqual(grades('x=2/1'), ['solved']);
  assert.deepEqual(grades('2x/3=4/3'), ['equivalent']);
});

test('limits apply before grading an oversized or excessively long derivation', () => {
  assert.deepEqual(grades('x=' + '9'.repeat(180)), ['unreadable']);
  assert.equal(grades('2x=4\n'.repeat(12) + 'x=2').at(-1), 'unreadable');
});
