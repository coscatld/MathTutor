import type {DesktopMemory} from "../types";

function version(value: string): bigint | null {
  const milliseconds=Date.parse(value);
  if (!Number.isFinite(milliseconds)) return null;
  const fraction=/\.(\d+)(?:Z|[+-]\d{2}:\d{2})$/i.exec(value)?.[1] ?? "";
  const microseconds=Number(fraction.slice(0,6).padEnd(6,"0"));
  return BigInt(milliseconds)*1000n+BigInt(microseconds%1000);
}

/** Ignore older receipts, including versions within the same millisecond. */
export function mergeMemoryUpdate(memories: DesktopMemory[], incoming: DesktopMemory): DesktopMemory[] {
  return memories.map(current=>{
    if (current.memory_id!==incoming.memory_id) return current;
    const next=version(incoming.updated_at),previous=version(current.updated_at);
    return next!==null && (previous===null || next>previous) ? incoming : current;
  });
}
