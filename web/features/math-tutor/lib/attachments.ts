import { apiFetch, apiUrl } from "@/lib/api";
export interface MessageAttachment { id: string; type: "image"; mimeType: string; name: string; size: number; url: string }
export interface ChatAttachment { id: string; type: "image"; file: File; mimeType: string; name: string; size: number; previewUrl: string }
export const MAX_IMAGES = 4;
export const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
export const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
export const VISION_UNSUPPORTED = "当前配置未启用图片输入。若模型官方确认支持视觉，请到设置 → 高级选项 → 图片输入能力选择启用并保存。";
export function validateImage(file: File, count: number): string | null {
  if (!IMAGE_TYPES.includes(file.type)) return "暂不支持该图片格式";
  if (file.size > MAX_IMAGE_BYTES) return "单张图片不能超过 10 MB";
  if (!file.size) return "图片文件为空";
  if (count >= MAX_IMAGES) return "每条消息最多上传 4 张图片";
  return null;
}
export function clipboardImages(items: ArrayLike<{ kind: string; getAsFile(): File | null }>): File[] {
  return Array.from(items).flatMap(item => { const file = item.kind === "file" ? item.getAsFile() : null; return file?.type.startsWith("image/") ? [file] : []; });
}
export function ingestPaste(data: Pick<DataTransfer, "items" | "getData">, addFiles: (files: File[]) => void, preventDefault: () => void) {
  const files = clipboardImages(data.items);
  if (files.length) { addFiles(files); if (!data.getData("text/plain")) preventDefault(); }
}
export async function deliverDraft(text: string, attachments: ChatAttachment[], send: (text: string, files: ChatAttachment[]) => Promise<boolean>, clear: () => void): Promise<boolean> {
  if (!text.trim() && !attachments.length) return false;
  const success = await send(text.trim(), attachments);
  if (success) clear();
  return success;
}
/** Shared synchronous store also enforces limits during rapid pastes. */
export class AttachmentStore {
  items: ChatAttachment[] = [];
  constructor(private urls: Pick<typeof URL, "createObjectURL" | "revokeObjectURL"> = URL, private id: () => string = () => crypto.randomUUID()) {}
  add(files: Iterable<File>): string[] {
    const errors: string[] = [];
    for (const file of files) {
      const error = validateImage(file, this.items.length);
      if (error) { errors.push(error); continue; }
      this.items = [...this.items, { id: this.id(), type: "image", file, mimeType: file.type, name: file.name || "截图", size: file.size, previewUrl: this.urls.createObjectURL(file) }];
    }
    return errors;
  }
  remove(id: string) { this.items = this.items.filter(item => { if (item.id !== id) return true; this.urls.revokeObjectURL(item.previewUrl); return false; }); }
  clear() { for (const item of this.items) this.urls.revokeObjectURL(item.previewUrl); this.items = []; }
}
export function projectAttachments(value: unknown): MessageAttachment[] {
  if (!Array.isArray(value)) return [];
  return value.filter((x): x is MessageAttachment => Boolean(x && x.type === "image" && typeof x.id === "string" && /^[a-f0-9-]{36}$/.test(x.id) && IMAGE_TYPES.includes(x.mimeType)))
    .slice(0, MAX_IMAGES).map(x => ({ id: x.id, type: "image", mimeType: x.mimeType, name: String(x.name || "图片"), size: Number(x.size || 0), url: `/api/v2/math-tutor/images/${x.id}` }));
}
/** Local HTTP blob repository, independent from Composer and history. */
export class ImageUploadRepository {
  private uploaded = new WeakMap<File, MessageAttachment>();
  async upload(items: ChatAttachment[]): Promise<MessageAttachment[]> {
    if (!items.length) return [];
    const caps = await apiFetch(apiUrl("/api/v2/math-tutor/image-capabilities"));
    if (!caps.ok) throw new Error("无法检查模型图片能力，请稍后重试。");
    if (!(await caps.json()).vision) throw new Error(VISION_UNSUPPORTED);
    const result = [];
    for (const item of items) {
      let saved = this.uploaded.get(item.file);
      if (!saved) {
        const form = new FormData(); form.append("file", item.file, item.name);
        const response = await apiFetch(apiUrl("/api/v2/math-tutor/images"), { method: "POST", body: form });
        if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(typeof body.detail === "string" ? body.detail : "图片上传失败，请重试。"); }
        saved = projectAttachments([await response.json()])[0];
        if (!saved) throw new Error("图片保存响应不完整，请重试。");
        this.uploaded.set(item.file, saved);
      }
      result.push(saved);
    }
    return result;
  }
}
