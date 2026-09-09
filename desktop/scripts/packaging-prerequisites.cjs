"use strict";

const fs = require("node:fs");
const path = require("node:path");

function inside(root, file) {
  const relative = path.relative(root, file);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== ".." && !path.isAbsolute(relative));
}

function resolvePythonRuntime({ env = process.env, platform = process.platform } = {}) {
  const explicit = env.MATHTUTOR_PYTHON_RUNTIME?.trim();
  if (!explicit) throw new Error("target packaging runtime not provisioned: set MATHTUTOR_PYTHON_RUNTIME to a relocatable target-OS runtime directory");
  const root = fs.realpathSync(path.resolve(explicit));
  if (!fs.statSync(root).isDirectory()) throw new Error("MATHTUTOR_PYTHON_RUNTIME must be a runtime directory, not a Python executable");
  for (const hosted of [env.RUNNER_TOOL_CACHE, env.pythonLocation]) {
    if (hosted && inside(fs.existsSync(hosted) ? fs.realpathSync(hosted) : path.resolve(hosted), root)) throw new Error("Hosted Python is not a provisioned distribution runtime");
  }
  if (fs.existsSync(path.join(root, "pyvenv.cfg"))) throw new Error("A venv is not a relocatable distribution runtime");
  const executable = path.join(root, platform === "win32" ? "python.exe" : "bin/python");
  if (!fs.existsSync(executable) || !fs.statSync(executable).isFile()) throw new Error(`Target Python executable missing: ${executable}`);
  const stdlib = platform === "win32"
    ? fs.readdirSync(root).some(name => /^python3\d+\.zip$/.test(name)) || fs.existsSync(path.join(root, "Lib", "encodings"))
    : fs.existsSync(path.join(root, "lib")) && fs.readdirSync(path.join(root, "lib")).some(name => /^python3\.\d+$/.test(name) && fs.existsSync(path.join(root, "lib", name, "encodings")));
  if (!stdlib) throw new Error("Target runtime standard library is missing");
  // Reject broken/external symlinks throughout the runtime, not just bin/python.
  function checkLinks(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name);
      if (entry.isSymbolicLink()) {
        if (path.isAbsolute(fs.readlinkSync(file)) || !inside(root, fs.realpathSync(file))) throw new Error(`Non-relocatable runtime symlink: ${file}`);
      } else if (entry.isDirectory()) checkLinks(file);
    }
  }
  checkLinks(root);
  return root;
}

function resolvePackagingPrerequisites({ repoDir = path.resolve(__dirname, "../.."), env = process.env, platform = process.platform } = {}) {
  // Resolve first: missing runtime is an explicit release failure, not a copy warning.
  const runtime = resolvePythonRuntime({ env, platform });
  for (const relative of ["standalone/server.js", "static", "standalone/node_modules"]) {
    const file = path.join(repoDir, "web", ".next-mathtutor", relative);
    if (!fs.existsSync(file)) throw new Error(`Packaging frontend prerequisite missing: ${file}; build the production web app first`);
  }
  return runtime;
}

module.exports = { resolvePythonRuntime, resolvePackagingPrerequisites, inside };
