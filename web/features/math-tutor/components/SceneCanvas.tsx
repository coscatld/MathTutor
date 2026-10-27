"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Eraser, Pause, Play } from "lucide-react";
import { formatTick, niceStep } from "../lib/function-graph";
import {
  derivative, evaluate, fitView, formatNumber, marchingSquares, paramValues, resolvePoints,
  sampleFunction, sampleParametric, sampleRegion, type EvalEnv, type Point2,
} from "../lib/scene-eval";
import type { ExprAst, Scene, SceneObject } from "../lib/scene-types";
import { sceneSessionKey } from "../lib/scene-identity";

const HEIGHT = 320;
const PAD = { left: 40, right: 16, top: 14, bottom: 28 };
const PERIOD_SECONDS = 8;
const TRAIL_LIMIT = 1500;
const MODEL_NOTICE = "示意图：定义来自模型，图形由应用计算，未经数学核验";
// Validated categorical palette in fixed order; slot 1 is the theme's --primary. Never cycled.
const PALETTE = [
  { light: "", dark: "" },
  { light: "#eb6834", dark: "#d95926" },
  { light: "#1baf7a", dark: "#199e70" },
  { light: "#eda100", dark: "#c98500" },
  { light: "#e87ba4", dark: "#d55181" },
];
// Second and later curves also differ by dash so identity is not colour-alone.
const DASHES: number[][] = [[], [7, 4], [2, 4], [10, 4, 2, 4], [4, 4]];
const OVERFLOW_DASH = [6, 3, 1, 3];
const CURVES = new Set(["function", "implicit", "parametric", "region", "tangent", "circle"]);
const KIND_NAMES: Record<SceneObject["type"], string> = {
  function: "函数", implicit: "曲线", parametric: "参数曲线", region: "区域", point: "点", segment: "线段",
  line: "直线", ray: "射线", vector: "向量", polygon: "多边形", circle: "圆", tangent: "切线", text: "文字",
};

interface Colors { ink: string; muted: string; grid: string; surface: string; dark: boolean; primary: string }

function themeColors(): Colors {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  return {
    ink: read("--foreground", "#16181d"), muted: read("--muted-foreground", "#626875"),
    grid: read("--border", "#e7e9ee"), surface: read("--card", "#ffffff"), primary: read("--primary", "#2f4fe8"),
    dark: document.documentElement.classList.contains("dark"),
  };
}

/** Colour slot per curve-like object in definition order; null once the palette runs out. */
function curveSlots(scene: Scene): Map<string, number | null> {
  const slots = new Map<string, number | null>();
  for (const object of scene.objects) {
    if (object.hidden || !CURVES.has(object.type)) continue;
    slots.set(object.id, slots.size < PALETTE.length ? slots.size : null);
  }
  return slots;
}

function slotColor(slot: number | null, dark: boolean, primary: string, fallback: string): string {
  if (slot === null) return fallback;
  return slot === 0 ? primary : dark ? PALETTE[slot].dark : PALETTE[slot].light;
}

function stepDigits(step: number): number {
  return Math.max(0, Math.min(6, Math.ceil(-Math.log10(step) - 1e-9)));
}

function describe(object: SceneObject, env: EvalEnv): string {
  const name = object.label || object.id;
  const kind = KIND_NAMES[object.type];
  const coord = (value: Point2 | null | undefined) => (value ? `(${formatNumber(value[0], 2)}, ${formatNumber(value[1], 2)})` : "（无定义）");
  switch (object.type) {
    case "point": return `${kind} ${name} ${coord(env.points[object.id])}`;
    case "segment": case "line": case "ray": case "vector": return `${kind} ${object.label || `${object.from}${object.to}`}`;
    case "polygon": return `${kind} ${object.label || object.points.join("")}`;
    case "circle": return `${kind} ${object.label ? `${object.label}，` : ""}圆心 ${object.center}，半径 ${formatNumber(evaluate(object.radius, env), 2)}`;
    case "tangent": return `${kind} ${object.label ? `${object.label}，` : ""}${object.of} 在 x = ${formatNumber(evaluate(object.at, env), 2)} 处`;
    case "text": return `${kind}：${object.text}`;
    default: return `${kind} ${name}`;
  }
}

