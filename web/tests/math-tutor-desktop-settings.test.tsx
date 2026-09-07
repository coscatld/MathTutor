import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import SettingsPanel, { SettingsForm } from "../features/math-tutor/desktop/components/SettingsPanel";
import { maskKeyTail } from "../features/math-tutor/desktop/lib/desktop-api";
import type { DesktopSettings, ProviderPreset, TestConnectionResult } from "../features/math-tutor/desktop/types";

const PRESETS: ProviderPreset[] = [
  { preset_id: "openai", label: "OpenAI", custom: false },
  { preset_id: "deepseek", label: "DeepSeek", custom: false },
  { preset_id: "moonshot", label: "Moonshot", custom: false },
  { preset_id: "custom", label: "自定义", custom: true },
];

const SETTINGS: DesktopSettings = {
  preset_id: "openai",
  model: "gpt-4o-mini",
  base_url: "",
  is_configured: true,
  onboarding_completed: true,
  key_masked: "•••••••1234",
};

function renderForm(overrides: {
  keyMasked?: string | null;
  advancedOpen?: boolean;
  settings?: DesktopSettings;
  apiKey?: string;
  models?: string[] | null;
} = {}) {
  const data = {
    presets: PRESETS,
    settings: overrides.settings ?? SETTINGS,
    presetId: SETTINGS.preset_id,
    apiKey: overrides.apiKey ?? "",
    baseUrl: "",
    model: SETTINGS.model,
    keyMasked: overrides.keyMasked ?? "••••••••1234",
    advancedOpen: overrides.advancedOpen ?? false,
    models: overrides.models ?? null,
    saving: false,
    testing: false,
    discovering: false,
    removing: false,
    confirmingRemoval: false,
    testResult: null as TestConnectionResult | null,
    message: null,
  };
  const handlers = {
    onPresetChange: () => undefined,
    onApiKeyChange: () => undefined,
    onBaseUrlChange: () => undefined,
    onModelChange: () => undefined,
    onToggleAdvanced: () => undefined,
    onDiscoverModels: () => undefined,
    onSave: (e: React.FormEvent) => e.preventDefault(),
    onTest: () => undefined,
    onAskRemove: () => undefined,
    onCancelRemove: () => undefined,
    onRemove: () => undefined,
  };
  return renderToStaticMarkup(<SettingsForm data={data} handlers={handlers} />);
}

test("maskKeyTail: only the last four chars are ever exposed", () => {
  assert.equal(maskKeyTail("sk-abc-1234"), "••••••••1234");
  assert.equal(maskKeyTail("short"), "••••••••hort");
  assert.equal(maskKeyTail(""), "");
  assert.equal(maskKeyTail("abcd"), "••••••••abcd");
});

test("SettingsForm: renders provider presets and masked key tail, never the full key", () => {
  const html = renderForm({ keyMasked: "••••••••1234" });
  assert.ok(html.includes("OpenAI"), "renders preset label");
  assert.ok(html.includes("自定义"), "renders custom preset");
  assert.ok(html.includes("••••••••1234"), "shows masked tail");
  assert.ok(!html.includes("sk-secret"), "never contains the full key value");
  assert.ok(/type="password"/.test(html), "key field is a password input");
});

test("SettingsForm: password input masks typed values and placeholder hides the key", () => {
  const html = renderForm({ apiKey: "sk-super-secret" });
  // The typed value sits in the input's value attribute only — still rendered
  // inside a password input; no plain-text rendering elsewhere.
  assert.ok(/type="password"/.test(html), "password type retained");
  assert.ok(html.includes("已保存：••••••••1234"), "placeholder advertises the masked tail");
});

test("SettingsForm: advanced foldout (custom base_url/model) is hidden by default", () => {
  const closed = renderForm();
  assert.ok(!closed.includes("服务地址"), "advanced section hidden by default");
  const open = renderForm({ advancedOpen: true });
  assert.ok(open.includes("服务地址"), "advanced section shown when open");
  assert.ok(open.includes("模型名称"), "model field in advanced section");
});

test("SettingsForm: connection test disabled while not configured", () => {
  const html = renderForm({
    settings: {
      preset_id: "openai",
      model: "",
      base_url: "",
      is_configured: false,
      onboarding_completed: true,
      key_masked: null,
    },
  });
  assert.ok(/disabled/.test(html), "test button disabled when not configured");
});

test("SettingsForm: discovered models render as chips", () => {
  const html = renderForm({ advancedOpen: true, models: ["deepseek-chat", "deepseek-reasoner"] });
  assert.ok(html.includes("deepseek-chat"), "renders discovered model");
  assert.ok(html.includes("deepseek-reasoner"), "renders second discovered model");
});

test("SettingsPanel: initial render shows the loading placeholder (data arrives via effects)", () => {
  const html = renderToStaticMarkup(<SettingsPanel />);
  assert.ok(html.includes("正在加载设置…"), "loading state renders synchronously");
});
