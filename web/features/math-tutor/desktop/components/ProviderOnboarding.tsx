"use client";

import {
  ArrowRight,
  BookOpenCheck,
  Check,
  ChevronDown,
  KeyRound,
  Loader2,
  LockKeyhole,
  Sparkles,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  DesktopApiError,
  fetchPresets,
  fetchSettings,
  saveSettings,
  skipProviderOnboarding,
} from "../lib/desktop-api";
import type { DesktopSettings, ProviderPreset } from "../types";

/** Dedicated first-run product onboarding. Secret input never leaves memory. */
export default function ProviderOnboarding() {
  const router = useRouter();
  const [presets, setPresets] = useState<ProviderPreset[]>([]);
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [presetId, setPresetId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [error, setError] = useState("");

  const currentPreset = useMemo(
    () => presets.find((preset) => preset.preset_id === presetId) ?? null,
    [presetId, presets],
  );
  const keepingExistingKey = Boolean(
    settings?.is_configured &&
      settings.preset_id === presetId &&
      settings.key_masked,
  );

  useEffect(() => {
    (async () => {
      try {
        const [available, current] = await Promise.all([
          fetchPresets(),
          fetchSettings(),
        ]);
        if (current.is_configured || current.onboarding_completed) {
          router.replace("/math-tutor");
          return;
        }
        setPresets(available);
        setSettings(current);
        setPresetId(current.preset_id || available[0]?.preset_id || "");
        setBaseUrl(current.base_url);
        setModel(current.model);
      } catch {
        setError("暂时无法读取本地配置，请稍后重试。");
      } finally {
        setLoading(false);
      }
    })().catch(() => undefined);
  }, [router]);

  const handleSave = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    if (!currentPreset) {
      setError("请选择一个模型服务商。");
      return;
    }
    if (!apiKey.trim() && !keepingExistingKey) {
      setError("请填写 API Key，或选择“暂时跳过”使用模板教学。");
      return;
    }
    if (currentPreset.custom && !baseUrl.trim()) {
      setError("自定义服务商需要填写 API 地址。");
      return;
    }
    setSaving(true);
    try {
      await saveSettings({
        preset_id: currentPreset.preset_id,
        api_key: apiKey.trim() || undefined,
        base_url: currentPreset.custom ? baseUrl.trim() : undefined,
        model: currentPreset.custom ? model.trim() : undefined,
      });
      setApiKey("");
      router.replace("/math-tutor");
    } catch (reason) {
      setError(
        reason instanceof DesktopApiError
          ? reason.message
          : "保存失败，请检查后重试。",
      );
    } finally {
      setSaving(false);
    }
  };

  const handleSkip = async () => {
    setSkipping(true);
    setError("");
    try {
      await skipProviderOnboarding();
      router.replace("/math-tutor");
    } catch (reason) {
      setError(
        reason instanceof DesktopApiError
          ? reason.message
          : "暂时无法保存该选择，请稍后重试。",
      );
    } finally {
      setSkipping(false);
    }
  };

  return (
    <main className="relative h-screen overflow-y-auto bg-[#f8f7f2] text-[#172033]">
      <div className="pointer-events-none absolute inset-0 [background-image:linear-gradient(rgba(37,99,235,0.045)_1px,transparent_1px),linear-gradient(90deg,rgba(37,99,235,0.045)_1px,transparent_1px)] [background-size:36px_36px]" />
      <div className="pointer-events-none absolute -left-32 top-12 h-80 w-80 rounded-full bg-[#2563EB]/10 blur-3xl" />
      <div className="pointer-events-none absolute -right-24 bottom-0 h-72 w-72 rounded-full bg-[#d97706]/10 blur-3xl" />

      <div className="relative mx-auto grid min-h-full w-full max-w-6xl items-center gap-10 px-6 py-10 lg:grid-cols-[0.82fr_1.18fr] lg:px-10">
        <section className="hidden lg:block" aria-label="MathTutor 介绍">
          <div className="inline-flex items-center gap-2 rounded-full border border-[#2563EB]/20 bg-white/75 px-3 py-1.5 text-xs font-semibold tracking-[0.14em] text-[#1D4ED8] shadow-sm backdrop-blur">
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
            MATH TUTOR · LOCAL FIRST
          </div>
          <h2 className="mt-8 max-w-md font-serif text-5xl font-semibold leading-[1.08] tracking-[-0.035em]">
            把好奇心
            <span className="mt-2 block text-[#2563EB]">变成一步步的解题思路</span>
          </h2>
          <div className="mt-10 max-w-sm rotate-[-2deg] rounded-[28px] border border-[#d9d5c7] bg-white/90 p-6 shadow-[0_24px_60px_rgba(23,32,51,0.12)]">
            <div className="flex items-center justify-between text-xs text-[#7a7468]">
              <span>今日练习</span>
              <span className="rounded-full bg-[#eaf0ff] px-2.5 py-1 text-[#1D4ED8]">引导式辅导</span>
            </div>
            <p className="mt-8 font-serif text-3xl font-semibold tracking-tight">
              2x + 3 = 11
            </p>
            <div className="mt-7 h-px bg-[#e8e4da]" />
            <p className="mt-4 text-sm leading-6 text-[#635f57]">
              先想想：如果两边同时减去 3，等式会变成什么？
            </p>
          </div>
        </section>

        <section className="mx-auto w-full max-w-2xl rounded-[30px] border border-white/80 bg-white/95 p-6 shadow-[0_30px_90px_rgba(23,32,51,0.14)] backdrop-blur md:p-9">
          <div className="flex items-start gap-4">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-[#2563EB] text-white shadow-lg shadow-blue-200">
              <BookOpenCheck className="h-6 w-6" aria-hidden="true" />
            </div>
            <div>
              <p className="text-sm font-semibold text-[#2563EB]">欢迎使用 MathTutor</p>
              <h1 className="mt-1 font-serif text-3xl font-semibold tracking-[-0.025em] text-[#172033]">
                配置你的 AI 数学辅导模型
              </h1>
              <p className="mt-3 max-w-xl text-sm leading-6 text-[#6c7280]">
                选择模型服务商并填写 API Key。学习记录、资料和个人记忆始终保存在这台电脑上。
              </p>
            </div>
          </div>

          {loading ? (
            <div className="flex min-h-72 items-center justify-center text-sm text-[#6c7280]">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
              正在加载本地配置…
            </div>
          ) : (
            <form onSubmit={handleSave} className="mt-8 space-y-6" aria-label="AI 模型首次配置">
              <fieldset>
                <legend className="text-sm font-semibold text-[#293247]">选择模型服务商</legend>
                <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
                  {presets.map((preset) => {
                    const selected = preset.preset_id === presetId;
                    return (
                      <button
                        key={preset.preset_id}
                        type="button"
                        role="radio"
                        aria-checked={selected}
                        onClick={() => {
                          setPresetId(preset.preset_id);
                          setError("");
                          if (preset.custom) setAdvancedOpen(true);
                        }}
                        className={`relative min-h-[54px] rounded-2xl border px-3 py-2.5 text-left text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB] ${
                          selected
                            ? "border-[#2563EB] bg-[#edf3ff] text-[#1D4ED8] shadow-sm"
                            : "border-[#e2e4e9] bg-white text-[#4c5568] hover:border-[#9db7ef] hover:bg-[#f8faff]"
                        }`}
                      >
                        {preset.label}
                        {selected ? (
                          <Check className="absolute right-2 top-2 h-3.5 w-3.5" aria-hidden="true" />
                        ) : null}
                      </button>
                    );
                  })}
                </div>
              </fieldset>

              <div>
                <label htmlFor="onboarding-api-key" className="text-sm font-semibold text-[#293247]">
                  API Key
                </label>
                <div className="relative mt-2">
                  <KeyRound className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[#818898]" aria-hidden="true" />
                  <input
                    id="onboarding-api-key"
                    type="password"
                    autoComplete="off"
                    required={!keepingExistingKey}
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    placeholder={keepingExistingKey ? `已保存：${settings?.key_masked}` : "粘贴你的 API Key"}
                    className="h-12 w-full rounded-2xl border border-[#dfe2e8] bg-[#fbfcfe] pl-11 pr-4 text-sm text-[#172033] outline-none transition placeholder:text-[#9aa0ad] focus:border-[#2563EB] focus:bg-white focus:ring-4 focus:ring-[#2563EB]/10"
                  />
                </div>
                <p className="mt-2 flex items-center gap-1.5 text-xs leading-5 text-[#747b89]">
                  <LockKeyhole className="h-3.5 w-3.5 text-[#2563EB]" aria-hidden="true" />
                  API Key 使用系统安全凭据存储，不会写入学习数据库或浏览器存储。
                </p>
              </div>

              <div>
                <button
                  type="button"
                  onClick={() => setAdvancedOpen((open) => !open)}
                  aria-expanded={advancedOpen}
                  className="inline-flex min-h-[40px] items-center gap-1.5 text-sm font-semibold text-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB]"
                >
                  {currentPreset?.custom ? "自定义模型设置" : "高级选项"}
                  <ChevronDown className={`h-4 w-4 transition ${advancedOpen ? "rotate-180" : ""}`} aria-hidden="true" />
                </button>
                {advancedOpen ? (
                  <div className="mt-2 grid gap-3 rounded-2xl border border-[#e3e6eb] bg-[#f8f9fb] p-4 sm:grid-cols-2">
                    <label className="text-xs font-semibold text-[#4c5568]">
                      服务地址 {currentPreset?.custom ? "（必填）" : ""}
                      <input
                        type="url"
                        value={baseUrl}
                        onChange={(event) => setBaseUrl(event.target.value)}
                        disabled={!currentPreset?.custom}
                        placeholder="https://api.example.com/v1"
                        className="mt-1.5 h-11 w-full rounded-xl border border-[#dfe2e8] bg-white px-3 font-normal outline-none focus:border-[#2563EB] disabled:opacity-55"
                      />
                    </label>
                    <label className="text-xs font-semibold text-[#4c5568]">
                      模型名称（可选）
                      <input
                        type="text"
                        value={model}
                        onChange={(event) => setModel(event.target.value)}
                        disabled={!currentPreset?.custom}
                        placeholder="留空则自动发现"
                        className="mt-1.5 h-11 w-full rounded-xl border border-[#dfe2e8] bg-white px-3 font-normal outline-none focus:border-[#2563EB] disabled:opacity-55"
                      />
                    </label>
                  </div>
                ) : null}
              </div>

              {error ? (
                <p role="alert" className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {error}
                </p>
              ) : null}

              <div className="flex flex-col gap-3 border-t border-[#ece9df] pt-5 sm:flex-row sm:items-center">
                <button
                  type="submit"
                  disabled={saving || skipping}
                  className="inline-flex min-h-[48px] flex-1 items-center justify-center gap-2 rounded-2xl bg-[#2563EB] px-5 text-sm font-semibold text-white shadow-lg shadow-blue-200 transition hover:-translate-y-0.5 hover:bg-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB] disabled:translate-y-0 disabled:opacity-55"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
                  {saving ? "正在安全保存…" : "保存并继续"}
                  {!saving ? <ArrowRight className="h-4 w-4" aria-hidden="true" /> : null}
                </button>
                <button
                  type="button"
                  onClick={() => void handleSkip()}
                  disabled={saving || skipping}
                  className="inline-flex min-h-[48px] items-center justify-center rounded-2xl px-5 text-sm font-semibold text-[#5d6472] transition hover:bg-[#f1f2f5] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#2563EB] disabled:opacity-55"
                >
                  {skipping ? "正在进入…" : "暂时跳过，使用模板教学"}
                </button>
              </div>
              <p className="text-center text-xs leading-5 text-[#858b96]">
                跳过后仍可使用核心练习，并随时在“设置”中完成配置。
              </p>
            </form>
          )}
        </section>
      </div>
    </main>
  );
}
