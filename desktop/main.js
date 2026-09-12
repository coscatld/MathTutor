"use strict";

/**
 * K12 MathTutor desktop shell — Electron main process.
 *
 * RESPONSIBILITIES (and only these):
 *   1. spawn the local Python product service (standalone project Python +
 *      uvicorn, `--factory` entrypoint) on 127.0.0.1 with a random port;
 *   2. spawn the Next.js frontend (production `next start` when a build
 *      exists, else `next dev`) pointed at that backend;
 *   3. host a loopback-only `/native-pick` HTTP endpoint that opens the OS
 *      file dialog and returns the picked file bytes to the Python bridge
 *      (invoked only on the user's explicit click in the UI);
 *   4. open one BrowserWindow with a locked-down webPreferences.
 *
 * NO business logic lives here: no API keys, no documents, no memory, no
 * tutoring state. The renderer reaches the backend through the Next
 * middleware proxy exactly like the web app; the only Electron-specific path
 * is the native file pick, and it never scans directories — it returns only
 * the bytes of the single file the user picked.
 */

const { app, BrowserWindow, dialog, utilityProcess } = require("electron");
// Under plain node (or with ELECTRON_RUN_AS_NODE=1, which some dev shells
// export) require("electron") returns the binary path string and the API
// objects are undefined. Headless modes (--smoke / --smoke-full) still work
// there; the GUI requires the real Electron runtime (`electron .`).
const isHeadlessNode = !app;
const http = require("node:http");
const net = require("node:net");
const { spawn, spawnSync } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const crypto = require("node:crypto");
const {
  BACKEND_ENTRY,
  resolveDataLayoutPaths,
  resolvePythonRuntime,
  resolveResourceRoot,
  resolveUserDataRoot,
  resolveWebRoot,
} = require("./runtime/paths");

const DESKTOP_DIR = __dirname;
const IS_PACKAGED = Boolean(app && app.isPackaged);
const RESOURCES_DIR = resolveResourceRoot({
  isPackaged: IS_PACKAGED,
  resourcesPath: process.resourcesPath,
  desktopDir: DESKTOP_DIR,
});
const WEB_ROOT = resolveWebRoot({
  explicitRoot: process.env.MATHTUTOR_WEB_ROOT,
  isPackaged: IS_PACKAGED,
  resourcesDir: RESOURCES_DIR,
  desktopDir: DESKTOP_DIR,
});
const SERVICE_NAME = "com.mathtutor.product";

const HOST = "127.0.0.1"; // loopback only — never a LAN interface
const BACKEND_READY_TIMEOUT_MS = 60000;
const FRONTEND_READY_TIMEOUT_MS = 120000;
const PICK_FILTERS = [
  { name: "学习资料", extensions: ["txt", "md", "markdown", "tex", "pdf"] },
  { name: "所有文件", extensions: ["*"] },
];
const MAX_PICK_BYTES = 20 * 1024 * 1024; // matches MAX_DOCUMENT_BYTES

const isSmoke = process.argv.includes("--smoke");
// --smoke-full: headless full-product E2E (no GUI window). Starts the real
// backend + frontend on loopback, drives the real product flow over HTTP/WS
// (bootstrap → cycle → attempt → practice offer → backups), kills and
// restarts the backend, then verifies readiness + durability again.
const isSmokeFull = process.argv.includes("--smoke-full");
const isSmokeProduction = process.argv.includes("--smoke-production");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function log(...args) {
  process.stdout.write(`[desktop] ${args.join(" ")}\n`);
}

function fail(message) {
  process.stderr.write(`[desktop] FATAL: ${message}\n`);
  if (app && app.isReady() && !isSmokeFull) {
    // Headless smoke must never block on a GUI error box.
    dialog.showErrorBox("MathTutor 启动失败", message);
  }
  process.exit(1);
}

