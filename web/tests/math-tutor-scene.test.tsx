import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import TutorActionCard from "../features/math-tutor/components/TutorActionCard";
import SceneCanvas from "../features/math-tutor/components/SceneCanvas";
import {
  evaluate, fitView, formatNumber, marchingSquares, parseScene, resolvePoints, sampleFunction, sampleRegion, splitSceneMessage,
  type EvalEnv,
} from "../features/math-tutor/lib/scene-eval";
import type { ExprAst, Scene } from "../features/math-tutor/lib/scene-types";
import type { TutorMessage } from "../features/math-tutor/types";
import { sceneSessionKey } from "../features/math-tutor/lib/scene-identity";

const num = (v: number): ExprAst => ({ k: "num", v });
const v = (n: string): ExprAst => ({ k: "var", n });
const op = (o: "+" | "-" | "*" | "/" | "^", a: ExprAst, b: ExprAst): ExprAst => ({ k: "op", o, a: [a, b] });
const fn = (f: string, ...a: ExprAst[]): ExprAst => ({ k: "fn", f, a });
const coord = (p: string, c: "x" | "y"): ExprAst => ({ k: "coord", p, c });
const geo = (f: "dist" | "slope" | "angle" | "area" | "mid_x" | "mid_y", ...p: string[]): ExprAst => ({ k: "geo", f, p });

// x²/4 + y²/3 − 1 = 0 with P(2cos t, √3 sin t) and focus F(1, 0).
const fixture = {
  v: 2,
  title: "椭圆上的动点到焦点的距离",
  source: "deterministic",
  x_range: [-3, 3],
  y_range: [-2.5, 2.5],
  equal_aspect: true,
  params: [{ name: "t", min: 0, max: 6.2832, step: 0.01, value: 0.8, animate: true, label: "t" }],
  objects: [
    { id: "E", type: "implicit", expr: op("-", op("+", op("/", op("^", v("x"), num(2)), num(4)), op("/", op("^", v("y"), num(2)), num(3))), num(1)), label: "x²/4 + y²/3 = 1" },
    { id: "F", type: "point", x: num(1), y: num(0), label: "F" },
    { id: "P", type: "point", x: op("*", num(2), fn("cos", v("t"))), y: op("*", fn("sqrt", num(3)), fn("sin", v("t"))), label: "P", trace: true },
    { id: "PF", type: "segment", from: "P", to: "F" },
  ],
  readouts: [{ label: "|PF|", expr: geo("dist", "P", "F"), digits: 3 }],
  marks: [{ x: 1, y: 0, label: "焦点 (1, 0)" }],
  note: "",
};
const clone = () => JSON.parse(JSON.stringify(fixture));
const scene = parseScene(fixture) as Scene;

test("scene sessions follow message/block identity and definition content, including fresh object copies", () => {
  const identity = JSON.stringify(["message-a", 0]);
  const key = sceneSessionKey(scene, identity);
  const rebuilt = JSON.parse(JSON.stringify(scene)) as Scene;
  assert.notEqual(rebuilt, scene);
  assert.equal(sceneSessionKey(rebuilt, identity), key);
  assert.equal(sceneSessionKey(Object.fromEntries(Object.entries(rebuilt).reverse()) as unknown as Scene, identity), key);
  assert.notEqual(sceneSessionKey(scene, JSON.stringify(["message-b", 0])), key);
  assert.notEqual(sceneSessionKey(scene, JSON.stringify(["message-a", 1])), key);
  assert.notEqual(sceneSessionKey({ ...scene, params: [{ ...scene.params[0], value: 1.2 }] }, identity), key);
  assert.notEqual(sceneSessionKey({ ...scene, objects: scene.objects.slice(1) }, identity), key);
});

