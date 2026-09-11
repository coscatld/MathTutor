import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import BootstrapStatus, { BootstrapStatusControl, isFinal } from "../features/math-tutor/desktop/components/BootstrapStatus";
import BackupPanel, { RestoreConfirmDialog } from "../features/math-tutor/desktop/components/BackupPanel";
import PrivacyPanel, { ConfirmableDelete, PrivacySummary } from "../features/math-tutor/desktop/components/PrivacyPanel";
import { ModelTestCard } from "../features/math-tutor/desktop/components/SettingsPanel";
import {
  MODEL_ERROR_COPY,
  modelErrorCopy,
  masteryLevelLabel,
  sortBackups,
} from "../features/math-tutor/desktop/lib/desktop-api";
import type { BackupRecord, BootstrapPayload, ModelErrorKind, StudentSummary } from "../features/math-tutor/desktop/types";

// ---------------------------------------------------------------------------
// BootstrapStatus — polling settles into a final tri-state badge.
// ---------------------------------------------------------------------------

const READY_BOOTING: BootstrapPayload = {
  readiness: "READY",
  phase: "booting",
  reason: null,
  steps: [
    { key: "database", label: "", status: "ok", detail: "数据库已就绪" },
    { key: "migration", label: "数据库迁移", status: "blocked", detail: null },
  ],
};

const FINAL_READY: BootstrapPayload = {
  readiness: "READY",
  phase: "READY",
  reason: null,
  steps: [{ key: "secret_store", label: "系统凭据库", status: "ok", detail: null }],
};

const FINAL_DEGRADED: BootstrapPayload = {
  readiness: "DEGRADED",
  phase: "READY",
  reason: "AI 模型未配置",
  steps: [
    { key: "model_gateway", label: "AI 模型服务", status: "degraded", detail: "尚未配置 API 密钥" },
  ],
};

const FINAL_BLOCKED: BootstrapPayload = {
  readiness: "BLOCKED",
  phase: "BLOCKED",
  reason: "数据目录不可写",
  steps: [{ key: "check_data_root", label: "数据目录", status: "blocked", detail: null }],
};

test("isFinal: only READY phase or BLOCKED readiness end the boot sequence", () => {
  assert.equal(isFinal(null), false);
  assert.equal(isFinal(FINAL_READY), true);
  assert.equal(isFinal(FINAL_DEGRADED), true);
  assert.equal(isFinal(FINAL_BLOCKED), true);
  assert.equal(isFinal(READY_BOOTING), false, "phase=booting keeps polling even when readiness=READY");
});

test("BootstrapStatus: initial render shows the boot pill, never a final badge", () => {
  const html = renderToStaticMarkup(<BootstrapStatus />);
  assert.ok(html.includes("正在启动本地服务…"), "boot pill renders synchronously");
  assert.ok(!html.includes("一切就绪"), "no final badge before data arrives");
  assert.ok(/aria-live="polite"/.test(html), "status announced politely for screen readers");
});

test("BootstrapStatusControl: booting pill counts finished steps", () => {
  const html = renderToStaticMarkup(
    <BootstrapStatusControl payload={READY_BOOTING} open={false} refreshing={false} onToggle={() => undefined} onRefresh={() => undefined} />,
  );
  assert.ok(html.includes("正在启动… 1/2"), "counts ok steps while booting");
  // The final label may only live inside the sr-only live region / aria-label;
  // the visible pill must still show the boot progress, never the final badge.
  const visible = html
    .replace(/<span[^>]*sr-only[^>]*>[\s\S]*?<\/span>/g, "")
    .replace(/aria-label="[^"]*"/g, "");
  assert.ok(!visible.includes("一切就绪"), "visible pill still boots");
});

test("BootstrapStatusControl: final tri-state badges render distinct labels", () => {
  const ready = renderToStaticMarkup(
    <BootstrapStatusControl payload={FINAL_READY} open={false} refreshing={false} onToggle={() => undefined} onRefresh={() => undefined} />,
  );
  assert.ok(ready.includes("一切就绪"), "READY badge");
  const degraded = renderToStaticMarkup(
    <BootstrapStatusControl payload={FINAL_DEGRADED} open={false} refreshing={false} onToggle={() => undefined} onRefresh={() => undefined} />,
  );
  assert.ok(degraded.includes("部分功能可用"), "DEGRADED badge");
  const blocked = renderToStaticMarkup(
    <BootstrapStatusControl payload={FINAL_BLOCKED} open={false} refreshing={false} onToggle={() => undefined} onRefresh={() => undefined} />,
  );
  assert.ok(blocked.includes("服务不可用"), "BLOCKED badge");
});