/** Interactive canvas for a server-compiled Scene v2: the app evaluates and draws every definition. */
export default function SceneCanvas({ scene, sceneId = "standalone" }: { scene: Scene; sceneId?: string }) {
  // A genuine definition change starts a new interaction session. This boundary
  // remains correct when callers rebuild equal objects or React discards a memo.
  return <SceneCanvasSession key={sceneSessionKey(scene, sceneId)} initialScene={scene} />;
}

function SceneCanvasSession({ initialScene }: { initialScene: Scene }) {
  const [scene] = useState(initialScene);
  const uid = useId();
  const figure = useRef<HTMLElement>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const trails = useRef<Record<string, Point2[]>>({});
  const [width, setWidth] = useState(0);
  const [theme, setTheme] = useState(0);
  const [dark, setDark] = useState(false);
  const [values, setValues] = useState<Record<string, number>>(() => paramValues(scene));
  const [playing, setPlaying] = useState<Record<string, boolean>>({});
  const [foreground, setForeground] = useState(false);
  const [inView, setInView] = useState(false);
  const [trailVersion, setTrailVersion] = useState(0);
  const [hover, setHover] = useState<{ px: number; py: number } | null>(null);

  const plotW = Math.max(1, width - PAD.left - PAD.right);
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const view = useMemo(() => fitView(scene.x_range, scene.y_range, plotW, plotH, scene.equal_aspect), [scene, plotW, plotH]);
  const env = useMemo<EvalEnv>(() => ({ vars: paramValues(scene, values), points: resolvePoints(scene, values) }), [scene, values]);
  const slots = useMemo(() => curveSlots(scene), [scene]);
  const traced = scene.objects.some(object => object.type === "point" && object.trace);

  useEffect(() => {
    const element = wrapper.current;
    if (!element) return;
    setDark(document.documentElement.classList.contains("dark"));
    const resize = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    resize.observe(element);
    const themeWatch = new MutationObserver(() => {
      setTheme(value => value + 1);
      setDark(document.documentElement.classList.contains("dark"));
    });
    themeWatch.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme"] });
    return () => { resize.disconnect(); themeWatch.disconnect(); };
  }, []);

  // Initialise autoplay once per scene version. Visibility only gates execution;
  // it must never overwrite the reader's play/pause choice.
  useEffect(() => {
    const media = typeof window.matchMedia === "function" ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
    if (!media?.matches) {
      const auto = Object.fromEntries(scene.params.filter(param => param.animate).map(param => [param.name, true]));
      if (Object.keys(auto).length) setPlaying(auto);
    }
    const onMotion = () => { if (media?.matches) setPlaying({}); };
    media?.addEventListener("change", onMotion);
    return () => media?.removeEventListener("change", onMotion);
  }, [scene]);

  useEffect(() => {
    const onVisibility = () => setForeground(!document.hidden);
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, []);

  useEffect(() => {
    const element = figure.current;
    if (!element) return;
    if (typeof IntersectionObserver !== "function") { setInView(true); return; }
    const root = element.closest<HTMLElement>("[data-chat-scroll-root]");
    const observer = new IntersectionObserver(([entry]) => {
      setInView(entry.isIntersecting && entry.intersectionRect.width > 0 && entry.intersectionRect.height > 0);
    }, { root, threshold: 0 });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!foreground || !inView) return;
    const active = scene.params.filter(param => playing[param.name]);
    if (!active.length) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.1, Math.max(0, (now - last) / 1000));
      last = now;
      setValues(previous => {
        const next = { ...previous };
        for (const param of active) {
          const span = param.max - param.min;
          let value = (previous[param.name] ?? param.value) + (span * dt) / PERIOD_SECONDS;
          if (value > param.max) value = param.min + ((value - param.max) % span);
          next[param.name] = value;
        }
        return next;
      });
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, scene, foreground, inView]);

  // Record traced point positions as params change (runs before the draw effect).
  useEffect(() => {
    for (const object of scene.objects) {
      if (object.type !== "point" || !object.trace) continue;
      const point = env.points[object.id];
      if (!point) continue;
      const trail = (trails.current[object.id] ||= []);
      const last = trail[trail.length - 1];
      if (last && last[0] === point[0] && last[1] === point[1]) continue;
      trail.push(point);
      if (trail.length > TRAIL_LIMIT) trail.shift();
    }
  }, [scene, env]);

  useEffect(() => {
    const element = canvas.current;
    if (!element || width <= 0) return;
    const ratio = window.devicePixelRatio || 1;
    element.width = width * ratio;
    element.height = HEIGHT * ratio;
    const ctx = element.getContext("2d");
    if (!ctx) return;
    const colors = themeColors();
    const [x0, x1] = view.x;
    const [y0, y1] = view.y;
    const kx = plotW / (x1 - x0);
    const ky = plotH / (y1 - y0);
    const sx = (x: number) => PAD.left + (x - x0) * kx;
    const sy = (y: number) => PAD.top + (y1 - y) * ky;
    const diag = Math.hypot(x1 - x0, y1 - y0);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, HEIGHT);
    ctx.font = "11px system-ui, sans-serif";

    // Recessive grid and ticks (same look as the v1 function graph).
    const xStep = niceStep(x1 - x0, Math.max(4, Math.floor(plotW / 70)));
    const yStep = niceStep(y1 - y0, 6);
    ctx.lineWidth = 1;
    ctx.strokeStyle = colors.grid;
    ctx.fillStyle = colors.muted;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    for (let x = Math.ceil(x0 / xStep) * xStep; x <= x1 + 1e-9; x += xStep) {
      ctx.beginPath(); ctx.moveTo(sx(x), PAD.top); ctx.lineTo(sx(x), PAD.top + plotH); ctx.stroke();
      ctx.fillText(formatTick(x), sx(x), PAD.top + plotH + 6);
    }
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let y = Math.ceil(y0 / yStep) * yStep; y <= y1 + 1e-9; y += yStep) {
      ctx.beginPath(); ctx.moveTo(PAD.left, sy(y)); ctx.lineTo(PAD.left + plotW, sy(y)); ctx.stroke();
      ctx.fillText(formatTick(y), PAD.left - 6, sy(y));
    }
    ctx.strokeStyle = colors.muted;
    ctx.lineWidth = 1.25;
    if (y0 <= 0 && y1 >= 0) { ctx.beginPath(); ctx.moveTo(PAD.left, sy(0)); ctx.lineTo(PAD.left + plotW, sy(0)); ctx.stroke(); }
    if (x0 <= 0 && x1 >= 0) { ctx.beginPath(); ctx.moveTo(sx(0), PAD.top); ctx.lineTo(sx(0), PAD.top + plotH); ctx.stroke(); }

    ctx.save();
    ctx.beginPath();
    ctx.rect(PAD.left, PAD.top, plotW, plotH);
    ctx.clip();
    ctx.lineJoin = "round";
    ctx.lineCap = "round";

    const at = (extra: Record<string, number>): EvalEnv => ({ vars: { ...env.vars, ...extra }, points: env.points });
    const fn1 = (expr: ExprAst, name: string) => (v: number) => evaluate(expr, at({ [name]: v }));
    const fn2 = (expr: ExprAst) => (x: number, y: number) => evaluate(expr, at({ x, y }));
    const stroke = (id: string) => {
      const slot = slots.get(id) ?? null;
      ctx.strokeStyle = slotColor(slot, colors.dark, colors.primary, colors.muted);
      ctx.fillStyle = ctx.strokeStyle;
      ctx.setLineDash(slot === null ? OVERFLOW_DASH : DASHES[slot]);
      ctx.lineWidth = 2;
    };
    const polyline = (pieces: Point2[][]) => {
      for (const piece of pieces) {
        ctx.beginPath();
        piece.forEach(([x, y], i) => (i ? ctx.lineTo(sx(x), sy(y)) : ctx.moveTo(sx(x), sy(y))));
        ctx.stroke();
      }
    };
    const straight = (p: Point2, q: Point2, mode: "segment" | "line" | "ray" | "vector") => {
      const dx = q[0] - p[0];
      const dy = q[1] - p[1];
      const length = Math.hypot(dx, dy);
      if (length === 0) return;
      const reach = (4 * diag) / length;
      const start: Point2 = mode === "line" ? [p[0] - dx * reach, p[1] - dy * reach] : p;
      const end: Point2 = mode === "line" || mode === "ray" ? [p[0] + dx * reach, p[1] + dy * reach] : q;
      ctx.beginPath(); ctx.moveTo(sx(start[0]), sy(start[1])); ctx.lineTo(sx(end[0]), sy(end[1])); ctx.stroke();
      if (mode === "vector") {
        const angle = Math.atan2(sy(q[1]) - sy(p[1]), sx(q[0]) - sx(p[0]));
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(sx(q[0]), sy(q[1]));
        ctx.lineTo(sx(q[0]) - 10 * Math.cos(angle - 0.4), sy(q[1]) - 10 * Math.sin(angle - 0.4));
        ctx.lineTo(sx(q[0]) - 10 * Math.cos(angle + 0.4), sy(q[1]) - 10 * Math.sin(angle + 0.4));
        ctx.closePath();
        ctx.fill();
      }
    };
    const dot = (x: number, y: number, fill: string) => {
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(sx(x), sy(y), 4, 0, Math.PI * 2);
      ctx.fillStyle = fill;
      ctx.strokeStyle = colors.surface;
      ctx.lineWidth = 2;
      ctx.fill(); ctx.stroke();
    };
    const label = (x: number, y: number, value: string) => {
      if (!value) return;
      const right = sx(x) < PAD.left + plotW - 80;
      ctx.textAlign = right ? "left" : "right";
      ctx.textBaseline = "bottom";
      ctx.fillStyle = colors.ink;
      ctx.fillText(value, sx(x) + (right ? 7 : -7), sy(y) - 4);
    };
    const visible = scene.objects.filter(object => !object.hidden);

    // Regions first, as translucent cell fills.
    for (const object of visible) {
      if (object.type !== "region") continue;
      const nx = Math.max(8, Math.ceil(plotW / 2));
      const ny = Math.max(8, Math.ceil(plotH / 2));
      const f = fn2(object.expr);
      const cells = sampleRegion(f, object.relation, view.x, view.y, nx, ny);
      stroke(object.id);
      ctx.globalAlpha = 0.16;
      const cw = plotW / nx;
      const ch = plotH / ny;
      // One path, one fill: overlapping cell edges must not stack their alpha.
      ctx.beginPath();
      for (let j = 0; j < ny; j += 1) {
        let run = -1;
        for (let i = 0; i <= nx; i += 1) {
          const inside = i < nx && cells[j * nx + i] === 1;
          if (inside && run < 0) run = i;
          if (!inside && run >= 0) {
            ctx.rect(PAD.left + run * cw, PAD.top + plotH - (j + 1) * ch, (i - run) * cw + 0.5, ch + 0.5);
            run = -1;
          }
        }
      }
      ctx.fill();
      ctx.globalAlpha = 1;
      // Boundary: dashed for a strict inequality, solid when it is included.
      ctx.setLineDash(object.relation === "lt" || object.relation === "gt" ? [6, 4] : []);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      for (const [[ax, ay], [bx, by]] of marchingSquares(f, view.x, view.y, Math.ceil(plotW / 3), Math.ceil(plotH / 3))) {
        ctx.moveTo(sx(ax), sy(ay)); ctx.lineTo(sx(bx), sy(by));
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // Polygon fills under the curves.
    for (const object of visible) {
      if (object.type !== "polygon" || !object.fill) continue;
      const pts = object.points.map(id => env.points[id]);
      if (pts.some(point => !point)) continue;
      ctx.globalAlpha = 0.1;
      ctx.fillStyle = colors.ink;
      ctx.beginPath();
      (pts as Point2[]).forEach(([x, y], i) => (i ? ctx.lineTo(sx(x), sy(y)) : ctx.moveTo(sx(x), sy(y))));
      ctx.closePath();
      ctx.fill();
      ctx.globalAlpha = 1;
    }
    // Curves.
    for (const object of visible) {
      switch (object.type) {
        case "function": {
          const lo = Math.max(x0, object.domain ? object.domain[0] : x0);
          const hi = Math.min(x1, object.domain ? object.domain[1] : x1);
          if (lo >= hi) break;
          stroke(object.id);
          polyline(sampleFunction(fn1(object.expr, "x"), [lo, hi], view.y, Math.max(200, Math.ceil(plotW * 2 * (hi - lo) / (x1 - x0)))));
          break;
        }
        case "implicit": {
          const nx = 160;
          const ny = Math.max(60, Math.min(160, Math.round((nx * plotH) / plotW)));
          stroke(object.id);
          ctx.beginPath();
          for (const [[ax, ay], [bx, by]] of marchingSquares(fn2(object.expr), view.x, view.y, nx, ny)) {
            ctx.moveTo(sx(ax), sy(ay)); ctx.lineTo(sx(bx), sy(by));
          }
          ctx.stroke();
          break;
        }
        case "parametric":
          stroke(object.id);
          polyline(sampleParametric(fn1(object.x, "s"), fn1(object.y, "s"), object.s_range, view.x, view.y, 800));
          break;
        case "circle": {
          const center = env.points[object.center];
          const radius = evaluate(object.radius, env);
          if (!center || radius === null || radius <= 0) break;
          stroke(object.id);
          ctx.beginPath();
          ctx.ellipse(sx(center[0]), sy(center[1]), radius * kx, radius * ky, 0, 0, Math.PI * 2);
          ctx.stroke();
          break;
        }
        case "tangent": {
          const source = scene.objects.find(item => item.id === object.of);
          if (!source || source.type !== "function") break;
          const a = evaluate(object.at, env);
          if (a === null || (source.domain && (a < source.domain[0] || a > source.domain[1]))) break;
          const f = fn1(source.expr, "x");
          const fa = f(a);
          const slope = derivative(f, a, (x1 - x0) * 1e-5);
          if (fa === null || slope === null) break;
          stroke(object.id);
          straight([a, fa], [a + 1, fa + slope], "line");
          break;
        }
        default: break;
      }
    }
    // Straight constructions in the ink colour.
    ctx.setLineDash([]);
    ctx.lineWidth = 2;
    for (const object of visible) {
      ctx.strokeStyle = colors.ink;
      ctx.fillStyle = colors.ink;
      ctx.setLineDash([]);
      if (object.type === "segment" || object.type === "line" || object.type === "ray" || object.type === "vector") {
        const p = env.points[object.from];
        const q = env.points[object.to];
        if (p && q) straight(p, q, object.type);
      } else if (object.type === "polygon") {
        const pts = object.points.map(id => env.points[id]);
        if (pts.some(point => !point)) continue;
        ctx.beginPath();
        (pts as Point2[]).forEach(([x, y], i) => (i ? ctx.lineTo(sx(x), sy(y)) : ctx.moveTo(sx(x), sy(y))));
        ctx.closePath();
        ctx.stroke();
      }
    }
    // Faint trails of traced points.
    ctx.setLineDash([]);
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = colors.muted;
    ctx.globalAlpha = 0.55;
    for (const object of visible) {
      const trail = object.type === "point" && object.trace ? trails.current[object.id] : undefined;
      if (!trail || trail.length < 2) continue;
      ctx.beginPath();
      trail.forEach(([x, y], i) => {
        const previous = trail[i - 1];
        if (!previous || Math.hypot(x - previous[0], y - previous[1]) > diag / 4) ctx.moveTo(sx(x), sy(y));
        else ctx.lineTo(sx(x), sy(y));
      });
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
    // Static marks, then points on top, then free text.
    for (const mark of scene.marks) { dot(mark.x, mark.y, colors.muted); label(mark.x, mark.y, mark.label); }
    for (const object of visible) {
      if (object.type !== "point") continue;
      const point = env.points[object.id];
      if (!point) continue;
      dot(point[0], point[1], colors.ink);
      label(point[0], point[1], object.label ?? object.id);
    }
    for (const object of visible) {
      if (object.type !== "text") continue;
      const x = evaluate(object.x, env);
      const y = evaluate(object.y, env);
      if (x === null || y === null) continue;
      ctx.fillStyle = colors.ink;
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(object.text, sx(x), sy(y));
    }
    if (hover) {
      ctx.strokeStyle = colors.muted;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(hover.px, PAD.top); ctx.lineTo(hover.px, PAD.top + plotH);
      ctx.moveTo(PAD.left, hover.py); ctx.lineTo(PAD.left + plotW, hover.py);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.restore();
  }, [scene, env, view, slots, width, plotW, plotH, hover, theme, trailVersion]);

  const toData = (px: number, py: number): Point2 => [
    view.x[0] + ((px - PAD.left) / plotW) * (view.x[1] - view.x[0]),
    view.y[1] - ((py - PAD.top) / plotH) * (view.y[1] - view.y[0]),
  ];
  const onMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    if (px < PAD.left || px > PAD.left + plotW || py < PAD.top || py > PAD.top + plotH) { setHover(null); return; }
    setHover({ px, py });
  };
  const setParam = (name: string, value: number) => {
    setPlaying(previous => (previous[name] ? { ...previous, [name]: false } : previous));
    setValues(previous => ({ ...previous, [name]: value }));
  };
  const clearTrails = () => {
    trails.current = {};
    setTrailVersion(value => value + 1);
  };

  const visible = scene.objects.filter(object => !object.hidden);
  const legend = visible.filter(object => CURVES.has(object.type) && object.label);
  const readouts = scene.readouts.map(readout => ({ label: readout.label, value: formatNumber(evaluate(readout.expr, env), readout.digits ?? 3) }));
  const summary = [scene.title, ...scene.marks.map(mark => mark.label)].filter(Boolean).join("；");
  const hoverPoint = hover ? toData(hover.px, hover.py) : null;
  const hoverDigits = Math.max(0, Math.min(4, Math.ceil(-Math.log10((view.x[1] - view.x[0]) / 100))));

  return (
    <figure ref={figure} className="mt-scene my-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
      {scene.source === "model" ? <p role="note" className="mb-2 text-xs leading-5 text-[var(--muted-foreground)]">{MODEL_NOTICE}</p> : null}
      {legend.length >= 2 ? (
        <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--foreground)]" aria-label="图例">
          {legend.map(object => {
            const slot = slots.get(object.id) ?? null;
            const color = slotColor(slot, dark, "var(--primary)", "var(--muted-foreground)");
            const dash = slot === null ? OVERFLOW_DASH : DASHES[slot];
            return <li key={object.id} className="flex min-w-0 items-center gap-1.5">
              <svg width="18" height="6" className="shrink-0" aria-hidden="true"><line x1="1" y1="3" x2="17" y2="3" stroke={color} strokeWidth="2" strokeDasharray={dash.length ? dash.map(v => Math.max(1, Math.round(v * 0.7))).join(" ") : undefined} strokeLinecap="round" /></svg>
              {object.label}
            </li>;
          })}
        </ul>
      ) : null}
      <div ref={wrapper} className="relative">
        <canvas ref={canvas} role="img" aria-label={summary || "数形结合图"} style={{ width: "100%", height: HEIGHT, touchAction: "pan-y" }}
          onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} />
        {hover && hoverPoint ? <div className="pointer-events-none absolute top-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-xs text-[var(--foreground)] shadow-[var(--shadow-xs)]"
          style={hover.px > width / 2 ? { right: width - hover.px + 8 } : { left: hover.px + 8 }}>
          ({formatNumber(hoverPoint[0], hoverDigits)}, {formatNumber(hoverPoint[1], hoverDigits)})
        </div> : null}
      </div>
      {scene.params.length || traced ? (
        <div className="mt-2 flex flex-col gap-2 text-sm text-[var(--foreground)]">
          {scene.params.map(param => {
            const id = `${uid}-param-${param.name}`;
            const value = values[param.name] ?? param.value;
            const shown = formatNumber(value, stepDigits(param.step));
            const on = !!playing[param.name];
            return <div key={param.name} className="mt-scene-param">
              <div className="mt-scene-param-meta">
                <label htmlFor={id}>{param.label}</label>
                <output htmlFor={id} className="tabular-nums text-[var(--muted-foreground)]">{shown}</output>
              </div>
              <div className="mt-scene-param-controls">
              <input id={id} type="range" min={param.min} max={param.max} step={param.step} value={value}
                aria-valuetext={`${param.label} = ${shown}`} className="accent-[var(--primary)]"
                onChange={event => setParam(param.name, Number(event.currentTarget.value))} />
              {param.animate ? <button type="button" aria-pressed={on} aria-label={`${on ? "暂停" : "播放"} ${param.label} 动画`}
                className="flex min-h-11 shrink-0 items-center justify-center gap-1 rounded-md border border-[var(--border)] px-2 text-xs"
                onClick={() => setPlaying(previous => ({ ...previous, [param.name]: !on }))}>
                {on ? <Pause className="h-3.5 w-3.5" aria-hidden="true" /> : <Play className="h-3.5 w-3.5" aria-hidden="true" />}{on ? "暂停" : "播放"}
              </button> : null}
              </div>
            </div>;
          })}
          {traced ? <div><button type="button" onClick={clearTrails}
            className="flex min-h-11 items-center gap-1 rounded-md border border-[var(--border)] px-2 text-xs">
            <Eraser className="h-3.5 w-3.5" aria-hidden="true" />清除轨迹</button></div> : null}
        </div>
      ) : null}
      {readouts.length ? (
        <dl className="mt-scene-readouts mt-2 grid gap-x-3 gap-y-0.5 text-sm text-[var(--foreground)]" aria-label="读数">
          {readouts.map((readout, index) => <div key={index} className="contents">
            <dt className="text-[var(--muted-foreground)]">{readout.label}</dt>
            <dd className="tabular-nums">{readout.value}</dd>
          </div>)}
        </dl>
      ) : null}
      {scene.note ? <p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">{scene.note}</p> : null}
      <figcaption className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">
        {scene.marks.length ? <div><span className="sr-only">图上标出的点：</span>{scene.marks.map(mark => mark.label).join(" · ")}</div> : null}
        <details>
          <summary className="cursor-pointer">图中对象</summary>
          <ul className="mt-1 list-disc pl-5">
            {scene.title ? <li>{scene.title}</li> : null}
            {visible.map(object => <li key={object.id}>{describe(object, env)}</li>)}
            {scene.marks.map((mark, index) => <li key={`mark-${index}`}>标注 {mark.label}</li>)}
            {readouts.map((readout, index) => <li key={`readout-${index}`}>{readout.label} = {readout.value}</li>)}
          </ul>
        </details>
      </figcaption>
    </figure>
  );
}
