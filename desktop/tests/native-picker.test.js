"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const { validBridgeHeader } = require("../runtime/transport-boundary");
const bridgeSecret = "isolated-native-picker-test-" + "x".repeat(32);

const main = fs.readFileSync(path.join(__dirname, "..", "main.js"), "utf8");
const start = main.indexOf("function startPickerServer(port)");
const end = main.indexOf("\nfunction stopPickerServer", start);
const factory = main.slice(start, end) + "\nstartPickerServer;";

async function picker(run) {
  const calls = [];
  let reads = 0;
  const create = vm.runInNewContext(factory, {
    http, path, HOST: "127.0.0.1", MAX_PICK_BYTES: 20 * 1024 * 1024,
    validBridgeHeader, bridgeSecret,
    PICK_FILTERS: [{ name: "学习资料", extensions: ["md"] }],
    BrowserWindow: { getFocusedWindow: () => undefined },
    dialog: { showOpenDialog: async (_window, options) => { calls.push(options); return { canceled: false, filePaths: ["/测试目录/课堂.md"] }; } },
    fs: { readFile: (_path, callback) => { reads++; callback(null, Buffer.from("课堂资料")); } },
  });
  const server = create(0);
  await new Promise(resolve => server.on("listening", resolve));
  const endpoint = `http://127.0.0.1:${server.address().port}`;
  try { await run({ endpoint, calls, reads: () => reads }); }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

test("directory selection returns only the chosen path and never reads or scans files", async () => {
  await picker(async ({ endpoint, calls, reads }) => {
    const response = await fetch(endpoint + "/native-directory", { method: "POST", headers: { "Content-Type": "application/json", "X-MathTutor-Bridge": bridgeSecret }, body: JSON.stringify({ student_id: "owner" }) });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { cancelled: false, path: "/测试目录/课堂.md" });
    assert.deepEqual(Array.from(calls[0].properties), ["openDirectory"]);
    assert.equal(reads(), 0);
  });
});

test("file selection retains its single-file byte import contract", async () => {
  await picker(async ({ endpoint, calls, reads }) => {
    const response = await fetch(endpoint + "/native-pick", { method: "POST", headers: { "Content-Type": "application/json", "X-MathTutor-Bridge": bridgeSecret }, body: JSON.stringify({ student_id: "owner" }) });
    const result = await response.json();
    assert.equal(response.status, 200);
    assert.deepEqual(Array.from(calls[0].properties), ["openFile"]);
    assert.equal(result.filename, "课堂.md");
    assert.equal(Buffer.from(result.data_base64, "base64").toString(), "课堂资料");
    assert.equal(reads(), 1);
  });
});

test("web origins and simple form requests cannot open native dialogs", async () => {
  await picker(async ({ endpoint, calls }) => {
    for (const headers of [{ "Content-Type": "application/json", Origin: "https://example.invalid" }, { "Content-Type": "text/plain" }]) {
      const response = await fetch(endpoint + "/native-directory", { method: "POST", headers, body: JSON.stringify({ student_id: "owner" }) });
      assert.equal(response.status, 403);
    }
    const denied = await fetch(endpoint + "/native-directory", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
    assert.equal(denied.status, 403);
    const response = await fetch(endpoint + "/native-directory", { method: "POST", headers: { "Content-Type": "application/json", "X-MathTutor-Bridge": bridgeSecret }, body: "{}" });
    assert.equal(response.status, 400);
    assert.equal(calls.length, 0);
  });
});
