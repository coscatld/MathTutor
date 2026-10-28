import { apiFetch } from "@/lib/api";
import { root } from "./api";

export type NoteFields = { title: string; body: string; tags: string; relativePath: string };
export type NoteIdentity = { libraryId: string; documentId: string | null; version: number | null; previousPath: string };
export type NoteSubmission = Readonly<NoteFields & NoteIdentity & { generation: number; revision: number; operationId: string }>;
export type NoteReceipt = { document_id: string; version?: number; relative_path?: string };

/** An unknown transport outcome is retried with its original immutable input. */
export class NoteSaveTracker {
  generation = 0;
  revision = 0;
  pending: NoteSubmission | null = null;
  constructor(private operationId = () => crypto.randomUUID()) {}
  reset() { this.generation++; this.revision = 0; this.pending = null; }
  edit() { this.revision++; }
  prepare(identity: NoteIdentity, fields: NoteFields): NoteSubmission {
    if (!this.pending) this.pending = Object.freeze({ ...identity, ...fields, generation: this.generation, revision: this.revision, operationId: this.operationId() });
    return this.pending;
  }
  current(submission: NoteSubmission) { return submission.generation === this.generation; }
  unchanged(submission: NoteSubmission) { return this.current(submission) && submission.revision === this.revision; }
  release(submission: NoteSubmission) { if (this.pending === submission) this.pending = null; }
}

/** A response rejecting the write is distinct from an unknown network outcome. */
export class NoteSaveRejected extends Error {}

export async function submitNote(submission: NoteSubmission): Promise<NoteReceipt & { version: number }> {
  const response = await apiFetch(`${root}/libraries/${encodeURIComponent(submission.libraryId)}/notes`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      title: submission.title, body: submission.body, tags: submission.tags.split(/[,，]/).map(tag => tag.trim()).filter(Boolean),
      operation_id: submission.operationId, document_id: submission.documentId, expected_version: submission.version,
      relative_path: submission.relativePath, previous_relative_path: submission.documentId && submission.previousPath ? submission.previousPath : undefined,
    }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message = typeof body.detail === "string" ? body.detail : "笔记没有保存，请重试。";
    if (response.status >= 400 && response.status < 500) throw new NoteSaveRejected(message);
    throw new Error(message);
  }
  const receipt: NoteReceipt = await response.json();
  if (!receipt || typeof receipt.document_id !== "string" || !receipt.document_id
    || (submission.documentId && receipt.document_id !== submission.documentId)
    || typeof receipt.version !== "number" || !Number.isInteger(receipt.version) || receipt.version < Math.max(1, submission.version || 1)) {
    throw new Error("保存回执不完整，请重试确认同一次提交。");
  }
  return receipt as NoteReceipt & { version: number };
}
