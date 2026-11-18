"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useI18n } from "@/lib/i18n";
import { productClass } from "@/styles/product-classes";
import { useUnsavedNavigation } from "../hooks/useUnsavedNavigation";
import { ExplorationApiError, explorationApi, type ExplorationConfiguration } from "./api";
import { RecommendationSettings } from "./Recommendations";
import { ExplorationRequests } from "./requests";

export function ConnectionForm({ configuration, apiKey, busy, error, notice, onKeyChange, onSave, onRemove }: {
  configuration: ExplorationConfiguration | null; apiKey: string; busy: boolean; error: string; notice: string;
  onKeyChange: (value: string) => void; onSave: () => void; onRemove: () => void;
}) {
  const { t } = useI18n();
  return <section aria-labelledby="zhihu-connection-title" className="max-w-2xl">
    <h2 id="zhihu-connection-title" className="text-xl font-bold tracking-tight">{t("知识来源")}</h2>
    <p className="mt-2 text-base leading-7 text-[var(--muted-foreground)]">{t("连接知乎，在数学问题中阅读原文、对照条件并检验理解。")}</p>
    <div className="mt-6 border-t border-[var(--border)] pt-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="text-lg font-semibold">{t("知乎开放平台")}</h3>
        <p className="text-sm text-[var(--muted-foreground)]" role="status">{configuration ? t(configuration.configured ? "已配置" : "尚未连接") : t("正在读取连接状态…")}</p>
      </div>
      {configuration?.environment_managed ? <p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">{t("当前使用运行环境提供的凭据。移除本机保存的凭据不会关闭该连接。")}</p> : null}
      {configuration && !configuration.persistent && configuration.has_saved_secret ? <p className="mt-3 text-sm leading-7 text-[var(--warning)]">{t("凭据仅在本次运行有效，重启后需要重新连接。")}</p> : null}
      <form className="mt-5" onSubmit={event => { event.preventDefault(); onSave(); }}>
        <label htmlFor="zhihu-access-secret" className="block text-sm font-medium">{t("知乎 Access Secret")}</label>
        <input id="zhihu-access-secret" name="zhihu-access-secret" type="password" autoComplete="off" spellCheck={false}
          value={apiKey} onChange={event => onKeyChange(event.target.value)} maxLength={4096} disabled={busy}
          aria-describedby="zhihu-secret-location" className={productClass("mt-input mt-2 min-h-11 text-base")} />
        <p id="zhihu-secret-location" className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{t("凭据交由后端保存，不存入浏览器。")}</p>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button type="submit" disabled={busy || apiKey.trim().length < 8} className={productClass("mt-btn mt-btn-primary min-h-11")}>{t("保存连接")}</button>
          {configuration?.has_saved_secret ? <button type="button" disabled={busy} onClick={onRemove} className={productClass("mt-btn mt-btn-ghost min-h-11")}>{t("移除已保存凭据")}</button> : null}
          {configuration?.configured ? <Link href="/math-tutor" className={productClass("mt-btn mt-btn-ghost min-h-11")}>{t("开始联网提问")}</Link> : null}
        </div>
      </form>
      {error ? <p role="alert" className="mt-4 text-sm leading-6 text-[var(--destructive)]">{error}</p> : null}
      {notice ? <p role="status" className="mt-4 text-sm leading-6 text-[var(--muted-foreground)]">{notice}</p> : null}
    </div>
    <p className="mt-5 text-sm leading-7 text-[var(--muted-foreground)]">{t("联网回答会发送当前问题和本次对话中上一条联网问题，不发送学习画像或私有资料。")}</p>
    <RecommendationSettings />
  </section>;
}

export default function ZhihuConnection() {
  const { t } = useI18n();
  const [configuration, setConfiguration] = useState<ExplorationConfiguration | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const requests = useRef(new ExplorationRequests());
  useUnsavedNavigation(apiKey ? t("连接凭据尚未保存。") : "", undefined, apiKey);
  useEffect(() => {
    const owner = requests.current;
    const request = owner.begin();
    explorationApi.configuration(request.signal).then(value => { if (owner.accepts(request)) setConfiguration(value); })
      .catch(error => { if (owner.accepts(request)) setError(t(error instanceof ExplorationApiError ? error.message : "连接状态暂不可用，请重试。")); })
      .finally(() => { if (owner.accepts(request)) { owner.finish(request); setBusy(false); } });
    return () => owner.cancel();
  }, [t]);

  const change = async (remove: boolean) => {
    if (requests.current.busy) return;
    const request = requests.current.begin();
    setBusy(true); setError(""); setNotice("");
    try {
      const value = await (remove ? explorationApi.disconnect(request.signal) : explorationApi.configure(apiKey.trim(), request.signal));
      if (!requests.current.accepts(request)) return;
      setConfiguration(value); setApiKey("");
      setNotice(t(remove ? "已移除本机保存的凭据。" : "连接已保存。"));
    } catch (error) {
      if (requests.current.accepts(request)) setError(t(error instanceof ExplorationApiError ? error.message : "连接未能保存，请重试。"));
    } finally {
      if (requests.current.accepts(request)) { requests.current.finish(request); setBusy(false); }
    }
  };

  return <><ConnectionForm configuration={configuration} apiKey={apiKey} busy={busy} error={error} notice={notice}
    onKeyChange={setApiKey} onSave={() => void change(false)} onRemove={() => void change(true)} />
    {!configuration && !busy ? <button type="button" className={productClass("mt-btn mt-4 min-h-11")} onClick={async () => {
      if (requests.current.busy) return;
      const request = requests.current.begin(); setBusy(true); setError("");
      try { const value = await explorationApi.configuration(request.signal); if (requests.current.accepts(request)) setConfiguration(value); }
      catch { if (requests.current.accepts(request)) setError(t("连接状态暂不可用，请重试。")); }
      finally { if (requests.current.accepts(request)) { requests.current.finish(request); setBusy(false); } }
    }}>{t("重试")}</button> : null}</>;
}
