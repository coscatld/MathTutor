"use client";

import { useEffect, useId, useRef, useState } from "react";
import { formatTick, niceStep, valueAt, type GraphSpec } from "../lib/function-graph";

const HEIGHT = 300;
const PAD = { left: 40, right: 16, top: 14, bottom: 28 };
// Slot 2 of the validated categorical palette; slot 1 is the theme's --primary.
const SECOND = { light: "#eb6834", dark: "#d95926" };

interface Hover { px: number; x: number; values: (number | null)[] }
interface Readout { x: number; values: (number | null)[] }

const formatReadout = (value: number) => String(Number(value.toPrecision(8)));

function themeColors() {
  const style = getComputedStyle(document.documentElement);
  const read = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback;
  const dark = document.documentElement.classList.contains("dark");
  return {
    ink: read("--foreground", "#16181d"), muted: read("--muted-foreground", "#626875"),
    grid: read("--border", "#e7e9ee"), surface: read("--card", "#ffffff"),
    series: [read("--primary", "#2f4fe8"), dark ? SECOND.dark : SECOND.light],
  };
}

/** Canvas drawing with pointer read-out and an equivalent keyboard lookup. */
export default function FunctionGraph({ spec }: { spec: GraphSpec }) {
  // Streaming prose can reparse an unchanged graph. Preserve its lookup state,
  // while replacing the graph content starts a fresh input/result/live region.
  return <FunctionGraphView key={JSON.stringify(spec)} spec={spec} />;
}

