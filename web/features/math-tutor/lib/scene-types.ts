/**
 * Scene v2 wire types (see docs/SCENE_SPEC.md). The server compiles every
 * expression to this AST; the client only evaluates and draws it.
 */

export type ExprAst =
  | { k: "num"; v: number }
  | { k: "var"; n: string }
  | { k: "op"; o: "+" | "-" | "*" | "/" | "^"; a: [ExprAst, ExprAst] }
  | { k: "neg"; a: [ExprAst] }
  | { k: "fn"; f: string; a: ExprAst[] }
  | { k: "coord"; p: string; c: "x" | "y" }
  | { k: "geo"; f: "dist" | "slope" | "angle" | "area" | "mid_x" | "mid_y"; p: string[] };

export interface SceneParam {
  name: string;
  min: number;
  max: number;
  step: number;
  value: number;
  animate: boolean;
  label: string;
}

interface Base { id: string; label?: string; hidden?: boolean }

export type SceneObject =
  | (Base & { type: "function"; expr: ExprAst; domain?: [number, number] })
  | (Base & { type: "implicit"; expr: ExprAst })
  | (Base & { type: "parametric"; x: ExprAst; y: ExprAst; s_range: [number, number] })
  | (Base & { type: "region"; expr: ExprAst; relation: "lt" | "le" | "gt" | "ge" })
  | (Base & { type: "point"; x: ExprAst; y: ExprAst; trace?: boolean })
  | (Base & { type: "segment" | "line" | "ray" | "vector"; from: string; to: string })
  | (Base & { type: "polygon"; points: string[]; fill?: boolean })
  | (Base & { type: "circle"; center: string; radius: ExprAst })
  | (Base & { type: "tangent"; of: string; at: ExprAst })
  | (Base & { type: "text"; x: ExprAst; y: ExprAst; text: string });

export interface SceneReadout { label: string; expr: ExprAst; digits?: number }
export interface SceneMark { x: number; y: number; label: string }

export interface Scene {
  v: 2;
  title: string;
  source: "deterministic" | "model";
  x_range: [number, number];
  y_range: [number, number];
  equal_aspect: boolean;
  params: SceneParam[];
  objects: SceneObject[];
  readouts: SceneReadout[];
  marks: SceneMark[];
  note: string;
}

export const SCENE_LIMITS = {
  params: 4,
  objects: 40,
  readouts: 8,
  marks: 12,
  astDepth: 40,
  astNodes: 400,
  idLength: 8,
} as const;

export const UNARY_FUNCTIONS = ["sin", "cos", "tan", "asin", "acos", "atan", "sqrt", "abs", "ln", "log", "exp", "floor", "ceil", "sign"] as const;
export const BINARY_FUNCTIONS = ["min", "max", "atan2"] as const;
export const RESERVED_NAMES = ["x", "y", "s", "e"] as const;
