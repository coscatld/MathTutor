"use client";
import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent } from "react";
import { AttachmentStore, ingestPaste, type ChatAttachment } from "../lib/attachments";
import { useToast } from "../desktop/components/ToastProvider";
export function useChatAttachments() {
  const store = useRef<AttachmentStore | null>(null);
  if (!store.current) store.current = new AttachmentStore();
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [dragging, setDragging] = useState(false);
  const depth = useRef(0);
  const toast = useToast();
  const addFiles = (files: Iterable<File>) => { const errors = store.current!.add(files); setAttachments([...store.current!.items]); for (const error of new Set(errors)) toast({ title: error, tone: "error" }); };
  const removeAttachment = (id: string) => { store.current!.remove(id); setAttachments([...store.current!.items]); };
  const clearAttachments = () => { store.current!.clear(); setAttachments([]); };
  const handlePaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    ingestPaste(event.clipboardData, addFiles, () => event.preventDefault());
  };
  const handleDrop = (event: DragEvent) => { event.preventDefault(); depth.current = 0; setDragging(false); addFiles(Array.from(event.dataTransfer.files)); };
  const onDragEnter = (event: DragEvent) => { if (event.dataTransfer.types.includes("Files")) { event.preventDefault(); depth.current++; setDragging(true); } };
  const onDragLeave = () => { depth.current = Math.max(0, depth.current - 1); if (!depth.current) setDragging(false); };
  useEffect(() => () => store.current!.clear(), []);
  return { attachments, dragging, addFiles, removeAttachment, clearAttachments, handlePaste, handleDrop, onDragEnter, onDragLeave };
}
