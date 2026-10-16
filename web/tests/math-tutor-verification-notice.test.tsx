import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import TutorActionCard from "../features/math-tutor/components/TutorActionCard";
import { splitVerificationNotice } from "../features/math-tutor/lib/verification-notice";
import { projectStudentFrame } from "../features/math-tutor/lib/protocol";
import { initialMathTutorState, mathTutorReducer } from "../features/math-tutor/lib/reducer";

const render = (text: string) => renderToStaticMarkup(<TutorActionCard message={{id:"m",kind:"tutor",text,action:"TUTOR_CHAT",assistanceLevel:0,version:1}} />);
test("ordinary explanation scope is available after the lesson, closed by default",()=>{
  const html=render("> 本段讲解未经逐句数学核验。\n\n把参数范围转成函数值域，是分离参数的目的。");
  assert.match(html,/<details[^>]*aria-label="本条回复的核验范围"/);
  assert.doesNotMatch(html,/<details[^>]*\bopen/);
  assert.ok(html.indexOf("分离参数的目的")<html.indexOf("核验范围"));
  assert.match(html,/未经逐句数学核验/);
});
test("actual refutations remain prominent instead of hiding in scope details",()=>{
  const text="> ⚠️ 本段讲解中有 1 处算式没有通过本地验证器核对。\n\n3+4=8（⚠️ 核验未通过）";
  assert.equal(splitVerificationNotice(text).body,text);
  assert.match(render(text),/核验未通过/);
  assert.doesNotMatch(render(text),/本条回复的核验范围/);
});

test("structured scope survives live completion and a restored transcript without entering the lesson", () => {
  const notice = "本段讲解未经逐句数学核验。";
  const body = "把分母的非零条件保留下来，再进行化简。";
  const frame = (event_type: string, payload: Record<string, unknown>) => projectStudentFrame({
    event_type, payload: {turn_id: "turn-1", message_id: "message-1", conversation_id: "c", ...payload},
  })!;
  let state = mathTutorReducer(initialMathTutorState("c"), {type: "frame", frame: frame("assistant_delta", {student_message: body})});
  state = mathTutorReducer(state, {type: "frame", frame: frame("assistant_complete", {final_text: body, verification_notice: notice})});
  assert.equal(state.messages[0].text, body);
  assert.equal(state.messages[0].verificationNotice, notice);
  const restored = mathTutorReducer(initialMathTutorState("c"), {type: "restore", summary: {messages: [{
    role: "tutor", content: body, message_id: "message-1", turn_id: "turn-1", verification_notice: notice,
  }]}});
  assert.equal(restored.messages[0].verificationNotice, notice);
  for (const message of [state.messages[0], restored.messages[0]]) {
    const html = renderToStaticMarkup(<TutorActionCard message={message} />);
    assert.ok(html.indexOf(body) < html.indexOf("<details"));
    assert.match(html, /<details[^>]*aria-label="本条回复的核验范围"/);
    assert.doesNotMatch(html, /<details[^>]*\bopen/);
    assert.equal(html.split(notice).length - 1, 1);
  }
});

test("structured scope arrives with a delta and remains after metadata-only completion", () => {
  const notice = "本段讲解中的算式已经过核对，其余文字未经逐句数学核验。";
  const delta = projectStudentFrame({event_type: "assistant_delta", payload: {
    turn_id: "t", student_message: "先写出等式。", verification_notice: notice,
  }})!;
  const complete = projectStudentFrame({event_type: "assistant_complete", payload: {turn_id: "t"}})!;
  let state = mathTutorReducer(initialMathTutorState("c"), {type: "frame", frame: delta});
  state = mathTutorReducer(state, {type: "frame", frame: complete});
  assert.equal(state.messages[0].verificationNotice, notice);
  assert.equal(state.messages[0].text, "先写出等式。");
});

test("mixed old and new notice formats render one scope while actual refutations stay in the body", () => {
  const notice = "本段讲解未经逐句数学核验。";
  const text = `> ${notice}\n\n3+4=8（⚠️ 核验未通过）`;
  const html = renderToStaticMarkup(<TutorActionCard message={{
    id: "mixed", kind: "tutor", text, verificationNotice: notice, action: "TUTOR_CHAT", assistanceLevel: 0, version: 1,
  }} />);
  assert.equal(html.split(notice).length - 1, 1);
  assert.ok(html.indexOf("核验未通过") < html.indexOf("<details"));
});

test("scope projection rejects objects instead of exposing arbitrary payload data", () => {
  const frame = projectStudentFrame({event_type: "assistant_delta", payload: {
    student_message: "讲解正文。", verification_notice: {private_reasoning: "do-not-render"},
  }})!;
  assert.equal(frame.payload.verification_notice, undefined);
  assert.doesNotMatch(JSON.stringify(frame), /do-not-render|private_reasoning/);
});
