// Uses real QuestionBankService tree/detail projections, optionally supplied
// by BANK_FIXTURE_PATH. All network traffic is intercepted; no model is invoked.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFile, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
const project = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const fixture = JSON.parse(process.env.BANK_FIXTURE_PATH ? await readFile(process.env.BANK_FIXTURE_PATH, "utf8") : execFileSync(process.env.MATHTUTOR_TEST_PYTHON || "python3", ["-c", `
import asyncio, json
from mathtutor.question_bank.service import QuestionBankService
bank = QuestionBankService()
fixture = {"banks": {stage: bank.tree(stage) for stage in ["primary", "middle", "high"]}, "details": {}}
for code in ["h2b-u2-p4", "g1a-u7-p2", "g8a-u5-p2"]:
    fixture["details"][code] = asyncio.run(bank.point(code))
print(json.dumps(fixture, ensure_ascii=False))
`], { cwd: project, env: { ...process.env, PYTHONPATH: path.join(project, "src") }, encoding: "utf8", timeout: 30000 }));
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const output = await mkdtemp(path.join(tmpdir(), "mathtutor-bank-browser-"));
const browser = await chromium.launch({ executablePath: process.env.CHROME_EXECUTABLE, headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.emulateMedia({ reducedMotion: "reduce" });
const errors = [], envelopes = [];
page.on("pageerror", e => errors.push(e.message));
await page.route("**/api/**", async route => {
  const url = new URL(route.request().url()), p = url.pathname;
  let json = [];
  if (p.endsWith("/auth/status")) json = { enabled: false, authenticated: true };
  else if (p.endsWith("/bootstrap")) json = { phase: "READY", readiness: "READY", steps: [] };
  else if (p.endsWith("/settings")) json = { is_configured: true, onboarding_completed: true, model: "fixture", preset_id: "local", key_masked: null, provider_configs: {} };
  else if (p.endsWith("/settings/learner")) json = { stage: "high", grade: 11, stages: [{ stage: "primary", label: "小学", grades: [1, 2, 3, 4, 5, 6] }, { stage: "middle", label: "初中", grades: [7, 8, 9] }, { stage: "high", label: "高中", grades: [10, 11, 12] }] };
  else if (p.endsWith("/exercise-bank")) json = fixture.banks[url.searchParams.get("stage") || "high"];
  else if (p.includes("/exercise-bank/points/")) json = fixture.details[p.split("/").at(-1)];
  else if (p.includes("/sessions/")) json = { cycle_id: null, state_version: 0, state: "idle", messages: [], allowed_next_inputs: ["send_message", "submit_problem"] };
  else if (p.includes("embedding")) json = { enabled: false, local_models: [], status: "disabled" };
  await route.fulfill({ json });
});
let resolveLaunch;
const launched = new Promise(resolve => { resolveLaunch = resolve; });
await page.routeWebSocket("**/api/**", ws => ws.onMessage(data => {
  const envelope = JSON.parse(data.toString()); envelopes.push(envelope);
  if (envelope.command === "send_message") resolveLaunch(envelope);
}));
const base = process.env.LAYOUT_URL || "http://localhost:3197";
const screenshot = async name => {
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: path.join(output, `${name}.png`), animations: "disabled" });
};
try {
  await page.goto(`${base}/math-tutor/question-bank`);
  const grade = page.getByRole("combobox", { name: "按年级查看", exact: true });
  await grade.waitFor();
  await grade.selectOption("11");
  assert.equal(await page.locator("summary").filter({ hasText: "高三上 · 选择性必修第三册" }).count(), 1, "recommended cross-year courses must be visible to grade 11");
  assert.equal(await page.locator("summary").filter({ hasText: "高一上 · 必修第一册" }).count(), 0);
  await page.getByRole("searchbox", { name: "搜索知识点", exact: true }).fill("导数与参数");
  await page.getByRole("button", { name: "查看知识点：导数与参数、零点", exact: true }).click();
  const references = page.getByRole("list", { name: "课程参考题", exact: true });
  await references.waitFor();
  assert.equal(await references.locator("details[open]").count(), 0, "reference answers must start hidden");
  await references.locator("summary").first().click();
  const question = fixture.details["h2b-u2-p4"].reference_problems[0];
  await references.getByText(question.reference_answer, { exact: true }).waitFor();
  assert.equal(await references.getByText("参考答案，作答过程未自动核验", { exact: true }).count(), fixture.details["h2b-u2-p4"].reference_problems.length);
  await screenshot("high-school-reference");
  await references.locator("summary").first().click();
  await page.getByRole("button", { name: "小学", exact: true }).click();
  await grade.selectOption("1");
  assert.equal(await grade.locator("option").count(), 7);
  await page.getByRole("searchbox", { name: "搜索知识点", exact: true }).fill("半时");
  await page.getByRole("button", { name: "查看知识点：认识半时", exact: true }).click();
  await page.getByRole("heading", { name: "认识半时", exact: true }).waitFor();
  await page.setViewportSize({ width: 375, height: 812 });
  await page.waitForFunction(() => document.querySelector(".mt-sidebar")?.dataset.collapsed === "true");
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.getByRole("heading", { name: "认识半时", exact: true }).scrollIntoViewIfNeeded();
  await screenshot("primary-reference-mobile");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "初中", exact: true }).click();
  await grade.selectOption("8");
  assert.equal(await grade.locator("option").count(), 4);
  await page.getByRole("searchbox", { name: "搜索知识点", exact: true }).fill("分式的运算");
  await page.getByRole("button", { name: "查看知识点：分式的运算", exact: true }).click();
  await page.getByRole("heading", { name: "分式的运算", exact: true }).waitFor();
  await page.getByRole("button", { name: "高中", exact: true }).click();
  await grade.selectOption("11");
  await page.getByRole("searchbox", { name: "搜索知识点", exact: true }).fill("导数与参数");
  await page.getByRole("button", { name: "查看知识点：导数与参数、零点", exact: true }).click();
  await page.getByRole("button", { name: `请 Tutor 讲解：${question.text}`, exact: true }).click();
  const envelope = await Promise.race([launched, new Promise((_, reject) => setTimeout(() => reject(new Error("question launch timed out")), 10000))]);
  assert.deepEqual(envelope.payload, { text: question.text });
  assert.equal(envelope.command, "send_message");
  assert.ok(!JSON.stringify(envelope).includes(question.reference_answer), "launch must never pass the reference answer");
  assert.deepEqual(errors, []);
  await writeFile(path.join(output, "result.json"), JSON.stringify({ status: "PASS", actual_bank_fixture: true, paid_model_calls: 0, launch: { command: envelope.command, payload: envelope.payload }, page_errors: errors }, null, 2));
  console.log(JSON.stringify({ status: "PASS", output, paid_model_calls: 0 }));
} finally { await browser.close(); }
