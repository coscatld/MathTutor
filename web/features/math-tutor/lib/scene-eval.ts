/**
 * Scene v2 (docs/SCENE_SPEC.md): strict projection of the server JSON, an AST
 * evaluator and the sampling helpers the canvas uses. Pure functions only.
 * Model text never reaches here: callers check the server-owned message action.
 */

import {
  BINARY_FUNCTIONS, RESERVED_NAMES, SCENE_LIMITS, UNARY_FUNCTIONS,
  type ExprAst, type Scene, type SceneMark, type SceneObject, type SceneParam, type SceneReadout,
} from "./scene-types";

const BLOCK = /```mathtutor-scene\n([\s\S]*?)\n```/;
const ID = /^[A-Za-z0-9]{1,8}$/;
const PARAM_NAME = /^[A-Za-z]$/;
const OPS = new Set(["+", "-", "*", "/", "^"]);
const UNARY = new Set<string>(UNARY_FUNCTIONS);
const BINARY = new Set<string>(BINARY_FUNCTIONS);
const RESERVED = new Set<string>(RESERVED_NAMES);
const GEO_ARITY: Record<string, [number, number]> = {
  dist: [2, 2], slope: [2, 2], angle: [3, 3], area: [3, SCENE_LIMITS.objects], mid_x: [2, 2], mid_y: [2, 2],
};

const finite = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const isObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown, max: number) => (typeof value === "string" ? value.slice(0, max) : "");

function range(value: unknown): [number, number] | null {
  return Array.isArray(value) && value.length === 2 && finite(value[0]) && finite(value[1]) && value[0] < value[1]
    ? [value[0], value[1]] : null;
}

/** What an expression may name: plot variables, params and point ids. */
interface AstScope { vars: Set<string>; points: Set<string> }

/** Validate and copy one AST; null when any node is outside the whitelist or limits. */
export function parseAst(raw: unknown, scope: AstScope): ExprAst | null {
  let nodes = 0;
  const walk = (node: unknown, depth: number): ExprAst | null => {
    nodes += 1;
    if (depth > SCENE_LIMITS.astDepth || nodes > SCENE_LIMITS.astNodes || !isObject(node)) return null;
    const args = (count: number): ExprAst[] | null => {
      if (!Array.isArray(node.a) || node.a.length !== count) return null;
      const out: ExprAst[] = [];
      for (const child of node.a) {
        const parsed = walk(child, depth + 1);
        if (!parsed) return null;
        out.push(parsed);
      }
      return out;
    };
    switch (node.k) {
      case "num":
        return finite(node.v) ? { k: "num", v: node.v } : null;
      case "var":
        return typeof node.n === "string" && scope.vars.has(node.n) ? { k: "var", n: node.n } : null;
      case "op": {
        if (typeof node.o !== "string" || !OPS.has(node.o)) return null;
        const a = args(2);
        return a ? { k: "op", o: node.o as "+", a: [a[0], a[1]] } : null;
      }
      case "neg": {
        const a = args(1);
        return a ? { k: "neg", a: [a[0]] } : null;
      }
      case "fn": {
        if (typeof node.f !== "string") return null;
        const arity = UNARY.has(node.f) ? 1 : BINARY.has(node.f) ? 2 : 0;
        const a = arity ? args(arity) : null;
        return a ? { k: "fn", f: node.f, a } : null;
      }
      case "coord":
        return typeof node.p === "string" && scope.points.has(node.p) && (node.c === "x" || node.c === "y")
          ? { k: "coord", p: node.p, c: node.c } : null;
      case "geo": {
        const arity = typeof node.f === "string" ? GEO_ARITY[node.f] : undefined;
        if (!arity || !Object.prototype.hasOwnProperty.call(GEO_ARITY, node.f as string) || !Array.isArray(node.p)) return null;
        if (node.p.length < arity[0] || node.p.length > arity[1]) return null;
        if (!node.p.every(id => typeof id === "string" && scope.points.has(id))) return null;
        return { k: "geo", f: node.f as "dist", p: [...(node.p as string[])] };
      }
      default:
        return null;
    }
  };
  return walk(raw, 1);
}

