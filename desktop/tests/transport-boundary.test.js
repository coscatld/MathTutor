"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");
const { BACKEND_ENTRY } = require("../runtime/paths");
const { rendererHeaders, validBridgeHeader, secretRedactor, isZhihuSourceLink, isReadingLink } = require("../runtime/transport-boundary");
const frontend = "http://127.0.0.1:31245";
const secret = "per-launch-" + "s".repeat(48);
const details = { webContentsId: 17, frame: { url: frontend + "/math-tutor" },
  url: frontend + "/api/v2/math-tutor/sessions", requestHeaders: {} };

test("development and packaged backends keep auth budgets on the direct socket peer", () => {
  // Evaluate the real launch helper without booting Electron or any service.
  const source = fs.readFileSync(path.join(__dirname, "..", "main.js"), "utf8");
  const start = source.indexOf("function backendCommand(");
  const end = source.indexOf("\nfunction frontendCommand(", start);
  assert.ok(start >= 0 && end > start);
  for (const IS_PACKAGED of [false, true]) {
    const command = vm.runInNewContext(
      source.slice(start, end) + '\nbackendCommand({ python: "test-python" }, 45678)',
      { IS_PACKAGED, HOST: "127.0.0.1", BACKEND_ENTRY },
    );
    assert.equal(command.cmd, "test-python");
    assert.equal(command.args[command.args.indexOf("--factory") + 1], BACKEND_ENTRY);
    assert.equal(command.args[command.args.indexOf("--host") + 1], "127.0.0.1");
    assert.equal(command.args.filter(arg => arg === "--no-proxy-headers").length, 1);
    assert.equal(command.args.includes("--proxy-headers"), false);
  }
});

test("only the exact trusted renderer frame and API destination get the credential", () => {
  assert.equal(rendererHeaders(details, 17, frontend, secret)["X-MathTutor-Bridge"], secret);
  assert.equal(rendererHeaders({ ...details, url: details.url.replace("http:", "ws:") }, 17, frontend, secret)["X-MathTutor-Bridge"], secret);
  for (const changed of [
    { webContentsId: 18 }, { frame: null }, { frame: { url: "https://evil.example" } },
    { frame: { url: frontend.replace("31245", "31246") } },
    { url: "https://evil.example/api/v2/auth/status" }, { url: frontend + "/image.png" },
    { requestHeaders: { Origin: "null" } }, { requestHeaders: { Origin: "https://evil.example" } },
  ]) {
    const headers = rendererHeaders({ ...details, ...changed }, 17, frontend, secret);
    assert.equal(headers["X-MathTutor-Bridge"], undefined);
  }
});

test("spoofed or redirected credential headers are stripped", () => {
  const headers = rendererHeaders({ ...details, url: "https://evil.example/", requestHeaders: {
    "x-mathtutor-bridge": secret, "X-MathTutor-Bridge": secret } }, 17, frontend, secret);
  assert.deepEqual(headers, {});
  assert.equal(validBridgeHeader(undefined, secret), false);
  assert.equal(validBridgeHeader("wrong", secret), false);
  assert.equal(validBridgeHeader(secret, secret), true);
});

test("service output redacts credentials even across arbitrary pipe chunk boundaries", () => {
  let logged = "";
  const redactor = secretRedactor(secret, text => { logged += text; });
  const text = "request header: " + secret + "\nready\n";
  for (let index = 0; index < text.length; index += 7) redactor.write(text.slice(index, index + 7));
  redactor.end();
  assert.equal(logged, "request header: [redacted]\nready\n");
  assert.equal(logged.includes(secret), false);
});

test("desktop source clicks open only HTTPS Zhihu content pages", () => {
  for (const url of [
    "https://www.zhihu.com/question/12/answer/34?utm_medium=openapi_platform",
    "https://zhuanlan.zhihu.com/p/22", "https://zhihu.com/en/answer/44",
  ]) assert.equal(isZhihuSourceLink(url), true);
  for (const url of [
    "https://www.zhihu.com/", "http://www.zhihu.com/question/12",
    "https://www.zhihu.com:8080/question/12", "https://example.org/question/12",
    "file:///question/12", "https://www.zhihu.com/redirect?target=other", undefined,
  ]) assert.equal(isZhihuSourceLink(url), false);
});

test("desktop public readings open only revisions, licensed book sections and the license", () => {
  for (const link of [
    "https://zh.wikipedia.org/w/index.php?oldid=13", "https://en.wikibooks.org/w/index.php?oldid=52",
    "https://discrete.openmathbooks.org/dmoi3/sec_logic-proofs.html", "https://activecalculus.org/single/sec-1-7-lim-cont-diff.html",
    "https://creativecommons.org/licenses/by-sa/4.0/", "https://www.zhihu.com/question/12",
  ]) assert.equal(isReadingLink(link), true, link);
  for (const link of [
    "https://zh.wikipedia.org.evil.test/w/index.php?oldid=13", "https://en.wikibooks.org/w/index.php?oldid=7&returnto=other",
    "https://user@en.wikipedia.org/w/index.php?oldid=2", "https://activecalculus.org/single/unrelated.html",
    "https://en.wikipedia.org/w/index.php?oldid=0", "https://en.wikibooks.org/wiki/Special:Redirect", "file:///tmp/private",
  ]) assert.equal(isReadingLink(link), false, link);
});
