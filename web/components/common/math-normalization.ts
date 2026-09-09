/** Display-only normalization. Preserve code spans, fences, links and plain brackets. */
export function normalizeMath(content: string): string {
  // Protect fenced and inline code before touching delimiters.
  return content.split(/(`{3,}[^\n]*\n[\s\S]*?(?:\n`{3,}|$)|~{3,}[^\n]*\n[\s\S]*?(?:\n~{3,}|$)|`+[^`\n]*`+)/g).map((part, index) => {
    if (index % 2) return part;
    return part
      .replace(/\\\[([\s\S]*?)\\\]/g, (_, math) => `\n$$\n${math.trim()}\n$$\n`)
      .replace(/\\\(([^\n]*?)\\\)/g, (_, math) => `$${math.trim()}$`)
      .replace(/(^|\n)[ \t]*\[([^\]\n]+)\][ \t]*(?=\n|$)/g, (whole, prefix, math) => {
        if (!/\\(?:frac|times|sqrt|lim|int|sum|prod)\b/.test(math)) return whole;
        if (/[\u3400-\u9fff]|https?:|`/.test(math)) return whole;
        const residue = math.replace(/\\[a-zA-Z]+/g, '');
        if (/[a-zA-Z]{3,}/.test(residue)) return whole;
        return `${prefix}$$\n${math.trim()}\n$$`;
      });
  }).join('');
}