test("BootstrapStatusControl: step list shows friendly labels, statuses, and plain-text details only", () => {
  const payload: BootstrapPayload = {
    readiness: "DEGRADED",
    phase: "READY",
    reason: "部分系统组件降级",
    steps: [
      { key: "database", label: "", status: "ok", detail: '发现损坏文件 <img src=x onerror=alert(1)>' },
      { key: "model_gateway", label: "AI 模型服务", status: "degraded", detail: null },
    ],
  };
  const html = renderToStaticMarkup(
    <BootstrapStatusControl payload={payload} open={true} refreshing={false} onToggle={() => undefined} onRefresh={() => undefined} />,
  );
  assert.ok(html.includes("本地数据库"), "label falls back to the local friendly map");
  assert.ok(html.includes("正常"), "ok step status label");
  assert.ok(html.includes("降级"), "degraded step status label");
  // Details are plain text — any embedded markup must be escaped, never rendered.
  assert.ok(html.includes("&lt;img"), "detail markup is escaped");
  assert.ok(!html.includes("<img src=x"), "raw markup never reaches the DOM");
  assert.ok(html.includes("部分系统组件降级"), "reason rendered");
  assert.ok(html.includes("核心练习与模板辅导仍可使用"), "non-READY advice rendered");
});

// ---------------------------------------------------------------------------
// BackupPanel — restore requires a double confirmation with explicit copy.
// ---------------------------------------------------------------------------

const BACKUP: BackupRecord = {
  path: "backup-20260821-1030.db",
  created_at: "2026-08-21T10:30:00+08:00",
  size_bytes: 2048,
  integrity: "ok",
  sha256_prefix: "ab12cd34ef56",
};

test("RestoreConfirmDialog: alertdialog with explicit consequence copy", () => {
  const html = renderToStaticMarkup(
    <RestoreConfirmDialog backup={BACKUP} busy={false} onConfirm={() => undefined} onCancel={() => undefined} />,
  );
  assert.ok(/role="alertdialog"/.test(html), "role=alertdialog");
  assert.ok(html.includes("覆盖当前数据"), "states the overwrite consequence");
  assert.ok(html.includes("应用将重新启动"), "states the restart consequence");
  assert.ok(html.includes("此操作无法撤销"), "states irreversibility");
  assert.ok(html.includes(BACKUP.path), "names the backup being restored");
  assert.ok(html.includes("取消"), "cancel available");
  assert.ok(html.includes("确认恢复"), "confirm button available");
});

test("RestoreConfirmDialog: busy state disables both actions and shows progress", () => {
  const html = renderToStaticMarkup(
    <RestoreConfirmDialog backup={BACKUP} busy={true} onConfirm={() => undefined} onCancel={() => undefined} />,
  );
  assert.ok(html.includes("恢复中…"), "progress label while busy");
  assert.ok(/disabled/.test(html), "actions disabled while busy");
});

test("BackupPanel: initial render shows the loading state and backup summary skeleton", () => {
  const html = renderToStaticMarkup(<BackupPanel />);
  assert.ok(html.includes("正在加载备份…"), "loading state renders synchronously");
  assert.ok(html.includes("数据备份"), "section title");
  assert.ok(html.includes("立即备份"), "create-backup action");
  assert.ok(html.includes("保留策略"), "policy row");
});

test("sortBackups: newest first, invalid dates last", () => {
  const sorted = sortBackups([
    { ...BACKUP, path: "old.db", created_at: "2026-08-01T00:00:00Z" },
    { ...BACKUP, path: "new.db", created_at: "2026-08-20T00:00:00Z" },
    { ...BACKUP, path: "invalid.db", created_at: "not-a-date" },
  ]);
  assert.deepEqual(
    sorted.map((b) => b.path),
    ["new.db", "old.db", "invalid.db"],
  );
});

// ---------------------------------------------------------------------------
// PrivacyPanel — read-only profile / summary, no mastery edit entry.
// ---------------------------------------------------------------------------

const SUMMARY: StudentSummary = {
  skills: [
    { code: "alg-linear-1", label: "一元一次方程", mastery: 0.85, grade_band: "G7" },
    { code: "frac", label: "分数运算", mastery: 0.6, grade_band: null },
    { code: "dec", label: "小数", mastery: 0.3, grade_band: null },
    { code: "geo", label: "几何初步", mastery: null, grade_band: null },
  ],
  total_attempts: 42,
  active_misconceptions: 3,
};

