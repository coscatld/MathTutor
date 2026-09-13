import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ActionBar from "../features/math-tutor/components/ActionBar";
import TutorActionCard from "../features/math-tutor/components/TutorActionCard";
import HintLadder from "../features/math-tutor/components/HintLadder";
import { CurrentProblem, DiagnosisNotice, EvidenceSummaryCard } from "../features/math-tutor/components/TeachingContext";
import { PrivacySummary } from "../features/math-tutor/desktop/components/PrivacyPanel";
import PracticeOfferCard from "../features/math-tutor/desktop/components/PracticeOfferCard";
import { allowedInputsToButtons, buildEnvelope, projectAllowedActions, projectStudentFrame } from "../features/math-tutor/lib/protocol";
import { initialMathTutorState, mathTutorReducer } from "../features/math-tutor/lib/reducer";
import { isAcceptableOffer, projectEvidenceSummary, projectTeachingPlan } from "../features/math-tutor/lib/teaching-contract";
import type { ActiveOffer, AllowedAction, EvidenceSummary, MathTutorCommand, ProblemContext, TeachingPlan } from "../features/math-tutor/types";
import { presentationAcknowledgement, presentationFromFrame } from "../features/math-tutor/lib/delivery";

const plan: TeachingPlan = { action: "ask_subgoal", strategy: "guided_steps", question_goal: "由 3x=9 求 x", target_subgoal_id: "solve_x", target_skill_ids: ["solve_one_variable"], reason_codes: ["current_step_unanswered"], support_mode: "concept_cue", exit_options: ["view_solution", "pause"] };
const context: ProblemContext = { problem_id: "p", display_text: "2x+y=7；x-y=2，求 x 和 y", skill_ids: ["elimination"], lifecycle: "ACTIVE", current_subgoal: { id: "solve_x", prompt_target: "由 3x=9 求 x", status: "pending" } };
const evidence: EvidenceSummary = { independent: 1, assisted: 2, post_solution: 3, diagnostic: 0, ungradable: 1, status: "needs_confirmation" };
const offer: ActiveOffer = { offer_id: "offer", title: "独立运用一次消元", status: "ACTIVE", purpose: "post_solution" };
const capability = (command: MathTutorCommand, enabled = true): AllowedAction => ({command, enabled, label: "", description: "", reason_code: enabled ? "AVAILABLE" : "UNAVAILABLE"});

test("teaching metadata projection excludes private material and model vectors", () => {
  const raw = { event_type: "turn_end", teaching_plan: {...plan, material_refs: ["secret"], disclosure: { answer: "secret" }}, problem_context: {...context, verified_solution_ref: "secret", answer: "secret"}, evidence_summary: {...evidence, latent_state: [99]}, active_offer: {...offer, solution: "secret"} };
  const frame = projectStudentFrame(raw)!;
  assert.deepEqual(frame.teaching_plan, plan);
  assert.deepEqual(frame.problem_context, context);
  assert.deepEqual(frame.evidence_summary, evidence);
  assert.deepEqual(frame.active_offer, offer);
  assert.ok(!JSON.stringify(frame).includes("secret"));
  assert.ok(!JSON.stringify(frame).includes("latent_state"));
});

test("malformed teaching metadata does not become invented progress or evidence", () => {
  assert.equal(projectTeachingPlan("already mastered"), null);
  assert.equal(projectEvidenceSummary(null), null);
  assert.deepEqual(projectEvidenceSummary({independent: -1, assisted: "4", post_solution: Number.NaN}), {independent: 0, assisted: 0, post_solution: 0, diagnostic: 0, ungradable: 0, status: ""});
  assert.equal(isAcceptableOffer({...offer, offer_id: " "}), false);
  assert.equal(isAcceptableOffer({...offer, status: "FAILED"}), false);
});

