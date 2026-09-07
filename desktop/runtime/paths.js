"use strict";

/** Cross-platform desktop path/runtime resolution. No product logic lives here. */

const path = require("node:path");

const BACKEND_ENTRY = "mathtutor.standalone:create_standalone_app";

function resolveResourceRoot({ isPackaged, resourcesPath, desktopDir }) {
  return isPackaged ? path.resolve(resourcesPath) : path.resolve(desktopDir, "..");
}

function resolveWebRoot({ explicitRoot, isPackaged, resourcesDir, desktopDir }) {
  return path.resolve(
    explicitRoot ||
      (isPackaged
        ? path.join(resourcesDir, "web")
        : path.join(desktopDir, "..", "web")),
  );
}

function bundledPythonPath({ platform, resourcesDir }) {
  return platform === "win32"
    ? path.join(resourcesDir, "python-runtime", "python.exe")
    : path.join(resourcesDir, "python-runtime", "bin", "python");
}

function developmentPythonCandidates({ platform, desktopDir }) {
  return [
    path.join(
      desktopDir,
      "..",
      ".venv",
      platform === "win32" ? path.join("Scripts", "python.exe") : path.join("bin", "python"),
    ),
  ];
}

function resolvePythonRuntime({
  explicitPython,
  isPackaged,
  platform,
  resourcesDir,
  desktopDir,
  exists,
}) {
  if (explicitPython) return path.resolve(explicitPython);
  if (isPackaged) {
    const bundled = bundledPythonPath({ platform, resourcesDir });
    return exists(bundled) ? bundled : null;
  }
  return developmentPythonCandidates({ platform, desktopDir }).find(exists) || null;
}

function resolveUserDataRoot({ explicitRoot, electronUserData, tempDir }) {
  return path.resolve(explicitRoot || electronUserData || path.join(tempDir, "MathTutor"));
}

function resolveDataLayoutPaths(root) {
  const resolvedRoot = path.resolve(root);
  return {
    root: resolvedRoot,
    database: path.join(resolvedRoot, "math_tutor.db"),
    uploads: path.join(resolvedRoot, "uploads"),
    backups: path.join(resolvedRoot, "backups"),
    config: path.join(resolvedRoot, "config"),
    logs: path.join(resolvedRoot, "logs"),
  };
}

module.exports = {
  BACKEND_ENTRY,
  bundledPythonPath,
  developmentPythonCandidates,
  resolveDataLayoutPaths,
  resolvePythonRuntime,
  resolveResourceRoot,
  resolveUserDataRoot,
  resolveWebRoot,
};
