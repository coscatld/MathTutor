// Real Chromium + React interactions. API/WS fixtures never call a model or alter user data.
// The direct component fixture is bundled in memory from installed packages; no test route is shipped.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { mkdtemp, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const localRequire = createRequire(path.join(webRoot, "package.json"));
const ts = localRequire("typescript");
const base = process.env.LAYOUT_URL || "http://127.0.0.1:3000";
const output = await mkdtemp(path.join(tmpdir(), "mathtutor-scene-browser-"));
const checks = [], errors = [], layout = [];
const pass = name => { checks.push(name); console.log(`PASS ${name}`); };
const num = v => ({ k: "num", v });
const variable = n => ({ k: "var", n });
const scene = {
  v: 2, title: "动态图形生命周期验收", source: "deterministic", x_range: [-2, 2], y_range: [-2, 2], equal_aspect: true,
  params: [
    { name: "t", label: "t", min: 0, max: 6.28, value: 0.8, step: 0.01, animate: true },
    { name: "a", label: "参数取值".repeat(8), min: -10, max: 10, value: -1, step: 0.01, animate: true },
    { name: "b", label: "long_label_".repeat(6).slice(0, 60), min: -10, max: 10, value: 1, step: 0.01, animate: true },
    { name: "c", label: "带符号的大读数", min: -1e19, max: 1e19, value: -1234567890123456789, step: 0.01, animate: false },
  ],
  objects: [
    { id: "P", type: "point", x: { k: "fn", f: "cos", a: [variable("t")] }, y: { k: "fn", f: "sin", a: [variable("t")] }, trace: true, label: "动点 P" },
    { id: "F", type: "function", expr: variable("x"), label: "y = x" },
    { id: "G", type: "function", expr: { k: "op", o: "^", a: [variable("x"), num(2)] }, label: "y = x²" },
  ],
  readouts: [{ label: "完整显示的带符号大读数".repeat(4), expr: variable("c"), digits: 3 }], marks: [], note: "",
};
const sceneText = `可暂停后独立观察。\n\n\`\`\`mathtutor-scene\n${JSON.stringify(scene)}\n\`\`\``;