test("teaching plan, goal, and evidence hydrate from the same server summary", () => {
  const summary = {cycle_id: "cycle", state_version: 4, state: "awaiting_attempt", teaching_plan: plan, problem_context: context, evidence_summary: evidence, active_offer: offer};
  const restored = mathTutorReducer(initialMathTutorState("c"), {type: "restore", summary});
  assert.deepEqual(restored.teachingPlan, plan);
  assert.deepEqual(restored.problemContext, context);
  assert.deepEqual(restored.evidenceSummary, evidence);
  assert.deepEqual(restored.activeOffer, offer);
  const frame = projectStudentFrame({event_type: "turn_end", cycle_state_version: 4, ...summary})!;
  const live = mathTutorReducer(initialMathTutorState("c"), {type: "frame", frame});
  assert.deepEqual(live.teachingPlan, restored.teachingPlan);
  assert.deepEqual(live.evidenceSummary, restored.evidenceSummary);
});

test("switching problem clears the old teaching goal and offer until new metadata arrives", () => {
  const old = {...initialMathTutorState("c"), cycleId: "old", teachingPlan: plan, problemContext: context, evidenceSummary: evidence, activeOffer: offer};
  const fresh = mathTutorReducer(old, {type: "frame", frame: projectStudentFrame({event_type: "turn_end", cycle_id: "new"})!});
  assert.equal(fresh.teachingPlan, null);
  assert.equal(fresh.problemContext, null);
  assert.equal(fresh.evidenceSummary, null);
  assert.equal(fresh.activeOffer, null);
  const restored = mathTutorReducer(old, {type: "restore", summary: {cycle_id: "new"}});
  assert.equal(restored.teachingPlan, null);
  assert.equal(restored.problemContext, null);
});

test("generic lifecycle nulls cannot erase a just-committed public snapshot", () => {
  const snapshot = projectStudentFrame({event_type: "assistant_complete", cycle_id: "cycle", cycle_state_version: 4,
    allowed_actions: [capability("request_practice")], teaching_plan: plan, problem_context: context,
    evidence_summary: evidence, active_offer: offer, diagnosis: {status: "running", can_skip: true, question_count: 3, answered: 1},
    payload: {conversation_id: "c", turn_id: "r"}})!;
  const committed = mathTutorReducer(initialMathTutorState("c"), {type: "frame", frame: snapshot});
  for (const event_type of ["turn_end", "assistant_start", "assistant_delta"] as const) {
    const generic = projectStudentFrame({event_type, cycle_id: "", cycle_state: "", cycle_state_version: 0,
      allowed_actions: null, teaching_plan: null, problem_context: null, evidence_summary: null, active_offer: null, diagnosis: null, payload: {}})!;
    const state = mathTutorReducer(committed, {type: "frame", frame: generic});
    assert.deepEqual(state.teachingPlan, committed.teachingPlan);
    assert.deepEqual(state.problemContext, committed.problemContext);
    assert.deepEqual(state.evidenceSummary, committed.evidenceSummary);
    assert.deepEqual(state.activeOffer, committed.activeOffer);
    assert.deepEqual(state.diagnosis, committed.diagnosis);
    assert.deepEqual(state.allowedActions, committed.allowedActions);
  }
});

test("authoritative null snapshot can still clear a consumed offer and finished diagnosis", () => {
  const prior = {...initialMathTutorState("c"), cycleId: "cycle", activeOffer: offer, diagnosis: {status: "running", can_skip: true, question_count: 3, answered: 1, started_at: ""}};
  const frame = projectStudentFrame({event_type: "assistant_complete", cycle_id: "cycle", allowed_actions: [], active_offer: null, diagnosis: null})!;
  const state = mathTutorReducer(prior, {type: "frame", frame});
  assert.equal(state.activeOffer, null);
  assert.equal(state.diagnosis, null);
  assert.deepEqual(state.allowedNextInputs, []);
});

test("icon-only Tutor tools have persistent accessible names without relying on tooltip hover", () => {
  const source = fs.readFileSync(path.resolve(process.cwd(), "features/math-tutor/components/MathTutorPage.tsx"), "utf8");
  for (const label of ["当前教学支持与可用操作", "当前对话的学习资料", "查看 Tutor 使用的学习记忆", "收起右侧工具"]) {
    assert.ok(source.includes(`<button type="button" aria-label="${label}"`));
  }
});

