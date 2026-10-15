"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const { EventEmitter, once } = require("node:events");
const { spawn } = require("node:child_process");
const { createServer } = require("node:http");
const { claimSingleInstance, monitorService, waitForService } = require("../runtime/startup");

test("a second instance quits before starting services; the owner restores its window", () => {
  const second = new EventEmitter();
  second.requestSingleInstanceLock = () => false;
  let quit = false;
  second.quit = () => { quit = true; };
  assert.equal(claimSingleInstance(second, () => []), false);
  assert.equal(quit, true);

  const first = new EventEmitter();
  first.requestSingleInstanceLock = () => true;
  const actions = [];
  const window = { isMinimized: () => true, restore: () => actions.push("restore"),
    show: () => actions.push("show"), focus: () => actions.push("focus") };
  let windows = [];
  assert.equal(claimSingleInstance(first, () => windows), true);
  first.emit("second-instance"); // duplicate while still starting
  windows = [window];
  first.emit("second-instance");
  assert.deepEqual(actions, ["restore", "show", "focus"]);
});

test("a failed service reports its exit and stderr without waiting for the health timeout", async () => {
  const child = spawn(process.execPath, ["-e", "console.error('migration sentinel 023/024'); process.exit(7)"]);
  const log = [];
  const service = monitorService(child, (data) => log.push(data));
  await once(child, "close");
  await assert.rejects(waitForService("http://127.0.0.1:1/health", {
    timeoutMs: 60000, what: "本地辅导服务", services: [service],
  }), /已退出（exit=7）[\s\S]*migration sentinel 023\/024/);
  assert.match(log.join(""), /migration sentinel/);
});

test("spawn errors are owned and included in the startup failure", async () => {
  const child = spawn("missing-mathtutor-startup-executable-24792", []);
  const service = monitorService(child);
  await new Promise((resolve) => child.once("error", resolve));
  await assert.rejects(waitForService("http://127.0.0.1:1/health", {
    timeoutMs: 60000, what: "本地辅导服务", services: [service],
  }), /ENOENT/);
});

test("health can recover from a pending service and a hung response cannot bypass the timeout", async () => {
  let ready = false;
  const server = createServer((req, res) => {
    if (req.url === "/hung") return;
    res.writeHead(ready ? 200 : 503).end();
    ready = true;
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    assert.equal(await waitForService(`${base}/health`, { timeoutMs: 3000, what: "service", intervalMs: 5 }), true);
    await assert.rejects(waitForService(`${base}/hung`, { timeoutMs: 50, what: "service" }), /未就绪/);
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
});
