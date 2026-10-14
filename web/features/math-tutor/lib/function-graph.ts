/**
 * Server-computed function graphs. The server sends sampled points inside a
 * `mathtutor-graph` fenced block on a SHOW_GRAPH message; this module only
 * validates them for drawing. Model text never reaches here: callers check
 * the server-owned message action first.
 */

export const GRAPH_ACTION = "SHOW_GRAPH";
/** Free-chat answer whose scenes the server built from draw_scene calls. */
export const FIGURE_ACTION = "TUTOR_CHAT_FIGURE";

export interface GraphMark { x: number; y: number; label: string }
export interface GraphSeries { label: string; segments: [number, number][][] }
export interface GraphSpec {
  title: string;
  xRange: [number, number];
  yRange: [number, number];
  series: GraphSeries[];
  vertical: { x: number; label: string }[];
  marks: GraphMark[];
  note: string;
}

const BLOCK = /```mathtutor-graph\n([\s\S]*?)\n```/;
const MAX_SERIES = 4;
const MAX_POINTS = 4000;

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const label = (value: unknown) => (typeof value === "string" ? value.slice(0, 80) : "");

function range(value: unknown): [number, number] | null {
  return Array.isArray(value) && value.length === 2 && finite(value[0]) && finite(value[1]) && value[0] < value[1]
    ? [value[0], value[1]] : null;
}

/** Strict projection; anything malformed is dropped rather than half-drawn. */
export function parseGraphSpec(raw: unknown): GraphSpec | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  const xRange = range(value.x_range);
  const yRange = range(value.y_range);
  if (value.v !== 1 || !xRange || !yRange || !Array.isArray(value.series) || value.series.length > MAX_SERIES) return null;
  let points = 0;
  const series: GraphSeries[] = [];
  for (const item of value.series) {
    if (!item || typeof item !== "object" || !Array.isArray((item as GraphSeries).segments)) return null;
    const segments: [number, number][][] = [];
    for (const segment of (item as GraphSeries).segments) {
      if (!Array.isArray(segment)) return null;
      const clean = segment.filter((p): p is [number, number] => Array.isArray(p) && p.length === 2 && finite(p[0]) && finite(p[1]));
      points += clean.length;
      if (clean.length > 1) segments.push(clean);
    }
    series.push({ label: label((item as GraphSeries).label), segments });
  }
  if (points > MAX_POINTS) return null;
  const marks = (Array.isArray(value.marks) ? value.marks : []).slice(0, 8)
    .filter((m): m is GraphMark => !!m && finite(m.x) && finite(m.y))
    .map(m => ({ x: m.x, y: m.y, label: label(m.label) }));
  const vertical = (Array.isArray(value.vertical) ? value.vertical : []).slice(0, 4)
    .filter((v): v is { x: number; label: string } => !!v && finite(v.x))
    .map(v => ({ x: v.x, label: label(v.label) }));
  return { title: label(value.title), xRange, yRange, series, vertical, marks, note: label(value.note) };
}

/** Split a SHOW_GRAPH message into prose before/after and the graph spec. */
export function splitGraphMessage(text: string): { before: string; spec: GraphSpec | null; after: string } {
  const match = BLOCK.exec(text);
  if (!match) return { before: text, spec: null, after: "" };
  let spec: GraphSpec | null = null;
  try {
    spec = parseGraphSpec(JSON.parse(match[1]));
  } catch {
    spec = null;
  }
  return { before: text.slice(0, match.index).trim(), spec, after: text.slice(match.index + match[0].length).trim() };
}

/** Round axis steps to 1, 2 or 5 × 10^k so about `target` ticks fit. */
export function niceStep(span: number, target = 8): number {
  const rough = span / target;
  const power = 10 ** Math.floor(Math.log10(rough));
  const unit = rough / power;
  return (unit < 1.5 ? 1 : unit < 3.5 ? 2 : unit < 7.5 ? 5 : 10) * power;
}

/** Linear interpolation of a series at x; null in gaps (asymptotes, domain holes). */
export function valueAt(series: GraphSeries, x: number): number | null {
  for (const segment of series.segments) {
    for (let i = 1; i < segment.length; i += 1) {
      const [x0, y0] = segment[i - 1];
      const [x1, y1] = segment[i];
      if (x >= x0 && x <= x1) return x1 === x0 ? y0 : y0 + ((y1 - y0) * (x - x0)) / (x1 - x0);
    }
  }
  return null;
}

export function formatTick(value: number): string {
  const rounded = Math.round(value * 1000) / 1000;
  return Object.is(rounded, -0) ? "0" : String(rounded);
}