/** Grab a free loopback port. */
function freePort() {
  return new Promise((resolve, reject) => {
    const srv = net.createServer();
    srv.once("error", reject);
    srv.listen(0, HOST, () => {
      const { port } = srv.address();
      srv.close(() => resolve(port));
    });
  });
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Resolve the Python interpreter that runs the MathTutor product service. */
function resolvePython() {
  const python = resolvePythonRuntime({
    explicitPython: process.env.MATHTUTOR_PYTHON,
    isPackaged: IS_PACKAGED,
    platform: process.platform,
    resourcesDir: RESOURCES_DIR,
    desktopDir: DESKTOP_DIR,
    exists: fs.existsSync,
  });
  if (python) return { python, viaCondaRun: false };
  fail(
    IS_PACKAGED
      ? "安装包缺少内置 Python runtime。请重新安装完整发行包。"
      : "未找到 MathTutor Python：请在项目根目录创建 .venv，或设置 MATHTUTOR_PYTHON。",
  );
}

function backendCommand(python, port) {
  const args = ["-m", "uvicorn", "--factory",
    BACKEND_ENTRY,
    "--host", HOST, "--port", String(port), "--log-level", "warning"];
  return { cmd: python.python, args };
}

function frontendCommand(port) {
  if (IS_PACKAGED) {
    const server = path.join(WEB_ROOT, "server.js");
    if (!fs.existsSync(server)) {
      fail(`安装包缺少 Next.js standalone server（${server}）。`);
    }
    return {
      cmd: process.execPath,
      args: [server],
      cwd: WEB_ROOT,
      env: {
        PORT: String(port),
        HOSTNAME: HOST,
        NODE_PATH: path.join(WEB_ROOT, "vendor_modules"),
      },
    };
  }
  const nextBin = path.join(WEB_ROOT, "node_modules", ".bin", "next");
  if (!fs.existsSync(nextBin)) {
    fail(`未找到 Next.js 可执行文件（${nextBin}）。请先在 web/ 目录执行 npm install。`);
  }
  // A directory may exist without a completed production build — require the
  // BUILD_ID marker so `next start` never crashes on stale artifacts.
  const productionBuild =
    fs.existsSync(path.join(WEB_ROOT, ".next-mathtutor", "BUILD_ID")) ||
    fs.existsSync(path.join(WEB_ROOT, ".next", "BUILD_ID"));
  return {
    cmd: process.execPath, // run through this Node so PATH is irrelevant
    args: [nextBin, productionBuild ? "start" : "dev", "-p", String(port)],
    cwd: WEB_ROOT,
    env: {},
  };
}

/** Production data never lives in the app bundle/source tree. */
function resolveDataLayout() {
  const root = resolveUserDataRoot({
    explicitRoot: process.env.MATHTUTOR_DATA_ROOT,
    electronUserData: app ? app.getPath("userData") : "",
    tempDir: os.tmpdir(),
  });
  const layout = resolveDataLayoutPaths(root);
  for (const directory of [root, layout.uploads, layout.backups, layout.config, layout.logs]) {
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  }
  return layout;
}

function backendEnvironment(dataLayout, extra = {}) {
  return {
    MATHTUTOR_DATA_ROOT: dataLayout.root,
    MATHTUTOR_DB_PATH: dataLayout.database,
    // A packaged backend must never inherit a checkout/editable import path.
    PYTHONPATH: IS_PACKAGED ? path.join(RESOURCES_DIR, "python-app") : process.env.PYTHONPATH,
    PYTHONNOUSERSITE: IS_PACKAGED ? "1" : process.env.PYTHONNOUSERSITE,
    ...extra,
  };
}

function authEnvironment(value) {
  const normalized = String(value);
  return { MATHTUTOR_AUTH_ENABLED: normalized, AUTH_ENABLED: normalized };
}

function packagedImportProbe(python, cwd) {
  if (!IS_PACKAGED) return null;
  const appRoot = path.join(RESOURCES_DIR, "python-app");
  const code = [
    "import json, pathlib",
    "import mathtutor.standalone as standalone",
    "import mathtutor.infrastructure.schema as schema",
    "import mathtutor.infrastructure.verifier_worker as worker",
    `root = pathlib.Path(${JSON.stringify(appRoot)}).resolve()`,
    "mods = {'standalone': standalone, 'schema': schema, 'verifier_worker': worker}",
    "files = {k: str(pathlib.Path(v.__file__).resolve()) for k, v in mods.items()}",
    "assert all(pathlib.Path(f).is_relative_to(root) for f in files.values()), files",
    "print(json.dumps(files, sort_keys=True))",
  ].join("; ");
  const env = {
    PATH: process.env.PATH || "/usr/bin:/bin",
    HOME: process.env.HOME || os.homedir(),
    LANG: process.env.LANG || "C.UTF-8",
    PYTHONPATH: appRoot,
    PYTHONNOUSERSITE: "1",
  };
  const result = spawnSync(python.python, ["-c", code], {
    cwd,
    env,
    encoding: "utf8",
    timeout: 30000,
  });
  if (result.status !== 0) {
    throw new Error(`packaged self-contained import failed: ${(result.stderr || result.stdout).trim()}`);
  }
  const files = JSON.parse(result.stdout.trim());
  log(`smoke: SELF_CONTAINED_IMPORT=${JSON.stringify(files)}`);
  return files;
}

function startMockProvider(port) {
  const server = http.createServer((req, res) => {
    // Never log or echo Authorization. The sentinel exists only in the
    // test-profile InMemorySecretStore.
    if (req.method === "GET" && req.url === "/v1/models") {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ data: [{ id: "local-smoke-model" }] }));
      return;
    }
    if (req.method === "POST" && req.url === "/v1/chat/completions") {
      let body = "";
      req.setEncoding("utf8");
      req.on("data", (chunk) => { body += chunk; });
      req.on("end", () => {
        let practiceGenerator = false;
        try {
          const payload = JSON.parse(body);
          practiceGenerator = Array.isArray(payload.messages) && payload.messages.some(
            (message) => typeof message.content === "string" &&
              message.content.includes("K12 数学练习题生成器"),
          );
        } catch {}
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({
          choices: [{
            // A transfer task must not share the parent's answer (x=2).
            message: { content: practiceGenerator ? '["3x + 1 = 10"]' : "本地 mock 表达。" },
            finish_reason: "stop",
          }],
        }));
      });
      return;
    }
    res.writeHead(404).end();
  });
  server.listen(port, HOST);
  return server;
}

// ---------------------------------------------------------------------------
// Loopback native picker endpoint (dialog only, explicit user click).
// ---------------------------------------------------------------------------

let pickerServer = null;

function startPickerServer(port) {
  const server = http.createServer((req, res) => {
    if (req.method !== "POST" || req.url !== "/native-pick") {
      res.writeHead(404).end();
      return;
    }
    let body = "";
    req.on("data", (chunk) => {
      body += chunk;
      if (body.length > 64 * 1024) req.destroy();
    });
    req.on("end", () => {
      let payload;
      try {
        payload = JSON.parse(body || "{}");
      } catch {
        res.writeHead(400, { "Content-Type": "application/json" }).end(
          JSON.stringify({ error: "malformed request" }),
        );
        return;
      }
      if (typeof payload.student_id !== "string" || !payload.student_id) {
        res.writeHead(400, { "Content-Type": "application/json" }).end(
          JSON.stringify({ error: "student_id required" }),
        );
        return;
      }
      // The OS dialog is opened ONLY here, and only because the UI's
      // explicit "添加资料" click reached this endpoint via the bridge.
      dialog
        .showOpenDialog(BrowserWindow.getFocusedWindow() || undefined, {
          title: "选择学习资料",
          properties: ["openFile"],
          filters: PICK_FILTERS,
        })
        .then((result) => {
          if (result.canceled || result.filePaths.length === 0) {
            res.writeHead(200, { "Content-Type": "application/json" }).end(
              JSON.stringify({ cancelled: true }),
            );
            return;
          }
          const filePath = result.filePaths[0];
          fs.readFile(filePath, (err, data) => {
            if (err || data.length === 0) {
              res.writeHead(200, { "Content-Type": "application/json" }).end(
                JSON.stringify({ cancelled: true }),
              );
              return;
            }
            if (data.length > MAX_PICK_BYTES) {
              res.writeHead(200, { "Content-Type": "application/json" }).end(
                JSON.stringify({
                  error: "文件超过 20MB 上限，请选择更小的文件。",
                }),
              );
              return;
            }
            const mime =
              path.extname(filePath).toLowerCase() === ".pdf" ? "application/pdf" : "text/plain";
            res.writeHead(200, { "Content-Type": "application/json" }).end(
              JSON.stringify({
                filename: path.basename(filePath),
                mime_type: mime,
                data_base64: data.toString("base64"),
                original_path: filePath,
              }),
            );
          });
        })
        .catch(() => {
          res.writeHead(500, { "Content-Type": "application/json" }).end(
            JSON.stringify({ error: "picker failed" }),
          );
        });
    });
  });
  server.listen(port, HOST);
  return server;
}

function stopPickerServer() {
  if (pickerServer) {
    pickerServer.close();
    pickerServer = null;
  }
}

// ---------------------------------------------------------------------------
// Process lifecycle
// ---------------------------------------------------------------------------

const children = [];

function startChild(cmd, args, env, cwd) {
  const child = spawn(cmd, args, {
    env: { ...process.env, ...env },
    cwd: cwd || undefined,
    stdio: isSmoke ? "inherit" : ["ignore", "pipe", "pipe"],
  });
  children.push(child);
  if (!isSmoke) {
    child.stdout.on("data", (d) => process.stdout.write(`[child] ${String(d)}`));
    child.stderr.on("data", (d) => process.stderr.write(`[child] ${String(d)}`));
  }
  child.on("exit", (code, signal) => {
    const idx = children.indexOf(child);
    if (idx >= 0) children.splice(idx, 1);
    if ((!app || !app.isQuitting) && code !== 0 && signal !== "SIGTERM") {
      log(`child exited unexpectedly (code=${code}, signal=${signal})`);
    }
  });
  return child;
}