// Minimal CommonJS loader for these existing React client components. TypeScript
// transpiles the real sources; React, React DOM and icons come from node_modules.
function browserBundle(entry) {
  const modules = [], ids = new Map();
  function add(filename, supplied) {
    if (ids.has(filename)) return ids.get(filename);
    const id = modules.length; ids.set(filename, id); modules.push(null);
    let source = supplied ?? readFileSync(filename, "utf8");
    if (/\.tsx?$/.test(filename)) source = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText;
    const deps = {};
    for (const match of source.matchAll(/require\(["']([^"']+)["']\)/g)) {
      const request = match[1];
      const target = request.startsWith(".") || path.isAbsolute(request) ? ["", ".ts", ".tsx", ".js", "/index.js"].map(suffix => path.resolve(path.dirname(filename), request + suffix)).find(existsSync) : createRequire(filename).resolve(request);
      assert.ok(target, `Cannot bundle ${request} from ${filename}`);
      deps[request] = add(target);
    }
    modules[id] = `[function(require,module,exports){\n${source}\n},${JSON.stringify(deps)}]`;
    return id;
  }
  add(path.join(webRoot, "__scene-browser-entry.tsx"), entry);
  return `(()=>{const process={env:{NODE_ENV:"development"}};const modules=[${modules.join(",")}],cache={};function load(id){if(cache[id])return cache[id].exports;const module=cache[id]={exports:{}};const [run,deps]=modules[id];run(name=>load(deps[name]),module,module.exports);return module.exports;}load(0);})();`;
}
const directScene = { ...scene, params: [scene.params[0]], readouts: [], objects: [...scene.objects, {
  id: "C", type: "implicit", label: "x² + y² = 1", expr: { k: "op", o: "-", a: [{ k: "op", o: "+", a: [{ k: "op", o: "^", a: [variable("x"), num(2)] }, { k: "op", o: "^", a: [variable("y"), num(2)] }] }, num(1)] },
}] };
const bundle = browserBundle(`
import React from "react";
import { createRoot } from "react-dom/client";
import SceneCanvas from "./features/math-tutor/components/SceneCanvas";
const initial = ${JSON.stringify(directScene)};
let first = structuredClone(initial), appended = 0;
const root = createRoot(document.getElementById("fixture"));
function render() {
  root.render(<React.StrictMode><div data-chat-scroll-root="true" id="fixture-log" style={{height:560,overflowY:"auto",padding:16}}>
    <section id="first"><SceneCanvas scene={structuredClone(first)} sceneId={JSON.stringify(["first-message",0])}/></section>
    <div style={{height:700}}>历史消息间隔</div>
    <section id="second"><SceneCanvas scene={structuredClone(initial)} sceneId={JSON.stringify(["second-message",0])}/></section>
    {Array.from({length:appended},(_,i)=><p key={i}>新消息 {i+1}</p>)}
  </div></React.StrictMode>);
}
window.sceneFixture = { rebuild:render, append(){appended++;render();}, version(){first={...first,params:[{...first.params[0],value:2}]};render();}, unmount(){root.unmount();} };
render();
`);
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true });
const page = await browser.newPage({ viewport: { width: 1024, height: 900 }, hasTouch: true });
page.on("pageerror", error => errors.push(error.message));
const summary = { cycle_id: "scene-cycle", problem_revision: "r1", state_version: 1, state: "awaiting_attempt", allowed_next_inputs: ["send_message", "submit_attempt"], messages: [{ message_id: "scene-message", role: "tutor", content: sceneText, action: "SHOW_GRAPH", assistance_level: 0 }], problem_context: { problem_id: "scene-p", display_text: "观察参数变化", lifecycle: "ACTIVE", skill_ids: [] } };
let socket;
await page.route("**/api/**", async route => {
  const p = new URL(route.request().url()).pathname;
  let body = [];
  if (p.endsWith("/auth/status")) body = { enabled: false, authenticated: true };
  else if (p.endsWith("/bootstrap")) body = { phase: "READY", readiness: "READY", steps: [] };
  else if (p.endsWith("/settings")) body = { is_configured: true, onboarding_completed: true, provider_configs: {} };
  else if (p.endsWith("/settings/embedding")) body = { status: "disabled", status_label: "关键词检索" };
  else if (p.endsWith("/sessions")) body = [{ conversation_id: "scene-fixture", title: "动态图形验收" }];
  else if (p.includes("/sessions/")) body = summary;
  else if (p.includes("/knowledge/conversations/")) body = { space_ids: [], document_ids: [], only_selected: false, mode: "tutor", save_space_id: "", tool_mode: "native", available_documents: [], effective_document_ids: [] };
  else if (p.endsWith("/resources")) body = { documents: [], images: [], message_count: 1 };
  await route.fulfill({ json: body });
});
await page.routeWebSocket("**/api/**", ws => { socket = ws; });
const delay = (target = page, ms = 220) => target.waitForTimeout(ms);
const value = locator => locator.inputValue().then(Number);
const pauseAll = async () => { while (await page.locator('.mt-scene button[aria-pressed="true"]').count()) await page.locator('.mt-scene button[aria-pressed="true"]').first().click(); };
try {
  await page.goto(`${base}/math-tutor?session=scene-fixture`);
  await page.locator(".mt-scene input[type=range]").first().waitFor();
  await page.waitForFunction(() => document.querySelector('.mt-scene button[aria-pressed="true"]'));
  await pauseAll();
  const firstRange = page.locator(".mt-scene input[type=range]").first();
  const held = await value(firstRange);
  await page.getByRole("button", { name: "当前教学支持与可用操作", exact: true }).click();
  await delay(); assert.equal(await value(firstRange), held);
  await page.getByRole("button", { name: "关闭工具栏", exact: true }).click();
  socket.send(JSON.stringify({ event_type: "assistant_start", cycle_id: "scene-cycle", cycle_state_version: 2, payload: { message_id: "new-message", action: "TUTOR_CHAT" } }));
  socket.send(JSON.stringify({ event_type: "assistant_delta", cycle_id: "scene-cycle", cycle_state_version: 3, payload: { message_id: "new-message", student_message: "追加消息保持原图暂停。" } }));
  await page.getByText("追加消息保持原图暂停。", { exact: true }).waitFor();
  await delay(); assert.equal(await value(firstRange), held);
  pass("actual chat: opening teaching panel and appending a message preserve pause");

  // These are CSS viewport widths; the final case explicitly stresses CSS 200%
  // layout zoom. Device pixel density is never reported as browser zoom.
  for (const [width, zoom] of [[320, 1], [375, 1], [768, 1], [768, 2]]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.evaluate(z => { document.documentElement.style.zoom = String(z); }, zoom);
    await firstRange.scrollIntoViewIfNeeded(); await delay();
    const metrics = await page.locator(".mt-scene").evaluate(figure => {
      const bounds = figure.getBoundingClientRect();
      const ranges = [...figure.querySelectorAll('input[type="range"]')].map(el => ({ width: el.getBoundingClientRect().width / Number(document.documentElement.style.zoom || 1), min: el.min, max: el.max }));
      const visibleText = [...figure.querySelectorAll("label,output,dt,dd,button")].every(el => { const r = el.getBoundingClientRect(); return r.left >= bounds.left && r.right <= bounds.right + 1 && el.scrollWidth <= el.clientWidth + 1; });
      const log = figure.closest("[data-chat-scroll-root]");
      return { ranges, visibleText, figureWidth: bounds.width, overflow: log.scrollWidth > log.clientWidth + 1 };
    });
    assert.ok(metrics.ranges.every(range => range.width >= 120), JSON.stringify({ width, zoom, metrics }));
    assert.equal(metrics.visibleText, true, JSON.stringify({ width, zoom, metrics }));
    assert.equal(metrics.overflow, false, JSON.stringify({ width, zoom, metrics }));
    for (const range of await page.locator('.mt-scene input[type="range"]').all()) {
      await range.press("Home"); assert.equal(await value(range), Number(await range.getAttribute("min")));
      await range.press("End"); assert.equal(await value(range), Number(await range.getAttribute("max")));
    }
    await page.locator(".mt-scene").screenshot({ path: path.join(output, `controls-${width}-css-zoom-${zoom}.png`) });
    layout.push({ width, cssZoom: zoom, ...metrics });
  }
  await page.evaluate(() => { document.documentElement.style.zoom = "1"; });
  await page.setViewportSize({ width: 375, height: 1000 });
  await firstRange.scrollIntoViewIfNeeded();
  const track = await firstRange.boundingBox();
  await page.touchscreen.tap(track.x + 1, track.y + track.height / 2);
  assert.equal(await value(firstRange), Number(await firstRange.getAttribute("min")));
  await page.touchscreen.tap(track.x + track.width - 1, track.y + track.height / 2);
  assert.equal(await value(firstRange), Number(await firstRange.getAttribute("max")));
  // Check the pressed state at the smallest layout too, without altering labels.
  await page.locator('.mt-scene button[aria-pressed="false"]').first().click();
  await page.locator('.mt-scene button[aria-pressed="true"]').first().waitFor();
  await page.locator(".mt-scene").screenshot({ path: path.join(output, "controls-375-playing.png") });
  await pauseAll();
  pass("actual chat: 320/375/768 CSS px + CSS 200% zoom; long labels/readouts wrap, ranges >=120px, keyboard and touch endpoints");

  const styles = await page.locator('link[rel="stylesheet"]').evaluateAll(links => links.map(link => link.href));
  const fixtureUrl = `${base}/__scene-client-fixture`;
  await page.route("**/__scene-client-fixture", route => route.fulfill({ contentType: "text/html", body: `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">${styles.map(href => `<link rel="stylesheet" href="${href}">`).join("")}</head><body><div id="fixture" style="max-width:640px;margin:16px auto"></div></body></html>` }));
  await page.addInitScript(() => {
    window.sceneProbe = { observers: new Set(), frames: new Set(), roots: [] };
    const nativeObserver = window.IntersectionObserver;
    window.IntersectionObserver = class extends nativeObserver {
      constructor(callback, options) { super(callback, options); window.sceneProbe.observers.add(this); window.sceneProbe.roots.push(options.root?.id); }
      disconnect() { window.sceneProbe.observers.delete(this); super.disconnect(); }
    };
    const raf = window.requestAnimationFrame.bind(window), cancel = window.cancelAnimationFrame.bind(window);
    window.requestAnimationFrame = callback => { const id = raf(now => { window.sceneProbe.frames.delete(id); callback(now); }); window.sceneProbe.frames.add(id); return id; };
    window.cancelAnimationFrame = id => { window.sceneProbe.frames.delete(id); cancel(id); };
    const transform = CanvasRenderingContext2D.prototype.setTransform;
    CanvasRenderingContext2D.prototype.setTransform = function (...args) { this.canvas.dataset.draws = String(Number(this.canvas.dataset.draws || 0) + 1); return transform.apply(this, args); };
    window.sceneHidden = false;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => window.sceneHidden });
    window.setSceneHidden = hidden => { window.sceneHidden = hidden; document.dispatchEvent(new Event("visibilitychange")); };
  });
  await page.setViewportSize({ width: 900, height: 800 });
  await page.goto(fixtureUrl); await page.addScriptTag({ content: bundle });
  const first = page.locator("#first"), second = page.locator("#second");
  const firstInput = first.locator('input[type="range"]'), secondInput = second.locator('input[type="range"]');
  const firstButton = first.locator("button[aria-pressed]"), secondButton = second.locator("button[aria-pressed]");
  await firstButton.waitFor(); await delay();
  assert.equal(await firstButton.getAttribute("aria-pressed"), "true");
  const moving = await value(firstInput); await delay(); assert.notEqual(await value(firstInput), moving);
  assert.equal(await value(secondInput), directScene.params[0].value, "initially offscreen scene must not advance");
  assert.ok(await page.evaluate(() => window.sceneProbe.roots.every(root => root === "fixture-log")));
  await firstButton.click(); await delay();
  const paused = await value(firstInput);
  await page.evaluate(() => { window.originalCanvas = document.querySelector("#first canvas"); window.sceneFixture.rebuild(); window.sceneFixture.append(); });
  await delay(); assert.equal(await value(firstInput), paused);
  assert.equal(await firstButton.getAttribute("aria-pressed"), "false");
  assert.equal(await page.evaluate(() => window.originalCanvas === document.querySelector("#first canvas")), true);
  await firstButton.click(); await firstInput.press("ArrowRight"); await delay();
  const dragged = await value(firstInput);
  await page.evaluate(() => window.sceneFixture.rebuild()); await delay();
  assert.equal(await value(firstInput), dragged); assert.equal(await firstButton.getAttribute("aria-pressed"), "false");
  pass("direct React StrictMode: new equal scene objects preserve paused/slider state and canvas across parent rebuild and append");

  await page.evaluate(() => { window.setSceneHidden(true); window.sceneFixture.version(); });
  await delay(); assert.equal(await value(firstInput), 2);
  assert.equal(await firstButton.getAttribute("aria-pressed"), "true");
  assert.equal(await page.evaluate(() => window.originalCanvas === document.querySelector("#first canvas")), false);
  await page.evaluate(() => window.setSceneHidden(false)); await delay();
  assert.notEqual(await value(firstInput), 2);
  pass("true scene-content change resets initial values, trail canvas and autoplay intent; foreground gate delays execution");

  const snapshot = async section => ({ value: await value(section.locator('input[type="range"]')), draws: Number(await section.locator("canvas").getAttribute("data-draws")) });
  const profiler = await page.context().newCDPSession(page);
  await profiler.send("Profiler.enable"); await profiler.send("Profiler.setSamplingInterval", { interval: 1000 });
  async function profilePhase(name) {
    await profiler.send("Profiler.start"); await delay(page, 500);
    const { profile } = await profiler.send("Profiler.stop");
    await writeFile(path.join(output, `scene-${name}.cpuprofile`), JSON.stringify(profile));
    const byId = new Map(profile.nodes.map(node => [node.id, node])), parents = new Map();
    for (const node of profile.nodes) for (const child of node.children || []) parents.set(child, node.id);
    const functions = ["sampleFunction", "marchingSquares", "sampleGrid", "evaluate"];
    const counts = Object.fromEntries(functions.map(name => [name, 0]));
    for (const id of profile.samples || []) {
      const found = new Set();
      for (let current = id; current; current = parents.get(current)) { const name = byId.get(current)?.callFrame.functionName; if (functions.includes(name)) found.add(name); }
      for (const name of found) counts[name]++;
    }
    return { samples: profile.samples?.length || 0, sampledStacksContaining: counts };
  }
  const profiles = { visible: await profilePhase("visible") };
  await page.locator("#fixture-log").evaluate(root => { root.scrollTop += document.querySelector("#first").getBoundingClientRect().bottom - root.getBoundingClientRect().top + 4; });
  await delay();
  const allOffscreen = [await snapshot(first), await snapshot(second)];
  profiles.offscreen = await profilePhase("offscreen");
  assert.deepEqual([await snapshot(first), await snapshot(second)], allOffscreen);
  assert.ok(Object.values(profiles.visible.sampledStacksContaining).some(count => count > 0), JSON.stringify(profiles));
  assert.ok(Object.values(profiles.offscreen.sampledStacksContaining).every(count => count === 0), JSON.stringify(profiles));
  await profiler.send("Profiler.disable"); await profiler.detach();
  await writeFile(path.join(output, "profiles.json"), JSON.stringify(profiles, null, 2));
  pass("native Chromium CPU profiles capture sampling while visible and no sampled scene evaluation/sampling stacks while all scenes are offscreen");
  await second.scrollIntoViewIfNeeded(); await delay();
  const firstOffscreen = await snapshot(first), secondVisible = await snapshot(second);
  await delay(); assert.deepEqual(await snapshot(first), firstOffscreen); assert.notDeepEqual(await snapshot(second), secondVisible);
  await secondButton.click(); await delay(); const secondPaused = await snapshot(second);
  await first.scrollIntoViewIfNeeded(); await delay(); const firstResumed = await snapshot(first);
  await delay(); assert.notDeepEqual(await snapshot(first), firstResumed);
  await second.scrollIntoViewIfNeeded(); await delay(); assert.deepEqual(await snapshot(second), secondPaused);
  assert.equal(await secondButton.getAttribute("aria-pressed"), "false");
  await first.scrollIntoViewIfNeeded(); await delay();
  await page.evaluate(() => window.setSceneHidden(true)); await delay();
  const hidden = [await snapshot(first), await snapshot(second)]; await delay();
  assert.deepEqual([await snapshot(first), await snapshot(second)], hidden);
  await page.evaluate(() => window.setSceneHidden(false)); await delay();
  assert.notDeepEqual(await snapshot(first), hidden[0]); assert.deepEqual(await snapshot(second), hidden[1]);
  await page.screenshot({ path: path.join(output, "lifecycle-direct-fixture.png") });
  pass("native IntersectionObserver: offscreen values/draws stop, visible scene advances, only intended playback resumes; simulated document visibility gates all");

  await page.evaluate(() => window.sceneFixture.unmount()); await delay();
  assert.deepEqual(await page.evaluate(() => ({ observers: window.sceneProbe.observers.size, frames: window.sceneProbe.frames.size })), { observers: 0, frames: 0 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(fixtureUrl); await page.addScriptTag({ content: bundle }); await delay();
  assert.equal(await firstButton.getAttribute("aria-pressed"), "false");
  const reduced = await value(firstInput); await delay(); assert.equal(await value(firstInput), reduced);
  await firstButton.click(); await delay(); assert.notEqual(await value(firstInput), reduced, "explicit playback remains available under reduced motion");
  await page.emulateMedia({ reducedMotion: "no-preference" }); await delay();
  await page.emulateMedia({ reducedMotion: "reduce" }); await delay();
  assert.equal(await firstButton.getAttribute("aria-pressed"), "false");
  await page.evaluate(() => window.sceneFixture.unmount()); await delay();
  assert.deepEqual(await page.evaluate(() => ({ observers: window.sceneProbe.observers.size, frames: window.sceneProbe.frames.size })), { observers: 0, frames: 0 });
  pass("StrictMode/unmount releases observers and rAF; reduced motion suppresses autoplay and preference changes stop motion");
  assert.deepEqual(errors, []);
  const result = { result: "PASS", checks, layout, profiles, screenshots: output, boundary: "Native Chromium layout, range/touch/keyboard, canvas, CPU profiles and IntersectionObserver. document.hidden and visibilitychange are deterministic browser probes; CSS zoom 2 is layout stress, not a claim of native browser toolbar zoom. Draw counts and short synthetic CPU profiles are execution checks, not frame-rate or power measurements." };
  await writeFile(path.join(output, "results.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
} finally { await browser.close(); }