test("support panel describes assistance without a level ladder, ability score, or forced sequence", () => {
  const html = renderToStaticMarkup(<HintLadder level={4} plan={plan} />);
  for (const text of ["当前支持", "分步引导", "由 3x=9 求 x", "先确认当前这一步", "已展示内容", "局部过程示范"]) assert.ok(html.includes(text));
  assert.ok(!html.includes("提示阶梯") && !html.includes("L4") && !html.includes("progressbar"));
  assert.ok(!html.includes("width:80%") && !html.includes("第 4 级"));
});

test("current problem displays a verified subgoal without claiming the whole problem complete", () => {
  const html = renderToStaticMarkup(<CurrentProblem context={{...context, current_subgoal: {...context.current_subgoal!, status: "verified"}}} />);
  assert.ok(html.includes(context.display_text));
  assert.ok(html.includes("已验证步骤") && html.includes("辅导中"));
  assert.ok(!html.includes("本题已完成"));
  assert.equal(renderToStaticMarkup(<CurrentProblem context={null} />), "");
});

test("evidence card separates independent, assisted, post-solution, and unknown observations", () => {
  const html = renderToStaticMarkup(<EvidenceSummaryCard evidence={evidence} />);
  for (const text of ["独立作答", "受助作答", "看答案后作答", "暂无法判断", "仍需独立检测"]) assert.ok(html.includes(text));
  assert.ok(!html.includes("%") && !html.includes("已掌握"));
});

test("privacy profile displays verified evidence rather than a legacy mastery percentage", () => {
  const html = renderToStaticMarkup(<PrivacySummary summary={{total_attempts: 7, active_misconceptions: 0, skills: [{code: "eq", label: "等式性质", mastery: 0.99, grade_band: null, evidence_summary: evidence}]}} />);
  assert.ok(html.includes("独立 1 次") && html.includes("受助 2 次") && html.includes("看答案后 3 次"));
  assert.ok(!html.includes("99%"));
});

test("public practice, return, end, and optional diagnosis commands round-trip", () => {
  const commands: MathTutorCommand[] = ["request_practice", "request_foundation", "request_review", "resume_problem", "end_problem", "start_diagnostic", "skip_diagnostic"];
  assert.deepEqual(projectAllowedActions(commands.map(command => capability(command))).map(action => action.command), commands);
  const buttons = allowedInputsToButtons(commands);
  assert.equal(buttons.length, commands.length);
  for (const button of buttons) assert.equal(JSON.parse(buildEnvelope(button.command, {}, "c")).command, button.command);
  assert.deepEqual(allowedInputsToButtons([]), []);
});

test("accepting requires an active offer identity even when a stale capability says enabled", () => {
  for (const activeOffer of [null, {...offer, offer_id: ""}, {...offer, status: "FAILED"}]) {
    const html = renderToStaticMarkup(<ActionBar offer={activeOffer} actions={[capability("accept_practice_offer")]} allowed={["accept_practice_offer"]} busy={false} disabled={false} onCommand={() => {}} />);
    assert.ok(html.includes('disabled=""'));
    assert.ok(html.includes("当前没有可接受的有效练习"));
  }
});

test("foundation and review controls require actual enabled server capabilities", () => {
  const allowed = ["request_foundation", "request_review"];
  const html = renderToStaticMarkup(<ActionBar actions={[]} allowed={allowed} busy={false} disabled={false} onCommand={() => {}} />);
  assert.equal(html, "");
  const blocked = renderToStaticMarkup(<ActionBar actions={[capability("request_foundation", false), capability("request_review", false)]} allowed={allowed} busy={false} disabled={false} onCommand={() => {}} />);
  assert.ok(blocked.includes("先补基础") && blocked.includes("做一道复习题"));
  assert.equal((blocked.match(/disabled=""/g) || []).length, 2);
});

test("historical evidence plans and post-solution status retain the server's meaning", () => {
  const html = renderToStaticMarkup(<HintLadder level={2} plan={{...plan, strategy: "compare_methods", reason_codes: ["MULTIPLE_INDEPENDENT_ITEMS"]}} />);
  assert.ok(html.includes("比较可行方法") && html.includes("不同题目的独立作答记录"));
  const shown = renderToStaticMarkup(<EvidenceSummaryCard evidence={{...evidence, status: "已看过解答，需换题独立检测"}} />);
  assert.ok(shown.includes("已看过解答，需换题独立检测"));
  assert.ok(!shown.includes("已掌握"));
});

