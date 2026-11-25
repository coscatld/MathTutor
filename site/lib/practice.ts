export const practiceExamples = [
  { equation: '2x + 3 = 7', value: '2', hint: { zh: '试着从等号两边都减去 3，再看看未知数的系数。', en: 'Subtract 3 from both sides, then look at the coefficient of x.' } },
  { equation: '3x + 1 = 3', value: '2/3', hint: { zh: '先把常数项移到右边。最后的答案可以用分数表示。', en: 'Move the constant to the right first. You can leave your answer as a fraction.' } },
  { equation: '5 − 2x = 11', value: '-3', hint: { zh: '先从两边减去 5。下一步留意 x 前面的负号。', en: 'Subtract 5 from both sides. Keep the sign of the coefficient of x in the next step.' } },
] as const;

type Linear = { coefficient: bigint; constant: bigint; denominator: bigint };
type StepStatus = 'equivalent' | 'solved' | 'changed' | 'unreadable';
export type CheckedStep = { line: number; expression: string; status: StepStatus };

// The demo only accepts signed sums of rational constants and multiples of x.
function readSide(side: string): Linear | undefined {
  if (!side || side.length > 160) return;
  const terms = side.match(/[+-]?[^+-]+/g);
  if (!terms || terms.join('') !== side) return;
  let coefficient = 0n, constant = 0n, denominator = 1n;
  for (const term of terms) {
    const parts = /^([+-]?)(?:(\d+(?:\.\d+)?)(?:\/(\d+))?(?:\*?(x))?|(x))(?:\/(\d+))?$/.exec(term);
    if (!parts || (parts[6] && !parts[4] && !parts[5]) || (parts[3] && parts[6])) return;
    const [, sign, magnitude = '1', divisor, xAfter, xOnly, xDivisor] = parts;
    const [whole, decimal = ''] = magnitude.split('.');
    const n = (sign === '-' ? -1n : 1n) * BigInt(whole + decimal);
    const d = 10n ** BigInt(decimal.length) * BigInt(divisor ?? xDivisor ?? '1');
    if (d === 0n) return;
    const variable = Boolean(xAfter || xOnly);
    coefficient = coefficient * d + (variable ? n * denominator : 0n);
    constant = constant * d + (variable ? 0n : n * denominator);
    denominator *= d;
  }
  return { coefficient, constant, denominator };
}

function checkLine(expression: string, reference: Linear): StepStatus {
  const normalized = expression.normalize('NFKC').replace(/[−–]/g, '-').replace(/×/g, '*').replace(/÷/g, '/').trim();
  if (/\d\s+\d/.test(normalized)) return 'unreadable';
  const sides = normalized.replace(/\s+/g, '').split('=');
  if (sides.length > 2) return 'unreadable';
  const [leftText, rightText] = sides.length === 1 ? ['x', sides[0]] : sides;
  const left = readSide(leftText), right = readSide(rightText);
  if (!left || !right || (sides.length === 1 && /x/.test(rightText))) return 'unreadable';
  const a = left.coefficient * right.denominator - right.coefficient * left.denominator;
  const b = left.constant * right.denominator - right.constant * left.denominator;
  if (a === 0n || a * reference.constant + b * reference.denominator !== 0n) return 'changed';
  if ((leftText === 'x' && !rightText.includes('x')) || (rightText === 'x' && !leftText.includes('x'))) return 'solved';
  return 'equivalent';
}

export function checkPractice(draft: string, example: typeof practiceExamples[number]): CheckedStep[] {
  const reference = readSide(example.value)!;
  const result: CheckedStep[] = [];
  const lines = draft.split(/\r?\n/);
  for (const [index, line] of lines.entries()) {
    const expression = line.trim();
    if (!expression) continue;
    const status = result.length >= 12 ? 'unreadable' : checkLine(expression, reference);
    result.push({ line: index + 1, expression, status });
    if (status === 'unreadable' || status === 'changed') break;
  }
  return result;
}
