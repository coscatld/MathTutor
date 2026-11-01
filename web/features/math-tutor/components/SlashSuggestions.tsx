"use client";
import {useI18n} from "@/lib/i18n";
import type {PluginCommand} from "../community/api";
import "./slash-suggestions.css";

export default function SlashSuggestions({id, items, selected, loading, error, choose, select, retry}: {id: string; items: PluginCommand[]; selected: number; loading: boolean; error: string; choose: (command: PluginCommand) => void; select: (index: number) => void; retry: () => void}) {
  const {t} = useI18n();
  return <div className="mt-slash-suggestions"><p className="mt-slash-heading">{t("插件命令 · 选择后发送具体请求")}</p>{loading ? <p role="status" className="mt-slash-message">{t("正在读取可用命令…")}</p> : error ? <div role="status" className="mt-slash-message">{t(error)}<button type="button" onClick={retry}>{t("重新读取")}</button></div> : !items.length ? <p role="status" className="mt-slash-message">{t("没有匹配的可用命令，可先在社区导入并启用插件。")}</p> : null}<ul id={id} role="listbox" aria-label={t("可用插件命令")}>{items.map((item, index) => <li id={`${id}-${index}`} key={item.plugin_id} role="option" aria-selected={index === selected} onMouseEnter={() => select(index)}><button type="button" tabIndex={-1} onMouseDown={event => event.preventDefault()} onClick={() => choose(item)}><span><strong>/{item.command}</strong><span>{item.name}</span></span><small>{item.description}</small></button></li>)}</ul></div>;
}
