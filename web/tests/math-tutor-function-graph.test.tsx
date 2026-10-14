import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import TutorActionCard from "../features/math-tutor/components/TutorActionCard";
import StudentNextStep from "../features/math-tutor/components/StudentNextStep";
import { niceStep, parseGraphSpec, splitGraphMessage, valueAt } from "../features/math-tutor/lib/function-graph";
import { projectProblemContext } from "../features/math-tutor/lib/teaching-contract";
import type { TutorMessage } from "../features/math-tutor/types";

const spec = { v: 1, title: "y = x^2 - 2x - 3", x_range: [-4, 6], y_range: [-6, 21],
  series: [{ label: "y = x^2 - 2x - 3", segments: [[[-4, 21], [1, -4], [6, 21]]] }],
  vertical: [], marks: [{ x: 3, y: 0, label: "与 x 轴交点 (3, 0)" }], note: "" };
const text = `**函数图像**：y = x^2 - 2x - 3\n\n\`\`\`mathtutor-graph\n${JSON.stringify(spec)}\n\`\`\`\n\n说明`;
const message = (action: string): TutorMessage => ({ id: "m", kind: "tutor", text, action, assistanceLevel: 0, version: 1 });

test("graph spec projection rejects malformed or oversized data", () => {
  assert.equal(parseGraphSpec({ ...spec, v: 2 }), null);
  assert.equal(parseGraphSpec({ ...spec, x_range: [5, 1] }), null);
  assert.equal(parseGraphSpec({ ...spec, series: [{ label: "", segments: [Array.from({ length: 4001 }, (_, i) => [i, i])] }] }), null);
  const parsed = parseGraphSpec({ ...spec, marks: [...spec.marks, { x: "NaN", y: 0, label: "bad" }] });
  assert.deepEqual(parsed?.marks.map(mark => mark.label), ["与 x 轴交点 (3, 0)"]);
});

test("split keeps the prose around the graph block", () => {
  const split = splitGraphMessage(text);
  assert.equal(split.before, "**函数图像**：y = x^2 - 2x - 3");
  assert.equal(split.after, "说明");
  assert.equal(split.spec?.series[0].segments[0].length, 3);
  assert.equal(valueAt(split.spec!.series[0], 1), -4);
  assert.equal(valueAt(split.spec!.series[0], 0), 1);
  assert.equal(valueAt(split.spec!.series[0], 9), null);
  assert.equal(niceStep(10, 8), 1);
});

test("only a server SHOW_GRAPH message renders a canvas", () => {
  const graph = renderToStaticMarkup(<TutorActionCard message={message("SHOW_GRAPH")} />);
  assert.match(graph, /<canvas/);
  assert.match(graph, /函数图像/);
  assert.match(graph, /与 x 轴交点 \(3, 0\)/);
  assert.doesNotMatch(graph, /mathtutor-graph/);
  const chat = renderToStaticMarkup(<TutorActionCard message={message("TUTOR_CHAT")} />);
  assert.doesNotMatch(chat, /<canvas/);
});

test("the graph button follows the server graphable flag", () => {
  const raw = { problem_id: "p", display_text: "x^2-5x+6=0", skill_ids: [], lifecycle: "ACTIVE", current_subgoal: null };
  const render = (graphable: boolean) => renderToStaticMarkup(<StudentNextStep context={projectProblemContext({ ...raw, graphable })}
    allowed={["request_hint", "submit_attempt"]} busy={false} disabled={false} onWrite={() => {}} onCommand={() => {}} />);
  assert.match(render(true), /看图像/);
  assert.doesNotMatch(render(false), /看图像/);
});
