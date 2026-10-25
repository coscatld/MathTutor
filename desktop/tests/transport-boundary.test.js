"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { rendererHeaders, validBridgeHeader, secretRedactor } = require("../runtime/transport-boundary");
const frontend = "http://127.0.0.1:31245";
const secret = "per-launch-" + "s".repeat(48);
const details = { webContentsId: 17, frame: { url: frontend + "/math-tutor" },
  url: frontend + "/api/v2/math-tutor/sessions", requestHeaders: {} };

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
