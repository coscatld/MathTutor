import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import {renderToStaticMarkup} from "react-dom/server";
import {I18nProvider} from "../lib/i18n";
import {SettingsOperations} from "../features/math-tutor/desktop/lib/settings-operations";
import {SettingsForm, type SettingsFormData, type SettingsFormHandlers} from "../features/math-tutor/desktop/components/SettingsPanel";

const identity = {revision: 10, epoch: "runtime-a", preset_id: "custom"};
function operations() {let n = 0; return new SettingsOperations(() => `op-${++n}`);}
const receipt = (id: string, revision = 10) => ({operation_id: id, revision, current_revision: revision, epoch: "runtime-a", accepted: true});

test("settings actions are mutually exclusive before the next React render", () => {
  const owner = operations(), action = owner.begin("test", identity)!;
  for (const kind of ["save", "remove", "discover", "test"] as const) assert.equal(owner.begin(kind, identity), null);
  owner.finish(action); assert.ok(owner.begin("save", identity));
});

test("editing a provider, model, or key invalidates a captured probe without changing its identity", () => {
  const owner = operations(), action = owner.begin("test", identity)!;
  owner.edit(); assert.equal(owner.unchanged(action), false);
  assert.equal(action.preset_id, "custom"); assert.equal(action.revision, 10); assert.ok(Object.isFrozen(action));
});

test("only the exact operation, epoch, and configuration revision can accept a probe", () => {
  const owner = operations(), action = owner.begin("test", identity)!;
  assert.equal(owner.accepts(action, receipt(action.id)), true);
  for (const invalid of [{...receipt(action.id), operation_id: "other"}, {...receipt(action.id), epoch: "restarted"}, {...receipt(action.id), revision: 9}, {...receipt(action.id), current_revision: 11}, {...receipt(action.id), accepted: false}, {}]) assert.equal(owner.accepts(action, invalid), false);
});

test("a confirmed runtime-only save advances the baseline while keeping a newer draft dirty", () => {
  const owner = operations(), action = owner.begin("save", identity)!;
  owner.edit();
  assert.equal(owner.accepts(action, {...receipt(action.id, 11), persisted: false}, true), true);
  assert.equal(owner.unchanged(action), false);
  assert.equal(owner.accepts(action, receipt(action.id, 10), true), false);
});

test("an old finally cannot release another settings action", () => {
  const owner = operations(), first = owner.begin("test", identity)!;
  owner.finish(first); const second = owner.begin("save", identity)!;
  owner.finish(first); assert.equal(owner.active, second); assert.equal(owner.accepts(first, receipt(first.id)), false);
});

const handlers: SettingsFormHandlers = {onPresetChange() {}, onApiKeyChange() {}, onBaseUrlChange() {}, onModelChange() {}, onToggleAdvanced() {}, onDiscoverModels() {}, onSave() {}, onTest() {}, onAskRemove() {}, onCancelRemove() {}, onRemove() {}};
const data: SettingsFormData = {presets: [{preset_id: "custom", label: "custom", custom: true}], settings: {...identity, model: "model", base_url: "https://example.invalid", is_configured: true, onboarding_completed: true, key_masked: "tail"}, presetId: "custom", apiKey: "", baseUrl: "https://example.invalid", model: "model", keyMasked: "tail", advancedOpen: false, models: null, saving: false, testing: false, discovering: false, removing: false, confirmingRemoval: false, testResult: null, message: null};

test("save and test controls disable each other in either language", () => {
  for (const locale of ["zh-CN", "en"] as const) for (const flag of ["saving", "testing"] as const) {
    const html = renderToStaticMarkup(<I18nProvider initialLocale={locale}><SettingsForm data={{...data, [flag]: true}} handlers={handlers} /></I18nProvider>);
    const submit = html.match(/<button[^>]*type="submit"[^>]*>/)?.[0] || "";
    assert.match(submit, /disabled/);
    const testButton = html.match(/<button[^>]*disabled[^>]*>[\s\S]*?(测试连接|Test connection)<\/button>/)?.[0];
    assert.ok(testButton);
  }
});

test("runtime-only persistence feedback is explicit in Chinese and English", () => {
  const text = "本次运行已生效，尚未保存到磁盘。请重试保存；重启后可能恢复上次配置。";
  const zh = renderToStaticMarkup(<SettingsForm data={{...data, message: {kind: "error", text}}} handlers={handlers} />);
  const en = renderToStaticMarkup(<I18nProvider initialLocale="en"><SettingsForm data={{...data, message: {kind: "error", text}}} handlers={handlers} /></I18nProvider>);
  assert.match(zh, /尚未保存到磁盘/); assert.match(en, /not saved to disk/); assert.doesNotMatch(en, /本次运行/);
});
