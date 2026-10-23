"""Package a bounded Harness-style tool API subset using the existing code ABI.

This adapts source modules, not Cordis packages. Author code runs only after
normal local-code consent in the existing TypeScript subprocess.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from mathtutor.extensions.code_plugins import export_code_package, parse_code_upload


_WRAPPER = r'''
import * as plugin from __MODULE__;

function fail() { throw new Error("Unsupported Harness tool subset or invalid tool arguments/result"); }
function record(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }
function keys(v, allowed) { if (!record(v) || Object.keys(v).some(k => !allowed.includes(k))) fail(); }
function schema(s, depth = 0) {
  if (depth > 10) fail();
  keys(s, ["type", "description", "title", "enum", "properties", "required", "additionalProperties", "items"]);
  if (!["object", "array", "string", "number", "integer", "boolean", "null"].includes(s.type)) fail();
  if (s.enum !== undefined && (!Array.isArray(s.enum) || s.enum.length > 64 || s.enum.some(v => v !== null && !["string", "number", "boolean"].includes(typeof v)))) fail();
  if (s.type === "object") {
    if (s.properties !== undefined && !record(s.properties)) fail();
    if (s.additionalProperties !== undefined && typeof s.additionalProperties !== "boolean") fail();
    if (s.required !== undefined && (!Array.isArray(s.required) || s.required.some(k => typeof k !== "string" || !Object.hasOwn(s.properties || {}, k)))) fail();
    for (const child of Object.values(s.properties || {})) schema(child, depth + 1);
  } else if (s.properties !== undefined || s.required !== undefined || s.additionalProperties !== undefined) fail();
  if (s.type === "array") { if (s.items !== undefined) schema(s.items, depth + 1); }
  else if (s.items !== undefined) fail();
}
function validate(v, s, depth = 0) {
  if (depth > 10) fail();
  if (s.enum && !s.enum.some(x => Object.is(x, v))) fail();
  if (s.type === "null") { if (v !== null) fail(); }
  else if (s.type === "object") {
    if (!record(v)) fail();
    for (const k of s.required || []) if (!Object.hasOwn(v, k)) fail();
    for (const [k, value] of Object.entries(v)) {
      if (Object.hasOwn(s.properties || {}, k)) validate(value, s.properties[k], depth + 1);
      else if (s.additionalProperties === false) fail();
    }
  } else if (s.type === "array") {
    if (!Array.isArray(v)) fail();
    if (s.items) for (const value of v) validate(value, s.items, depth + 1);
  } else if (s.type === "integer") { if (!Number.isSafeInteger(v)) fail(); }
  else if (typeof v !== s.type || (s.type === "number" && !Number.isFinite(v))) fail();
}
function only(values) {
  return new Proxy(Object.freeze(values), { get(target, key) {
    if (!Object.hasOwn(target, key)) fail();
    return target[key];
  }});
}
export async function run(request) {
  if (typeof plugin.apply !== "function" || Object.keys(plugin).some(k => !["apply", "name", "inject"].includes(k))) fail();
  if (plugin.inject !== undefined && (!Array.isArray(plugin.inject) || plugin.inject.some(k => k !== "tools"))) fail();
  const tools = new Map();
  const ctx = only({ tools: only({ register(definition) {
    keys(definition, ["name", "description", "parameters", "output", "execute"]);
    if (typeof definition.name !== "string" || !/^[a-z][a-z0-9_-]{1,63}$/.test(definition.name) || tools.has(definition.name) || tools.size >= 8 || typeof definition.description !== "string" || typeof definition.execute !== "function") fail();
    schema(definition.parameters);
    if (definition.parameters.type !== "object") fail();
    keys(definition.output, ["schema", "render"]);
    schema(definition.output.schema);
    if (typeof definition.output.render !== "function") fail();
    tools.set(definition.name, definition);
    return () => { if (tools.get(definition.name) === definition) tools.delete(definition.name); };
  } }) });
  await plugin.apply(ctx, request.config);
  const tool = tools.get(__TOOL__);
  if (!tool) fail();
  const args = JSON.parse(request.text || "{}");
  schema(tool.parameters);
  validate(args, tool.parameters);
  const exec = only({ name: tool.name, arguments: args, signal: AbortSignal.timeout(4500) });
  const value = await tool.execute(args, exec);
  schema(tool.output.schema);
  validate(value, tool.output.schema);
  const content = tool.output.render(args, value);
  if (!Array.isArray(content) || content.some(c => !record(c) || Object.keys(c).some(k => !["type", "text"].includes(k)) || c.type !== "text" || typeof c.text !== "string")) fail();
  return { text: content.map(c => c.text).join("\n"), data: value, tool: tool.name, compatibility: "harness-tool-subset-v1" };
}
'''


def adapt(directory: Path, included: list[str], tool: str) -> bytes:
    """Wrap an explicitly selected apply/register tool without evaluating it."""
    from mathtutor.extensions.developer import build

    if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", tool):
        raise ValueError("Invalid tool name")
    package = parse_code_upload(build(directory, included), "plugin.zip")
    if package.runtime != "typescript":
        raise ValueError("Harness subset requires TypeScript")
    wrapper = "mathtutor-harness-entry.ts"
    if wrapper in package.files:
        raise ValueError("Adapter entrypoint already exists")
    source = _WRAPPER.replace("__TOOL__", json.dumps(tool)).replace("__MODULE__", json.dumps("./" + package.entrypoint))
    payload = package.model_dump()
    payload.update(entrypoint=wrapper, files={**package.files, wrapper: source}, file_hashes={})
    return export_code_package(payload)