function parseParams(raw: unknown): SceneParam[] | null {
  if (raw === undefined) return [];
  if (!Array.isArray(raw) || raw.length > SCENE_LIMITS.params) return null;
  const seen = new Set<string>();
  const params: SceneParam[] = [];
  for (const item of raw) {
    if (!isObject(item)) return null;
    const { name, min, max, step, value } = item;
    if (typeof name !== "string" || !PARAM_NAME.test(name) || RESERVED.has(name) || seen.has(name)) return null;
    if (!finite(min) || !finite(max) || !finite(step) || !finite(value) || min >= max || step <= 0 || value < min || value > max) return null;
    if (item.animate !== undefined && typeof item.animate !== "boolean") return null;
    seen.add(name);
    params.push({ name, min, max, step, value, animate: item.animate === true, label: text(item.label, 60) || name });
  }
  return params;
}

function parseObjects(raw: unknown, paramNames: string[]): SceneObject[] | null {
  if (!Array.isArray(raw) || raw.length > SCENE_LIMITS.objects) return null;
  const ids = new Set<string>();
  const kinds = new Map<string, string>();
  for (const item of raw) {
    if (!isObject(item) || typeof item.id !== "string" || !ID.test(item.id) || ids.has(item.id) || typeof item.type !== "string") return null;
    ids.add(item.id);
    kinds.set(item.id, item.type);
  }
  const allPoints = new Set([...kinds].filter(([, type]) => type === "point").map(([id]) => id));
  const earlierPoints = new Set<string>();
  const scope = (plot: string[], points: Set<string>): AstScope => ({ vars: new Set([...plot, ...paramNames]), points });
  const isPoint = (id: unknown): id is string => typeof id === "string" && allPoints.has(id);

  const objects: SceneObject[] = [];
  for (const item of raw as Record<string, unknown>[]) {
    const id = item.id as string;
    if (item.hidden !== undefined && typeof item.hidden !== "boolean") return null;
    const base = { id, ...(typeof item.label === "string" ? { label: item.label.slice(0, 60) } : {}), ...(item.hidden ? { hidden: true } : {}) };
    // Non-point objects are drawn after every point is resolved, so they may name any point.
    let object: SceneObject | null = null;
    switch (item.type) {
      case "function": {
        const expr = parseAst(item.expr, scope(["x"], allPoints));
        const domain = item.domain === undefined ? undefined : range(item.domain);
        if (expr && domain !== null) object = { ...base, type: "function", expr, ...(domain ? { domain } : {}) };
        break;
      }
      case "implicit": {
        const expr = parseAst(item.expr, scope(["x", "y"], allPoints));
        if (expr) object = { ...base, type: "implicit", expr };
        break;
      }
      case "region": {
        const expr = parseAst(item.expr, scope(["x", "y"], allPoints));
        const relation = item.relation;
        if (expr && (relation === "lt" || relation === "le" || relation === "gt" || relation === "ge")) object = { ...base, type: "region", expr, relation };
        break;
      }
      case "parametric": {
        const x = parseAst(item.x, scope(["s"], allPoints));
        const y = parseAst(item.y, scope(["s"], allPoints));
        const sRange = range(item.s_range);
        if (x && y && sRange) object = { ...base, type: "parametric", x, y, s_range: sRange };
        break;
      }
      case "point": {
        const x = parseAst(item.x, scope([], earlierPoints));
        const y = parseAst(item.y, scope([], earlierPoints));
        if (item.trace !== undefined && typeof item.trace !== "boolean") return null;
        if (x && y) object = { ...base, type: "point", x, y, ...(item.trace ? { trace: true } : {}) };
        earlierPoints.add(id);
        break;
      }
      case "segment": case "line": case "ray": case "vector":
        if (isPoint(item.from) && isPoint(item.to)) object = { ...base, type: item.type, from: item.from, to: item.to };
        break;
      case "polygon":
        if (Array.isArray(item.points) && item.points.length >= 3 && item.points.length <= SCENE_LIMITS.objects && item.points.every(isPoint)
          && (item.fill === undefined || typeof item.fill === "boolean")) {
          object = { ...base, type: "polygon", points: [...(item.points as string[])], fill: item.fill === true };
        }
        break;
      case "circle": {
        const radius = parseAst(item.radius, scope([], allPoints));
        if (isPoint(item.center) && radius) object = { ...base, type: "circle", center: item.center, radius };
        break;
      }
      case "tangent": {
        const at = parseAst(item.at, scope([], allPoints));
        if (typeof item.of === "string" && kinds.get(item.of) === "function" && at) object = { ...base, type: "tangent", of: item.of, at };
        break;
      }
      case "text": {
        const x = parseAst(item.x, scope([], allPoints));
        const y = parseAst(item.y, scope([], allPoints));
        if (x && y && typeof item.text === "string") object = { ...base, type: "text", x, y, text: item.text.slice(0, 60) };
        break;
      }
      default:
        return null;
    }
    if (!object) return null;
    objects.push(object);
  }
  return objects;
}

