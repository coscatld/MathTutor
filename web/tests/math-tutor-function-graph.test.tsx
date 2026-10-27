import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import FunctionGraph from "../features/math-tutor/components/FunctionGraph";
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

test("sampled lookup includes endpoints without interpolating across segment gaps", () => {
  const series = { label: "分段函数", segments: [[[-4, -8], [-2, -4]], [[2, 4], [6, 12]]] as [number, number][][] };
  assert.equal(valueAt(series, -4), -8);
  assert.equal(valueAt(series, 6), 12);
  assert.equal(valueAt(series, 3), 6);
  assert.equal(valueAt(series, 0), null);
  assert.equal(valueAt(series, -5), null);
  assert.equal(valueAt(series, 7), null);
  assert.equal(valueAt(series, Number.NaN), null);
  assert.equal(valueAt(series, Number.POSITIVE_INFINITY), null);
  assert.equal(valueAt(series, Number.NEGATIVE_INFINITY), null);
  const huge = Number.MAX_VALUE;
  const extreme = { label: "有限大数", segments: [[[-huge, huge], [huge, -huge]]] as [number, number][][] };
  assert.equal(valueAt(extreme, -huge), huge);
  assert.equal(valueAt(extreme, 0), 0);
  assert.equal(valueAt(extreme, huge), -huge);
});

test("graphs expose a labelled bounded keyboard lookup and describe sampled values", () => {
  const graph = renderToStaticMarkup(<FunctionGraph spec={parseGraphSpec(spec)!} />);
  const inputId = /<input id="([^"]+)"/.exec(graph)?.[1];
  assert.ok(inputId);
  assert.ok(graph.includes(`for="${inputId}"`));
  assert.match(graph, /type="number" min="-4" max="6" step="any" required=""/);
  assert.match(graph, /<button type="submit"[^>]*>读取<\/button>/);
  assert.doesNotMatch(graph, /输入后按 Enter|选择“读取”/);
  assert.match(graph, /采样点作线性插值/);
  assert.match(graph, /不跨段插值/);
  assert.match(graph, /role="status" aria-live="polite" aria-atomic="true"><\/p>/);
  assert.doesNotMatch(graph, /<table/);
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
