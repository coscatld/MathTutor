import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import TutorActionCard from "../features/math-tutor/components/TutorActionCard";
import { actionLabel } from "../features/math-tutor/lib/protocol";
import type { TutorMessage } from "../features/math-tutor/types";

// A model-defined scene as the server renders it after a draw_scene call.
const scene = {
  v: 2, title: "椭圆与焦点", source: "model", x_range: [-3, 3], y_range: [-2.5, 2.5], equal_aspect: true,
  params: [{ name: "t", min: 0, max: 6.2832, step: 0.01, value: 0.8, animate: true, label: "t" }],
  objects: [
    { id: "F", type: "point", x: { k: "num", v: 1 }, y: { k: "num", v: 0 }, label: "F" },
    { id: "P", type: "point", x: { k: "op", o: "*", a: [{ k: "num", v: 2 }, { k: "fn", f: "cos", a: [{ k: "var", n: "t" }] }] },
      y: { k: "fn", f: "sin", a: [{ k: "var", n: "t" }] }, label: "P", trace: true },
    { id: "PF", type: "segment", from: "P", to: "F" },
  ],
  readouts: [{ label: "|PF|", expr: { k: "geo", f: "dist", p: ["P", "F"] }, digits: 3 }],
  marks: [], note: "示意图：定义来自模型，图形由应用计算，未经数学核验",
};
const block = (title: string) => `**数形结合**：${title}\n\n\`\`\`mathtutor-scene\n${JSON.stringify({ ...scene, title })}\n\`\`\`\n\n${scene.note}`;
const text = `椭圆上任一点到两焦点的距离和是定值。\n\n${block("椭圆与焦点")}`;
const message = (body: string, action: string): TutorMessage => ({ id: "m", kind: "tutor", text: body, action, assistanceLevel: 0, version: 1 });

test("TUTOR_CHAT_FIGURE messages draw the server's scene with the prose around it", () => {
  const html = renderToStaticMarkup(<TutorActionCard message={message(text, "TUTOR_CHAT_FIGURE")} />);
  assert.match(html, /<canvas/);
  assert.match(html, /讲解配图/);
  assert.match(html, /距离和是定值/);
  assert.match(html, /未经数学核验/);
  assert.doesNotMatch(html, /mathtutor-scene/);
  assert.equal(actionLabel("TUTOR_CHAT_FIGURE"), "讲解配图");
});

test("two drawn scenes both render", () => {
  const html = renderToStaticMarkup(<TutorActionCard message={message(`${text}\n\n${block("第二张")}`, "TUTOR_CHAT_FIGURE")} />);
  assert.equal(html.match(/<canvas/g)?.length, 2);
  assert.doesNotMatch(html, /mathtutor-scene/);
});

test("ordinary chat never renders scene blocks, and a broken block draws nothing", () => {
  const chat = renderToStaticMarkup(<TutorActionCard message={message(text, "TUTOR_CHAT")} />);
  assert.doesNotMatch(chat, /<canvas/);
  const broken = renderToStaticMarkup(<TutorActionCard message={message(text.replace('"v":2', '"v":3'), "TUTOR_CHAT_FIGURE")} />);
  assert.doesNotMatch(broken, /<canvas/);
});