/** Run the packaged Next server as a Chromium utility process.
 *
 * Spawning process.execPath directly starts the executable inside the .app a
 * second time. macOS may then surface that background server as an extra
 * generic "exec" application icon. UtilityProcess uses Electron's dedicated
 * helper service, which stays background-only while preserving the Node
 * runtime Next standalone needs.
 */
function startPackagedFrontend(server, env, cwd) {
  if (!utilityProcess) fail("Electron utility process API unavailable.");
  const runner = path.join(DESKTOP_DIR, "runtime", "frontend-runner.js");
  const child = utilityProcess.fork(runner, [server], {
    env: { ...process.env, ...env, MATHTUTOR_WEB_CWD: cwd },
    cwd,
    stdio: "pipe",
    serviceName: "MathTutor Web Runtime",
  });
  children.push(child);
  child.stdout?.on("data", (d) => process.stdout.write(`[child] ${String(d)}`));
  child.stderr?.on("data", (d) => process.stderr.write(`[child] ${String(d)}`));
  child.on("exit", (code) => {
    const idx = children.indexOf(child);
    if (idx >= 0) children.splice(idx, 1);
    if ((!app || !app.isQuitting) && code !== 0) {
      log(`frontend utility process exited unexpectedly (code=${code})`);
    }
  });
  return child;
}

function stopChildren() {
  for (const child of children) {
    try {
      if ("spawnfile" in child) child.kill("SIGTERM");
      else child.kill();
    } catch {
      /* already gone */
    }
  }
}

async function waitForHttp(url, timeoutMs, what) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url);
      if (res.ok) return true;
    } catch {
      /* not up yet */
    }
    await sleep(300);
  }
  fail(`${what} 在 ${Math.round(timeoutMs / 1000)} 秒内未就绪。`);
  return false;
}

/** Prove the rendered page's browser JS/CSS is actually available. */
async function verifyFrontendAssets(pageUrl) {
  const page = await fetch(pageUrl);
  if (!page.ok) throw new Error(`frontend page returned HTTP ${page.status}`);
  const html = await page.text();
  const paths = [...html.matchAll(/(?:src|href)="(\/_next\/static\/[^"?#]+(?:\?[^"#]*)?)"/g)]
    .map((match) => match[1]);
  const unique = [...new Set(paths)];
  if (unique.length === 0) throw new Error("frontend page referenced no Next.js static assets");
  for (const assetPath of unique) {
    const asset = await fetch(new URL(assetPath, pageUrl));
    if (!asset.ok) {
      throw new Error(`frontend asset ${assetPath} returned HTTP ${asset.status}`);
    }
  }
  return unique.length;
}

// ---------------------------------------------------------------------------
// --smoke-full: headless full-product E2E (no GUI window).
// ---------------------------------------------------------------------------

function waitChildExit(child) {
  return new Promise((resolve) => {
    if (child.exitCode !== null || child.signalCode !== null) {
      resolve();
      return;
    }
    child.once("exit", () => resolve());
  });
}

function descendantPids(rootPids) {
  if (process.platform === "win32") {
    const script = [
      "$items = Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId",
      `$roots = @(${rootPids.filter(Boolean).join(",")})`,
      "$seen = [System.Collections.Generic.HashSet[int]]::new()",
      "$queue = [System.Collections.Generic.Queue[int]]::new()",
      "$roots | ForEach-Object { $queue.Enqueue([int]$_) }",
      "while ($queue.Count -gt 0) { $p = $queue.Dequeue(); $items | Where-Object ParentProcessId -eq $p | ForEach-Object { if ($seen.Add([int]$_.ProcessId)) { $queue.Enqueue([int]$_.ProcessId) } } }",
      "$seen | Sort-Object",
    ].join("; ");
    const result = spawnSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
      encoding: "utf8",
      timeout: 10000,
    });
    if (result.status !== 0) return [];
    return result.stdout
      .split(/\s+/)
      .map(Number)
      .filter((pid) => Number.isInteger(pid) && pid > 0);
  }
  const result = spawnSync("ps", ["-axo", "pid=,ppid="], { encoding: "utf8", timeout: 10000 });
  if (result.status !== 0) return [];
  const byParent = new Map();
  for (const line of result.stdout.split("\n")) {
    const [pid, ppid] = line.trim().split(/\s+/).map(Number);
    if (!Number.isInteger(pid) || !Number.isInteger(ppid)) continue;
    if (!byParent.has(ppid)) byParent.set(ppid, []);
    byParent.get(ppid).push(pid);
  }
  const descendants = [];
  const queue = rootPids.filter(Boolean);
  while (queue.length) {
    const parent = queue.shift();
    for (const pid of byParent.get(parent) || []) {
      descendants.push(pid);
      queue.push(pid);
    }
  }
  return descendants;
}

function processIsAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

async function waitForProcessesGone(pids, timeoutMs = 10000) {
  const unique = [...new Set(pids.filter((pid) => Number.isInteger(pid) && pid > 0))];
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (unique.every((pid) => !processIsAlive(pid))) return true;
    await sleep(100);
  }
  return unique.every((pid) => !processIsAlive(pid));
}

function releaseJsonProbe(python, smokeDir, backendEnv, operation, args = []) {
  const result = spawnSync(
    python.python,
    ["-m", "mathtutor.release_probe", operation, ...args],
    {
    cwd: IS_PACKAGED ? smokeDir : path.resolve(DESKTOP_DIR, ".."),
    env: { ...process.env, ...backendEnv },
    encoding: "utf8",
    timeout: 30000,
    },
  );
  if (result.status !== 0) {
    throw new Error(`Python RC probe failed: ${(result.stderr || result.stdout).trim()}`);
  }
  return JSON.parse(result.stdout.trim());
}

function containsAuthorityLeak(value) {
  const forbiddenKeys = new Set([
    "answer_key", "correct_answer", "final_answer", "solution_candidate",
    "attestation", "verification_log", "hidden_reasoning",
  ]);
  if (Array.isArray(value)) return value.some(containsAuthorityLeak);
  if (!value || typeof value !== "object") return false;
  return Object.entries(value).some(
    ([key, nested]) => forbiddenKeys.has(String(key).toLowerCase()) || containsAuthorityLeak(nested),
  );
}

async function httpJson(url, init) {
  const res = await fetch(url, init);
  const text = await res.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = null;
  }
  return { status: res.status, body, headers: res.headers };
}

