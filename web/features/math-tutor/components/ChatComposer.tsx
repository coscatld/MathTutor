"use client";

import { productClass } from "@/styles/product-classes";
import {useI18n} from "@/lib/i18n";
import { ArrowUp, Globe2, ImagePlus, Loader2, Paperclip, Sigma } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { useUnsavedNavigation } from "../hooks/useUnsavedNavigation";
import { useChatAttachments } from "../hooks/useChatAttachments";
import { deliverDraft, type ChatAttachment } from "../lib/attachments";
import { useToast } from "../desktop/components/ToastProvider";
import { formulaKeys, insertFormula } from "../lib/formula-input";
import ImageAttachments from "./ImageAttachments";
import SlashSuggestions from "./SlashSuggestions";
import {usePluginCommands} from "../hooks/usePluginCommands";
import {availableCommands, isSlashCommand, slashQuery} from "../lib/plugin-commands";
import type {PluginCommand} from "../community/api";
export default function ChatComposer({ busy, disabled, onSend, onSendAttempt, networkSearch = false, onNetworkSearchChange, attemptMode = false, problemKey = "", onExitAttempt, onAddMaterial, onCancel, focusRequest = 0, placeholder = "输入问题，或粘贴截图…" }: { busy: boolean; disabled: boolean; onSend: (text: string, attachments: ChatAttachment[]) => Promise<boolean>; onSendAttempt?: (text: string) => Promise<boolean>; networkSearch?: boolean; onNetworkSearchChange?: (enabled: boolean) => void; attemptMode?: boolean; problemKey?: string; onExitAttempt?: () => void; onAddMaterial: () => void; onCancel?: () => void; focusRequest?: number; placeholder?: string }) {
  const {t} = useI18n();
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState(false);
  const inFlight = useRef(false);
  const picker = useRef<HTMLInputElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (focusRequest > 0) input.current?.focus(); }, [focusRequest]);
  useLayoutEffect(() => {
    const node = input.current;
    if (!node) return;
    const resize = () => { node.style.height = "0px"; node.style.height = `${node.scrollHeight}px`; };
    resize();
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width !== lastWidth) { lastWidth = width; resize(); }
    });
    let lastWidth = node.getBoundingClientRect().width;
    observer.observe(node);
    return () => observer.disconnect();
  }, [text]);
  const images = useChatAttachments();
  const [formulasOpen, setFormulasOpen] = useState(false);
  const formulasId = useId();
  const cursorAfterInsert = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (cursorAfterInsert.current === null || !input.current) return;
    input.current.focus();
    input.current.setSelectionRange(cursorAfterInsert.current, cursorAfterInsert.current);
    cursorAfterInsert.current = null;
  });
  const addFormula = (token: typeof formulaKeys[number]["insert"]) => {
    const node = input.current;
    if (!node) return;
    const next = insertFormula(text, node.selectionStart, node.selectionEnd, token);
    if (next.text === text) {
      node.focus();
      node.setSelectionRange(next.cursor, next.cursor);
    } else {
      cursorAfterInsert.current = next.cursor;
      setText(next.text);
    }
  };
  const [draftProblem, setDraftProblem] = useState<string | null>(null);
  useEffect(() => {
    if (!text.trim() && !images.attachments.length) setDraftProblem(null);
    else if (attemptMode && draftProblem === null) setDraftProblem(problemKey);
  }, [text, images.attachments.length, attemptMode, draftProblem, problemKey]);
  const staleAttempt = draftProblem !== null && draftProblem !== problemKey;
  const discard = () => { setText(""); images.clearAttachments(); setDraftProblem(null); };
  const draftVersion = JSON.stringify([text, images.attachments.map(attachment => attachment.id), draftProblem, problemKey, attemptMode]);
  useUnsavedNavigation(text.trim() || images.attachments.length ? t("有未发送的文字或图片，离开将丢弃这份草稿。") : "", discard, draftVersion);
  const exitAttempt = () => { setDraftProblem(null); onExitAttempt?.(); };
  const toast = useToast();
  const locked = busy || sending || disabled;
  const commandDraft = isSlashCommand(text.trim());
  const stepDraft = attemptMode && !commandDraft;
  const imageDraft = images.attachments.length > 0;
  const readyToSend = Boolean(text.trim() || (!attemptMode && imageDraft)) && !(attemptMode && commandDraft && imageDraft);
  const query = slashQuery(text), [dismissed, setDismissed] = useState(false), [selected, setSelected] = useState(0), [composing, setComposing] = useState(false), listId = useId();
  const menu = query !== null && !dismissed && !locked && !composing;
  const commands = usePluginCommands(menu), candidates = availableCommands(commands.items, query || "");
  useEffect(() => {setSelected(0);}, [query]);
  const chosen = Math.min(selected, Math.max(0, candidates.length - 1));
  const choose = (command: PluginCommand) => {setText(`/${command.command} `); setDismissed(true); input.current?.focus();};
  const submit = async () => {
    if (!readyToSend || locked || staleAttempt || inFlight.current) return;
    inFlight.current = true; setSending(true); setFailed(false);
    try {
      const sendDraft = stepDraft ? (draft: string) => onSendAttempt?.(draft) ?? Promise.resolve(false) : onSend;
      if (!await deliverDraft(text, stepDraft ? [] : images.attachments, sendDraft, discard)) {
        setFailed(true); toast({ title: "发送未完成，文字和图片已保留，可点击重试。", tone: "error" });
      }
    } catch (error) { setFailed(true); toast({ title: error instanceof Error ? error.message : "发送失败，请重试。", tone: "error" }); }
    finally { inFlight.current = false; setSending(false); }
  };
  return <div className={productClass("mt-composer")}>
    {staleAttempt ? <p role="alert" className="mt-note mt-note-warning p-3 text-sm">{t("这是旧题草稿，题目已变化，不能提交到当前题目。")}<button type="button" onClick={exitAttempt} className={productClass("mt-btn")}>{t("保留文字并改为提问")}</button><button type="button" onClick={discard} className={productClass("mt-btn")}>{t("丢弃旧题草稿")}</button></p> : null}
    {attemptMode ? <div className={productClass("mt-composer-mode")} role="status"><span>{imageDraft ? t("草稿图仅供对照，输入的文字步骤将由本机核验。") : commandDraft ? t("本条将调用插件，不记为本题作答") : t("正在写本题步骤 · 发送后检查这一步")}</span><button type="button" disabled={locked} onClick={exitAttempt}>{imageDraft ? t("改为图片提问") : t("改为提问")}</button></div> : null}
    <div onDragEnter={locked ? undefined : images.onDragEnter} onDragLeave={images.onDragLeave} onDragOver={e => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }} onDrop={e => { if (locked) e.preventDefault(); else images.handleDrop(e); }} className={productClass(`mt-composer-box relative ${images.dragging ? "ring-2 ring-[var(--ring)]" : ""}`)}>
      {images.dragging && <div className={productClass("pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-[24px] bg-[var(--primary-soft)] text-sm text-[var(--primary-text)]")}>{t("松开以上传图片")}</div>}
      <ImageAttachments images={images.attachments.map(a => ({ id: a.id, name: a.name, url: a.previewUrl }))} onRemove={images.removeAttachment} disabled={locked} />
      {menu ? <SlashSuggestions id={listId} items={candidates} selected={chosen} loading={commands.loading} error={commands.error} choose={choose} select={setSelected} retry={() => void commands.refresh()} /> : null}
      <textarea ref={input} value={text} onChange={event => {setText(event.target.value); setDismissed(false);}} onPaste={images.handlePaste} onCompositionStart={() => setComposing(true)} onCompositionEnd={() => setComposing(false)} onFocus={() => {if (menu) void commands.refresh();}} onKeyDown={event => {
        if (event.nativeEvent.isComposing || composing) return;
        if (menu && event.key === "Escape") {event.preventDefault(); setDismissed(true); return;}
        if (menu && candidates.length && (event.key === "ArrowDown" || event.key === "ArrowUp")) {event.preventDefault(); setSelected((chosen + (event.key === "ArrowDown" ? 1 : -1) + candidates.length) % candidates.length); return;}
        if (menu && candidates.length && event.key === "Enter" && !event.shiftKey) {event.preventDefault(); choose(candidates[chosen]); return;}
        if (event.key === "Enter" && !event.shiftKey) {event.preventDefault(); void submit();}
      }} rows={1} disabled={locked} aria-label={t("聊天输入")} aria-describedby="composer-help" aria-autocomplete="list" aria-haspopup="listbox" aria-expanded={menu} aria-controls={menu ? listId : undefined} aria-activedescendant={menu && candidates.length ? `${listId}-${chosen}` : undefined} placeholder={attemptMode ? t("写本题的一步等式或答案，例如 2x=4…") : t(placeholder)} className={productClass("mt-composer-input")} />
      {formulasOpen && <div id={formulasId} role="group" aria-label={t("常用公式")} className="flex flex-wrap gap-1 border-t border-[var(--border)] py-1">
        {formulaKeys.map(key => <button key={key.insert} type="button" disabled={locked || composing} title={t(key.label)} aria-label={t(key.label)} onClick={() => addFormula(key.insert)}
          className="min-h-11 min-w-11 rounded-md px-2 font-mono text-base hover:bg-[var(--accent)] focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--ring)]">{key.symbol}</button>)}
      </div>}
      <div className={productClass("flex flex-wrap items-center gap-1")}>
        <input ref={picker} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={event => { images.addFiles(Array.from(event.target.files || [])); event.target.value = ""; }} />
        <button type="button" disabled={locked} onClick={() => picker.current?.click()} className={productClass("mt-icon-button p-2")} aria-label={t("上传图片")}><ImagePlus className="h-5 w-5" /></button>
        <button type="button" disabled={locked} onClick={() => setFormulasOpen(!formulasOpen)} aria-expanded={formulasOpen} aria-controls={formulasOpen ? formulasId : undefined} aria-label={t("常用公式")} title={t("常用公式")} className={productClass("mt-icon-button p-2")}><Sigma className="h-5 w-5" aria-hidden="true" /></button>
        <button type="button" onClick={onAddMaterial} className={productClass("mt-icon-button p-2")} aria-label={t("为当前对话添加资料")}><Paperclip className="h-5 w-5" /></button>
        {onNetworkSearchChange ? <button type="button" disabled={locked || attemptMode} onClick={() => onNetworkSearchChange(!networkSearch)} aria-pressed={networkSearch} title={t("按需搜索知乎公开资料")} className={`inline-flex min-h-11 items-center gap-1.5 rounded-full px-3 text-sm transition-colors ${networkSearch ? "bg-[var(--accent)] text-[var(--primary)]" : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]"}`}><Globe2 className="h-4 w-4" aria-hidden="true" />{t("联网")}</button> : null}
        <span className={productClass("flex-1")} />
        {imageDraft && !attemptMode && <span className="text-[11px] text-[var(--muted-foreground)]">{images.attachments.length}{t("/4 · 发送时交给当前模型")}</span>}
        {busy && onCancel && <button type="button" onClick={onCancel} className="min-h-9 rounded-full px-3 text-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]">{t("停止生成")}</button>}
        <button type="button" onClick={() => void submit()} disabled={!readyToSend || locked || staleAttempt} className={productClass("mt-send-button")} aria-label={failed ? t("重试发送") : attemptMode && !commandDraft ? t("提交本题步骤") : t("发送")}>{sending || busy ? <Loader2 className="h-4 w-4 animate-spin" /> : failed ? t("重试") : <ArrowUp className="h-[18px] w-[18px]" strokeWidth={2.25} />}</button>
      </div>
    </div>
    <p id="composer-help" className="sr-only">{attemptMode && !commandDraft ? <><kbd>Enter</kbd>{t("提交步骤 ·")}<kbd>Shift</kbd> + <kbd>Enter</kbd>{t("换行")}</> : <><kbd>Enter</kbd>{t("发送 ·")}<kbd>Shift</kbd> + <kbd>Enter</kbd>{t("换行 · 粘贴 / 拖入图片，每张最多 10 MB")}</>}</p>
  </div>;
}
