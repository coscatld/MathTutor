import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import StudentNextStep, { studentActionEnabled, studentStepGuidance } from "../features/math-tutor/components/StudentNextStep";
import TutorWelcome, { STARTER_PROBLEMS } from "../features/math-tutor/components/TutorWelcome";
import NearbyPractice from "../features/math-tutor/components/NearbyPractice";
import { mathTutorReducer, initialMathTutorState } from "../features/math-tutor/lib/reducer";
import { projectStudentFrame } from "../features/math-tutor/lib/protocol";
import type { ActiveOffer, AllowedAction, MathTutorCommand, ProblemContext, TeachingPlan } from "../features/math-tutor/types";

const context: ProblemContext = { problem_id: "problem", display_text: "2x+3=7", skill_ids: ["equality_preservation"], lifecycle: "ACTIVE", current_subgoal: { id: "balance", prompt_target: "保持两边相等，先去掉常数项", status: "pending" } };
const plan: TeachingPlan = { action: "ASK_STUDENT", strategy: "focused_question", question_goal: "等号两边都减去 3 后，式子变成什么？", target_subgoal_id: "balance", target_skill_ids: ["equality_preservation"], reason_codes: [], support_mode: "guided", exit_options: [] };
const offer: ActiveOffer = { offer_id: "offer-2", title: "换一道题，自己试试移项", purpose: "A2", status: "ACTIVE" };
const capability = (command: MathTutorCommand, enabled = true): AllowedAction => ({ command, enabled, reason_code: enabled ? "AVAILABLE" : "ACTION_NOT_APPLICABLE", description: enabled ? "" : "当前阶段暂不能使用这个操作。", label: "" });
const normalActions = ["request_hint", "submit_attempt", "request_example", "request_practice"].map(command => capability(command as MathTutorCommand));

function buttons(node: React.ReactNode): Array<React.ReactElement<{ children?: React.ReactNode; disabled?: boolean; onClick?: () => void }>> {
  const result: Array<React.ReactElement<{ children?: React.ReactNode; disabled?: boolean; onClick?: () => void }>> = [];
  React.Children.forEach(node, child => {
    if (!React.isValidElement<{ children?: React.ReactNode; disabled?: boolean; onClick?: () => void }>(child)) return;
    if (child.type === "button") result.push(child);
    else result.push(...buttons(child.props.children));
  });
  return result;
}

test("empty conversation offers three usable exercises and a student-facing invitation", () => {
  const sent: string[] = [];
  const element = TutorWelcome({ disabled: false, onChoose: text => sent.push(text) });
  const html = renderToStaticMarkup(element);
  assert.equal(buttons(element).length, 3);
  for (const button of buttons(element)) button.props.onClick?.();
  assert.deepEqual([...sent], STARTER_PROBLEMS.map(problem => problem.text));
  assert.match(html, /发来题目或写下你的第一步/);
  assert.doesNotMatch(html, /挂载|session|掌握概率/);
  const locked = TutorWelcome({ disabled: true, onChoose: text => sent.push(text) });
  for (const button of buttons(locked)) button.props.onClick?.();
  assert.equal(sent.length, 3);
  assert.equal((renderToStaticMarkup(locked).match(/disabled=""/g) || []).length, 3);
});

test("next step exposes four actions beside the actual goal and focuses writing without submitting an empty attempt", () => {
  const sent: Array<{ command: MathTutorCommand; payload?: Record<string, string> }> = [];
  let writes = 0;
  const element = StudentNextStep({ context, plan, actions: normalActions, allowed: [], busy: false, disabled: false, onWrite: () => writes++, onCommand: (command, payload) => sent.push({ command, payload }) });
  const html = renderToStaticMarkup(element);
  for (const text of ["轮到你写", plan.question_goal, "提示", "我来写", "看一步", "再来一道"]) assert.ok(html.includes(text));
  assert.match(html, /看相关例题的示范/);
  for (const button of buttons(element).slice(0, 4)) button.props.onClick?.();
  assert.equal(writes, 1);
  assert.deepEqual(sent, [{ command: "request_hint", payload: undefined }, { command: "request_example", payload: undefined }, { command: "request_practice", payload: undefined }]);
});

test("authoritative disabled or missing capabilities override stale legacy allowed inputs", () => {
  assert.equal(studentActionEnabled("request_hint", [], ["request_hint"]), false);
  assert.equal(studentActionEnabled("request_hint", [capability("request_hint", false)], ["request_hint"]), false);
  assert.equal(studentActionEnabled("request_hint", undefined, ["request_hint"]), true);
  let invoked = false;
  const element = StudentNextStep({ context, plan, actions: normalActions.map(action => ({ ...action, enabled: false })), allowed: normalActions.map(action => action.command), busy: false, disabled: false, onWrite: () => { invoked = true; }, onCommand: () => { invoked = true; } });
  for (const button of buttons(element)) { assert.equal(button.props.disabled, true); button.props.onClick?.(); }
  assert.equal(invoked, false);
  assert.equal(renderToStaticMarkup(<StudentNextStep context={null} actions={normalActions} allowed={[]} busy={false} disabled={false} onWrite={() => {}} onCommand={() => {}} />), "");
});

