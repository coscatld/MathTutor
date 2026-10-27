// Run against `npm run dev -- --port 3198`. All API/WS traffic is mocked.
import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const output = await mkdtemp(path.join(tmpdir(), "mathtutor-function-graph-"));
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const graph = {
  v: 1, title: "函数读数练习", x_range: [-4, 6], y_range: [-10, 14],
  series: [
    { label: "y = x + 2", segments: [[[-4, -2], [0, 2], [6, 8]]] },
    { label: "分段曲线", segments: [[[-4, -8], [-2, -4]], [[2, 4], [6, 12]]] },
  ],
  vertical: [], marks: [], note: "",
};
const summary = {
  cycle_id: "graph-cycle", state_version: 1, state: "awaiting_attempt",
  problem_context: { problem_id: "p", display_text: "比较两条曲线的函数值", skill_ids: [], lifecycle: "ACTIVE", current_subgoal: null },
  messages: [{ message_id: "graph-message", role: "tutor", content: `函数读数练习\n\n\`\`\`mathtutor-graph\n${JSON.stringify(graph)}\n\`\`\``, action: "SHOW_GRAPH", assistance_level: 0 }],
};
const settings = { is_configured: true, onboarding_completed: true, preset_id: "deepseek", model: "deepseek-flash", base_url: "https://api.deepseek.com", key_masked: "••••8055", provider_configs: {}, vision_mode: "auto" };
await page.route("**/api/**", async route => {
  const url = new URL(route.request().url());
  let body = [];
  if (url.pathname.endsWith("/auth/status")) body = { enabled: false, authenticated: true };
  else if (url.pathname.endsWith("/bootstrap")) body = { phase: "READY", readiness: "READY", steps: [] };
  else if (url.pathname.endsWith("/settings")) body = settings;
  else if (url.pathname.endsWith("/presets")) body = [{ preset_id: "deepseek", label: "DeepSeek", default_model: "deepseek-flash", base_url: "https://api.deepseek.com", editable_base_url: true }];
  else if (url.pathname.endsWith("/sessions")) body = [{ conversation_id: "function-graph", title: "函数读数练习" }];
  else if (url.pathname.includes("/sessions/")) body = summary;
  else if (url.pathname.endsWith("/resources")) body = { documents: [], images: [], message_count: 1 };
  else if (url.pathname.includes("embedding")) body = { enabled: false, provider: "local", status: "disabled", local_models: [], status_label: "未启用 Embedding" };
  await route.fulfill({ json: body });
});
let socket;
await page.routeWebSocket("**/api/**", ws => { socket = ws; });
const replaceGraph = (spec, prose, version) => socket.send(JSON.stringify({
  event_type: "assistant_delta", cycle_id: "graph-cycle", cycle_state_version: version,
  payload: { message_id: "graph-message", content_mode: "snapshot", student_message: `${prose}\n\n\`\`\`mathtutor-graph\n${JSON.stringify(spec)}\n\`\`\`` },
}));

