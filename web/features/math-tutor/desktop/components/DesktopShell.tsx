"use client";

import { BookCheck, BookOpen, BrainCircuit, ChevronLeft, Compass, FileText, GraduationCap, Library, MessageSquarePlus, Settings, ShieldCheck, Trash2 } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiUrl } from "@/lib/api";
import { makeSessionId } from "../../lib/protocol";
import { commitTutorNavigation, requestTutorNavigation, requestTutorNavigationPermission } from "../../lib/navigation-guard";
import ConversationDeleteDialog from "./ConversationDeleteDialog";
import { conversationAction } from "../lib/conversation-trash";
import Tooltip from "./Tooltip";
import BrandMark from "@/components/common/BrandMark";
import ThemeQuickSwitch from "@/components/common/ThemeQuickSwitch";
import { useToast } from "./ToastProvider";

type Conversation = { conversation_id: string; title?: string; updated_at?: string };
const NAV_ITEMS = [
  { href: "/math-tutor", label: "辅导", icon: GraduationCap },
  { href: "/math-tutor/profile", label: "学习画像", icon: ShieldCheck },
  { href: "/math-tutor/offers", label: "推荐练习", icon: BookOpen },
  { href: "/math-tutor/question-bank", label: "题库", icon: BookCheck },
  { href: "/math-tutor/documents", label: "资料", icon: FileText },
  { href: "/math-tutor/knowledge", label: "知识库", icon: Library },
  { href: "/math-tutor/community", label: "社区", icon: Compass },
  { href: "/math-tutor/memory", label: "记忆", icon: BrainCircuit },
];

export default function DesktopShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const search = useSearchParams();
  const toast = useToast();
  const [collapsed, setCollapsed] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<Conversation | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  useEffect(() => {
    const small = window.matchMedia("(max-width: 800px)");
    const adapt = () => setCollapsed(small.matches);
    adapt();
    small.addEventListener("change", adapt);
    return () => small.removeEventListener("change", adapt);
  }, []);
  const inTutor = pathname === "/math-tutor";
  const selected = search.get("session") || "";

  const loadConversations = useCallback(async () => {
    try {
      const response = await apiFetch(apiUrl("/api/v2/math-tutor/sessions"));
      if (response.ok) setConversations(await response.json());
    } catch { /* history stays optional while offline */ }
  }, []);
  useEffect(() => {
    void loadConversations();
    window.addEventListener("mathtutor-conversations-changed", loadConversations);
    return () => window.removeEventListener("mathtutor-conversations-changed", loadConversations);
  }, [loadConversations]);

  const createConversation = () => {
    if (!requestTutorNavigation()) return;
    const conversationId = makeSessionId();
    // A URL/session id is only an in-memory draft. The backend creates the
    // durable conversation when the first student message arrives.
    router.push(`/math-tutor?session=${encodeURIComponent(conversationId)}`);
  };

  return <div className="mt-workspace">
    <aside aria-label="侧栏" data-collapsed={collapsed} className="mt-sidebar">
      <div className={`mt-sidebar-brand relative flex items-center ${collapsed ? "justify-center px-3" : "gap-2.5 px-4"}`}>
        {collapsed ? <Tooltip label="展开侧栏" side="right"><button type="button" aria-label="展开侧栏" onClick={() => setCollapsed(false)} className="mt-brand-mark"><BrandMark /></button></Tooltip> : <>
          <div className="mt-brand-mark"><BrandMark /></div>
          <p className="mt-wordmark min-w-0 truncate">Math<span>Tutor</span></p>
          <button type="button" aria-label="收起侧栏" onClick={() => setCollapsed(true)} className="mt-icon-button ml-auto p-2"><ChevronLeft className="h-4 w-4" /></button>
        </>}
      </div>
      <div className="px-3 pb-2 pt-1"><Tooltip label="新建辅导对话" side={collapsed ? "right" : "bottom"} wrapperClassName="flex w-full justify-center"><button type="button" aria-label="新建对话" onClick={createConversation} className={`mt-new-chat ${collapsed ? "w-11" : "w-full px-3"}`}><MessageSquarePlus className="h-4 w-4 shrink-0" />{!collapsed ? "新建对话" : null}</button></Tooltip></div>
      {!collapsed ? <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        <p className="mt-sidebar-label">最近对话</p>
        <div className="space-y-0.5">{conversations.length ? conversations.map((item) => <div key={item.conversation_id} className="mt-history-row flex min-w-0 items-center"><Link href={`/math-tutor?session=${encodeURIComponent(item.conversation_id)}`} aria-current={selected === item.conversation_id ? "true" : undefined} className="mt-history-item">{item.title || "新对话"}</Link><button type="button" aria-label={`删除对话：${item.title || "新对话"}`} onClick={() => setDeleteTarget(item)} className="mt-history-delete flex h-10 w-9 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--destructive)]"><Trash2 className="h-4 w-4" aria-hidden="true" /></button></div>) : <p className="px-3 py-2 text-xs leading-5 text-[var(--muted-foreground)]">发出第一条消息后，对话会保存在这里。</p>}</div>
      </div> : <div className="flex-1" />}
      <nav aria-label="主要功能" className="flex min-h-0 shrink flex-col gap-0.5 overflow-y-auto p-3">{NAV_ITEMS.map((item) => {
        const active = item.href === "/math-tutor" ? inTutor : pathname.startsWith(item.href);
        const link = <Link key={item.href} href={item.href} aria-label={item.label} aria-current={active ? "page" : undefined} className="mt-nav-item"><item.icon className="h-4 w-4 shrink-0" />{!collapsed ? item.label : null}</Link>;
        return collapsed ? <Tooltip key={item.href} label={item.label} side="right" wrapperClassName="flex w-full">{link}</Tooltip> : link;
      })}</nav>
      <div className={`flex shrink-0 gap-1 border-t p-3 ${collapsed ? "flex-col items-center" : "items-center"}`}>{collapsed ? <Tooltip label="设置" side="right" wrapperClassName="flex w-full"><Link href="/math-tutor/settings" aria-label="设置" aria-current={pathname.startsWith("/math-tutor/settings") ? "page" : undefined} className="mt-nav-item"><Settings className="h-4 w-4" /></Link></Tooltip> : <Link href="/math-tutor/settings" aria-label="设置" aria-current={pathname.startsWith("/math-tutor/settings") ? "page" : undefined} className="mt-nav-item"><Settings className="h-4 w-4" />设置</Link>}<ThemeQuickSwitch compact={collapsed} /></div>
    </aside>
    <main id="workspace-content" className={`min-h-0 min-w-0 flex-1 ${inTutor || pathname.startsWith("/math-tutor/settings") ? "overflow-hidden" : "overflow-y-auto"}`}>{children}</main>
    {deleteTarget ? <ConversationDeleteDialog title={deleteTarget.title || "对话"} onCancel={() => setDeleteTarget(null)} onConfirm={async () => {
      const operation = {};
      const permission = inTutor && selected === deleteTarget.conversation_id ? requestTutorNavigationPermission(operation) : undefined;
      if (permission === null) return "cancelled";
      await conversationAction(deleteTarget.conversation_id, "trash");
      setConversations(rows => rows.filter(row => row.conversation_id !== deleteTarget.conversation_id));
      if (permission) {
        if (commitTutorNavigation(permission, operation)) router.push(`/math-tutor?session=${encodeURIComponent(makeSessionId())}`);
        else toast({ title: "对话已移入垃圾桶，新的草稿与当前页面已保留。", tone: "info" });
      }
      setDeleteTarget(null);
      return "deleted";
    }} /> : null}
  </div>;
}
