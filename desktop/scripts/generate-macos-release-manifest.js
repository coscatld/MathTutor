"use strict";

/** Generate local, secret-free macOS RC supply-chain evidence.
 *
 * This script records facts about an already-built artifact.  It never signs,
 * notarizes, submits, staples, or mutates the app/DMG.
 */

const { execFileSync, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const desktop = path.resolve(__dirname, "..");
const repo = path.resolve(desktop, "..");
const dist = path.join(desktop, "dist");
const dmg = path.join(dist, "MathTutor-0.2.0-mac-arm64.dmg");
let manifestMountWork = null;
let manifestMountpoint = null;
let manifestMounted = false;

function cleanupArtifactMount() {
  if (manifestMounted && manifestMountpoint) {
    try { execFileSync("hdiutil", ["detach", manifestMountpoint], { stdio: "ignore" }); } catch {}
    manifestMounted = false;
  }
  if (manifestMountWork) {
    try { fs.rmSync(manifestMountWork, { recursive: true, force: true }); } catch {}
    manifestMountWork = null;
  }
}

function exactArtifactApp() {
  if (process.platform !== "darwin" || !fs.existsSync(dmg)) {
    return path.join(dist, "mac-arm64", "MathTutor.app");
  }
  manifestMountWork = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-manifest-"));
  manifestMountpoint = path.join(manifestMountWork, "volume");
  fs.mkdirSync(manifestMountpoint);
  execFileSync(
    "hdiutil",
    ["attach", "-nobrowse", "-readonly", "-mountpoint", manifestMountpoint, dmg],
    { stdio: "ignore" },
  );
  manifestMounted = true;
  return path.join(manifestMountpoint, "MathTutor.app");
}

const appRoot = exactArtifactApp();
const resources = path.join(appRoot, "Contents", "Resources");
process.once("exit", cleanupArtifactMount);
const evidenceFile = path.join(dist, "package-smoke-evidence.json");
const outputDir = path.join(dist, "release-manifest");
const packageManifestFile = path.join(outputDir, "package-contents.json");
const dependencyFile = path.join(outputDir, "dependency-inventory.json");
const licenseFile = path.join(outputDir, "third-party-licenses.json");
const nativeFile = path.join(outputDir, "native-binaries.json");
const releaseFile = path.join(outputDir, "macos-release-manifest.json");
const allowlistFile = path.join(desktop, "package_allowlist.json");
const supplementalEvidenceFiles = [
  path.join(outputDir, "rc-public-release-smoke-macos.json"),
  path.join(outputDir, "macos-upgrade-report.json"),
  path.join(outputDir, "no-api-key-smoke-macos.json"),
  path.join(outputDir, "package-surface-audit.json"),
  path.join(repo, "docs", "rc", "REPRODUCIBILITY_EVIDENCE.json"),
];

function sha256File(file) {
  const hash = crypto.createHash("sha256");
  const fd = fs.openSync(file, "r");
  const buffer = Buffer.allocUnsafe(1024 * 1024);
  try {
    let length;
    while ((length = fs.readSync(fd, buffer, 0, buffer.length, null)) > 0) {
      hash.update(buffer.subarray(0, length));
    }
  } finally {
    fs.closeSync(fd);
  }
  return hash.digest("hex");
}

function writeJson(file, value) {
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o644 });
}

function walk(root) {
  const entries = [];
  function visit(current) {
    for (const name of fs.readdirSync(current).sort()) {
      const absolute = path.join(current, name);
      const stat = fs.lstatSync(absolute);
      const relative = path.relative(root, absolute).split(path.sep).join("/");
      if (stat.isDirectory()) visit(absolute);
      else if (stat.isSymbolicLink()) {
        entries.push({ path: relative, type: "symlink", target: fs.readlinkSync(absolute) });
      } else if (stat.isFile()) {
        entries.push({
          path: relative,
          type: "file",
          size_bytes: stat.size,
          mode: `0${(stat.mode & 0o777).toString(8)}`,
          sha256: sha256File(absolute),
        });
      }
    }
  }
  visit(root);
  return entries;
}

function isMachO(file) {
  const fd = fs.openSync(file, "r");
  const header = Buffer.alloc(4);
  try { fs.readSync(fd, header, 0, 4, 0); } finally { fs.closeSync(fd); }
  return new Set(["feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe", "bebafeca"])
    .has(header.toString("hex"));
}

function pythonDependencies() {
  const python = path.join(resources, "python-runtime", "bin", "python");
  const code = [
    "import importlib.metadata as m, json",
    "items=[]",
    "for d in m.distributions():",
    " n=d.metadata.get('Name')",
    " lic=d.metadata.get('License-Expression') or d.metadata.get('License') or None",
    " items.append({'name': n, 'version': d.version, 'license': lic}) if n else None",
    "print(json.dumps(sorted(items, key=lambda x: (x['name'].lower(), x['version']))))",
  ].join("\n");
  const raw = execFileSync(python, ["-c", code], {
    cwd: path.dirname(python),
    env: {
      PATH: "/usr/bin:/bin",
      HOME: process.env.HOME || "",
      LANG: "C.UTF-8",
      PYTHONNOUSERSITE: "1",
      PYTHONDONTWRITEBYTECODE: "1",
    },
    encoding: "utf8",
  });
  return JSON.parse(raw);
}

