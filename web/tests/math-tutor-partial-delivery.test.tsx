import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { I18nProvider } from "../lib/i18n";
import TutorActionCard from "../features/math-tutor/components/TutorActionCard";
import { draftWasDelivered } from "../features/math-tutor/lib/delivery";
import { deliverDraft } from "../features/math-tutor/lib/attachments";
import { projectStudentFrame } from "../features/math-tutor/lib/protocol";
import { initialMathTutorState, mathTutorReducer } from "../features/math-tutor/lib/reducer";

const content = "定义先约定讨论对象；结论是在给定条件下推出的判断。";
const frame = (event: string, extra: Record<string, unknown> = {}) => projectStudentFrame({ event_type: event,
  payload: { conversation_id: "session", turn_id: "turn", status: "PARTIAL", finish_reason: "PROVIDER_ERROR", final_text: content, ...extra } })!;

test("persisted partial delivery clears the submitted draft without completing the answer", async () => {
  let draft = "数学概念里，定义和结论有什么区别？";
  let state = mathTutorReducer(initialMathTutorState("session"), { type: "frame", frame: frame("assistant_delta", { student_message: content }) });
  const terminal = frame("assistant_partial");
  const delivered = await deliverDraft(draft, [], async () => {
    state = mathTutorReducer(state, { type: "frame", frame: terminal });
    return draftWasDelivered(terminal);
  }, () => { draft = ""; });
  assert.equal(delivered, true);
  assert.equal(draft, "");
  assert.equal(state.messages.length, 1);
  assert.equal(state.messages[0].text, content);
  assert.equal(state.messages[0].status, "PARTIAL");
  assert.equal(state.messages[0].finishReason, "PROVIDER_ERROR");
});

test("streaming, rejected, empty and interrupted transport responses retain the draft", async () => {
  for (const terminal of [frame("assistant_delta"), frame("turn_end"), frame("assistant_error", { status: "FAILED" }),
    frame("assistant_partial", { status: "PARTIAL", final_text: "" }), frame("assistant_partial", { status: "FAILED" })]) {
    let draft = "保留这条未确认的请求";
    assert.equal(await deliverDraft(draft, [], async () => draftWasDelivered(terminal), () => { draft = ""; }), false);
    assert.equal(draft, "保留这条未确认的请求");
  }
});

const reasons = [
  ["PROVIDER_ERROR", "模型服务暂时不可用。", "The model service is temporarily unavailable."],
  ["TIMEOUT", "模型响应超时。", "The model response timed out."],
  ["STREAM_INTERRUPTED", "回答传输中断。", "The response connection was interrupted."],
  ["TOKEN_LIMIT", "本轮回答长度已达到上限。", "This reply reached its length limit."],
  ["STEP_CAP", "本轮处理次数已达到上限。", "This reply reached its processing limit."],
  ["COST_LIMIT", "本轮用量已达到设置上限。", "This reply reached the configured usage limit."],
  ["INVALID_TOOL_SEQUENCE", "本轮处理未能继续。", "Processing this reply could not continue."],
  ["INTERNAL_ERROR", "本轮处理发生错误。", "An error interrupted this reply."],
  ["USER_CANCELLED", "已按你的要求停止生成。", "Generation stopped at your request."],
] as const;

for (const [reason, chinese, english] of reasons) test(`restored partial ${reason} displays a localized reason and continuation`, () => {
  const state = mathTutorReducer(initialMathTutorState("session"), { type: "restore", summary: {
    messages: [{ message_id: "message", turn_id: "turn", role: "tutor", content, status: "PARTIAL", finish_reason: reason }],
  } });
  for (const locale of ["zh-CN", "en"] as const) {
    const html = renderToStaticMarkup(<I18nProvider initialLocale={locale}><TutorActionCard message={state.messages[0]} onContinue={() => {}} /></I18nProvider>);
    assert(html.includes(locale === "en" ? english : chinese));
    assert(html.includes(locale === "en" ? "Continue the explanation" : "继续讲完"));
    assert(html.includes(content));
    assert(!html.includes(reason));
  }
});

test("unknown provider details are not rendered as a reason and completed text has no partial notice", () => {
  const message = { id: "m", kind: "tutor" as const, text: content, action: "TUTOR_CHAT", version: 1, assistanceLevel: 0,
    status: "PARTIAL" as const, finishReason: "private provider details" };
  const html = renderToStaticMarkup(<TutorActionCard message={message} />);
  assert(html.includes("这段还没讲完"));
  assert(!html.includes("private provider details"));
  const completed = renderToStaticMarkup(<TutorActionCard message={{ ...message, status: "COMPLETED", finishReason: "PROVIDER_ERROR" }} />);
  assert(!completed.includes("模型服务暂时不可用"));
});
