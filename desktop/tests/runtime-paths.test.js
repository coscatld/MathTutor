"use strict";

const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const {
  bundledPythonPath,
  developmentPythonCandidates,
  resolveDataLayoutPaths,
  resolvePythonRuntime,
} = require("../runtime/paths");

test("Windows runtime paths use the packaged executable and Scripts layout", () => {
  const resources = path.resolve("fixture", "resources");
  assert.equal(
    bundledPythonPath({ platform: "win32", resourcesDir: resources }),
    path.join(resources, "python-runtime", "python.exe"),
  );
  const candidates = developmentPythonCandidates({
    platform: "win32",
    desktopDir: path.resolve("fixture", "desktop"),
  });
  assert.match(candidates[0], /[\\/]\.venv[\\/]Scripts[\\/]python\.exe$/);
});

test("macOS runtime paths use the packaged bin/python layout", () => {
  const resources = path.resolve("fixture", "resources");
  const expected = path.join(resources, "python-runtime", "bin", "python");
  assert.equal(bundledPythonPath({ platform: "darwin", resourcesDir: resources }), expected);
  assert.equal(resolvePythonRuntime({
    explicitPython: "",
    isPackaged: true,
    platform: "darwin",
    resourcesDir: resources,
    desktopDir: path.resolve("fixture", "desktop"),
    exists: (candidate) => candidate === expected,
  }), expected);
});

test("user data layout is rooted under one dynamically resolved directory", () => {
  const root = path.resolve("fixture", "user-data");
  const layout = resolveDataLayoutPaths(root);
  assert.equal(layout.root, root);
  for (const value of Object.values(layout)) {
    assert.ok(value === root || value.startsWith(`${root}${path.sep}`));
  }
});
