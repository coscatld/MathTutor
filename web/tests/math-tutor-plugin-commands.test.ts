import test from "node:test";
import assert from "node:assert/strict";
import type {PluginCommand} from "../features/math-tutor/community/api";
import {availableCommands, isSlashCommand, slashQuery} from "../features/math-tutor/lib/plugin-commands";

test("slash candidates only activate for a leading command token and preserve raw arguments", () => {
  assert.equal(slashQuery("/"), ""); assert.equal(slashQuery("/re"), "re");
  for (const text of ["算一算 /report", "/report 近一周", "\n/report", " /report", "/学习"]) assert.equal(slashQuery(text), null);
  assert.equal(isSlashCommand("/report 近一周"), true);
  assert.equal(isSlashCommand("/unknown"), true, "unknown commands must still reach the server as chat, not as math attempts");
  for (const text of ["x/y=2", " /report", "/r", "/大写命令", "步骤/report"]) assert.equal(isSlashCommand(text), false);
});
test("slash candidates come only from enabled commands with an available runtime", () => {
  const make = (command: string, fields: Partial<PluginCommand> = {}): PluginCommand => ({command, plugin_id: command, name: command, description: "", enabled: true, runtime_available: true, kind: "teaching-plugin", ...fields});
  const list = [make("report"), make("review"), make("disabled", {enabled: false}), make("missing", {runtime_available: false}), make("Bad Alias")];
  assert.deepEqual(availableCommands(list, "re").map(item => item.command), ["report", "review"]);
  assert.deepEqual(availableCommands(list, "").map(item => item.command), ["report", "review"]);
  assert.equal(availableCommands(Array.from({length: 20}, (_, i) => make(`command${i}`)), "").length, 12);
});
