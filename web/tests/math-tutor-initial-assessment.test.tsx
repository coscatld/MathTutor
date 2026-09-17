import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {readFileSync} from "node:fs";
import {decideStartupRoute} from "../features/math-tutor/desktop/lib/startup";
import {projectChoices} from "../features/math-tutor/lib/teaching-contract";
import ChoiceQuestion from "../features/math-tutor/components/ChoiceQuestion";
import type {ChoiceSet} from "../features/math-tutor/types";

const choices: ChoiceSet = {format: "single_choice", version: "immutable", options: ["A", "B", "C", "D"].map((id, index) => ({id, text: String(index)}))};
test("pending assessment resumes after configuration, but never bypasses auth", () => {
  const settings = {preset_id: "custom", model: "test", base_url: "", key_masked: null, is_configured: true, onboarding_completed: true, initial_assessment_required: true};
  const bootstrap = {phase: "READY", readiness: "READY", reason: "", steps: []} as const;
  assert.equal(decideStartupRoute({enabled: false, authenticated: true}, {...bootstrap, steps: []}, settings), "assessment");
  assert.equal(decideStartupRoute({enabled: true, authenticated: false}, {...bootstrap, steps: []}, settings), "login");
  assert.equal(decideStartupRoute({enabled: false, authenticated: true}, {...bootstrap, steps: []}, {...settings, initial_assessment_required: false}), "workspace");
});
test("choice projection whitelists only the immutable public options", () => {
  assert.deepEqual(projectChoices({...choices, correct_id: "A", weights: [1]}), choices);
  assert.equal(projectChoices({...choices, options: [{id: "A", text: "1"}]}), null);
  assert.equal(projectChoices({...choices, options: choices.options.map(o => ({...o, id: "A"}))}), null);
});
test("choices provide native radios, uncertainty and disabled submission", () => {
  const html = renderToStaticMarkup(<ChoiceQuestion choices={choices} busy={false} allowUnsure onSubmit={() => undefined} />);
  assert.equal((html.match(/type="radio"/g) || []).length, 5);
  assert.match(html, /不记为答错/);
  assert.match(html, /<legend/);
  assert.match(html, /type="submit" disabled/);
});
test("initial assessment has no client grading or persisted credentials", () => {
  const page = readFileSync("features/math-tutor/desktop/components/InitialAssessmentPage.tsx", "utf8");
  assert.match(page, /assessmentRequest/);
  assert.doesNotMatch(page, /localStorage|sessionStorage|api_key|correct_id/);
  assert.match(page, /DKT 目标域模型仍在验证/);
});
