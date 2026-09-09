"use client";

import { BookOpen, BrainCircuit, ChevronLeft, FileText, GraduationCap, MessageSquarePlus, Settings, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, apiUrl } from "@/lib/api";
import { makeSessionId } from "../../lib/protocol";
import PrivacyPanel from "./PrivacyPanel";
import Tooltip from "./Tooltip";

type Conversation = { conversation_id: string; title?: string; updated_at?: string };
const NAV_ITEMS = [
  { href: "/math-tutor", label: "辅导", icon: GraduationCap },
  { href: "/math-tutor/offers", label: "练习邀请", icon: BookOpen },
  { href: "/math-tutor/documents", label: "资料", icon: FileText },
  { href: "/math-tutor/memory", label: "记忆", icon: BrainCircuit },
];

export default function DesktopShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const router = useRouter();
  const search = useSearchParams();
  const [collapsed, setCollapsed] = useState(false);
  const [privacyOpen, setPrivacyOpen] = useState(false);
  const [conversations, setConversations] = useState<Conversation[]>([]);
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
    const conversationId = makeSessionId();
    // A URL/session id is only an in-memory draft. The backend creates the
    // durable conversation when the first student message arrives.
    router.push(`/math-tutor?session=${encodeURIComponent(conversationId)}`);
  };

  return <div className="flex h-full min-h-0 w-full bg-[#f7f6f2] text-[#263238] dark:bg-[#101417] dark:text-slate-100">
    <aside className={`flex shrink-0 flex-col border-r border-[#deddd7] bg-[#efeee9] transition-[width] duration-200 dark:border-slate-800 dark:bg-[#171c20] ${collapsed ? "w-[72px]" : "w-[252px]"}`}>
      <div className={`relative flex h-16 items-center border-b border-[#deddd7] dark:border-slate-800 ${collapsed ? "justify-center px-3" : "gap-3 px-4"}`}>
        {collapsed ? <Tooltip label="展开侧栏" side="right"><button type="button" aria-label="展开侧栏" onClick={() => setCollapsed(false)} className="flex h-9 w-9 items-center justify-center rounded-xl bg-[#1d5fd1] text-white"><GraduationCap className="h-5 w-5" /></button></Tooltip> : <>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[#1d5fd1] text-white"><GraduationCap className="h-5 w-5" /></div>
          <div className="min-w-0"><p className="truncate font-serif text-base font-bold">MathTutor</p><p className="text-[11px] text-slate-500">你的数学学习桌</p></div>
          <button type="button" aria-label="收起侧栏" onClick={() => setCollapsed(true)} className="ml-auto rounded-lg p-2 text-slate-500 hover:bg-white dark:hover:bg-slate-800"><ChevronLeft className="h-4 w-4" /></button>
        </>}
      </div>
      <div className="p-3"><Tooltip label="新建辅导对话" side={collapsed ? "right" : "bottom"} wrapperClassName="flex w-full justify-center"><button type="button" onClick={createConversation} className={`flex h-11 items-center justify-center rounded-xl bg-[#1d5fd1] text-sm font-semibold text-white shadow-sm hover:bg-[#174fab] ${collapsed ? "w-11" : "w-full gap-2 px-3"}`}><MessageSquarePlus className="h-4 w-4 shrink-0" />{!collapsed ? "新建对话" : null}</button></Tooltip></div>
      {!collapsed ? <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3">
        <p className="px-2 pb-2 pt-1 text-[11px] font-bold uppercase tracking-[.16em] text-slate-500">最近对话</p>
        <div className="space-y-1">{conversations.length ? conversations.map((item) => <Link key={item.conversation_id} href={`/math-tutor?session=${encodeURIComponent(item.conversation_id)}`} className={`block truncate rounded-lg px-3 py-2 text-sm transition-colors ${selected === item.conversation_id ? "bg-white font-medium text-[#164da8] shadow-sm dark:bg-slate-800 dark:text-blue-300" : "text-slate-600 hover:bg-white/70 dark:text-slate-400 dark:hover:bg-slate-800/70"}`}>{item.title || "新对话"}</Link>) : <p className="px-2 py-3 text-xs leading-5 text-slate-500">发出第一条消息后，对话会保存在这里。</p>}</div>
      </div> : <div className="flex-1" />}
      <nav aria-label="主要功能" className="flex shrink-0 flex-col gap-1 border-t border-[#deddd7] p-3">{NAV_ITEMS.map((item) => {
        const active = item.href === "/math-tutor" ? inTutor : pathname.startsWith(item.href);
        const link = <Link key={item.href} href={item.href} aria-current={active ? "page" : undefined} className={`flex h-10 w-full items-center rounded-lg text-sm ${collapsed ? "justify-center" : "gap-3 px-3"} ${active ? "bg-[#dde7f7] font-semibold text-[#174c9e] dark:bg-blue-950 dark:text-blue-300" : "text-slate-600 hover:bg-white/70 dark:text-slate-400 dark:hover:bg-slate-800"}`}><item.icon className="h-4 w-4 shrink-0" />{!collapsed ? item.label : null}</Link>;
        return collapsed ? <Tooltip key={item.href} label={item.label} side="right" wrapperClassName="flex w-full">{link}</Tooltip> : link;
      })}<button type="button" onClick={() => setPrivacyOpen(true)} className={`flex h-10 w-full items-center rounded-lg text-sm text-slate-600 hover:bg-white/70 dark:text-slate-400 dark:hover:bg-slate-800 ${collapsed ? "justify-center" : "gap-3 px-3"}`}><ShieldCheck className="h-4 w-4 shrink-0" />{!collapsed ? "我的数据" : null}</button></nav>
      <div className="shrink-0 border-t border-[#deddd7] p-3 dark:border-slate-800">{collapsed ? <Tooltip label="设置" side="right" wrapperClassName="flex w-full"><Link href="/math-tutor/settings" aria-current={pathname.startsWith("/math-tutor/settings") ? "page" : undefined} className={`flex h-10 w-full items-center justify-center rounded-lg ${pathname.startsWith("/math-tutor/settings") ? "bg-[#dde7f7] text-[#174c9e] dark:bg-blue-950 dark:text-blue-300" : "text-slate-600 hover:bg-white/70 dark:text-slate-400 dark:hover:bg-slate-800"}`}><Settings className="h-4 w-4" /></Link></Tooltip> : <Link href="/math-tutor/settings" aria-current={pathname.startsWith("/math-tutor/settings") ? "page" : undefined} className={`flex h-10 w-full items-center gap-3 rounded-lg px-3 text-sm ${pathname.startsWith("/math-tutor/settings") ? "bg-[#dde7f7] font-semibold text-[#174c9e] dark:bg-blue-950 dark:text-blue-300" : "text-slate-600 hover:bg-white/70 dark:text-slate-400 dark:hover:bg-slate-800"}`}><Settings className="h-4 w-4" />设置</Link>}</div>
    </aside>
    <main className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</main>
    {privacyOpen ? <PrivacyPanel onClose={() => setPrivacyOpen(false)} /> : null}
  </div>;
}
