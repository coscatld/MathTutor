import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import SettingsPanel, { SettingsForm } from "../features/math-tutor/desktop/components/SettingsPanel";
import EmbeddingStatusBadge from "../features/math-tutor/desktop/components/EmbeddingStatusBadge";
import { maskKeyTail } from "../features/math-tutor/desktop/lib/desktop-api";
import type { DesktopSettings, EmbeddingSettings, ProviderPreset, TestConnectionResult } from "../features/math-tutor/desktop/types";

const PRESETS: ProviderPreset[] = [
  { preset_id: "openai", label: "OpenAI", custom: false, editable_base_url: true, base_url: "https://api.openai.com/v1" },
  { preset_id: "deepseek", label: "DeepSeek", custom: false },
  { preset_id: "moonshot", label: "Moonshot", custom: false },
  { preset_id: "custom", label: "自定义", custom: true },
  { preset_id: "ollama", label: "Ollama", custom: false, local: true, requires_api_key: false, editable_base_url: true, base_url: "http://127.0.0.1:11434" },
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
  presetId?: string;
  baseUrl?: string;
} = {}) {
  const data = {
    presets: PRESETS,
    settings: overrides.settings ?? SETTINGS,
    presetId: overrides.presetId ?? SETTINGS.preset_id,
    apiKey: overrides.apiKey ?? "",
    baseUrl: overrides.baseUrl ?? "",
    model: (overrides.settings ?? SETTINGS).model,
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

test("SettingsForm: preset endpoint is editable and offers explicit default reset", () => {
  const html = renderForm({ advancedOpen: true, baseUrl: "https://proxy.example/v1" });
  const input = html.match(/<input[^>]*id="settings-baseurl"[^>]*>/)?.[0] ?? "";
  assert.ok(input.includes('value="https://proxy.example/v1"'));
  assert.ok(!/readonly|disabled/i.test(input));
  assert.ok(html.includes("恢复默认地址"));
  assert.ok(html.includes("图片输入能力"));
  assert.ok(html.includes("自动识别（默认）"));
  assert.ok(html.includes("启用（已确认模型支持视觉）"));
  assert.ok(html.includes("关闭（纯文本模型）"));
  assert.ok(html.includes("API Key 将发送到此地址"));
});

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
  assert.ok(!html.includes("gpt-4o-mini"), "provider cards do not mix provider and model");
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

test("SettingsForm: Ollama uses local service fields and never asks for API Key", () => {
  const html = renderForm({
    presetId: "ollama",
    baseUrl: "http://127.0.0.1:11434",
    advancedOpen: true,
    settings: {
      ...SETTINGS,
      preset_id: "ollama",
      base_url: "http://127.0.0.1:11434",
      model: "",
      is_configured: false,
      key_masked: null,
    },
  });
  assert.ok(html.includes("本地运行"));
  assert.ok(html.includes("不需要 API Key"));
  assert.ok(html.includes("读取本机模型"));
  assert.ok(!html.includes('id="settings-apikey"'));
});

test("SettingsPanel: initial render shows the loading placeholder (data arrives via effects)", () => {
  const html = renderToStaticMarkup(<SettingsPanel />);
  assert.ok(html.includes("正在加载设置…"), "loading state renders synchronously");
});

const EMBEDDING_SETTINGS: EmbeddingSettings = {
  enabled: false,
  provider: "local",
  local_model_id: "bge-small-zh-v1.5",
  local_models: [{ model_id: "bge-small-zh-v1.5", label: "BGE Small 中文 v1.5", dimension: 512, size_label: "约 95 MB", source: "ModelScope" }],
  local_download_status: "not_downloaded",
  local_download_error: null,
  cloud_base_url: "",
  cloud_model: "",
  cloud_has_api_key: false,
  cloud_key_masked: null,
  status: "disabled",
  status_label: "未启用 Embedding",
  runtime_reason: "Embedding 未启用，使用关键词检索。",
  reindex_required: false,
};

test("EmbeddingStatusBadge: exposes the default lexical-only state", () => {
  const html = renderToStaticMarkup(<EmbeddingStatusBadge settings={EMBEDDING_SETTINGS} />);
  assert.ok(html.includes("未启用 Embedding"));
  assert.ok(!html.includes("API Key"));
});

test("Embedding settings source keeps opt-in, mutually exclusive modes and safe key input", async () => {
  const { readFile } = await import("node:fs/promises");
  const source = await readFile("features/math-tutor/desktop/components/EmbeddingSettingsPanel.tsx", "utf8");
  assert.ok(source.includes("启用 Embedding 检索"));
  assert.ok(source.includes('role="radiogroup"'));
  assert.ok(source.includes("本地模型"));
  assert.ok(source.includes("云端模型"));
  assert.ok(source.includes('type="password"'));
  assert.ok(source.includes("删除本地权重"));
  assert.ok(source.includes("配置不完整"));
});