/** Strict projection; anything malformed rejects the whole scene rather than half-drawing it. */
export function parseScene(raw: unknown): Scene | null {
  if (!isObject(raw) || raw.v !== 2) return null;
  const xRange = range(raw.x_range);
  const yRange = range(raw.y_range);
  if (!xRange || !yRange) return null;
  if (raw.source !== "deterministic" && raw.source !== "model") return null;
  if (raw.equal_aspect !== undefined && typeof raw.equal_aspect !== "boolean") return null;
  const params = parseParams(raw.params);
  if (!params) return null;
  const paramNames = params.map(param => param.name);
  const objects = parseObjects(raw.objects, paramNames);
  if (!objects) return null;
  const pointIds = new Set(objects.filter(object => object.type === "point").map(object => object.id));

  const rawReadouts = raw.readouts === undefined ? [] : raw.readouts;
  if (!Array.isArray(rawReadouts) || rawReadouts.length > SCENE_LIMITS.readouts) return null;
  const readouts: SceneReadout[] = [];
  for (const item of rawReadouts) {
    if (!isObject(item)) return null;
    const expr = parseAst(item.expr, { vars: new Set(paramNames), points: pointIds });
    const digits = item.digits === undefined ? 3 : item.digits;
    if (!expr || typeof digits !== "number" || !Number.isInteger(digits) || digits < 0 || digits > 10) return null;
    readouts.push({ label: text(item.label, 60), expr, digits });
  }

  const rawMarks = raw.marks === undefined ? [] : raw.marks;
  if (!Array.isArray(rawMarks) || rawMarks.length > SCENE_LIMITS.marks) return null;
  const marks: SceneMark[] = [];
  for (const item of rawMarks) {
    if (!isObject(item) || !finite(item.x) || !finite(item.y)) return null;
    marks.push({ x: item.x, y: item.y, label: text(item.label, 60) });
  }

  return {
    v: 2, title: text(raw.title, 80), source: raw.source, x_range: xRange, y_range: yRange,
    equal_aspect: raw.equal_aspect === true, params, objects, readouts, marks, note: text(raw.note, 200),
  };
}

/** Split a SHOW_GRAPH message into prose before/after and the scene. */
export function splitSceneMessage(message: string): { before: string; scene: Scene | null; after: string } {
  const match = BLOCK.exec(message);
  if (!match) return { before: message, scene: null, after: "" };
  let scene: Scene | null = null;
  try {
    scene = parseScene(JSON.parse(match[1]));
  } catch {
    scene = null;
  }
  return { before: message.slice(0, match.index).trim(), scene, after: message.slice(match.index + match[0].length).trim() };
}

/** Every valid scene block in order (at most 4); null when the first is missing or invalid. */
export function splitSceneBlocks(message: string): { parts: { before: string; scene: Scene }[]; after: string } | null {
  const parts: { before: string; scene: Scene }[] = [];
  let rest = message;
  while (parts.length < 4) {
    const split = splitSceneMessage(rest);
    if (!split.scene) break;
    parts.push({ before: split.before, scene: split.scene });
    rest = split.after;
  }
  return parts.length ? { parts, after: rest } : null;
}

// ---------------------------------------------------------------------------
// Evaluation

export type Point2 = [number, number];
export interface EvalEnv { vars: Record<string, number>; points: Record<string, Point2 | null> }

const ok = (value: number): number | null => (Number.isFinite(value) ? value : null);

