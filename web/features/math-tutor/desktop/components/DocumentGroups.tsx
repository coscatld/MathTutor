"use client";
import { useEffect, useState, type ReactNode } from "react";
import ImageAttachments from "../../components/ImageAttachments";
import { fetchConversationResources } from "../lib/desktop-api";

type Conversation = {conversation_id: string; title: string};
import type { DesktopDocument } from "../types";

export function groupDocuments(documents: DesktopDocument[], history: Conversation[] = []) {
  const global = documents.filter(d => d.is_global);
  const unassigned = documents.filter(d => !d.is_global && !d.conversation_ids?.length);
  const conversations = new Map<string, { id: string; title: string; documents: DesktopDocument[] }>();
  for (const item of history) conversations.set(item.conversation_id, {id:item.conversation_id, title:item.title, documents:[]});
  for (const doc of documents.filter(d => !d.is_global)) for (const id of doc.conversation_ids || []) {
    if (!conversations.has(id)) conversations.set(id, { id, title: doc.conversation_titles?.[id] || "未命名对话", documents: [] });
    conversations.get(id)!.documents.push(doc);
  }
  return { global, unassigned, conversations: [...conversations.values()] };
}

export default function DocumentGroups({documents, conversations = [], renderDocument}: {documents: DesktopDocument[]; conversations?: Conversation[]; renderDocument: (doc: DesktopDocument) => ReactNode}) {
  const groups = groupDocuments(documents, conversations);
  const list = (docs: DesktopDocument[]) => <ul className="space-y-3 p-3">{docs.map(renderDocument)}</ul>;
  const heading = "cursor-pointer rounded-xl px-4 py-3 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-[var(--ring)]";
  return <div className="space-y-4">
    <details open className="mt-card">
      <summary className={heading}>总资料 · {groups.global.length} 份<span className="ml-3 font-normal text-[var(--muted-foreground)]">所有对话共享</span></summary>
      <p className="px-4 pb-2 text-xs text-[var(--muted-foreground)]">只有显式设为总资料的文件会进入此处；仍需开启文件的检索开关。</p>
      {groups.global.length ? list(groups.global) : <p className="px-4 pb-4 text-sm text-[var(--muted-foreground)]">尚未设置总资料。</p>}
    </details>
    <details open className="mt-card">
      <summary className={heading}>对话资料 · {groups.conversations.length} 个对话</summary>
      <div className="space-y-2 p-3">{groups.conversations.map(group => <ConversationSection key={group.id} id={group.id}>
        <summary className={heading}>{group.title}<span className="ml-3 font-normal text-[var(--muted-foreground)]">{group.documents.length} 份</span></summary>
        <a className="mx-4 text-xs text-[var(--primary-text)] underline" href={`/math-tutor?session=${encodeURIComponent(group.id)}`}>打开对话与图片记录</a>
        {list(group.documents)}
      </ConversationSection>)}{!groups.conversations.length ? <p className="px-1 text-sm text-[var(--muted-foreground)]">还没有关联对话的文档。</p> : null}</div>
    </details>
    {groups.unassigned.length ? <details open className="mt-card"><summary className={heading}>未归类 · {groups.unassigned.length} 份</summary><p className="px-4 text-xs text-[var(--muted-foreground)]">这些文件未绑定对话，也未启用全局共享。</p>{list(groups.unassigned)}</details> : null}
  </div>;
}

function ConversationSection({id,children}: {id:string;children:ReactNode}) {
  const [open,setOpen] = useState(false);
  const [images,setImages] = useState<Array<{id:string;name:string;url:string}>>([]);
  const [loading,setLoading] = useState(false);
  const [error,setError] = useState(false);
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true); setError(false);
    fetchConversationResources(id).then(result => {if(active) setImages(result.images);}).catch(() => {if(active) setError(true);}).finally(() => {if(active) setLoading(false);});
    return () => { active = false; };
  }, [id,open]);
  return <details className="rounded-xl border border-[var(--border)]" onToggle={event => setOpen(event.currentTarget.open)}>{children}
    {open ? <div className="px-3 pb-3">{loading ? <p role="status" className="text-xs text-[var(--muted-foreground)]">正在加载对话图片…</p> : error ? <p role="alert" className="text-xs text-[var(--destructive)]">图片暂时无法加载，请收起后重试。</p> : images.length ? <><p className="px-2 text-xs text-[var(--muted-foreground)]">已发送图片 · {images.length} 张</p><ImageAttachments images={images} /></> : <p className="px-2 text-xs text-[var(--muted-foreground)]">此对话暂无已发送图片。</p>}</div> : null}
  </details>;
}