test("new learning lifecycle actions display Chinese labels without exposing internal codes", () => {
  const cases = {RESUME_PROBLEM: "回到原题", END_PROBLEM: "本题已结束", SELF_REPORT: "理解反馈（自述）",
    DIAGNOSTIC: "可跳过的基础检查", DIAGNOSTIC_COMPLETE: "诊断已完成", ERROR_ANALYSIS: "教师示例找错", PRACTICE_DECLINED: "已略过练习"};
  for (const [action, label] of Object.entries(cases)) {
    const html = renderToStaticMarkup(<TutorActionCard message={{id: action, kind: "tutor", text: "当前学习记录已保留。", action, assistanceLevel: 0, version: 1, status: "COMPLETED"}} />);
    assert.ok(html.includes(label));
    assert.ok(!html.includes(action));
  }
  const semantic = renderToStaticMarkup(<HintLadder level={1} plan={{...plan, reason_codes: ["LANGUAGE_CONFUSION", "SEMANTIC_INTENT"]}} />);
  assert.ok(semantic.includes("你表达了当前的困惑") && semantic.includes("结合你的原话和当前目标"));
});

test("the actual action button passes the active offer id, not an empty request", () => {
  let sent: {command: MathTutorCommand; payload?: Record<string, string>} | undefined;
  const element = ActionBar({offer, actions: [capability("accept_practice_offer")], allowed: [], busy: false, disabled: false, onCommand: (command, payload) => { sent = {command, payload}; }});
  const visit = (node: React.ReactNode): void => { React.Children.forEach(node, child => {
    if (!React.isValidElement<{children?: React.ReactNode; onClick?: () => void}>(child)) return;
    if (child.type === "button") child.props.onClick?.(); else visit(child.props.children);
  }); };
  visit(element);
  assert.deepEqual(sent, {command: "accept_practice_offer", payload: {offer_id: "offer"}});
});

test("optional diagnosis does not start or fail a student from an empty observation", () => {
  assert.equal(renderToStaticMarkup(<DiagnosisNotice diagnosis={{status: "not_started", can_skip: true, question_count: 0, started_at: ""}} />), "");
  const html = renderToStaticMarkup(<DiagnosisNotice diagnosis={{status: "active", can_skip: true, question_count: 0, started_at: "2026-09-11"}} />);
  assert.ok(html.includes("跳过不会记为错误") && html.includes("随时跳过"));
  assert.ok(!html.includes("0 分") && !html.includes("秒后"));
  const running = renderToStaticMarkup(<DiagnosisNotice diagnosis={{status: "running", can_skip: true, question_count: 4, answered: 1, started_at: "2026-09-11"}} />);
  assert.ok(running.includes("已作答 1 / 4 道"));
  assert.ok(!running.includes("已记录 4 道"));
});

test("practice-list card rejects a missing offer identifier", () => {
  const html = renderToStaticMarkup(<PracticeOfferCard offer={{offer_id: "", parent_cycle_id: "cycle", status: "ACTIVE", skill_labels: [], concept_labels: [], difficulty: "easy", offered_at: "", expires_at: ""}} accepting={false} onStart={() => {}} />);
  assert.ok(!html.includes("开始练习"));
});

test("delivery ACK is only issued for a visible committed result, never reading or mastery", () => {
  const frame = projectStudentFrame({event_type: "assistant_complete", delivery_id: "delivery", payload: {message_id: "m", turn_id: "r"}})!;
  const pending = presentationFromFrame(frame)!;
  assert.equal(presentationFromFrame({...frame, event_type: "assistant_start"}), null);
  assert.equal(presentationAcknowledgement(pending, [], true), null);
  const message = {id: "m", turnId: "r", kind: "tutor" as const, text: "已验证的本题内容", action: "SHOW_SOLUTION", assistanceLevel: 5, version: 4, status: "COMPLETED"};
  assert.equal(presentationAcknowledgement(pending, [message], false), null);
  assert.equal(presentationAcknowledgement(pending, [{...message, status: "STREAMING"}], true), null);
  assert.deepEqual(JSON.parse(presentationAcknowledgement(pending, [message], true)!), {type: "delivery_presented", delivery_id: "delivery"});
});
