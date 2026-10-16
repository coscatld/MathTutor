/** Import this file in My Plugins, enable it, then send /double-ts 21. */
type Request = { text: string; config: Record<string, unknown> };

export async function run(request: Request): Promise<Record<string, unknown>> {
  const text = request.text.trim();
  if (!/^[+-]?\d+$/.test(text)) return { text: "请在命令后输入一个整数，例如 /double-ts 21。" };
  const value = Number(text);
  if (!Number.isSafeInteger(value) || Math.abs(value) > 1e12) return { text: "示例只处理绝对值不超过一万亿的整数。" };
  return { text: `${value} 的两倍是 ${value * 2}。`, data: { input: value, result: value * 2 } };
}