/**
 * Drive one WS turn: send one JSON command frame, collect frames until the
 * server's ``turn_end`` marker. Implements a minimal RFC 6455 CLIENT over
 * net + crypto (no dependencies — Electron 33's Node 20 has no WebSocket
 * global, and neither does headless mode). Client→server frames are masked
 * per the RFC; server→client text frames are parsed until ``turn_end``.
 */
function wsTurn(wsUrl, command, payload, sessionId, timeoutMs = 90000) {
  return new Promise((resolve, reject) => {
    let url;
    try {
      url = new URL(wsUrl);
    } catch {
      reject(new Error(`WS URL 无效: ${wsUrl}`));
      return;
    }
    const host = url.hostname;
    const port = url.port ? Number(url.port) : url.protocol === "wss:" ? 443 : 80;
    const socket = net.connect({ host, port });
    const frames = [];
    let buffer = Buffer.alloc(0);
    let handshakeBuf = "";
    let upgraded = false;
    let settled = false;
    let timer = null;

    const finish = (errorMessage) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      reject(new Error(errorMessage));
    };
    timer = setTimeout(() => finish("WS 回合超时（未收到 turn_end）"), timeoutMs);

    const buildClientFrame = (opcode, payloadBuf) => {
      const maskKey = crypto.randomBytes(4);
      let header;
      if (payloadBuf.length < 126) {
        header = Buffer.from([0x80 | opcode, 0x80 | payloadBuf.length]);
      } else if (payloadBuf.length < 65536) {
        header = Buffer.alloc(4);
        header[0] = 0x80 | opcode;
        header[1] = 0x80 | 126;
        header.writeUInt16BE(payloadBuf.length, 2);
      } else {
        header = Buffer.alloc(10);
        header[0] = 0x80 | opcode;
        header[1] = 0x80 | 127;
        header.writeBigUInt64BE(BigInt(payloadBuf.length), 2);
      }
      const masked = Buffer.allocUnsafe(payloadBuf.length);
      for (let i = 0; i < payloadBuf.length; i += 1) masked[i] = payloadBuf[i] ^ maskKey[i % 4];
      return Buffer.concat([header, maskKey, masked]);
    };

    const processFrames = () => {
      for (;;) {
        if (buffer.length < 2) return;
        const b0 = buffer[0];
        const b1 = buffer[1];
        const opcode = b0 & 0x0f;
        let len = b1 & 0x7f;
        let offset = 2;
        if (len === 126) {
          if (buffer.length < 4) return;
          len = buffer.readUInt16BE(2);
          offset = 4;
        } else if (len === 127) {
          if (buffer.length < 10) return;
          const big = buffer.readBigUInt64BE(2);
          if (big > BigInt(Number.MAX_SAFE_INTEGER)) return finish("WS 帧过大");
          len = Number(big);
          offset = 10;
        }
        const masked = (b1 & 0x80) !== 0;
        let maskKey = null;
        if (masked) {
          if (buffer.length < offset + 4) return;
          maskKey = buffer.slice(offset, offset + 4);
          offset += 4;
        }
        if (buffer.length < offset + len) return;
        let payloadBuf = buffer.slice(offset, offset + len);
        buffer = buffer.slice(offset + len);
        if (masked && maskKey) {
          const unmasked = Buffer.allocUnsafe(payloadBuf.length);
          for (let i = 0; i < payloadBuf.length; i += 1) unmasked[i] = payloadBuf[i] ^ maskKey[i % 4];
          payloadBuf = unmasked;
        }
        if (opcode === 0x8) return finish("WS 连接被服务端关闭（close frame）");
        if (opcode === 0x9) {
          socket.write(buildClientFrame(0xa, payloadBuf)); // pong
          continue;
        }
        if (opcode !== 0x1) continue; // skip binary/continuation for smoke
        let frame = null;
        try {
          frame = JSON.parse(payloadBuf.toString("utf8"));
        } catch {
          continue;
        }
        if (frame && typeof frame === "object") frames.push(frame);
        if (frame && frame.event_type === "turn_end") {
          clearTimeout(timer);
          settled = true;
          socket.end();
          resolve(frames);
          return;
        }
      }
    };

    socket.on("connect", () => {
      socket.write(
        `GET ${url.pathname}${url.search} HTTP/1.1\r\n` +
          `Host: ${host}:${port}\r\n` +
          "Upgrade: websocket\r\n" +
          "Connection: Upgrade\r\n" +
          `Sec-WebSocket-Key: ${crypto.randomBytes(16).toString("base64")}\r\n` +
          "Sec-WebSocket-Version: 13\r\n\r\n",
      );
    });

    socket.on("data", (chunk) => {
      if (!upgraded) {
        handshakeBuf += chunk.toString("latin1");
        const idx = handshakeBuf.indexOf("\r\n\r\n");
        if (idx === -1) return;
        const head = handshakeBuf.slice(0, idx);
        if (!/^HTTP\/1\.[01] 101/.test(head)) {
          return finish(`WS 握手失败: ${head.split("\r\n")[0] || "非 101 响应"}`);
        }
        upgraded = true;
        const rest = Buffer.from(handshakeBuf.slice(idx + 4), "latin1");
        handshakeBuf = "";
        buffer = rest;
        socket.write(
          buildClientFrame(0x1, Buffer.from(JSON.stringify({ command, payload, session_id: sessionId }), "utf8")),
        );
        processFrames();
        return;
      }
      buffer = Buffer.concat([buffer, chunk]);
      processFrames();
    });

    socket.on("error", (err) => finish(`WS 连接失败: ${err && err.message ? err.message : err}`));
    socket.on("close", () => {
      if (!settled) finish("WS 连接在回合结束前关闭");
    });
  });
}

function committed(frames) {
  return frames.filter((f) => f && f.event_type === "tutor_action_committed");
}

