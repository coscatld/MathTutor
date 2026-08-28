"use client";

import { CheckCircle2, ChevronDown, GraduationCap, KeyRound, Loader2, PlugZap, Sparkles } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  DesktopApiError,
  fetchPresets,
  fetchSettings,
  maskKeyTail,
  saveSettings,
  testModelConnection,
} from "../lib/desktop-api";
import type { ModelTestResult, ProviderPreset } from "../types";
import { ModelTestCard } from "./SettingsPanel";

export interface WelcomeHandlers {
  onDismiss: () => void;
}

interface Props {
  /** Injectable fetchers — tests pass fakes. */
  fetchPresetsFn?: typeof fetchPresets;
  fetchSettingsFn?: typeof fetchSettings;
  saveSettingsFn?: typeof saveSettings;
  testModelConnectionFn?: typeof testModelConnection;
  /** Close / skip — the shell hides the panel for the session. */
  onDismiss: () => void;
}

/**
 * First-run experience: welcome + AI service configuration. The user is
 * NEVER forced to configure — 「跳过」 continues with template tutoring.
 * System items (database/migration/curriculum/retrieval/storage) are
 * prepared automatically and are shown in the BootstrapStatus step list;
 * nothing here lets the user touch them.
 *
 * The API key lives in React state only, travels exclusively via
 * PUT /settings (→ backend SecretStore), and only the masked tail is ever
 * displayed. Nothing touches browser storage.
 */