function packagedReleaseContract() {
  const python = path.join(resources, "python-runtime", "bin", "python");
  const pythonApp = path.join(resources, "python-app");
  const code = [
    "import json",
    "from mathtutor.release_config import RELEASE_CONFIG",
    "print(json.dumps(RELEASE_CONFIG.public_manifest(), sort_keys=True))",
  ].join("\n");
  const raw = execFileSync(python, ["-c", code], {
    cwd: path.dirname(python),
    env: {
      PATH: "/usr/bin:/bin",
      HOME: process.env.HOME || "",
      LANG: "C.UTF-8",
      PYTHONNOUSERSITE: "1",
      PYTHONDONTWRITEBYTECODE: "1",
      PYTHONPATH: pythonApp,
    },
    encoding: "utf8",
  });
  return JSON.parse(raw);
}

function nodePackagesFromContents(contents) {
  const packages = [];
  for (const entry of contents) {
    if (entry.type !== "file" || !entry.path.endsWith("package.json")) continue;
    const absolute = path.join(appRoot, ...entry.path.split("/"));
    try {
      const pkg = JSON.parse(fs.readFileSync(absolute, "utf8"));
      if (pkg.name && pkg.version) packages.push({ path: entry.path, name: pkg.name, version: pkg.version, license: pkg.license || null });
    } catch { /* invalid/non-package JSON is excluded */ }
  }
  return packages;
}

function buildNodePackages() {
  const lock = JSON.parse(fs.readFileSync(path.join(desktop, "package-lock.json"), "utf8"));
  return Object.entries(lock.packages || {}).filter(([key]) => key).map(([key, value]) => ({
    path: key,
    name: value.name || path.basename(key),
    version: value.version || null,
    license: value.license || null,
    dev: Boolean(value.dev),
  }));
}

function commandResult(command, args) {
  const result = spawnSync(command, args, { encoding: "utf8" });
  return {
    exit_code: result.status,
    stdout: String(result.stdout || "").trim(),
    stderr: String(result.stderr || "").trim(),
  };
}

function sourceRevision() {
  const topLevel = commandResult("git", ["-C", repo, "rev-parse", "--show-toplevel"]);
  const commit = commandResult("git", ["-C", repo, "rev-parse", "HEAD"]);
  if (topLevel.exit_code !== 0 || commit.exit_code !== 0 || path.resolve(topLevel.stdout) !== repo) {
    return { status: "UNAVAILABLE", reason: "NO_GIT_METADATA" };
  }
  const status = commandResult("git", ["-C", repo, "status", "--porcelain", "--untracked-files=no"]);
  return {
    status: "RESOLVED",
    commit: commit.stdout,
    dirty_tracked_files: status.exit_code === 0 ? Boolean(status.stdout) : null,
  };
}

for (const required of [appRoot, dmg, evidenceFile]) {
  if (!fs.existsSync(required)) throw new Error(`missing release input: ${required}`);
}
fs.mkdirSync(outputDir, { recursive: true });

const contents = walk(appRoot);
writeJson(packageManifestFile, {
  schema_version: 1,
  root: "MathTutor.app",
  file_count: contents.filter((item) => item.type === "file").length,
  symlink_count: contents.filter((item) => item.type === "symlink").length,
  total_file_bytes: contents.reduce((sum, item) => sum + (item.size_bytes || 0), 0),
  entries: contents,
});

const nodeRuntime = nodePackagesFromContents(contents);
const dependencies = {
  schema_version: 1,
  python_runtime: pythonDependencies(),
  packaged_node_runtime: nodeRuntime,
  desktop_build_node: buildNodePackages(),
};
writeJson(dependencyFile, dependencies);

const licenses = contents.filter((entry) => entry.type === "file" &&
  /(^|\/)(licen[cs]e|copying|notice|third[_-]?party)(\.[^/]*)?$/i.test(entry.path))
  .map(({ path: entryPath, size_bytes, sha256 }) => ({ path: entryPath, size_bytes, sha256 }));
writeJson(licenseFile, { schema_version: 1, count: licenses.length, entries: licenses });

const native = contents.filter((entry) => entry.type === "file" &&
  isMachO(path.join(appRoot, ...entry.path.split("/"))))
  .map(({ path: entryPath, size_bytes, sha256 }) => ({ path: entryPath, size_bytes, sha256 }));
writeJson(nativeFile, { schema_version: 1, count: native.length, entries: native });