test("parseScene accepts the fixture and rejects malformed scenes", () => {
  assert.ok(scene);
  assert.equal(scene.objects.length, 4);
  assert.equal(parseScene({ ...clone(), v: 1 }), null);
  assert.equal(parseScene({ ...clone(), x_range: [Number.NaN, 2] }), null);
  assert.equal(parseScene({ ...clone(), y_range: [2, -2] }), null);
  assert.equal(parseScene({ ...clone(), source: "magic" }), null);

  const badRef = clone();
  badRef.objects[3].to = "Q";
  assert.equal(parseScene(badRef), null);

  const forward = clone();
  forward.objects[1].x = coord("P", "x"); // F (defined before P) names P.
  assert.equal(parseScene(forward), null);
  const backward = clone();
  backward.objects[2].x = op("+", coord("F", "x"), num(1)); // P names the earlier F: fine.
  assert.ok(parseScene(backward));

  const unknownFn = clone();
  unknownFn.objects[2].x = fn("eval", v("t"));
  assert.equal(parseScene(unknownFn), null);
  const wrongArity = clone();
  wrongArity.objects[2].x = fn("atan2", v("t"));
  assert.equal(parseScene(wrongArity), null);
  const strayVar = clone();
  strayVar.objects[2].x = v("x"); // points may not use plot variables
  assert.equal(parseScene(strayVar), null);
  const unknownParam = clone();
  unknownParam.objects[2].y = v("k");
  assert.equal(parseScene(unknownParam), null);

  const many = clone();
  many.objects = Array.from({ length: 41 }, (_, i) => ({ id: `A${i}`, type: "point", x: num(i), y: num(0) }));
  assert.equal(parseScene(many), null);
  const duplicate = clone();
  duplicate.objects[3].id = "F";
  assert.equal(parseScene(duplicate), null);
  const badId = clone();
  badId.objects[3].id = "P-F";
  assert.equal(parseScene(badId), null);

  const reserved = clone();
  reserved.params[0].name = "e";
  assert.equal(parseScene(reserved), null);
  const outOfRange = clone();
  outOfRange.params[0].value = 9;
  assert.equal(parseScene(outOfRange), null);

  let deep: ExprAst = num(1);
  for (let i = 0; i < 45; i += 1) deep = { k: "neg", a: [deep] };
  const tooDeep = clone();
  tooDeep.objects[2].x = deep;
  assert.equal(parseScene(tooDeep), null);

  const badTangent = clone();
  badTangent.objects.push({ id: "T", type: "tangent", of: "E", at: num(0) }); // E is implicit, not a function
  assert.equal(parseScene(badTangent), null);
});

test("splitSceneMessage keeps the prose around the scene block", () => {
  const split = splitSceneMessage(`看图\n\n\`\`\`mathtutor-scene\n${JSON.stringify(fixture)}\n\`\`\`\n\n说明`);
  assert.equal(split.before, "看图");
  assert.equal(split.after, "说明");
  assert.equal(split.scene?.title, "椭圆上的动点到焦点的距离");
  assert.equal(splitSceneMessage("```mathtutor-scene\n{oops\n```").scene, null);
  assert.equal(splitSceneMessage("plain").scene, null);
});

test("evaluate covers arithmetic, functions, coordinates and geometry", () => {
  const env: EvalEnv = { vars: { x: 2, a: 3 }, points: { A: [0, 0], B: [4, 0], C: [0, 3], D: [4, 4], N: null } };
  const close = (ast: ExprAst, expected: number) => assert.ok(Math.abs((evaluate(ast, env) as number) - expected) < 1e-9, JSON.stringify(ast));
  close(op("+", num(1), op("*", v("x"), v("a"))), 7);
  close(op("-", num(1), op("/", v("x"), num(4))), 0.5);
  close(op("^", v("x"), num(10)), 1024);
  close(op("^", num(-8), op("/", num(1), num(3))), -2);
  close({ k: "neg", a: [v("a")] }, -3);
  close(fn("sin", num(0)), 0);
  close(fn("ln", fn("exp", num(2))), 2);
  close(fn("log", num(1000)), 3);
  close(fn("atan2", num(1), num(1)), Math.PI / 4);
  close(fn("max", num(1), v("a")), 3);
  close(fn("sign", num(-5)), -1);
  close(fn("floor", num(2.7)), 2);
  close(coord("B", "x"), 4);
  close(geo("dist", "B", "C"), 5);
  close(geo("slope", "A", "D"), 1);
  close(geo("angle", "B", "A", "C"), 90);
  close(geo("angle", "B", "A", "D"), 45);
  close(geo("area", "A", "B", "C"), 6);
  close(geo("area", "A", "C", "B"), 6);
  close(geo("mid_x", "A", "B"), 2);
  close(geo("mid_y", "A", "C"), 1.5);
  assert.equal(evaluate(fn("sqrt", num(-1)), env), null);
  assert.equal(evaluate(op("/", num(1), num(0)), env), null);
  assert.equal(evaluate(fn("ln", num(0)), env), null);
  assert.equal(evaluate(op("^", num(-4), num(0.5)), env), null);
  assert.equal(evaluate(geo("slope", "A", "C"), env), null);
  assert.equal(evaluate(coord("N", "x"), env), null);
  assert.equal(evaluate(v("missing"), env), null);
  assert.equal(formatNumber(null), "无定义");
  assert.equal(formatNumber(-0.0001, 2), "0.00");
});

