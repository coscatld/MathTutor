export const formulaKeys = [
  { symbol: "( )", label: "括号", insert: "()" },
  { symbol: "a/b", label: "分数", insert: "/" },
  { symbol: "x²", label: "平方", insert: "^2" },
  { symbol: "≤", label: "小于等于", insert: "<=" },
  { symbol: "≥", label: "大于等于", insert: ">=" },
  { symbol: "↵", label: "下一行", insert: "\n" },
] as const;

export function insertFormula(text: string, start: number, end: number, token: typeof formulaKeys[number]["insert"]) {
  const selection = text.slice(start, end);
  let replacement: string = token;
  let cursor = start + token.length;
  if (token === "()") {
    replacement = "(" + selection + ")";
    cursor = start + (selection ? replacement.length : 1);
  } else if (selection && (token === "/" || token === "^2")) {
    replacement = "(" + selection + ")" + token;
    cursor = start + replacement.length;
  } else if ((token === "/" || token === "^2") && !/[\w)\]]\s*$/.test(text.slice(0, start))) {
    replacement = token === "/" ? "()/()" : "()^2";
    cursor = start + 1;
  }
  return { text: text.slice(0, start) + replacement + text.slice(end), cursor };
}
