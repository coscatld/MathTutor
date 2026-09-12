"use client";
import { useRef } from "react";
import { X } from "lucide-react";
export default function ImageAttachments({ images, onRemove, disabled = false }: { images: Array<{ id: string; name: string; url: string }>; onRemove?: (id: string) => void; disabled?: boolean }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const full = useRef<HTMLImageElement>(null);
  if (!images.length) return null;
  return <div className="flex flex-wrap gap-2 p-2">
    {images.map(image => <div key={image.id} className="group relative">
      <button type="button" aria-label={`放大图片：${image.name}`} className="block rounded-xl border border-black/10 bg-slate-100 p-1 focus-visible:ring-2 focus-visible:ring-blue-500" onClick={() => { if (full.current) { full.current.src = image.url; full.current.alt = image.name; } dialog.current?.showModal(); }}><img src={image.url} alt={image.name} className="h-24 max-w-28 rounded-lg object-contain" /></button>
      {onRemove && <button type="button" disabled={disabled} aria-label={`删除图片：${image.name}`} onClick={() => onRemove(image.id)} className="absolute -right-1 -top-1 rounded-full bg-slate-800 p-1 text-white opacity-80 hover:bg-red-600 group-hover:opacity-100 focus:opacity-100 md:opacity-0"><X className="h-3 w-3" /></button>}
    </div>)}
    <dialog ref={dialog} aria-label="图片预览" className="max-h-[90vh] max-w-[92vw] rounded-2xl bg-white p-3 backdrop:bg-black/60" onClick={event => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
      <button type="button" autoFocus aria-label="关闭图片预览" onClick={() => dialog.current?.close()} className="float-right rounded-lg p-2 text-slate-600"><X className="h-5 w-5" /></button>
      <img ref={full} alt="图片预览" className="max-h-[78vh] max-w-full object-contain" />
    </dialog>
  </div>;
}