test("I understand sends the student's self-report through the regular message route", () => {
  const sent: Array<{ command: MathTutorCommand; payload?: Record<string, string> }> = [];
  const element = StudentNextStep({ context, plan, actions: [capability("submit_attempt")], allowed: [], busy: false, disabled: false, onWrite: () => {}, onCommand: (command, payload) => sent.push({ command, payload }) });
  const selfReport = buttons(element).find(button => renderToStaticMarkup(button).includes("我懂了"));
  assert.ok(selfReport);
  selfReport.props.onClick?.();
  assert.deepEqual(sent, [{ command: "send_message", payload: { text: "我懂了" } }]);
  assert.equal(context.lifecycle, "ACTIVE");
});

test("valid inline offer sends its identity and an expired offer cannot expose acceptance", () => {
  const sent: Array<{ command: MathTutorCommand; payload?: Record<string, string> }> = [];
  const props = { context, offer, actions: [capability("accept_practice_offer"), capability("decline_practice_offer")], allowed: [], busy: false, disabled: false, onWrite: () => {}, onCommand: (command: MathTutorCommand, payload?: Record<string, string>) => sent.push({ command, payload }) };
  for (const button of buttons(StudentNextStep(props))) button.props.onClick?.();
  assert.deepEqual(sent, [{ command: "accept_practice_offer", payload: { offer_id: "offer-2" } }, { command: "decline_practice_offer", payload: { offer_id: "offer-2" } }]);
  assert.doesNotMatch(renderToStaticMarkup(<StudentNextStep {...props} offer={{ ...offer, status: "EXPIRED" }} />), /开始这道练习/);
});

test("server guidance survives live frames and restart recovery without exposing private plan material", () => {
  const rawPlan = { ...plan, student_guidance: "移项时符号还不稳定，先检查两边都减去同一个数。", material_refs: ["private"], evidence_refs: ["private"] };
  const summary = { cycle_id: "cycle", teaching_plan: rawPlan, problem_context: { ...context, understanding_check: true } };
  const restored = mathTutorReducer(initialMathTutorState("session"), { type: "restore", summary });
  const frame = projectStudentFrame({ event_type: "assistant_complete", ...summary })!;
  const live = mathTutorReducer(initialMathTutorState("session"), { type: "frame", frame });
  assert.equal(live.teachingPlan?.student_guidance, rawPlan.student_guidance);
  assert.deepEqual(live.teachingPlan, restored.teachingPlan);
  assert.equal(live.problemContext?.understanding_check, true);
  assert.equal(studentStepGuidance(live.teachingPlan), rawPlan.student_guidance);
  assert.doesNotMatch(JSON.stringify(frame), /private/);
  assert.doesNotMatch(studentStepGuidance(null), /已掌握|%|变号/);
});

test("understanding check offers an honest return to the original problem", () => {
  const sent: string[] = [];
  const element = StudentNextStep({ context: { ...context, understanding_check: true }, plan, actions: [capability("submit_attempt"), capability("skip_diagnostic"), capability("resume_problem")], allowed: [], busy: false, disabled: false, onWrite: () => {}, onCommand: command => sent.push(command) });
  const html = renderToStaticMarkup(element);
  assert.match(html, /用一道小题检查一下/);
  assert.match(html, /跳过检查，回到原题/);
  assert.doesNotMatch(html, /我懂了|诊断|已掌握/);
  const skip = buttons(element).find(button => renderToStaticMarkup(button).includes("跳过检查"));
  skip?.props.onClick?.();
  assert.deepEqual(sent, ["skip_diagnostic"]);
});

test("an interrupted unverified check exposes only authorized navigation in the conversation", () => {
  const sent: string[] = [];
  const props = { context: null, actions: [capability("resume_problem"), capability("skip_diagnostic"), capability("request_hint")], allowed: [], busy: false, disabled: false, onWrite: () => assert.fail(), onCommand: (command: MathTutorCommand) => sent.push(command) };
  const element = StudentNextStep(props);
  const html = renderToStaticMarkup(element);
  assert.match(html, /检查题尚未准备好，回到原题继续/);
  assert.equal(buttons(element).length, 2);
  assert.doesNotMatch(html, /提示|看一步|我来写|再来一道/);
  for (const button of buttons(element)) button.props.onClick?.();
  assert.deepEqual(sent, ["resume_problem", "skip_diagnostic"]);
  assert.equal(renderToStaticMarkup(<StudentNextStep {...props} actions={[]} allowed={["resume_problem"]} />), "", "an authoritative missing capability overrides stale inputs");
});

test("nearby practice keeps the original question until the student explicitly chooses the verified exercise", () => {
  const sent: string[] = [];
  const problem = { text: "2x+3=7", problem_type: "linear", relation: "先练列式后的一元一次方程，帮助你检查应用题的计算部分。" };
  const element = NearbyPractice({ problem, disabled: false, onChoose: text => sent.push(text) });
  assert.equal(sent.length, 0);
  assert.match(renderToStaticMarkup(element), /列式后的一元一次方程/);
  buttons(element)[0]?.props.onClick?.();
  assert.deepEqual(sent, ["换题：2x+3=7"]);
  buttons(NearbyPractice({ problem, disabled: true, onChoose: text => sent.push(text) }))[0]?.props.onClick?.();
  assert.equal(sent.length, 1);
});
