"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const minimatchModule = require("minimatch");

const minimatch = minimatchModule.minimatch || minimatchModule;
const desktop = path.resolve(__dirname, "..");
const policy = JSON.parse(fs.readFileSync(path.join(desktop, "package_allowlist.json"), "utf8"));
const config = require(path.join(desktop, "electron-builder.config.cjs"));

function sourceSelected(relative) {
  const resource = config.extraResources.find((item) => item.to === "python-app/mathtutor");
  const positives = resource.filter.filter((item) => !item.startsWith("!"));
  const negatives = resource.filter.filter((item) => item.startsWith("!")).map((item) => item.slice(1));
  return positives.some((pattern) => minimatch(relative, pattern))
    && !negatives.some((pattern) => minimatch(relative, pattern));
}

function javascriptText(root) {
  let combined = "";
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    const full = path.join(root, entry.name);
    if (entry.isDirectory()) combined += javascriptText(full);
    else if (entry.isFile() && entry.name.endsWith(".js")) {
      combined += fs.readFileSync(full, "utf8");
    }
  }
  return combined;
}

test("package allowlist retains each production entrypoint and runtime asset", () => {
  const required = [
    "api/product_app.py",
    "infrastructure/verifier_worker.py",
    "release_probe.py",
    "infrastructure/migrations/env.py",
    "infrastructure/migrations/script.py.mako",
    "infrastructure/migrations/versions/006_evidence_identity.py",
    "application/practice_release.py",
  ];
  for (const relative of required) {
    assert.equal(sourceSelected(relative), true, `required source excluded: ${relative}`);
  }
});

test("known generic execution and research surfaces cannot enter python-app", () => {
  const forbiddenExamples = [
    "agents/chat/capability.py",
    "agents/research/capability.py",
    "agents/math_animator/capability.py",
    "book/agents/writer.py",
    "capabilities/subagent/capability.py",
    "services/mcp/client.py",
    "services/search/providers/tavily.py",
    "services/subagent/process.py",
    "tools/exec_tool.py",
    "tools/web_search.py",
    "runtime/orchestrator.py",
  ];
  for (const relative of forbiddenExamples) {
    assert.equal(sourceSelected(relative), false, `forbidden source selected: ${relative}`);
  }
});

test("feature-only third-party runtimes and generic generated routes are excluded", () => {
  const runtime = config.extraResources.find((item) => item.to === "python-runtime");
  for (const featurePackage of policy.python_runtime.forbidden_feature_packages) {
    assert.ok(
      runtime.filter.includes(`!**/site-packages/${featurePackage}`),
      `runtime deny missing: ${featurePackage}`,
    );
  }
  const web = config.extraResources.find((item) => item.to === "web");
  for (const route of policy.web.exclude_generated_routes) {
    assert.ok(web.filter.includes(route.startsWith("!") ? route : `!${route}`));
  }
});

test("project license and third-party notices are explicit package resources", () => {
  const targets = new Set(config.extraResources.map((item) => item.to));
  assert.ok(targets.has("licenses/LICENSE"));
  assert.ok(targets.has("licenses/THIRD_PARTY_NOTICES.md"));
});

test("final artifact has no forbidden source paths", {
  skip: !process.env.MATHTUTOR_PACKAGE_APP,
}, () => {
  const resources = path.join(process.env.MATHTUTOR_PACKAGE_APP, "Contents", "Resources");
  for (const forbidden of policy.forbidden_artifact_paths) {
    assert.equal(fs.existsSync(path.join(resources, forbidden)), false, forbidden);
  }
  for (const required of [
    "python-app/mathtutor/api/product_app.py",
    "python-app/mathtutor/infrastructure/verifier_worker.py",
    "python-app/mathtutor/infrastructure/migrations/versions/006_evidence_identity.py",
    "licenses/LICENSE",
    "licenses/THIRD_PARTY_NOTICES.md",
  ]) {
    assert.equal(fs.existsSync(path.join(resources, required)), true, required);
  }
});

test("final artifact frontend uses the standalone v2 auth contract", {
  skip: !process.env.MATHTUTOR_PACKAGE_APP,
}, () => {
  const webBuild = path.join(
    process.env.MATHTUTOR_PACKAGE_APP,
    "Contents",
    "Resources",
    "web",
    ".next-mathtutor",
  );
  const bundled = javascriptText(webBuild);
  assert.match(bundled, /\/api\/v2\/auth\/status/);
  assert.match(bundled, /\/api\/v2\/auth\/register/);
  assert.match(bundled, /\/api\/v2\/auth\/login/);
  assert.doesNotMatch(bundled, /\/api\/v1\/auth\//);
});