test("PrivacySummary: legacy uncalibrated mastery is not a percentage or ability label", () => {
  const html = renderToStaticMarkup(<PrivacySummary summary={SUMMARY} />);
  assert.ok(!html.includes("85%") && !html.includes("熟练"));
  assert.ok(!html.includes("60%") && !html.includes("进阶中"));
  assert.ok(!html.includes("30%") && !html.includes("起步中"));
  assert.ok(html.includes("仍需独立检测"));
  assert.ok(html.includes("学段：G7"), "grade band shown");
  assert.ok(html.includes("42"), "total attempts");
  assert.ok(html.includes("3"), "active misconceptions");
  assert.ok(!html.includes("<button"), "absolutely no button affordances in the summary");
  assert.ok(!html.includes("<input") && !html.includes("<select") && !html.includes("<textarea"), "no editable controls in the summary");
  assert.ok(!html.includes("编辑"), "no edit copy in the summary");
});

test("ConfirmableDelete: first click asks, second click is the destructive action", () => {
  const idle = renderToStaticMarkup(
    <ConfirmableDelete
      title="记忆条目"
      detail="对象描述"
      confirming={false}
      busy={false}
      onAskDelete={() => undefined}
      onCancelDelete={() => undefined}
      onConfirmDelete={() => undefined}
    />,
  );
  assert.ok(idle.includes("记忆条目"), "title shown");
  assert.ok(idle.includes("删除"), "ask-delete button");
  assert.ok(!idle.includes("此操作无法撤销"), "no confirmation yet on first state");

  const confirming = renderToStaticMarkup(
    <ConfirmableDelete
      title="记忆条目"
      detail="对象描述"
      confirming={true}
      busy={false}
      onAskDelete={() => undefined}
      onCancelDelete={() => undefined}
      onConfirmDelete={() => undefined}
    />,
  );
  assert.ok(confirming.includes("确认删除「记忆条目」？此操作无法撤销。"), "inline double-confirm copy");
  assert.ok(confirming.includes("取消"), "cancel path available");
  assert.ok(confirming.includes("确认删除"), "confirm path available");
});

test("PrivacyPanel: read-only profile, double-confirm delete surfaces, no mastery editing", () => {
  const html = renderToStaticMarkup(<PrivacyPanel />);
  assert.ok(/role="dialog"/.test(html), "dialog surface");
  assert.ok(html.includes("我的数据"), "dialog title");
  assert.ok(html.includes("正在加载我的数据…"), "loading state renders synchronously");
  // The read-only profile copy renders only after data arrives (effects don't
  // run in static render) — pin the invariant at source level instead.
  const source = fs.readFileSync(
    path.resolve(process.cwd(), "features", "math-tutor", "desktop", "components", "PrivacyPanel.tsx"),
    "utf8",
  );
  assert.ok(source.includes("只读展示"), "profile is explicitly read-only");
  assert.ok(!source.includes(">编辑") && !source.includes('"编辑"'), "no edit entry in the panel source");
});

// ---------------------------------------------------------------------------
// Provider onboarding — first-run is focused and key handled safely.
// ---------------------------------------------------------------------------

test("ProviderOnboarding: dedicated page has focused copy and safe skip", () => {
  const source = fs.readFileSync(
    path.resolve(process.cwd(), "features", "math-tutor", "desktop", "components", "ProviderOnboarding.tsx"),
    "utf8",
  );
  assert.ok(source.includes("配置你的 AI 数学辅导模型"), "focused onboarding title");
  assert.ok(source.includes("正在加载本地配置…"), "initial local-config state");
  assert.ok(source.includes("暂时跳过，使用模板教学"), "skip remains available");
  assert.ok(source.includes("skipProviderOnboarding()"), "skip is persisted by the backend");
  assert.ok(/type="password"/.test(source), "API key input is type=password");
});

// ---------------------------------------------------------------------------
// Model test card — five distinct friendly error kinds (SettingsPanel task).
// ---------------------------------------------------------------------------

const ALL_KINDS: ModelErrorKind[] = [
  "credential_invalid",
  "network_unavailable",
  "provider_unsupported",
  "model_unavailable",
  "gateway_disabled",
];

test("MODEL_ERROR_COPY: all five kinds have distinct titles and advice", () => {
  for (const kind of ALL_KINDS) {
    const copy = MODEL_ERROR_COPY[kind];
    assert.ok(copy.title.length > 0, `${kind} has a title`);
    assert.ok(copy.advice.length > 0, `${kind} has advice`);
  }
  const titles = new Set(ALL_KINDS.map((k) => MODEL_ERROR_COPY[k].title));
  assert.equal(titles.size, 5, "titles are distinct across kinds");
  const fallback = modelErrorCopy(null);
  assert.ok(fallback.title.length > 0 && fallback.advice.length > 0, "null kind falls back to friendly copy");
});