test("resolvePoints evaluates dependent points in order", () => {
  const points = resolvePoints(scene, { t: 0 });
  assert.deepEqual(points.F, [1, 0]);
  assert.ok(Math.abs(points.P![0] - 2) < 1e-12 && Math.abs(points.P![1]) < 1e-12);
  const dependent = clone();
  dependent.objects.push({ id: "M", type: "point", x: geo("mid_x", "P", "F"), y: geo("mid_y", "P", "F") });
  const parsed = parseScene(dependent)!;
  const resolved = resolvePoints(parsed, { t: Math.PI / 2 });
  assert.ok(Math.abs(resolved.M![0] - 0.5) < 1e-9);
  assert.ok(Math.abs(resolved.M![1] - Math.sqrt(3) / 2) < 1e-9);
  // Readout of the fixture: |PF| = 2 − x/2 on this ellipse.
  const env = { vars: { t: 0.8 }, points: resolvePoints(scene, { t: 0.8 }) };
  assert.ok(Math.abs(evaluate(scene.readouts[0].expr, env)! - (2 - Math.cos(0.8))) < 1e-9);
});

test("marchingSquares traces the unit circle and sampling helpers behave", () => {
  const circle = (x: number, y: number) => x * x + y * y - 1;
  const segments = marchingSquares(circle, [-2, 2], [-2, 2], 80, 80);
  assert.ok(segments.length > 50);
  for (const [a, b] of segments) {
    assert.ok(Math.abs(Math.hypot(a[0], a[1]) - 1) < 0.02);
    assert.ok(Math.abs(Math.hypot(b[0], b[1]) - 1) < 0.02);
  }
  assert.equal(marchingSquares(() => null, [-1, 1], [-1, 1], 4, 4).length, 0);
  const cells = sampleRegion((x, y) => y - x, "gt", [0, 1], [0, 1], 2, 2);
  assert.deepEqual([...cells], [0, 0, 1, 0]);
  const pieces = sampleFunction(x => (x === 0 ? null : 1 / x), [-1, 1], [-5, 5], 200);
  assert.equal(pieces.length, 2);
  const view = fitView([-3, 3], [-2.5, 2.5], 600, 300, true);
  assert.deepEqual(view.y, [-2.5, 2.5]);
  assert.ok(Math.abs((view.x[1] - view.x[0]) - 10) < 1e-9);
});

test("SceneCanvas renders the canvas, controls, readouts and caption", () => {
  const html = renderToStaticMarkup(<SceneCanvas scene={scene} />);
  assert.match(html, /<canvas/);
  assert.equal((html.match(/type="range"/g) || []).length, 1);
  const id = /<input id="([^"]+)" type="range"/.exec(html)?.[1];
  assert.ok(id);
  assert.match(html, new RegExp(`<label for="${id}"[^>]*>t</label>`));
  assert.match(html, /aria-label="播放 t 动画"/);
  assert.match(html, /清除轨迹/);
  assert.match(html, /\|PF\|/);
  assert.match(html, /1\.303/);
  assert.match(html, /焦点 \(1, 0\)/);
  assert.match(html, /点 P \(1\.39, 1\.24\)/);
  assert.doesNotMatch(html, /未经数学核验/);
  const model = renderToStaticMarkup(<SceneCanvas scene={{ ...scene, source: "model" }} />);
  assert.match(model, /示意图：定义来自模型，图形由应用计算，未经数学核验/);
  const still = renderToStaticMarkup(<SceneCanvas scene={{ ...scene, params: [{ ...scene.params[0], animate: false }] }} />);
  assert.doesNotMatch(still, /播放/);
});

const sceneText = `**椭圆**\n\n\`\`\`mathtutor-scene\n${JSON.stringify(fixture)}\n\`\`\`\n\n看看 |PF| 怎么变`;
const graphSpec = { v: 1, title: "y = x", x_range: [-1, 1], y_range: [-1, 1], series: [{ label: "y = x", segments: [[[-1, -1], [1, 1]]] }], vertical: [], marks: [], note: "" };
const graphText = `图像\n\n\`\`\`mathtutor-graph\n${JSON.stringify(graphSpec)}\n\`\`\``;
const message = (text: string, action: string): TutorMessage => ({ id: "m", kind: "tutor", text, action, assistanceLevel: 0, version: 1 });

test("TutorActionCard draws scenes only for server SHOW_GRAPH messages", () => {
  const shown = renderToStaticMarkup(<TutorActionCard message={message(sceneText, "SHOW_GRAPH")} />);
  assert.match(shown, /<canvas/);
  assert.match(shown, /type="range"/);
  assert.match(shown, /看看 \|PF\| 怎么变/);
  assert.doesNotMatch(shown, /mathtutor-scene/);
  const chat = renderToStaticMarkup(<TutorActionCard message={message(sceneText, "TUTOR_CHAT")} />);
  assert.doesNotMatch(chat, /<canvas/);
  const v1 = renderToStaticMarkup(<TutorActionCard message={message(graphText, "SHOW_GRAPH")} />);
  assert.match(v1, /<canvas/);
  assert.doesNotMatch(v1, /type="range"/);
  const broken = renderToStaticMarkup(<TutorActionCard message={message(sceneText.replace('"v":2', '"v":3'), "SHOW_GRAPH")} />);
  assert.doesNotMatch(broken, /<canvas/);
});
