import test from "node:test";
import assert from "node:assert/strict";
import { commitTutorNavigation, registerNavigationGuard, requestTutorNavigation, requestTutorNavigationPermission } from "../features/math-tutor/lib/navigation-guard";

function browser() {
  const previousWindow = global.window, previousDocument = global.document;
  let accept = true;
  const messages: string[] = [];
  const view = Object.assign(new EventTarget(), {
    location: { href: "http://localhost/math-tutor?session=a" },
    confirm: (message: string) => { messages.push(message); return accept; },
    setTimeout,
  });
  global.window = view as unknown as Window & typeof globalThis;
  global.document = new EventTarget() as unknown as Document;
  const release: (() => void)[] = [];
  return {
    view, messages, reject: () => { accept = false; },
    guard: (guard: Parameters<typeof registerNavigationGuard>[0]) => { const stop = registerNavigationGuard(guard); release.push(stop); return stop; },
    restore: () => { release.forEach(stop => stop()); global.window = previousWindow; global.document = previousDocument; },
  };
}

test("deferred permission combines scope and message without discarding before API success", async () => {
  const env = browser();
  let text = "第一步\n第二步", attachments = 1, clears = 0;
  try {
    env.guard({ message: () => "未发送的文字或图片", version: () => 1, discard: () => { text = ""; attachments = 0; clears++; } });
    env.guard({ message: () => "参考范围尚未应用", version: () => 2 });
    const operation = {}, permission = requestTutorNavigationPermission(operation)!;
    assert.equal(env.messages.length, 1);
    assert.match(env.messages[0], /未发送.*\n参考范围/);
    assert.equal(text, "第一步\n第二步"); assert.equal(attachments, 1); assert.equal(clears, 0);
    await Promise.resolve();
    assert.equal(commitTutorNavigation(permission, operation), true);
    assert.equal(text, ""); assert.equal(attachments, 0); assert.equal(clears, 1);
    assert.equal(commitTutorNavigation(permission, operation), false);
    assert.equal(clears, 1);
  } finally { env.restore(); }
});

test("cancelled confirmation and failed deletion leave the draft untouched", async () => {
  const env = browser();
  let clears = 0, requests = 0;
  try {
    env.guard({ message: () => "未发送", discard: () => { clears++; } });
    env.reject();
    const permission = requestTutorNavigationPermission({});
    if (permission) requests++;
    assert.equal(permission, null); assert.equal(requests, 0); assert.equal(clears, 0);
  } finally { env.restore(); }
  const failure = browser();
  try {
    failure.guard({ message: () => "未发送", discard: () => { clears++; } });
    assert.ok(requestTutorNavigationPermission({}));
    await assert.rejects(Promise.reject(new Error("DELETE 500")), /500/);
    assert.equal(clears, 0);
  } finally { failure.restore(); }
});

for (const change of ["draft", "new-draft", "page", "registration", "operation"] as const) test(`old permission cannot commit after ${change} changes`, () => {
  const env = browser();
  let version = 1, clears = 0, message = change === "new-draft" ? "" : "未发送";
  try {
    const stop = env.guard({ message: () => message, version: () => version, discard: () => { clears++; } });
    const operation = {}, permission = requestTutorNavigationPermission(operation)!;
    if (change === "draft") version++;
    if (change === "new-draft") { message = "未发送"; version++; }
    if (change === "page") env.view.location.href = "http://localhost/math-tutor?session=b";
    if (change === "registration") { stop(); env.guard({ message: () => message, version: () => version, discard: () => { clears++; } }); }
    assert.equal(commitTutorNavigation(permission, change === "operation" ? {} : operation), false);
    assert.equal(clears, 0);
  } finally { env.restore(); }
});

test("immediate navigation still confirms and commits once; clean pages skip confirmation", () => {
  const env = browser();
  let message = "未发送", clears = 0;
  try {
    env.guard({ message: () => message, discard: () => { clears++; message = ""; } });
    assert.equal(requestTutorNavigation(), true);
    assert.equal(clears, 1); assert.equal(env.messages.length, 1);
    assert.equal(requestTutorNavigation(), true);
    assert.equal(clears, 1); assert.equal(env.messages.length, 1);
  } finally { env.restore(); }
});