export default function WelcomePanel({
  fetchPresetsFn = fetchPresets,
  fetchSettingsFn = fetchSettings,
  saveSettingsFn = saveSettings,
  testModelConnectionFn = testModelConnection,
  onDismiss,
}: Props) {
  const [presets, setPresets] = useState<ProviderPreset[]>([]);
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [presetId, setPresetId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [keyMasked, setKeyMasked] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [modelTest, setModelTest] = useState<ModelTestResult | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const currentPreset = presets.find((p) => p.preset_id === presetId) ?? null;

  useEffect(() => {
    (async () => {
      try {
        const [presetList, settings] = await Promise.all([fetchPresetsFn(), fetchSettingsFn()]);
        setPresets(presetList);
        setPresetId(settings.preset_id);
        setBaseUrl(settings.base_url);
        setModel(settings.model);
        setConfigured(settings.is_configured);
        if (settings.is_configured) {
          onDismiss();
        }
      } catch {
        // The backend may still be booting; the user can still skip.
        setConfigured(false);
      }
    })().catch(() => undefined);
  }, [fetchPresetsFn, fetchSettingsFn, onDismiss]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDismiss]);

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentPreset) return;
    setSaving(true);
    setMessage(null);
    try {
      const result = await saveSettingsFn({
        preset_id: currentPreset.preset_id,
        api_key: apiKey.trim() || undefined,
        base_url: currentPreset.custom ? baseUrl.trim() : undefined,
        model: currentPreset.custom ? model.trim() : undefined,
      });
      setKeyMasked(result.key_masked);
      setApiKey("");
      setConfigured(true);
      setMessage({ kind: "ok", text: "AI 服务已配置完成。" });
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "保存失败，请稍后再试。",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setModelTest(null);
    try {
      setModelTest(await testModelConnectionFn());
    } catch (err) {
      setModelTest({
        ok: false,
        error_kind: null,
        message: err instanceof DesktopApiError ? err.message : "连接测试失败。",
      });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="welcome-title"
    >
      <div className="flex max-h-[calc(100vh-4rem)] w-full max-w-2xl flex-col overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 shadow-xl">
        {/* Welcome */}
        <div className="flex flex-col gap-2">
          <h1 id="welcome-title" className="flex items-center gap-2 text-xl font-semibold text-[var(--foreground)]">
            <GraduationCap className="h-6 w-6 text-[#2563EB]" aria-hidden="true" />
            欢迎使用 MathTutor 数学辅导
          </h1>
          <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
            本地优先的学习辅导：练习记录、学习资料与记忆都保存在你的电脑上。系统组件（数据库、资料库、文档检索等）已自动准备，无需任何配置。
          </p>
        </div>

        {configured === null ? (
          <p className="mt-4 flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            正在准备…
          </p>
        ) : (
          <form onSubmit={handleSave} className="mt-4 flex flex-col gap-4" aria-label="AI 服务配置">
            <div className="flex flex-col gap-2 rounded-xl border border-[var(--border)] bg-[var(--background)] p-4">
              <p className="flex items-center gap-2 text-sm font-medium text-[var(--foreground)]">
                <Sparkles className="h-4 w-4 text-[#2563EB]" aria-hidden="true" />
                可选：配置 AI 服务，解锁个性化辅导
              </p>
              <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                不配置也可以直接开始——模板辅导与核心练习始终可用。密钥只保存在本机安全存储中，不会离开你的电脑。
              </p>

              {/* Provider preset dropdown */}
              <div className="flex flex-col gap-1.5">
                <label htmlFor="welcome-preset" className="text-sm font-medium text-[var(--foreground)]">
                  模型服务商
                </label>
                <select
                  id="welcome-preset"
                  value={presetId}
                  onChange={(e) => {
                    setPresetId(e.target.value);
                    setMessage(null);
                    setModelTest(null);
                  }}
                  className="h-11 w-full cursor-pointer rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ring)]"
                >
                  {presets.length === 0 ? <option value="">正在加载服务商…</option> : null}
                  {presets.map((preset) => (
                    <option key={preset.preset_id} value={preset.preset_id}>
                      {preset.label}
                      {preset.custom ? "（自定义）" : ""}
                    </option>
                  ))}
                </select>
              </div>

              {/* API key — password input, masked tail only */}
              <div className="flex flex-col gap-1.5">
                <label htmlFor="welcome-apikey" className="text-sm font-medium text-[var(--foreground)]">
                  API 密钥
                </label>
                <div className="relative">
                  <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" aria-hidden="true" />
                  <input
                    id="welcome-apikey"
                    type="password"
                    autoComplete="off"
                    placeholder={keyMasked ? `已保存：${keyMasked}（留空则保持不变）` : "粘贴 API 密钥"}
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] pl-10 pr-3 text-sm text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ring)]"
                  />
                </div>
                <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                  密钥加密保存在本机安全存储中，界面与浏览器存储永不回显完整密钥。
                </p>
              </div>

              {/* Advanced foldout */}
              <div className="flex flex-col gap-2">
                <button
                  type="button"
                  onClick={() => setAdvancedOpen((v) => !v)}
                  aria-expanded={advancedOpen}
                  className="inline-flex min-h-[40px] w-fit cursor-pointer items-center gap-1.5 text-sm font-medium text-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] dark:text-blue-400"
                >
                  高级选项
                  <ChevronDown className={`h-4 w-4 transition-transform duration-200 ${advancedOpen ? "rotate-180" : ""}`} aria-hidden="true" />
                </button>
                {advancedOpen && (
                  <div className="flex flex-col gap-3 rounded-xl border border-[var(--border)] p-3">
                    <label className="flex flex-col gap-1.5 text-sm font-medium text-[var(--foreground)]">
                      服务地址（Base URL）
                      <input
                        type="text"
                        autoComplete="off"
                        placeholder={currentPreset?.custom ? "https://…（必填）" : "使用服务商默认地址"}
                        value={baseUrl}
                        onChange={(e) => setBaseUrl(e.target.value)}
                        className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm font-normal text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ring)]"
                      />
                    </label>
                    <label className="flex flex-col gap-1.5 text-sm font-medium text-[var(--foreground)]">
                      模型名称
                      <input
                        type="text"
                        autoComplete="off"
                        placeholder={currentPreset?.custom ? "例如 deepseek-chat（必填）" : "使用服务商默认模型"}
                        value={model}
                        onChange={(e) => setModel(e.target.value)}
                        className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm font-normal text-[var(--foreground)] placeholder:text-[var(--muted-foreground)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ring)]"
                      />
                    </label>
                  </div>
                )}
              </div>

              {/* Test connection + five-kind result */}
              <div className="flex flex-col gap-2">
                <button
                  type="button"
                  onClick={handleTest}
                  disabled={testing || !configured}
                  className="inline-flex min-h-[44px] w-fit cursor-pointer items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-2 text-sm font-medium text-[var(--foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {testing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <PlugZap className="h-4 w-4" aria-hidden="true" />}
                  检测连接
                </button>
                {modelTest ? <ModelTestCard result={modelTest} /> : null}
              </div>
            </div>

            {message && (
              <p
                role="status"
                className={`flex items-center gap-2 rounded-xl px-3 py-2 text-sm ${
                  message.kind === "ok"
                    ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400"
                    : "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400"
                }`}
              >
                {message.kind === "ok" ? <CheckCircle2 className="h-4 w-4 shrink-0" aria-hidden="true" /> : null}
                {message.text}
              </p>
            )}

            {/* First-run is never forced: skip always available. */}
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="submit"
                disabled={saving}
                className="inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl bg-[#2563EB] px-5 py-2 text-sm font-medium text-white transition-colors duration-200 hover:bg-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                {saving ? "保存中…" : "保存并开始"}
              </button>
              <button
                type="button"
                onClick={onDismiss}
                className="inline-flex min-h-[44px] cursor-pointer items-center rounded-xl border border-[var(--border)] bg-[var(--card)] px-5 py-2 text-sm font-medium text-[var(--foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
              >
                跳过，使用模板教学
              </button>
              {configured && (
                <button
                  type="button"
                  onClick={onDismiss}
                  className="inline-flex min-h-[44px] cursor-pointer items-center rounded-xl px-3 text-sm font-medium text-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] dark:text-blue-400"
                >
                  进入应用 →
                </button>
              )}
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