async function runSmokeFull() {
  const smokeDir = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-smoke-full-"));
  log(`smoke-full: 临时数据目录 ${smokeDir}`);
  const results = [];
  const supplementalResults = [];
  const contractPending = [];
  const record = (name, ok, detail) => {
    results.push({ name, ok, detail: detail || "" });
    log(`smoke-full: ${ok ? "PASS" : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
  };
  const recordContractPending = (name) => {
    contractPending.push(name);
    log(`smoke-full: SKIP ${name} — 后端契约端点尚未接线（MAIN），接入后自动纳入强校验`);
  };
  const assertNamed = (name, ok, detail) => {
    supplementalResults.push({ name, ok, detail: detail || "" });
    log(`smoke-full: ${ok ? "PASS" : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
  };

  log("smoke-full: 解析运行环境…");
  const python = resolvePython();
  frontendCommand(8000); // throws/fails when the Next binary is missing

  let mockProviderPort = 0;
  [backendPort, frontendPort, mockProviderPort] = await Promise.all([
    freePort(), freePort(), freePort(),
  ]);
  backendUrl = `http://${HOST}:${backendPort}`;
  frontendUrl = `http://${HOST}:${frontendPort}`;
  const wsUrl = `ws://${HOST}:${backendPort}/api/v2/math-tutor/ws`;

  const backendEnv = {
    MATHTUTOR_DESKTOP: "1",
    MATHTUTOR_ELECTRON_PICKER_URL: "",
    MATHTUTOR_API_BASE_URL: backendUrl,
    // 本地无认证模式（开发环境 loopback 身份）——仅 full smoke 使用。
    ...authEnvironment("0"),
    // 一次性临时库：smoke 绝不写入用户的真实数据目录；重启仍走同一路径，
    // 所以 durability 断言依然真实。
    MATHTUTOR_DB_PATH: path.join(smokeDir, "math_tutor.db"),
    MATHTUTOR_ENVIRONMENT: "test",
    PYTHONPATH: IS_PACKAGED ? path.join(RESOURCES_DIR, "python-app") : process.env.PYTHONPATH,
    PYTHONNOUSERSITE: IS_PACKAGED ? "1" : process.env.PYTHONNOUSERSITE,
  };
  packagedImportProbe(python, smokeDir);
  const mockProvider = startMockProvider(mockProviderPort);
  const spawnBackend = () => {
    const b = backendCommand(python, backendPort);
    log(`smoke-full: backend: ${b.cmd} ${b.args.join(" ")}`);
    return startChild(b.cmd, b.args, backendEnv, IS_PACKAGED ? smokeDir : DESKTOP_DIR);
  };
  const spawnFrontend = () => {
    const f = frontendCommand(frontendPort);
    log(`smoke-full: frontend: ${f.cmd} ${f.args.join(" ")}`);
    return startChild(f.cmd, f.args, {
      ...f.env,
      MATHTUTOR_API_BASE_URL: backendUrl,
      ...authEnvironment("0"),
      // process.execPath may be the Electron binary; force the next CLI to
      // run as plain Node regardless of how smoke-full itself was launched.
      ELECTRON_RUN_AS_NODE: "1",
    }, f.cwd);
  };

  // 1. Start backend + frontend, wait for both.
  const coldStartAt = Date.now();
  let backendChild = spawnBackend();
  const frontendChild = spawnFrontend();
  await waitForHttp(`${backendUrl}/health`, BACKEND_READY_TIMEOUT_MS, "本地辅导服务");
  log(`smoke-full: METRIC backend_ready_ms=${Date.now() - coldStartAt}`);
  await waitForHttp(`${frontendUrl}/math-tutor`, FRONTEND_READY_TIMEOUT_MS, "前端页面");
  log(`smoke-full: METRIC frontend_ready_ms=${Date.now() - coldStartAt}`);
  const frontendAssetCount = await verifyFrontendAssets(`${frontendUrl}/math-tutor`);
  log(`smoke-full: ASSERT PASS frontend-assets — ${frontendAssetCount} files`);

  // 2. health.
  const health = await httpJson(`${backendUrl}/health`);
  record("health", health.status === 200 && health.body && health.body.status === "ok");
  assertNamed(
    "verifier-worker",
    health.status === 200 && health.body && health.body.verifier === "ok",
    `verifier=${health.body && health.body.verifier}`,
  );

  // 3. bootstrap (poll up to 30s: migrations run at startup).
  {
    const deadline = Date.now() + 30000;
    let bootstrap = null;
    let lastStatus = 0;
    while (Date.now() < deadline) {
      const res = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/bootstrap`);
      lastStatus = res.status;
      if (res.status === 200) {
        bootstrap = res.body;
        break;
      }
      await sleep(1000);
    }
    if (bootstrap === null) {
      if (lastStatus === 404 || lastStatus === 405) {
        recordContractPending("bootstrap");
      } else {
        record("bootstrap", false, `HTTP ${lastStatus}，30s 内未就绪`);
      }
    } else {
      const shapeOk =
        ["READY", "DEGRADED", "BLOCKED"].includes(bootstrap.readiness) &&
        Array.isArray(bootstrap.steps) &&
        bootstrap.steps.every(
          (s) => s && typeof s.key === "string" && typeof s.label === "string" &&
            ["ok", "degraded", "blocked"].includes(s.status),
        );
      record(
        "bootstrap",
        shapeOk,
        `readiness=${bootstrap.readiness}, steps=${bootstrap.steps.length}`,
      );
    }
  }

  // Frozen ReleaseConfig + live Alembic state must agree on the exact head.
  {
    const version = await httpJson(`${backendUrl}/version`);
    const live = releaseJsonProbe(
      python,
      smokeDir,
      backendEnv,
      "migration",
      [backendEnv.MATHTUTOR_DB_PATH],
    );
    const frozen = version.body && version.body.release_config && version.body.release_config.migration_head;
    assertNamed(
      "database-migration",
      version.status === 200 && frozen === "015" && live.head === frozen,
      `frozen=${frozen || "missing"}, live=${live.head || "missing"}`,
    );
  }

  // 4. Local OpenAI-compatible provider: explicit settings PUT + real
  //    /models probe. Test profile guarantees InMemorySecretStore; no network
  //    or real Keychain entry is touched.
  {
    const smokeKey = `smoke-${crypto.randomBytes(18).toString("hex")}`;
    const configured = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        preset_id: "custom",
        api_key: smokeKey,
        base_url: `http://${HOST}:${mockProviderPort}/v1`,
        model: "",
      }),
    });
    const tested = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/model/test`, {
      method: "POST",
    });
    const ready = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/readiness`);
    const gatewayOk = configured.status === 200 && tested.status === 200 &&
      tested.body && tested.body.ok === true && ready.status === 200 &&
      ready.body && ready.body.checks && ready.body.checks.gateway === "ok" &&
      ready.body.checks.embedding === "degraded";
    const configPath = path.join(smokeDir, "gateway.json");
    const persisted = fs.existsSync(configPath) ? fs.readFileSync(configPath, "utf8") : "";
    if (!gatewayOk || persisted.includes(smokeKey)) {
      throw new Error("local provider/readiness assertion failed or secret reached config");
    }
    log("smoke-full: ASSERT PASS local-provider — model/test ok, gateway=ok, embedding=degraded");
  }

  // 5. Desktop-owned knowledge surfaces: one explicit document import and
  //    personal-memory CRUD. These run against the same packaged backend.
  {
    const form = new FormData();
    form.append(
      "file",
      new Blob(["RC_RETRIEVAL_SENTINEL LINEAR_EQUATION：一元一次方程移项时两边做相同运算。"], { type: "text/plain" }),
      "smoke-notes.txt",
    );
    const imported = await httpJson(
      `${backendUrl}/api/v2/math-tutor/desktop/documents/import`,
      { method: "POST", body: form },
    );
    record(
      "document-import",
      imported.status === 200 && imported.body && typeof imported.body.document_id === "string",
      `HTTP ${imported.status}`,
    );
    const retrieval = releaseJsonProbe(
      python,
      smokeDir,
      backendEnv,
      "document-retrieval",
      [backendEnv.MATHTUTOR_DB_PATH, "RC_RETRIEVAL_SENTINEL"],
    );
    assertNamed(
      "document-retrieval",
      imported.status === 200 && retrieval.hit === true && retrieval.vector_used === false,
      `lexical_hit=${retrieval.hit}, vector_used=${retrieval.vector_used}`,
    );

    const memory = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/memory`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        memory_type: "learning_preference",
        subject: "我",
        predicate: "喜欢",
        object_json: { style: "逐步提示" },
      }),
    });
    const memoryOk = memory.status === 200 && memory.body && typeof memory.body.memory_id === "string";
    const memoryList = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/memory`);
    record(
      "memory-crud",
      memoryOk && memoryList.status === 200 && Array.isArray(memoryList.body) &&
        memoryList.body.some((item) => item.memory_id === memory.body.memory_id),
      `create=${memory.status}, list=${memoryList.status}`,
    );
    const memoryId = memoryOk ? memory.body.memory_id : "missing";
    const updated = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/memory/${memoryId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ predicate: "更喜欢", object_json: { style: "例子优先" } }),
    });
    const disabled = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/memory/${memoryId}/retrieval`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: false }),
    });
    const disposable = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/memory`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        memory_type: "learning_preference",
        subject: "临时",
        predicate: "删除验证",
        object_json: { disposable: true },
      }),
    });
    const disposableId = disposable.body && disposable.body.memory_id;
    const deleted = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/memory/${disposableId}`, {
      method: "DELETE",
    });
    const finalList = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/memory`);
    const crudComplete = updated.status === 200 && updated.body && updated.body.predicate === "更喜欢" &&
      disabled.status === 200 && disabled.body && disabled.body.retrieval_enabled === false &&
      disposable.status === 200 && deleted.status === 200 && deleted.body && deleted.body.deleted === true &&
      finalList.status === 200 && Array.isArray(finalList.body) &&
      finalList.body.some((item) => item.memory_id === memoryId && item.retrieval_enabled === false) &&
      !finalList.body.some((item) => item.memory_id === disposableId);
    assertNamed("memory-crud-complete", crudComplete, "create/read/update/toggle/delete");
  }

  // 5. Real product flow over WS: submit_problem → submit_attempt →
  //    solved + independent offer → accept → child judge; preserve parent.
  const sessionId = `smoke-full-${Date.now()}`;
  let parentCycleId = null;
  try {
    const first = await wsTurn(wsUrl, "submit_problem", { text: "2x + 3 = 7" }, sessionId);
    const firstStates = committed(first).map((c) => c.cycle_state);
    assertNamed(
      "submit-problem",
      firstStates.includes("awaiting_attempt"),
      `states=${JSON.stringify(firstStates)}`,
    );
    const incorrect = await wsTurn(wsUrl, "submit_attempt", { answer: "3" }, sessionId);
    const incorrectStates = committed(incorrect).map((c) => c.cycle_state);
    assertNamed(
      "incorrect-attempt",
      incorrectStates.includes("awaiting_retry") && !containsAuthorityLeak(incorrect),
      `states=${JSON.stringify(incorrectStates)}, authority_leak=${containsAuthorityLeak(incorrect)}`,
    );
    const second = await wsTurn(wsUrl, "submit_attempt", { answer: "2" }, sessionId);
    const states = committed(first.concat(incorrect, second)).map((c) => c.cycle_state);
    assertNamed("correct-attempt", states.includes("solved"), `states=${JSON.stringify(states)}`);
    record(
      "cycle-solve",
      states.includes("solved") && !states.includes("practice_offered") &&
        committed(second).at(-1)?.cycle_state === "solved",
      `states=${JSON.stringify(states)}`,
    );

    const offerEvent = committed(second).find(
      (c) => c.payload && c.payload.action === "practice_offered" && c.extra && c.extra.offer_id,
    );
    if (!offerEvent) {
      record("practice-offer", false, "未生成练习邀请");
    } else {
      parentCycleId = offerEvent.extra.parent_cycle_id || null;
      record("practice-offer", true, `offer_id=${offerEvent.extra.offer_id}`);
      const offers = await httpJson(`${backendUrl}/api/v2/math-tutor/offers`);
      const activeMatch =
        offers.status === 200 &&
        Array.isArray(offers.body) &&
        offers.body.some((o) => o.status === "ACTIVE" && o.offer_id === offerEvent.extra.offer_id);
      record("offers-list", activeMatch, activeMatch ? "ACTIVE 邀请可见" : `HTTP ${offers.status}`);

      const accepted = await wsTurn(
        wsUrl,
        "accept_practice_offer",
        { offer_id: offerEvent.extra.offer_id },
        sessionId,
      );
      const started = committed(accepted).find(
        (c) => c.extra && c.extra.child_cycle_id && c.payload && c.payload.action === "practice_started",
      );
      record("offer-accept", Boolean(started), started ? `child=${started.extra.child_cycle_id}` : "无 practice_started");

      if (started) {
        const childId = started.extra.child_cycle_id;
        const child = await httpJson(`${backendUrl}/api/v2/math-tutor/cycles/${childId}`);
        record(
          "child-cycle",
          child.status === 200 && ["awaiting_attempt", "problem_received"].includes(child.body && child.body.state),
          child.status === 200 ? `state=${child.body.state}` : `HTTP ${child.status}`,
        );
        const judged = await wsTurn(wsUrl, "submit_attempt", { answer: "3" }, sessionId);
        const judgedStates = committed(judged).map((c) => c.cycle_state);
        record("child-judge", judgedStates.includes("solved"), `states=${JSON.stringify(judgedStates)}`);
      }
    }
  } catch (err) {
    record("ws-product-flow", false, String(err && err.message ? err.message : err));
  }

  // 6. Backups endpoints, including a verified restore smoke.
  {
    const list = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/backups`);
    if (list.status === 404 || list.status === 405) {
      recordContractPending("backups (GET)");
    } else {
      const shapeOk =
        list.status === 200 &&
        list.body &&
        Array.isArray(list.body.backups) &&
        typeof list.body.backup_dir === "string" &&
        list.body.policy &&
        typeof list.body.policy.retention_limit === "number";
      record("backups-list", shapeOk, shapeOk ? `已有 ${list.body.backups.length} 份备份` : `HTTP ${list.status}`);
      if (shapeOk) {
        const created = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/backup`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        if (created.status === 404 || created.status === 405) {
          recordContractPending("backup (POST)");
        } else {
          const createdOk = created.status === 200 && created.body && created.body.ok === true && created.body.backup;
          record("backup-create", createdOk, createdOk ? `backup=${created.body.backup.path}` : `HTTP ${created.status}`);
          if (createdOk) {
            const verified = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/backup/verify`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ path: created.body.backup.path }),
            });
            if (verified.status === 404 || verified.status === 405) {
              recordContractPending("backup/verify (POST)");
            } else {
              record(
                "backup-verify",
                verified.status === 200 && verified.body && verified.body.ok === true,
                `HTTP ${verified.status}`,
              );
            }
            const restored = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/backup/restore`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ path: created.body.backup.path }),
            });
            record(
              "backup-restore",
              restored.status === 200 && restored.body && restored.body.ok === true &&
                restored.body.restart_required === true,
              `HTTP ${restored.status}${restored.body && restored.body.ok !== true ? ` — ${restored.body.message || "ok=false"}` : ""}`,
            );
          }
        }
      }
    }
  }

  // 7. Restart semantics: kill the backend, respawn on the same port,
  //    readiness again + cycle state survived (durable SQLite).
  log("smoke-full: 重启 backend 子进程（restart 语义）…");
  backendChild.kill("SIGTERM");
  await waitChildExit(backendChild);
  backendChild = spawnBackend();
  await waitForHttp(`${backendUrl}/health`, BACKEND_READY_TIMEOUT_MS, "重启后的本地辅导服务");
  record("restart-health", true);
  const restartBootstrap = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/bootstrap`);
  if (restartBootstrap.status === 404 || restartBootstrap.status === 405) {
    recordContractPending("bootstrap (restart)");
  } else {
    record(
      "restart-bootstrap",
      restartBootstrap.status === 200 &&
        ["READY", "DEGRADED", "BLOCKED"].includes(restartBootstrap.body && restartBootstrap.body.readiness),
      `readiness=${restartBootstrap.body && restartBootstrap.body.readiness}`,
    );
  }
  if (parentCycleId) {
    const parent = await httpJson(`${backendUrl}/api/v2/math-tutor/cycles/${parentCycleId}`);
    record(
      "restart-durability",
      parent.status === 200 && parent.body && parent.body.state === "solved",
      parent.status === 200 ? `parent state=${parent.body.state}` : `HTTP ${parent.status}`,
    );
  }

  // A fresh verified solve after restore/restart proves the restored database,
  // worker and state machine are usable rather than merely readable.
  {
    const restoredSession = `smoke-post-restore-${Date.now()}`;
    const problem = await wsTurn(wsUrl, "submit_problem", { text: "1 + 1" }, restoredSession);
    const attempt = await wsTurn(wsUrl, "submit_attempt", { answer: "2" }, restoredSession);
    const states = committed(problem.concat(attempt)).map((item) => item.cycle_state);
    assertNamed("post-restore-solve", states.includes("solved"), `states=${JSON.stringify(states)}`);
  }

  // 8. Teardown + summary. Kill the respawned backend and remove the temp
  //    data dir BEFORE exiting so no smoke artifacts survive.
  const trackedPids = [backendChild.pid, frontendChild.pid, ...descendantPids([
    backendChild.pid, frontendChild.pid,
  ])];
  backendChild.kill("SIGTERM");
  frontendChild.kill("SIGTERM");
  await waitChildExit(backendChild);
  await waitChildExit(frontendChild);
  const processesGone = await waitForProcessesGone(trackedPids);
  let dataGone = false;
  try {
    fs.rmSync(smokeDir, { recursive: true, force: true });
    dataGone = !fs.existsSync(smokeDir);
  } catch {
    dataGone = false;
  }
  await new Promise((resolve) => mockProvider.close(resolve));
  assertNamed(
    "clean-shutdown",
    processesGone && dataGone,
    `tracked=${trackedPids.length}, processes_gone=${processesGone}, temp_removed=${dataGone}`,
  );
  const failed = results.concat(supplementalResults).filter((r) => !r.ok);
  log(
    `smoke-full: 完成 — ${results.filter((r) => r.ok).length}/${results.length} 步通过` +
      (contractPending.length ? `；契约待接线：${contractPending.join("、")}` : ""),
  );
  if (failed.length > 0) {
    for (const f of failed) log(`smoke-full: FAILED — ${f.name}: ${f.detail}`);
    process.exit(1);
    return;
  }
  process.exit(0);
}

async function runSmokeProduction() {
  const smokeDir = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-production-smoke-"));
  log(`production-smoke: 临时数据目录 ${smokeDir}`);
  const python = resolvePython();
  frontendCommand(8000);
  packagedImportProbe(python, smokeDir);
  [backendPort, frontendPort] = await Promise.all([freePort(), freePort()]);
  backendUrl = `http://${HOST}:${backendPort}`;
  frontendUrl = `http://${HOST}:${frontendPort}`;
  const authEnv = authEnvironment("1");
  const dataLayout = {
    root: smokeDir,
    database: path.join(smokeDir, "math_tutor.db"),
  };
  const backend = backendCommand(python, backendPort);
  const backendChild = startChild(backend.cmd, backend.args, backendEnvironment(dataLayout, {
    ...authEnv,
    MATHTUTOR_DESKTOP: "1",
    MATHTUTOR_ELECTRON_PICKER_URL: "",
    MATHTUTOR_ENVIRONMENT: "production",
    MATHTUTOR_API_BASE_URL: backendUrl,
  }), smokeDir);
  const frontend = frontendCommand(frontendPort);
  const frontendChild = startChild(frontend.cmd, frontend.args, {
    ...frontend.env,
    ...authEnv,
    MATHTUTOR_API_BASE_URL: backendUrl,
    ELECTRON_RUN_AS_NODE: "1",
  }, frontend.cwd);
  const started = Date.now();
  await waitForHttp(`${backendUrl}/health`, BACKEND_READY_TIMEOUT_MS, "production backend");
  const backendMs = Date.now() - started;
  await waitForHttp(`${frontendUrl}/register`, FRONTEND_READY_TIMEOUT_MS, "production register UI");
  const frontendMs = Date.now() - started;
  await verifyFrontendAssets(`${frontendUrl}/register`);

  const first = await httpJson(`${backendUrl}/api/v2/auth/is_first_user`);
  const username = `smoke_${Date.now()}`;
  const password = `Smoke-${crypto.randomBytes(12).toString("hex")}!`;
  const registered = await httpJson(`${backendUrl}/api/v2/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const login = await httpJson(`${backendUrl}/api/v2/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const cookie = String(login.headers.get("set-cookie") || "").split(";")[0];
  const readiness = await httpJson(`${backendUrl}/api/v2/math-tutor/desktop/readiness`, {
    headers: { Cookie: cookie },
  });
  const ok = first.status === 200 && first.body && first.body.is_first_user === true &&
    registered.status === 201 && registered.body && registered.body.is_admin === true &&
    login.status === 200 && login.body && login.body.ok === true && cookie &&
    readiness.status === 200 && readiness.body &&
    ["READY", "DEGRADED"].includes(readiness.body.status);
  backendChild.kill("SIGTERM");
  frontendChild.kill("SIGTERM");
  try { fs.rmSync(smokeDir, { recursive: true, force: true }); } catch {}
  if (!ok) throw new Error(
    `production auth launch failed: first=${first.status}, register=${registered.status}, ` +
    `login=${login.status}, readiness=${readiness.status}`,
  );
  log(`production-smoke: PASS auth-on register/login/readiness ` +
    `backend_ready_ms=${backendMs} frontend_ready_ms=${frontendMs}`);
  process.exit(0);
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

let backendPort = 0;
let frontendPort = 0;
let pickerPort = 0;
let backendUrl = "";
let frontendUrl = "";
let pickerUrl = "";

if (app) app.isQuitting = false;

if (isHeadlessNode) {
  // Headless modes (plain node / ELECTRON_RUN_AS_NODE): no GUI, no app API.
  // Same verification as the electron-mode --smoke/--smoke-full branches.
  if (isSmokeProduction) {
    runSmokeProduction().then(
      () => process.exit(0),
      (err) => {
        log(`production-smoke: FATAL — ${err && err.message ? err.message : err}`);
        process.exit(1);
      },
    );
  } else if (isSmokeFull) {
    runSmokeFull().then(
      () => process.exit(0),
      (err) => {
        log(`smoke-full: FATAL — ${err && err.message ? err.message : err}`);
        process.exit(1);
      },
    );
  } else if (isSmoke) {
    log("smoke: resolving python…");
    const python = resolvePython();
    log(`smoke: python = ${python.python}`);
    log("smoke: resolving next binary…");
    frontendCommand(8000); // throws/fails if missing
    log("smoke: ok");
    process.exit(0);
  } else {
    fail(
      "Electron API 不可用（检测到 ELECTRON_RUN_AS_NODE=1 或直接以 node 运行）。" +
        "桌面 GUI 请取消该环境变量后运行 `electron .`；自动化验证请用 `npm run smoke` / `npm run smoke-full`。",
    );
  }
} else {
app.whenReady().then(async () => {
  if (isSmokeProduction) {
    try {
      await runSmokeProduction();
    } catch (err) {
      log(`production-smoke: FATAL — ${err && err.message ? err.message : err}`);
      process.exit(1);
    }
    return;
  }
  if (isSmokeFull) {
    // --smoke-full: headless full-product E2E over HTTP/WS. No GUI window is
    // created; the runner starts backend + frontend, drives a real solve →
    // practice-offer flow, exercises the backups endpoints, kills and
    // restarts the backend, then re-verifies readiness. Exits 0/1.
    try {
      await runSmokeFull();
    } catch (err) {
      log(`smoke-full: FATAL — ${err && err.message ? err.message : err}`);
      process.exit(1);
    }
    return;
  }

  if (isSmoke) {
    // --smoke: verify the shell can resolve the environment, then exit.
    log("smoke: resolving python…");
    const python = resolvePython();
    log(`smoke: python = ${python.python}`);
    log("smoke: resolving next binary…");
    frontendCommand(8000); // throws/fails if missing
    log("smoke: ok");
    app.exit(0);
    return;
  }

  // 1. Allocate loopback ports first (nothing can race them).
  [backendPort, frontendPort, pickerPort] = await Promise.all([
    freePort(),
    freePort(),
    freePort(),
  ]);
  backendUrl = `http://${HOST}:${backendPort}`;
  frontendUrl = `http://${HOST}:${frontendPort}`;
  pickerUrl = `http://${HOST}:${pickerPort}/native-pick`;

  // 2. Native picker endpoint (loopback only).
  pickerServer = startPickerServer(pickerPort);

  // 3. Spawn the Python product service. Every mutable product artifact is
  //    rooted in Electron's per-user data directory, never the app bundle.
  const dataLayout = resolveDataLayout();
  const python = resolvePython();
  const backend = backendCommand(python, backendPort);
  // MATHTUTOR_* is authoritative. The two older names are read-only aliases
  // for one upgrade cycle and are never emitted to child processes.
  // Packaged/source Electron is the personal loopback desktop profile:
  // account authentication is disabled by architecture, not by user setup.
  const authEnabled = "0";
  log(`backend: ${backend.cmd} ${backend.args.join(" ")}`);
  startChild(backend.cmd, backend.args, backendEnvironment(dataLayout, {
    MATHTUTOR_DESKTOP: "1",
    MATHTUTOR_ELECTRON_PICKER_URL: pickerUrl,
    MATHTUTOR_API_BASE_URL: backendUrl,
    // One value drives both the Python auth service and the frontend proxy.
    ...authEnvironment(authEnabled),
    MATHTUTOR_ENVIRONMENT: "production",
  }), dataLayout.root);

  // 4. Spawn the Next.js frontend pointed at that backend. next must run with
  //    cwd = web/ so it finds next.config and the .next build.
  const frontend = frontendCommand(frontendPort);
  log(`frontend: ${frontend.cmd} ${frontend.args.join(" ")}`);
  const frontendEnv = {
    ...frontend.env,
    MATHTUTOR_API_BASE_URL: backendUrl,
    ...authEnvironment(authEnabled),
  };
  if (IS_PACKAGED) {
    startPackagedFrontend(frontend.args[0], frontendEnv, frontend.cwd);
  } else {
    // Development still invokes Next's CLI through Electron's Node mode.
    startChild(frontend.cmd, frontend.args, {
      ...frontendEnv,
      ELECTRON_RUN_AS_NODE: "1",
    }, frontend.cwd);
  }

  // 5. Wait for readiness (backend first — the proxy needs it).
  await waitForHttp(`${backendUrl}/health`, BACKEND_READY_TIMEOUT_MS, "本地辅导服务");
  await waitForHttp(`${frontendUrl}/math-tutor`, FRONTEND_READY_TIMEOUT_MS, "前端页面");
  await verifyFrontendAssets(`${frontendUrl}/math-tutor`);

  // 6. The window. Locked-down: no node integration, contextIsolation on,
  //    sandbox on — the renderer runs the unmodified web build.
  const win = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 640,
    title: "MathTutor 数学辅导",
    webPreferences: {
      preload: path.join(DESKTOP_DIR, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  win.setMenuBarVisibility(false);
  win.loadURL(frontendUrl);
});

app.on("window-all-closed", () => {
  app.isQuitting = true;
  stopChildren();
  stopPickerServer();
  app.quit();
});

app.on("before-quit", () => {
  app.isQuitting = true;
  stopChildren();
  stopPickerServer();
});
}

process.on("exit", () => {
  stopChildren();
  stopPickerServer();
});
