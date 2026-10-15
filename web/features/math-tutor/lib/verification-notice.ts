/** Move routine scope receipts out of the lesson; actual errors stay visible. */
export function splitVerificationNotice(text: string): { body: string; scope: string | null } {
  const match = /^> (本段讲解(?:中的|未经)[^\n]*)\r?\n\r?\n/.exec(text);
  return match ? { body: text.slice(match[0].length), scope: match[1] } : { body: text, scope: null };
}