function unary(f: string, a: number): number {
  switch (f) {
    case "sin": return Math.sin(a);
    case "cos": return Math.cos(a);
    case "tan": return Math.abs(Math.cos(a)) < 1e-12 ? NaN : Math.tan(a);
    case "asin": return Math.asin(a);
    case "acos": return Math.acos(a);
    case "atan": return Math.atan(a);
    case "sqrt": return Math.sqrt(a);
    case "abs": return Math.abs(a);
    case "ln": return a > 0 ? Math.log(a) : NaN;
    case "log": return a > 0 ? Math.log10(a) : NaN;
    case "exp": return Math.exp(a);
    case "floor": return Math.floor(a);
    case "ceil": return Math.ceil(a);
    case "sign": return Math.sign(a);
    default: return NaN;
  }
}

function binary(f: string, a: number, b: number): number {
  switch (f) {
    case "min": return Math.min(a, b);
    case "max": return Math.max(a, b);
    case "atan2": return Math.atan2(a, b);
    default: return NaN;
  }
}

function power(base: number, exponent: number): number {
  if (base === 0 && exponent < 0) return NaN;
  if (base < 0 && !Number.isInteger(exponent)) {
    // Real odd roots of negatives, e.g. x^(1/3); even roots stay undefined.
    const inverse = 1 / exponent;
    const odd = Math.round(inverse);
    if (Math.abs(inverse - odd) < 1e-9 && Math.abs(odd) % 2 === 1) return -Math.pow(-base, exponent);
    return NaN;
  }
  return Math.pow(base, exponent);
}

function geo(f: string, pts: Point2[]): number {
  const [a, b, c] = pts;
  switch (f) {
    case "dist": return Math.hypot(b[0] - a[0], b[1] - a[1]);
    case "slope": return b[0] === a[0] ? NaN : (b[1] - a[1]) / (b[0] - a[0]);
    case "mid_x": return (a[0] + b[0]) / 2;
    case "mid_y": return (a[1] + b[1]) / 2;
    case "angle": {
      const u = [a[0] - b[0], a[1] - b[1]];
      const v = [c[0] - b[0], c[1] - b[1]];
      const norm = Math.hypot(u[0], u[1]) * Math.hypot(v[0], v[1]);
      if (norm === 0) return NaN;
      const cos = Math.max(-1, Math.min(1, (u[0] * v[0] + u[1] * v[1]) / norm));
      return (Math.acos(cos) * 180) / Math.PI;
    }
    case "area": {
      let twice = 0;
      pts.forEach((p, i) => { const q = pts[(i + 1) % pts.length]; twice += p[0] * q[1] - q[0] * p[1]; });
      return Math.abs(twice) / 2;
    }
    default: return NaN;
  }
}

/** Evaluate an AST; null for any non-finite or out-of-domain result. */
export function evaluate(ast: ExprAst, env: EvalEnv): number | null {
  switch (ast.k) {
    case "num": return ok(ast.v);
    case "var": {
      const value = env.vars[ast.n];
      return typeof value === "number" ? ok(value) : null;
    }
    case "neg": {
      const a = evaluate(ast.a[0], env);
      return a === null ? null : ok(-a);
    }
    case "op": {
      const a = evaluate(ast.a[0], env);
      if (a === null) return null;
      const b = evaluate(ast.a[1], env);
      if (b === null) return null;
      switch (ast.o) {
        case "+": return ok(a + b);
        case "-": return ok(a - b);
        case "*": return ok(a * b);
        case "/": return b === 0 ? null : ok(a / b);
        case "^": return ok(power(a, b));
        default: return null;
      }
    }
    case "fn": {
      const args: number[] = [];
      for (const child of ast.a) {
        const value = evaluate(child, env);
        if (value === null) return null;
        args.push(value);
      }
      return ok(args.length === 1 ? unary(ast.f, args[0]) : args.length === 2 ? binary(ast.f, args[0], args[1]) : NaN);
    }
    case "coord": {
      const point = env.points[ast.p];
      return point ? ok(ast.c === "x" ? point[0] : point[1]) : null;
    }
    case "geo": {
      const pts: Point2[] = [];
      for (const id of ast.p) {
        const point = env.points[id];
        if (!point) return null;
        pts.push(point);
      }
      return ok(geo(ast.f, pts));
    }
    default: return null;
  }
}

/** Current param values from the scene defaults, overridden by `values`. */
export function paramValues(scene: Scene, values: Record<string, number> = {}): Record<string, number> {
  const out: Record<string, number> = {};
  for (const param of scene.params) out[param.name] = typeof values[param.name] === "number" ? values[param.name] : param.value;
  return out;
}

