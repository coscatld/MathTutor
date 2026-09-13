import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { CurrentProblem } from "../features/math-tutor/components/TeachingContext";
import TutorActionCard from "../features/math-tutor/components/TutorActionCard";

test("current problem is a closed native disclosure, retaining the full authoritative goal", () => {
  const html = renderToStaticMarkup(<CurrentProblem context={{problem_id:"p", display_text:"理解公式", lifecycle:"ACTIVE", skill_ids:[], current_subgoal:{id:"s", status:"pending", prompt_target:"解释修正项"}}} />);
  assert.match(html, /<details[^>]*class="mt-context"/);
  assert.doesNotMatch(html, /<details[^>]*\sopen/);
  assert.match(html, /<summary aria-label="当前题目与目标"/);
  assert.match(html, /题目与目标详情/);
  assert.match(html, /解释修正项/);
});

test("long tutor answers use the reading surface instead of nested bordered cards", () => {
  const html = renderToStaticMarkup(<TutorActionCard message={{id:"t", kind:"tutor", text:"分步讲解", action:"hint", assistanceLevel:1, version:1}} />);
  assert.match(html, /mt-answer-text/);
  assert.doesNotMatch(html, /rounded-tl-sm/);
  assert.match(html, /分步讲解/);
});

test("reading layout keeps context in header and composer outside the only transcript scroll root", () => {
  const source = readFileSync("features/math-tutor/components/MathTutorPage.tsx", "utf8");
  assert.ok(source.indexOf("<CurrentProblem") < source.indexOf("</header>"));
  assert.equal((source.match(/<CurrentProblem/g) || []).length, 1);
  assert.match(source, /data-chat-scroll-root="true"/);
  assert.doesNotMatch(source, /scrollIntoView/);
});

test("shared pages and theme families retain responsive layout contracts", () => {
  for (const panel of ["DocumentsPanel", "MemoryPanel", "OffersPanel"]) {
    assert.match(readFileSync(`features/math-tutor/desktop/components/${panel}.tsx`, "utf8"), /className="mt-page"/);
  }
  assert.match(readFileSync("tailwind.config.js", "utf8"), /safelist:.*"dark"/);
  assert.match(readFileSync("features/math-tutor/components/ChatComposer.tsx", "utf8"), /rows=\{1\}/);
});