test("ModelTestCard: ok state and each error kind render friendly copy, never raw internals", () => {
  const ok = renderToStaticMarkup(
    <ModelTestCard result={{ ok: true, error_kind: null, message: "模型响应正常" }} />,
  );
  assert.ok(ok.includes("连接成功"), "ok card");
  assert.ok(ok.includes("模型响应正常"), "friendly backend message shown");
  assert.ok(!/traceback|Authorization|sk-/.test(ok), "no raw internals");

  for (const kind of ALL_KINDS) {
    const html = renderToStaticMarkup(
      <ModelTestCard result={{ ok: false, error_kind: kind, message: "后端友好提示" }} />,
    );
    assert.ok(html.includes(MODEL_ERROR_COPY[kind].title), `${kind}: mapped title rendered`);
    assert.ok(html.includes(MODEL_ERROR_COPY[kind].advice), `${kind}: advice rendered`);
    assert.ok(html.includes("后端友好提示"), `${kind}: friendly message rendered`);
    assert.ok(!/traceback|Authorization|api[_-]?key|sk-/.test(html), `${kind}: no raw tracebacks/headers/keys`);
  }
});

// ---------------------------------------------------------------------------
// Pure formatters.
// ---------------------------------------------------------------------------

test("masteryLevelLabel: null → 暂无数据, banded labels otherwise", () => {
  assert.equal(masteryLevelLabel(null), "暂无数据");
  assert.equal(masteryLevelLabel(Number.NaN), "暂无数据");
  assert.equal(masteryLevelLabel(0.8), "熟练");
  assert.equal(masteryLevelLabel(0.55), "进阶中");
  assert.equal(masteryLevelLabel(0.0), "起步中");
});

// ---------------------------------------------------------------------------
// PrivacyPanel danger zone — purge / educational history / export / rebuild.
// Every destructive action sits behind the double-confirm surface; the
// educational-history path never routes through the memory CRUD copy.
// ---------------------------------------------------------------------------

test("PrivacyPanel: danger zone renders purge/history/export/rebuild surfaces", () => {
  const html = renderToStaticMarkup(<PrivacyPanel />);
  assert.ok(html.includes("正在加载我的数据…"), "loading state renders synchronously");
  // The danger zone renders after data arrives (effects don't run in static
  // render) — pin the surfaces at source level, same as the profile test.
  const source = fs.readFileSync(
    path.resolve(process.cwd(), "features", "math-tutor", "desktop", "components", "PrivacyPanel.tsx"),
    "utf8",
  );
  assert.ok(source.includes("危险操作"), "danger zone section");
  assert.ok(source.includes("清空全部资料文档"), "purge documents action");
  assert.ok(source.includes("清空全部记忆"), "purge memory action");
  assert.ok(source.includes("删除学习记录"), "educational-history action");
  assert.ok(source.includes("重建检索索引"), "rebuild indexes tool");
  assert.ok(source.includes("导出我的数据"), "export tool");
  assert.ok(source.includes("不含任何密钥或系统内部数据"), "export privacy copy");
  assert.ok(source.includes("<ConfirmableDelete"), "every danger action reuses the double-confirm surface");
});

test("PrivacyPanel danger zone: source wires each action to its own client fn", () => {
  const panel = fs.readFileSync(
    path.resolve(process.cwd(), "features", "math-tutor", "desktop", "components", "PrivacyPanel.tsx"),
    "utf8",
  );
  assert.ok(panel.includes("purgeDocumentsFn()"), "purge documents calls the purge fn");
  assert.ok(panel.includes("purgeMemoryFn()"), "purge memory calls the purge fn");
  assert.ok(panel.includes("deleteHistoryFn()"), "educational history calls its own fn");
  assert.ok(panel.includes("rebuildIndexesFn()"), "rebuild calls its own fn");
  assert.ok(panel.includes("fetchExportFn()"), "export calls its own fn");
  assert.ok(panel.includes('Blob([JSON.stringify(body, null, 2)]'), "export builds a JSON download");
  assert.ok(panel.includes("deleteHistoryFn"), "educational history goes through the injected fn");
  assert.ok(!panel.includes("/privacy/"), "no hardcoded privacy route in the component");
});

test("desktop-api: privacy client fns point at the five backend routes", () => {
  const api = fs.readFileSync(
    path.resolve(process.cwd(), "features", "math-tutor", "desktop", "lib", "desktop-api.ts"),
    "utf8",
  );
  for (const route of [
    '"/privacy/purge-documents"',
    '"/privacy/purge-memory"',
    '"/privacy/educational-history"',
    '"/privacy/rebuild-indexes"',
    '"/privacy/export"',
  ]) {
    assert.ok(api.includes(route), `client exposes ${route}`);
  }
  assert.ok(api.includes('method: "POST"'), "destructive privacy calls are POSTs");
});
