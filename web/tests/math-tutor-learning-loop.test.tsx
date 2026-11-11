import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {I18nProvider} from "../lib/i18n";
import {LearningLoopCard} from "../features/math-tutor/desktop/components/LearningLoopPanel";
import {learningLoopRequest, type LoopEntry} from "../features/math-tutor/desktop/lib/learning-loop";

const idle: LoopEntry = {domain:"fraction_addition", label_zh:"分数加法", label_en:"Adding fractions", episode:null};
const question = {probe_id:"fraction_addition:review:00", domain:"fraction_addition" as const,
  family:"unequal_denominators",purpose:"review",statement:"1/6 + 1/7",prompt_zh:"计算并填写结果。",prompt_en:"Calculate and enter the answer."};
const active: LoopEntry = {...idle, episode:{episode_id:"episode",domain:"fraction_addition",phase:"practice",question,
  due_at:null,can_start:false,review_round:0,diagnostic:{status:"uncertain",answered:2,label_zh:"证据还不足。",label_en:"More evidence is needed."},
  evidence:{independent_practice:0,delayed_review:0,structural_transfer:0},feedback:null}};
const render = (entry: LoopEntry, english=false) => renderToStaticMarkup(
  <I18nProvider initialLocale={english?"en":"zh-CN"}><LearningLoopCard entry={entry} busy={false} onAction={async()=>true}/></I18nProvider>);

test("new concept check offers a bounded check without inventing evidence", () => {
  const html=render(idle);
  assert.match(html,/最多三道/);
  assert.match(html,/开始检查/);
  assert.ok(!html.includes("100%") && !html.includes("延迟复习记录"));
});
test("fresh free response has a visible label and an explicit assisted alternative", () => {
  const html=render(active,true);
  assert.match(html,/Enter your numerical answer/);
  assert.match(html,/<label[^>]+for=/);
  assert.match(html,/View solution \(assisted practice\)/);
  assert.ok(!html.includes("13/42"),"answer must not be in unsubmitted UI");
  assert.ok(!/[\u3400-\u9fff]/u.test(html));
});
test("feedback identifies the submitted problem separately from the next problem", () => {
  const html=render({...active,episode:{...active.episode!,feedback:{kind:"incorrect",probe_id:"old",
    statement:"1/2 + 1/3",answer:"5/6",explanation_en:"Use a common denominator.",explanation_zh:"先通分。",independent:true}}},true);
  assert.ok(html.indexOf("1/2 + 1/3") < html.indexOf("Answer: 5/6"));
  assert.ok(html.indexOf("Answer: 5/6") < html.indexOf("1/6 + 1/7"));
  assert.ok(!/[\u3400-\u9fff]/u.test(html));
});
test("review eligibility follows the server, and records remain separate", () => {
  const waiting: LoopEntry={...active,episode:{...active.episode!,phase:"waiting",question:null,
    due_at:"2026-11-12T06:00:00+00:00",evidence:{independent_practice:1,delayed_review:0,structural_transfer:0}}};
  const before=render(waiting,true);
  assert.match(before,/Next review:/);
  assert.ok(!before.includes("Start review"));
  assert.match(before,/Delayed review<\/dt><dd[^>]*>0/);
  const due=render({...waiting,episode:{...waiting.episode!,can_start:true}},true);
  assert.match(due,/Ready for review/);
  assert.match(due,/Start review/);
});
test("helped correct feedback does not claim independent success", () => {
  const html=render({...active,episode:{...active.episode!,feedback:{kind:"correct",probe_id:"old",independent:false}}},true);
  assert.match(html,/after viewing the solution is saved/);
  assert.match(html,/Independent practice<\/dt><dd[^>]*>0/);
  assert.ok(!html.includes("Tab") && !html.includes("Enter to"));
});
test("client preserves idempotency fields and uses the authenticated API boundary", async () => {
  const previous=globalThis.fetch;
  let request: {url:string; init?:RequestInit}|undefined;
  globalThis.fetch=async (input,init)=>{request={url:String(input),init};return Response.json({schema_version:"learning_loop_v1",server_time:"now",domains:[idle]});};
  try {
    await learningLoopRequest("answer",{domain:"fraction_addition",episode_id:"e",probe_id:"p",request_id:"same-retry",answer:"2/3"});
    assert.equal(request!.url,"/api/v2/math-tutor/desktop/learning-loop/answer");
    assert.equal(new Headers(request!.init!.headers).get("X-MathTutor-CSRF"),"1");
    assert.equal(JSON.parse(request!.init!.body as string).request_id,"same-retry");
    assert.equal(request!.init!.credentials,"include");
  } finally {globalThis.fetch=previous;}
});