try {
  const base = process.env.LAYOUT_URL || "http://127.0.0.1:3198";
  await page.goto(`${base}/math-tutor?session=function-graph`);
  const input = page.getByRole("spinbutton", { name: "x 坐标", exact: true });
  await input.waitFor();
  const figure = input.locator("xpath=ancestor::figure");
  const status = figure.getByRole("status");
  const table = figure.getByRole("table");
  assert.equal(await input.getAttribute("min"), "-4");
  assert.equal(await input.getAttribute("max"), "6");
  assert.equal(await status.textContent(), "");
  assert.equal(await table.count(), 0);
  assert.match(await figure.textContent(), /线性插值.*不跨段插值/);

  // Keyboard traversal reaches both controls, and Enter submits without a pointer.
  await page.locator("body").click({ position: { x: 2, y: 2 } });
  for (let i = 0; i < 80 && !await input.evaluate(el => el === document.activeElement); i += 1) await page.keyboard.press("Tab");
  assert.equal(await input.evaluate(el => el === document.activeElement), true);
  await page.keyboard.press("Tab");
  assert.equal(await figure.getByRole("button", { name: "读取", exact: true }).evaluate(el => el === document.activeElement), true);
  await page.keyboard.press("Shift+Tab");
  assert.equal(await input.evaluate(el => el === document.activeElement), true);
  await input.fill("0");
  assert.equal(await status.textContent(), "");
  await input.press("Enter");
  await table.waitFor();
  assert.match(await table.textContent(), /x = 0 的函数读数.*y = x \+ 2.*2.*分段曲线.*无定义/);
  assert.match(await status.textContent(), /x = 0.*y = x \+ 2：2.*分段曲线：无定义/);
  assert.equal(await status.getAttribute("aria-live"), "polite");
  const firstStatusNode = await status.locator("span").elementHandle();
  await input.press("Enter");
  assert.equal(await firstStatusNode.evaluate(el => el.isConnected), false, "repeating a reading refreshes the live region node");

  const firstAnnouncement = await status.textContent();
  await input.fill("3");
  assert.equal(await status.textContent(), firstAnnouncement, "typing does not announce speculative results");
  const canvas = figure.getByRole("img", { name: "函数读数练习", exact: true });
  const box = await canvas.boundingBox();
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.5);
  assert.match(await figure.locator('[aria-hidden="true"]').last().textContent(), /x =/);
  assert.equal(await status.textContent(), firstAnnouncement, "pointer movement must not update the live region");
  assert.match(await table.textContent(), /x = 0 的函数读数/);
  await input.press("Enter");
  assert.match(await table.textContent(), /x = 3 的函数读数.*y = x \+ 2.*5.*分段曲线.*6/);

  // Reparsing identical graph data during streaming keeps the active reading.
  replaceGraph(structuredClone(graph), "补充后的函数读数练习", 2);
  await page.getByText("补充后的函数读数练习", { exact: true }).waitFor();
  assert.match(await table.textContent(), /x = 3 的函数读数/);
  assert.equal(await input.inputValue(), "3");

  for (const [x, a, b] of [["-4", "-2", "-8"], ["6", "8", "12"]]) {
    await input.fill(x);
    await input.press("Enter");
    assert.match(await table.textContent(), new RegExp(`x = ${x} 的函数读数.*y = x \\+ 2.*${a}.*分段曲线.*${b}`));
  }
  for (const invalid of ["-5", "7", "", "1e309"]) {
    await input.fill(invalid);
    await input.press("Enter");
    assert.equal(await input.getAttribute("aria-invalid"), "true", `${invalid || "empty"} is rejected`);
    assert.match(await status.textContent(), /请输入 -4 到 6 之间的有限数值/);
    assert.match(await table.textContent(), /x = 6 的函数读数/, "invalid input does not replace the last valid result");
  }
  const firstErrorNode = await status.locator("span").elementHandle();
  await input.press("Enter");
  assert.equal(await firstErrorNode.evaluate(el => el.isConnected), false, "repeating an invalid submission refreshes its announcement");
  await input.fill("1");
  await input.press("Enter");
  assert.equal(await input.getAttribute("aria-invalid"), null);
  assert.match(await table.textContent(), /x = 1 的函数读数.*y = x \+ 2.*3.*分段曲线.*无定义/);

  // A genuinely different graph clears old results, errors and announcements.
  await input.fill("7");
  await input.press("Enter");
  const changedGraph = { ...graph, title: "新的函数读数练习", x_range: [10, 20], series: [{ label: "新曲线", segments: [[[10, 1], [20, 2]]] }] };
  replaceGraph(changedGraph, "已更新图像", 3);
  await figure.getByRole("img", { name: "新的函数读数练习", exact: true }).waitFor();
  assert.equal(await input.inputValue(), "10");
  assert.equal(await input.getAttribute("min"), "10");
  assert.equal(await input.getAttribute("aria-invalid"), null);
  assert.equal(await table.count(), 0);
  assert.equal(await status.textContent(), "");
  const hugeGraph = { ...graph, title: "有限大数读数练习", series: [{ label: "有限大数曲线", segments: [[[-4, Number.MAX_VALUE], [6, Number.MAX_VALUE]]] }] };
  replaceGraph(hugeGraph, "检查有限大数端点", 4);
  await figure.getByRole("img", { name: "有限大数读数练习", exact: true }).waitFor();
  await input.fill("-4");
  await input.press("Enter");
  assert.ok((await table.textContent()).includes("1.7976931e+308"), "finite maximum y must remain finite when formatted");
  assert.doesNotMatch(await status.textContent(), /Infinity/);
  replaceGraph(graph, "恢复函数读数练习", 5);
  await canvas.waitFor();
  await input.fill("1");
  await input.press("Enter");
  await page.mouse.move(1, 1);
  await figure.screenshot({ path: path.join(output, "desktop-keyboard-readout.png") });
  await page.evaluate(() => document.documentElement.classList.add("dark"));
  await figure.screenshot({ path: path.join(output, "desktop-dark.png") });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => document.documentElement.classList.remove("dark"));
  await input.scrollIntoViewIfNeeded();
  await input.fill("2.5");
  await input.press("Enter");
  assert.match(await table.textContent(), /x = 2.5 的函数读数.*4.5.*分段曲线.*5/);
  const dimensions = await figure.evaluate(el => ({ width: el.getBoundingClientRect().width, scrollWidth: el.scrollWidth, viewportWidth: innerWidth }));
  assert.ok(dimensions.width <= dimensions.viewportWidth && dimensions.scrollWidth <= Math.ceil(dimensions.width), JSON.stringify(dimensions));
  assert.ok((await input.boundingBox()).height >= 44);
  assert.ok((await figure.getByRole("button", { name: "读取", exact: true }).boundingBox()).height >= 44);
  await figure.screenshot({ path: path.join(output, "mobile-keyboard-readout.png") });
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ ok: true, checks: ["keyboard traversal and Enter", "all series and segment gaps", "range endpoints", "invalid and nonfinite input", "submit-only announcements", "pointer readout preserved", "streaming rerender preserves state", "changed graph resets state", "mobile overflow and 44px targets"], screenshots: output }));
} finally {
  await browser.close();
}
