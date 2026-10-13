import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { projectRecoveryProblem, projectStudentFrame } from "../features/math-tutor/lib/protocol";
import { initialMathTutorState, mathTutorReducer } from "../features/math-tutor/lib/reducer";
import TutorActionCard from "../features/math-tutor/components/TutorActionCard";

const recovery = {text: "2x+3=7", problem_type: "linear", relation: "先练习列好之后的一元一次方程。"};

test("recovery exercise projects only supported public fields", () => {
  assert.deepEqual(projectRecoveryProblem({...recovery, answer: "2", probability: 0.99}), recovery);
  for (const value of [null, {}, {...recovery, text: ""}, {...recovery, problem_type: "geometry"}, {...recovery, relation: 1}]) {
    assert.equal(projectRecoveryProblem(value), null);
  }
});

test("optional exercise survives reconnect and clears on authoritative new focus", () => {
  let state = mathTutorReducer(initialMathTutorState("c"), {type: "restore", summary: {cycle_id:"unsupported", recovery_problem:recovery}});
  assert.deepEqual(state.recoveryProblem, recovery);
  assert.equal(state.problemActive, false);
  // Generic null fields do not delete a still-current exercise.
  const generic = projectStudentFrame({event_type:"assistant_start", recovery_problem:null, payload:{conversation_id:"c"}})!;
  state = mathTutorReducer(state, {type:"frame", frame:generic});
  assert.deepEqual(state.recoveryProblem, recovery);
  const accepted = projectStudentFrame({event_type:"assistant_complete", cycle_id:"new", allowed_actions:[], recovery_problem:null})!;
  state = mathTutorReducer(state, {type:"frame", frame:accepted});
  assert.equal(state.recoveryProblem, null);
});

test("partial answer offers continuation and never claims the last formula complete", () => {
  const html = renderToStaticMarkup(<TutorActionCard message={{id:"p", kind:"tutor", text:"判别式为 Δ=16-16=", action:"TUTOR_CHAT", assistanceLevel:0, version:1, status:"PARTIAL"}} onContinue={() => {}} />);
  assert.match(html, /末尾的公式和结论可能不完整/);
  assert.match(html, /继续讲完/);
  assert.match(html, /type="button"/);
  const completed = renderToStaticMarkup(<TutorActionCard message={{id:"p", kind:"tutor", text:"已经讲完。", action:"TUTOR_CHAT", assistanceLevel:0, version:1, status:"COMPLETED"}} onContinue={() => {}} />);
  assert.doesNotMatch(completed, /继续讲完/);
});