/** Point coordinates in definition order; later points may use earlier ones. */
export function resolvePoints(scene: Scene, params: Record<string, number>): Record<string, Point2 | null> {
  const points: Record<string, Point2 | null> = {};
  const env: EvalEnv = { vars: paramValues(scene, params), points };
  for (const object of scene.objects) {
    if (object.type !== "point") continue;
    const x = evaluate(object.x, env);
    const y = evaluate(object.y, env);
    points[object.id] = x === null || y === null ? null : [x, y];
  }
  return points;
}

// ---------------------------------------------------------------------------
// Sampling

export type Segment = [Point2, Point2];

/** Grid values at (nx+1)×(ny+1) nodes, row-major from yRange[0]. NaN for undefined. */
function sampleGrid(f: (x: number, y: number) => number | null, xRange: [number, number], yRange: [number, number], nx: number, ny: number) {
  const values = new Float64Array((nx + 1) * (ny + 1));
  const dx = (xRange[1] - xRange[0]) / nx;
  const dy = (yRange[1] - yRange[0]) / ny;
  for (let j = 0; j <= ny; j += 1) {
    for (let i = 0; i <= nx; i += 1) {
      const value = f(xRange[0] + i * dx, yRange[0] + j * dy);
      values[j * (nx + 1) + i] = value === null ? NaN : value;
    }
  }
  return { values, dx, dy };
}

/**
 * Zero contour of f by marching squares. Cells touching an undefined node
 * are skipped; the saddle case is resolved by the cell-centre average.
 */
export function marchingSquares(
  f: (x: number, y: number) => number | null, xRange: [number, number], yRange: [number, number], nx: number, ny: number,
): Segment[] {
  const { values, dx, dy } = sampleGrid(f, xRange, yRange, nx, ny);
  const at = (i: number, j: number) => values[j * (nx + 1) + i];
  const segments: Segment[] = [];
  const cross = (xa: number, ya: number, va: number, xb: number, yb: number, vb: number): Point2 => {
    const t = va === vb ? 0.5 : va / (va - vb);
    return [xa + (xb - xa) * t, ya + (yb - ya) * t];
  };
  for (let j = 0; j < ny; j += 1) {
    for (let i = 0; i < nx; i += 1) {
      const v0 = at(i, j), v1 = at(i + 1, j), v2 = at(i + 1, j + 1), v3 = at(i, j + 1);
      if (Number.isNaN(v0) || Number.isNaN(v1) || Number.isNaN(v2) || Number.isNaN(v3)) continue;
      const code = (v0 > 0 ? 1 : 0) | (v1 > 0 ? 2 : 0) | (v2 > 0 ? 4 : 0) | (v3 > 0 ? 8 : 0);
      if (code === 0 || code === 15) continue;
      const x0 = xRange[0] + i * dx, x1 = x0 + dx, y0 = yRange[0] + j * dy, y1 = y0 + dy;
      // Edges: bottom (0-1), right (1-2), top (3-2), left (0-3).
      const bottom = () => cross(x0, y0, v0, x1, y0, v1);
      const right = () => cross(x1, y0, v1, x1, y1, v2);
      const top = () => cross(x0, y1, v3, x1, y1, v2);
      const left = () => cross(x0, y0, v0, x0, y1, v3);
      const centre = (v0 + v1 + v2 + v3) / 4 > 0;
      switch (code) {
        case 1: case 14: segments.push([left(), bottom()]); break;
        case 2: case 13: segments.push([bottom(), right()]); break;
        case 3: case 12: segments.push([left(), right()]); break;
        case 4: case 11: segments.push([right(), top()]); break;
        case 6: case 9: segments.push([bottom(), top()]); break;
        case 7: case 8: segments.push([left(), top()]); break;
        case 5: // corners 0 and 2 positive
          if (centre) { segments.push([left(), top()]); segments.push([bottom(), right()]); }
          else { segments.push([left(), bottom()]); segments.push([right(), top()]); }
          break;
        case 10: // corners 1 and 3 positive
          if (centre) { segments.push([left(), bottom()]); segments.push([right(), top()]); }
          else { segments.push([left(), top()]); segments.push([bottom(), right()]); }
          break;
        default: break;
      }
    }
  }
  return segments;
}

export type Relation = "lt" | "le" | "gt" | "ge";

