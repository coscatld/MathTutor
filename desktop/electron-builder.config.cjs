"use strict";

const fs = require("node:fs");
const path = require("node:path");

const projectDir = __dirname;
const repoDir = path.resolve(projectDir, "..");
const packageAllowlist = JSON.parse(
  fs.readFileSync(path.join(projectDir, "package_allowlist.json"), "utf8"),
);

function exclude(pattern) {
  return pattern.startsWith("!") ? pattern : `!${pattern}`;
}

const pythonSourceFilter = [
  ...packageAllowlist.python_source.include,
  ...packageAllowlist.python_source.exclude.map(exclude),
];

const runtimeFeatureExclusions = packageAllowlist.python_runtime.forbidden_feature_packages.flatMap(
  (pattern) => [
    `!**/site-packages/${pattern}`,
    `!**/site-packages/${pattern}/**`,
  ],
);

function pythonRuntime() {
  const explicit = process.env.MATHTUTOR_PYTHON_RUNTIME;
  if (explicit) return path.resolve(explicit);
  const candidates = [
    path.join(repoDir, ".venv"),
    process.env.CONDA_PREFIX,
  ].filter(Boolean);
  const runtime = candidates.find((candidate) =>
    fs.existsSync(path.join(candidate, process.platform === "win32" ? "python.exe" : "bin/python")),
  );
  if (!runtime) {
    throw new Error(
      "Python runtime not found. Set MATHTUTOR_PYTHON_RUNTIME to a relocatable target-OS environment.",
    );
  }
  return runtime;
}

const nextStandalone = path.join(repoDir, "web", ".next-mathtutor", "standalone");
if (!fs.existsSync(path.join(nextStandalone, "server.js"))) {
  throw new Error("Missing web/.next-mathtutor/standalone/server.js; build the production web app first.");
}
const nextStatic = path.join(repoDir, "web", ".next-mathtutor", "static");
if (!fs.existsSync(nextStatic)) {
  throw new Error("Missing web/.next-mathtutor/static; build the production web app first.");
}

module.exports = {
  appId: "com.mathtutor.product",
  productName: "MathTutor",
  directories: { output: "dist", buildResources: "build" },
  artifactName: "${productName}-${version}-${os}-${arch}.${ext}",
  afterPack: "scripts/after-pack-macos.cjs",
  asar: true,
  files: ["main.js", "preload.js", "package.json"],
  extraResources: [
    {
      from: nextStandalone,
      to: "web",
      // Next standalone can retain a build-time rimraf symlink whose target
      // is outside the copied tree.  A broken symlink makes strict codesign
      // verification fail and is not used by the production server.
      filter: [
        "**/*",
        "!**/.next-mathtutor/node_modules/rimraf-*",
        ...packageAllowlist.web.exclude_generated_routes.map(exclude),
      ],
    },
    // Next's standalone output deliberately omits browser assets. They must
    // be copied beside the standalone server at its configured distDir or the
    // HTML loads while every client JS/CSS request returns 404.
    { from: nextStatic, to: "web/.next-mathtutor/static" },
    // electron-builder intentionally filters a top-level directory named
    // node_modules from generic resources. Copy it under a neutral runtime
    // name and expose it through NODE_PATH in main.js.
    { from: path.join(nextStandalone, "node_modules"), to: "web/vendor_modules" },
    {
      from: path.join(repoDir, "src", "mathtutor"),
      to: "python-app/mathtutor",
      filter: pythonSourceFilter,
    },
    {
      from: pythonRuntime(),
      to: "python-runtime",
      filter: [
        "**/*",
        "!**/__pycache__",
        "!**/__pycache__/**",
        "!**/*.pyc",
        "!**/*.pyo",
        "!**/site-packages/__editable__.mathtutor-*.pth",
        "!**/site-packages/__editable___mathtutor_*_finder.py",
        "!**/site-packages/mathtutor",
        "!**/site-packages/mathtutor/**",
        "!**/site-packages/mathtutor-*.dist-info",
        "!**/site-packages/mathtutor-*.dist-info/**",
        "!**/site-packages/deeptutor",
        "!**/site-packages/deeptutor/**",
        "!**/site-packages/deeptutor-*.dist-info",
        "!**/site-packages/deeptutor-*.dist-info/**",
        ...runtimeFeatureExclusions,
      ],
    },
    { from: path.join(repoDir, "LICENSE"), to: "licenses/LICENSE" },
    {
      from: path.join(repoDir, "THIRD_PARTY_NOTICES.md"),
      to: "licenses/THIRD_PARTY_NOTICES.md",
    },
  ],
  mac: {
    target: [{ target: "dmg", arch: ["arm64"] }],
    category: "public.app-category.education",
    hardenedRuntime: true,
    gatekeeperAssess: false,
    entitlements: "build/entitlements.mac.plist",
    entitlementsInherit: "build/entitlements.mac.plist",
  },
  dmg: { sign: false },
  win: { target: [{ target: "nsis", arch: ["x64"] }] },
  nsis: {
    oneClick: false,
    allowToChangeInstallationDirectory: true,
    perMachine: false,
  },
  linux: {
    target: [{ target: "AppImage", arch: ["x64"] }],
    category: "Education",
  },
};