function FunctionGraphView({ spec }: { spec: GraphSpec }) {
  const wrapper = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  const [theme, setTheme] = useState(0);
  const [hover, setHover] = useState<Hover | null>(null);
  const inputId = useId();
  const [inputX, setInputX] = useState(() => String(Math.min(spec.xRange[1], Math.max(spec.xRange[0], 0))));
  const [readout, setReadout] = useState<Readout | null>(null);
  const [inputError, setInputError] = useState("");
  const [announcement, setAnnouncement] = useState({ text: "", sequence: 0 });

  useEffect(() => {
    const element = wrapper.current;
    if (!element) return;
    const resize = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    resize.observe(element);
    const themeWatch = new MutationObserver(() => setTheme(value => value + 1));
    themeWatch.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme"] });
    return () => { resize.disconnect(); themeWatch.disconnect(); };
  }, []);

  const [x0, x1] = spec.xRange;
  const [y0, y1] = spec.yRange;
  const plotW = Math.max(1, width - PAD.left - PAD.right);
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const sx = (x: number) => PAD.left + ((x - x0) / (x1 - x0)) * plotW;
  const sy = (y: number) => PAD.top + ((y1 - y) / (y1 - y0)) * plotH;

  useEffect(() => {
    const element = canvas.current;
    if (!element || width <= 0) return;
    const ratio = window.devicePixelRatio || 1;
    element.width = width * ratio;
    element.height = HEIGHT * ratio;
    const ctx = element.getContext("2d");
    if (!ctx) return;
    const colors = themeColors();
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, HEIGHT);
    ctx.font = "11px system-ui, sans-serif";

    // Recessive grid and ticks.
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
    // Axes through the origin when visible.
    ctx.strokeStyle = colors.muted;
    ctx.lineWidth = 1.25;
    if (y0 <= 0 && y1 >= 0) { ctx.beginPath(); ctx.moveTo(PAD.left, sy(0)); ctx.lineTo(PAD.left + plotW, sy(0)); ctx.stroke(); }
    if (x0 <= 0 && x1 >= 0) { ctx.beginPath(); ctx.moveTo(sx(0), PAD.top); ctx.lineTo(sx(0), PAD.top + plotH); ctx.stroke(); }

    ctx.save();
    ctx.beginPath();
    ctx.rect(PAD.left, PAD.top, plotW, plotH);
    ctx.clip();
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    spec.series.forEach((series, index) => {
      ctx.strokeStyle = colors.series[index % colors.series.length];
      ctx.setLineDash(index === 0 ? [] : [7, 4]);
      for (const segment of series.segments) {
        ctx.beginPath();
        segment.forEach(([x, y], i) => (i ? ctx.lineTo(sx(x), sy(y)) : ctx.moveTo(sx(x), sy(y))));
        ctx.stroke();
      }
    });
    spec.vertical.forEach((line, index) => {
      ctx.strokeStyle = colors.series[(spec.series.filter(s => s.segments.length).length + index) % colors.series.length];
      ctx.setLineDash([7, 4]);
      ctx.beginPath(); ctx.moveTo(sx(line.x), PAD.top); ctx.lineTo(sx(line.x), PAD.top + plotH); ctx.stroke();
    });
    ctx.setLineDash([]);
    // Marked points: 8px dot with a surface ring, short coordinate label.
    for (const mark of spec.marks) {
      ctx.beginPath();
      ctx.arc(sx(mark.x), sy(mark.y), 4, 0, Math.PI * 2);
      ctx.fillStyle = colors.ink;
      ctx.strokeStyle = colors.surface;
      ctx.lineWidth = 2;
      ctx.fill(); ctx.stroke();
      const text = mark.label.replace(/^[^(]*/, "");
      const right = sx(mark.x) < PAD.left + plotW - 70;
      ctx.textAlign = right ? "left" : "right";
      ctx.textBaseline = "bottom";
      ctx.fillStyle = colors.ink;
      ctx.fillText(text, sx(mark.x) + (right ? 7 : -7), sy(mark.y) - 4);
    }
    if (hover) {
      ctx.strokeStyle = colors.muted;
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath(); ctx.moveTo(hover.px, PAD.top); ctx.lineTo(hover.px, PAD.top + plotH); ctx.stroke();
      ctx.setLineDash([]);
      hover.values.forEach((value, index) => {
        if (value === null || value < y0 || value > y1) return;
        ctx.beginPath();
        ctx.arc(hover.px, sy(value), 4, 0, Math.PI * 2);
        ctx.fillStyle = colors.series[index % colors.series.length];
        ctx.strokeStyle = colors.surface;
        ctx.lineWidth = 2;
        ctx.fill(); ctx.stroke();
      });
    }
    ctx.restore();
  }, [spec, width, hover, theme, x0, x1, y0, y1, plotW, plotH]);

  const onMove = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const px = event.clientX - event.currentTarget.getBoundingClientRect().left;
    if (px < PAD.left || px > PAD.left + plotW) { setHover(null); return; }
    const x = x0 + ((px - PAD.left) / plotW) * (x1 - x0);
    setHover({ px, x, values: spec.series.map(series => valueAt(series, x)) });
  };

  const readValue = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const x = Number(inputX);
    if (!inputX.trim() || !Number.isFinite(x) || x < x0 || x > x1) {
      const error = `请输入 ${x0} 到 ${x1} 之间的有限数值（含端点）。`;
      setInputError(error);
      setAnnouncement(previous => ({ text: error, sequence: previous.sequence + 1 }));
      return;
    }
    const values = spec.series.map(series => valueAt(series, x));
    setInputError("");
    setReadout({ x, values });
    const text = `x = ${formatReadout(x)}。${values.length ? values.map((value, index) => `${spec.series[index].label || `曲线 ${index + 1}`}：${value === null ? "无定义" : formatReadout(value)}`).join("；") : "当前图中没有可读取 y 值的函数曲线。"}`;
    setAnnouncement(previous => ({ text, sequence: previous.sequence + 1 }));
  };

  const named = spec.series.filter(series => series.label && series.segments.length);
  const summary = [spec.title, ...spec.marks.map(mark => mark.label)].filter(Boolean).join("；");
  const submitted = readout;
  return (
    <figure className="my-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-3">
      {named.length + spec.vertical.length > 1 ? (
        <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--foreground)]" aria-label="图例">
          {named.map((series, index) => <li key={series.label} className="flex items-center gap-1.5">
            <svg width="18" height="6" aria-hidden="true"><line x1="1" y1="3" x2="17" y2="3" stroke={index === 0 ? "var(--primary)" : "#eb6834"} strokeWidth="2" strokeDasharray={index === 0 ? undefined : "5 3"} strokeLinecap="round" /></svg>{series.label}</li>)}
          {spec.vertical.map(line => <li key={line.label} className="flex items-center gap-1.5">
            <svg width="18" height="6" aria-hidden="true"><line x1="1" y1="3" x2="17" y2="3" stroke="#eb6834" strokeWidth="2" strokeDasharray="5 3" strokeLinecap="round" /></svg>{line.label}</li>)}
        </ul>
      ) : null}
      <div ref={wrapper} className="relative">
        <canvas ref={canvas} role="img" aria-label={summary || "函数图像"} aria-describedby={`${inputId}-help`} style={{ width: "100%", height: HEIGHT, touchAction: "pan-y" }}
          onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)} />
        {hover ? <div aria-hidden="true" className="pointer-events-none absolute top-1 rounded-md border border-[var(--border)] bg-[var(--card)] px-2 py-1 text-xs text-[var(--foreground)] shadow-[var(--shadow-xs)]"
          style={hover.px > width / 2 ? { right: width - hover.px + 8 } : { left: hover.px + 8 }}>
          <div className="text-[var(--muted-foreground)]">x = {formatTick(hover.x)}</div>
          {hover.values.map((value, index) => spec.series[index].segments.length ? <div key={index}>{named.length > 1 ? `${spec.series[index].label}：` : "y = "}{value === null ? "无定义" : formatTick(value)}</div> : null)}
        </div> : null}
      </div>
      {spec.marks.length ? <figcaption className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">
        <span className="sr-only">图上标出的点：</span>{spec.marks.map(mark => mark.label).join(" · ")}
      </figcaption> : null}
      <form onSubmit={readValue} noValidate className="mt-3 border-t border-[var(--border)] pt-3" aria-label="按 x 坐标读取函数值">
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-0 flex-1 basis-40">
            <label htmlFor={inputId} className="mb-1 block text-xs font-medium text-[var(--foreground)]">x 坐标</label>
            <input id={inputId} name="x" type="number" min={x0} max={x1} step="any" required value={inputX}
              onChange={event => { setInputX(event.target.value); setInputError(""); }}
              aria-invalid={inputError ? true : undefined} aria-describedby={`${inputId}-help${inputError ? ` ${inputId}-error` : ""}`}
              className="mt-input min-h-11 w-full min-w-0 text-base" />
          </div>
          <button type="submit" className="mt-btn min-h-11 shrink-0 px-4">读取</button>
        </div>
        <p id={`${inputId}-help`} className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">
          范围：{x0} ≤ x ≤ {x1}。读数按采样点作线性插值；分段空缺显示“无定义”，不跨段插值。
        </p>
        {inputError ? <p id={`${inputId}-error`} className="mt-1 text-xs leading-5 text-[var(--foreground)]">{inputError}</p> : null}
      </form>
      <p className="sr-only" role="status" aria-live="polite" aria-atomic="true">{announcement.text ? <span key={announcement.sequence}>{announcement.text}</span> : null}</p>
      {submitted ? spec.series.length ? <table className="mt-3 w-full table-fixed text-left text-xs leading-5 text-[var(--foreground)]">
        <caption className="mb-1 text-left font-medium">x = {formatReadout(submitted.x)} 的函数读数</caption>
        <thead><tr><th scope="col" className="w-2/3 py-1 pr-3 font-medium">函数</th><th scope="col" className="py-1 font-medium">y 值</th></tr></thead>
        <tbody>{submitted.values.map((value, index) => <tr key={index} className="border-t border-[var(--border)]">
          <th scope="row" className="break-words py-1 pr-3 font-normal">{spec.series[index].label || `曲线 ${index + 1}`}</th>
          <td className="break-words py-1">{value === null ? "无定义" : formatReadout(value)}</td>
        </tr>)}</tbody>
      </table> : <p className="mt-3 text-xs leading-5 text-[var(--foreground)]">当前图中没有可读取 y 值的函数曲线。</p> : null}
    </figure>
  );
}
