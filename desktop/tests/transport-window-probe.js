"use strict";

// Optional GUI-runtime probe; deliberately excluded from headless contracts.
// Run: npx electron tests/transport-window-probe.js (from desktop/).
const { app, BrowserWindow } = require("electron");
const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const { rendererHeaders } = require("../runtime/transport-boundary");

const secret = crypto.randomBytes(32).toString("hex");
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-window-probe-"));
app.setPath("userData", temporary);
const received = [];
const server = http.createServer((req, res) => {
  if (req.url.startsWith("/api/")) {
    const authorized = req.headers["x-mathtutor-bridge"] === secret;
    received.push(authorized);
    res.writeHead(authorized ? 200 : 403, { "Content-Type": "application/json" });
    res.end('{"ok":true}');
  } else {
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end("<!doctype html><title>Transport fixture</title><body>Fixture</body>");
  }
});
const alien = http.createServer((_req, res) => res.end("<!doctype html><title>Untrusted origin</title>"));
const listen = listener => new Promise(resolve => listener.listen(0, "127.0.0.1", resolve));

app.whenReady().then(async () => {
  await Promise.all([listen(server), listen(alien)]);
  const frontend = `http://127.0.0.1:${server.address().port}`;
  const win = new BrowserWindow({ show: false, webPreferences: {
    contextIsolation: true, nodeIntegration: false, sandbox: true, webSecurity: true,
  } });
  win.webContents.session.webRequest.onBeforeSendHeaders((details, callback) => {
    callback({ requestHeaders: rendererHeaders(details, win.webContents.id, frontend, secret) });
  });
  await win.loadURL(frontend);
  const result = await win.webContents.executeJavaScript(
    "fetch('/api/probe').then(async response => ({status: response.status, body: await response.text()}))",
  );
  assert.equal(result.status, 200);
  assert.equal(result.body.includes(secret), false);
  assert.equal(received[0], true);
  await win.loadURL(`http://127.0.0.1:${alien.address().port}`);
  await win.webContents.executeJavaScript(
    `fetch(${JSON.stringify(frontend + "/api/probe")}, {mode: 'no-cors'}).then(() => true).catch(() => false)`,
  );
  assert.deepEqual(received, [true, false]);
  console.log("PASS: real Electron trusted-frame injection, secret-free renderer response, and alien-frame rejection");
  win.destroy();
  app.exit(0);
}).catch(error => {
  console.error(error.message);
  app.exit(1);
});

process.on("exit", () => {
  server.close();
  alien.close();
  fs.rmSync(temporary, { recursive: true, force: true });
});