/** Cells (nx×ny, row-major from yRange[0]) whose centre satisfies `f relation 0`. */
export function sampleRegion(
  f: (x: number, y: number) => number | null, relation: Relation, xRange: [number, number], yRange: [number, number], nx: number, ny: number,
): Uint8Array {
  const cells = new Uint8Array(nx * ny);
  const dx = (xRange[1] - xRange[0]) / nx;
  const dy = (yRange[1] - yRange[0]) / ny;
  for (let j = 0; j < ny; j += 1) {
    for (let i = 0; i < nx; i += 1) {
      const value = f(xRange[0] + (i + 0.5) * dx, yRange[0] + (j + 0.5) * dy);
      if (value === null) continue;
      const inside = relation === "lt" ? value < 0 : relation === "le" ? value <= 0 : relation === "gt" ? value > 0 : value >= 0;
      if (inside) cells[j * nx + i] = 1;
    }
  }
  return cells;
}

/** Polyline pieces of y = f(x), broken at undefined values and asymptote jumps. */
export function sampleFunction(f: (x: number) => number | null, xRange: [number, number], yRange: [number, number], samples: number): Point2[][] {
  const span = yRange[1] - yRange[0];
  const low = yRange[0] - 4 * span;
  const high = yRange[1] + 4 * span;
  const pieces: Point2[][] = [];
  let current: Point2[] = [];
  let previous: number | null = null;
  for (let i = 0; i <= samples; i += 1) {
    const x = xRange[0] + ((xRange[1] - xRange[0]) * i) / samples;
    const y = f(x);
    const jump = y !== null && previous !== null && Math.abs(y - previous) > 2 * span && (y > high || y < low || previous > high || previous < low);
    if (y === null || jump) {
      if (current.length > 1) pieces.push(current);
      current = [];
    }
    if (y !== null) current.push([x, Math.max(low, Math.min(high, y))]);
    previous = y;
  }
  if (current.length > 1) pieces.push(current);
  return pieces;
}

/** Polyline pieces of a parametric curve, broken at undefined values and large jumps. */
export function sampleParametric(
  fx: (s: number) => number | null, fy: (s: number) => number | null, sRange: [number, number],
  xRange: [number, number], yRange: [number, number], samples: number,
): Point2[][] {
  const limit = Math.hypot(xRange[1] - xRange[0], yRange[1] - yRange[0]) / 2;
  const pieces: Point2[][] = [];
  let current: Point2[] = [];
  for (let i = 0; i <= samples; i += 1) {
    const s = sRange[0] + ((sRange[1] - sRange[0]) * i) / samples;
    const x = fx(s);
    const y = fy(s);
    const last = current[current.length - 1];
    if (x === null || y === null || (last && Math.hypot(x - last[0], y - last[1]) > limit)) {
      if (current.length > 1) pieces.push(current);
      current = [];
    }
    if (x !== null && y !== null) current.push([x, y]);
  }
  if (current.length > 1) pieces.push(current);
  return pieces;
}

/** Central-difference slope of f at x; null when f is undefined nearby. */
export function derivative(f: (x: number) => number | null, x: number, h: number): number | null {
  const a = f(x - h);
  const b = f(x + h);
  return a === null || b === null ? null : ok((b - a) / (2 * h));
}

/** View ranges; with equal aspect the shorter range grows so one unit is equal on both axes. */
export function fitView(xRange: [number, number], yRange: [number, number], plotW: number, plotH: number, equal: boolean) {
  if (!equal || plotW <= 0 || plotH <= 0) return { x: xRange, y: yRange };
  const xSpan = xRange[1] - xRange[0];
  const ySpan = yRange[1] - yRange[0];
  const unit = Math.max(xSpan / plotW, ySpan / plotH);
  const grow = (r: [number, number], span: number): [number, number] => {
    const mid = (r[0] + r[1]) / 2;
    return [mid - span / 2, mid + span / 2];
  };
  return { x: grow(xRange, unit * plotW), y: grow(yRange, unit * plotH) };
}

/** Fixed-digit number for readouts; null shows as 无定义. */
export function formatNumber(value: number | null, digits = 3): string {
  if (value === null) return "无定义";
  const fixed = value.toFixed(digits);
  return /^-0(\.0*)?$/.test(fixed) ? fixed.slice(1) : fixed;
}
