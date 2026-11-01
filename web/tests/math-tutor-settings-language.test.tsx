import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { I18nProvider, type Locale } from "../lib/i18n";
import { SettingsForm, ModelTestCard, type SettingsFormData, type SettingsFormHandlers } from "../features/math-tutor/desktop/components/SettingsPanel";
import { RestoreConfirmDialog } from "../features/math-tutor/desktop/components/BackupPanel";
import { ConfirmableDelete, PrivacySummary } from "../features/math-tutor/desktop/components/PrivacyPanel";
import { LearnerStageForm } from "../features/math-tutor/desktop/components/LearnerStagePanel";
import ConversationDeleteDialog from "../features/math-tutor/desktop/components/ConversationDeleteDialog";
import type { BackupRecord, StudentSummary } from "../features/math-tutor/desktop/types";

const render = (locale: Locale, children: React.ReactNode) => renderToStaticMarkup(<I18nProvider initialLocale={locale}>{children}</I18nProvider>);
const noOp = () => undefined;
const handlers: SettingsFormHandlers = {
  onPresetChange: noOp, onApiKeyChange: noOp, onBaseUrlChange: noOp, onModelChange: noOp,
  onToggleAdvanced: noOp, onDiscoverModels: noOp, onSave: noOp, onTest: noOp,
  onAskRemove: noOp, onCancelRemove: noOp, onRemove: noOp,
};
const form: SettingsFormData = {
  presets: [{ preset_id: "custom", label: "自定义 (OpenAI 兼容)", custom: true, editable_base_url: true }],
  settings: { preset_id: "custom", model: "用户模型名", base_url: "https://example.test/v1", is_configured: true, onboarding_completed: true, key_masked: "••••1234" },
  presetId: "custom", apiKey: "", baseUrl: "https://example.test/v1", model: "用户模型名", keyMasked: "••••1234",
  advancedOpen: true, models: ["中文模型名称"], saving: false, testing: false, discovering: false,
  removing: false, confirmingRemoval: false, testResult: null, message: { kind: "ok", text: "模型设置已保存并生效。" },
};

test("settings form localizes labels, status and choices without translating model names or changing values", () => {
  const html = render("en", <SettingsForm data={form} handlers={handlers} />);
  assert.ok(html.includes('aria-label="AI model settings"'));
  assert.ok(html.includes("Custom (OpenAI compatible)"));
  assert.ok(html.includes("Save settings") && html.includes("Image input support"));
  assert.ok(html.includes("Model settings saved and applied."));
  assert.ok(html.includes('value="用户模型名"') && html.includes("中文模型名称"));
  assert.ok(html.includes('value="auto"') && html.includes('value="enabled"') && html.includes('value="disabled"'));
  assert.ok(html.includes("••••1234"));
  const chinese = render("zh-CN", <SettingsForm data={form} handlers={handlers} />);
  assert.ok(chinese.includes("模型服务商") && chinese.includes("保存设置"));
});

test("connection error guidance uses localized product copy", () => {
  const html = render("en", <ModelTestCard result={{ ok: false, error_kind: "credential_invalid", message: "" }} />);
  assert.ok(html.includes("Invalid API key"));
  assert.ok(html.includes("Paste the full key and try again."));
});

test("restore confirmation translates consequences and accessibility while keeping the backup name", () => {
  const backup: BackupRecord = { path: "设置备份.db", created_at: "2026-10-28T00:00:00Z", size_bytes: 10, integrity: "ok", sha256_prefix: "abcd" };
  const html = render("en", <RestoreConfirmDialog backup={backup} busy={false} onConfirm={noOp} onCancel={noOp} />);
  assert.ok(html.includes('role="alertdialog"') && html.includes("Restore this backup?"));
  assert.ok(html.includes("overwrite current data") && html.includes("restart the app"));
  assert.ok(html.includes("设置备份.db") && html.includes('placeholder="Leave blank"'));
});

test("delete confirmations translate templates and keep user titles even when they match a translation key", () => {
  const item = render("en", <ConfirmableDelete title="通用" detail="用户原文" confirming busy={false} onAskDelete={noOp} onCancelDelete={noOp} onConfirmDelete={noOp} />);
  assert.ok(item.includes("通用") && item.includes("This cannot be undone."));
  const conversation = render("en", <ConversationDeleteDialog title="学习目标" onCancel={noOp} onConfirm={async () => "deleted"} />);
  assert.ok(conversation.includes("Move this conversation to trash?") && conversation.includes("学习目标"));
  assert.ok(conversation.includes("Settings &gt; Trash") && conversation.includes("Move to trash"));
});

test("stage options translate labels and grades while submitting the original stage and grade values", () => {
  const html = render("en", <LearnerStageForm stage="middle" grade={7} onStage={noOp} onGrade={noOp} onSave={noOp} />);
  assert.ok(html.includes("Primary school") && html.includes("Middle school") && html.includes("High school"));
  assert.ok(html.includes('value="7" selected=""') && html.includes("Grade 7"));
  assert.ok(html.includes('aria-label="Grade"') && html.includes("Save school stage"));
});

test("privacy evidence localizes fixed labels and counts without translating topic names", () => {
  const summary: StudentSummary = { total_attempts: 42, active_misconceptions: 3, skills: [{code: "fixture", label: "学习目标", mastery: null, grade_band: "G7"}] };
  const html = render("en", <PrivacySummary summary={summary} />);
  assert.ok(html.includes("Learning model summary") && html.includes("Total practice attempts"));
  assert.ok(html.includes("学习目标") && html.includes("42") && html.includes("3"));
  assert.ok(html.includes("Independent check still needed") && html.includes("School stage: G7"));
});