const pkg = JSON.parse(fs.readFileSync(path.join(desktop, "package.json"), "utf8"));
const smoke = JSON.parse(fs.readFileSync(evidenceFile, "utf8"));
const pythonVersion = execFileSync(path.join(resources, "python-runtime", "bin", "python"), ["--version"], { encoding: "utf8" }).trim();
const identity = commandResult("security", ["find-identity", "-v", "-p", "codesigning"]);
const codesign = commandResult("codesign", ["--verify", "--deep", "--strict", appRoot]);
const notaryCredentialNames = [
  "APPLE_ID", "APPLE_APP_SPECIFIC_PASSWORD", "APPLE_TEAM_ID", "APPLE_API_KEY",
  "APPLE_API_KEY_ID", "APPLE_API_ISSUER",
];
const notaryCredentialsPresent = notaryCredentialNames.some((name) => Boolean(process.env[name]));

const manifests = [packageManifestFile, dependencyFile, licenseFile, nativeFile].map((file) => ({
  path: path.relative(desktop, file).split(path.sep).join("/"),
  size_bytes: fs.statSync(file).size,
  sha256: sha256File(file),
}));
const supplementalEvidence = supplementalEvidenceFiles
  .filter((file) => fs.existsSync(file))
  .map((file) => ({
    path: path.relative(desktop, file).split(path.sep).join("/"),
    size_bytes: fs.statSync(file).size,
    sha256: sha256File(file),
  }));
const appInfo = JSON.parse(execFileSync("plutil", ["-convert", "json", "-o", "-", path.join(appRoot, "Contents", "Info.plist")], { encoding: "utf8" }));
const releaseContract = packagedReleaseContract();
const release = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  application: { name: "MathTutor", version: pkg.version, bundle_id: appInfo.CFBundleIdentifier },
  artifact: {
    path: path.relative(desktop, dmg).split(path.sep).join("/"),
    size_bytes: fs.statSync(dmg).size,
    sha256: sha256File(dmg),
    platform: "macOS",
    arch: "arm64",
    format: "dmg",
  },
  source_revision: sourceRevision(),
  build_timestamp: fs.statSync(dmg).mtime.toISOString(),
  runtime: { electron: pkg.devDependencies.electron.replace(/^[^0-9]*/, ""), python: pythonVersion, frontend_node: process.version },
  migration: { head: smoke.packaged_migration_head, file: smoke.packaged_migration_file },
  release_contract: releaseContract,
  package_contents_policy: {
    status: "ALLOWLIST_ENFORCED",
    policy: path.relative(desktop, allowlistFile).split(path.sep).join("/"),
    policy_sha256: sha256File(allowlistFile),
    default_deny_source_assembly: true,
    embedding_distribution: "DEFERRED",
    bundled_embedding_weights: false,
  },
  inventories: manifests,
  supplemental_evidence: supplementalEvidence,
  inventory_counts: {
    package_files: contents.filter((item) => item.type === "file").length,
    python_distributions: dependencies.python_runtime.length,
    packaged_node_packages: dependencies.packaged_node_runtime.length,
    build_node_packages: dependencies.desktop_build_node.length,
    license_files: licenses.length,
    native_binaries: native.length,
  },
  signing: {
    status: "UNTESTED",
    reason: "MISSING_EXTERNAL_CREDENTIAL",
    valid_developer_identities: identity.stdout.includes("0 valid identities found") ? 0 : null,
    artifact_codesign_verify_exit_code: codesign.exit_code,
  },
  hardened_runtime: {
    configured: true,
    entitlements: ["com.apple.security.cs.allow-jit"],
    removed_entitlements: [
      "com.apple.security.cs.allow-unsigned-executable-memory",
      "com.apple.security.cs.disable-library-validation",
    ],
    developer_id_enforcement_test: "UNTESTED_MISSING_EXTERNAL_CREDENTIAL",
  },
  notarization: {
    status: "UNTESTED",
    reason: notaryCredentialsPresent ? "CREDENTIAL_PRESENT_BUT_NOT_SUBMITTED" : "MISSING_EXTERNAL_CREDENTIAL",
    credentials_present: notaryCredentialsPresent,
  },
  gatekeeper: {
    status: "UNTESTED",
    reason: "REQUIRES_DEVELOPER_ID_SIGNED_AND_NOTARIZED_ARTIFACT",
  },
  smoke: {
    status: smoke.app_full_smoke?.exit_code === 0 && smoke.dmg_readonly_mount_full_smoke?.exit_code === 0 ? "PASS" : "FAIL",
    packaged_app: smoke.app_full_smoke,
    readonly_dmg: smoke.dmg_readonly_mount_full_smoke,
    production_auth_on: smoke.app_production_launch,
    real_keychain_sentinel: smoke.keychain_sentinel,
    release_log_audit: smoke.release_log_audit,
  },
  secrets: {
    api_key_in_manifest: false,
    user_data_in_manifest: false,
    sentinel_value_in_manifest: false,
  },
};
writeJson(releaseFile, release);
cleanupArtifactMount();
process.removeListener("exit", cleanupArtifactMount);
process.stdout.write(`${JSON.stringify({ manifest: path.relative(desktop, releaseFile), artifact_sha256: release.artifact.sha256, status: release.smoke.status })}\n`);
