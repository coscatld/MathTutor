import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import TutorActionCard from "../features/math-tutor/components/TutorActionCard";
import { splitVerificationNotice } from "../features/math-tutor/lib/verification-notice";

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
