import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { knowledgeSection } from "../features/math-tutor/knowledge/api";
import { teachingSkills, TeachingSkillsList } from "../features/math-tutor/knowledge/TeachingSkills";

const skill = {id: "test.stepwise", name: "逐步讲解", description: "围绕当前疑点提供小步骤。", enabled: false, source: "configured"};

test("knowledge only selects files or teaching methods, with old extensions links falling back to files", () => {
  assert.equal(knowledgeSection("skills"), "skills");
  for (const value of [null, "files", "extensions", "tools", "creator", "unknown"]) assert.equal(knowledgeSection(value), "files");
});

test("teaching-method projection discards developer tool, directory and schema fields", () => {
  const result = teachingSkills({skills: [{...skill, input_schema: {secret: true}, workspace_id: "private"}], sdk: "private", tools: [{secret: true}], workspaces: [{path: "/private"}]});
  assert.deepEqual(result, [skill]);
  assert.doesNotMatch(JSON.stringify(result), /private|schema|workspace|tools|sdk/);
});

test("incomplete skill responses are rejected instead of presenting false availability", () => {
  for (const value of [null, {}, {skills: {}}, {skills: [null]}, {skills: [{...skill, enabled: "yes"}]}]) assert.throws(() => teachingSkills(value));
  assert.deepEqual(teachingSkills({skills: []}), []);
});

test("teaching skills present real availability without developer controls", () => {
  const html = renderToStaticMarkup(<TeachingSkillsList skills={[skill, {...skill, id: "test.canvas", name: "交互画布", enabled: true, source: "builtin", activation: "数学对话按需提供"}]} />);
  assert.match(html, /未启用/); assert.match(html, /数学对话按需提供/);
  assert.doesNotMatch(html, /SDK|schema|授权|创作者接口|<button|<input|<pre/);
  assert.match(renderToStaticMarkup(<TeachingSkillsList skills={[]} />), /当前没有提供教学技能/);
});
