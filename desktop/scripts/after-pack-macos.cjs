"use strict";

/** Sign every Mach-O shipped outside Electron's normal nested bundles.
 *
 * electron-builder signs the Electron app/helpers after this hook.  The
 * bundled Python runtime and native Node extensions live under Resources and
 * must be signed first, deepest component first.  Unsigned local builds skip
 * deterministically.  Public release builds require an explicit CSC_NAME;
 * the identity name is public metadata, while its private key stays in the
 * macOS Keychain.
 */

const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const MACHO_MAGICS = new Set(["feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe", "bebafeca"]);

function isMachO(file) {
  const fd = fs.openSync(file, "r");
  const header = Buffer.alloc(4);
  try { fs.readSync(fd, header, 0, 4, 0); } finally { fs.closeSync(fd); }
  return MACHO_MAGICS.has(header.toString("hex"));
}

function filesUnder(root) {
  const result = [];
  function visit(current) {
    for (const name of fs.readdirSync(current)) {
      const file = path.join(current, name);
      const stat = fs.lstatSync(file);
      if (stat.isDirectory()) visit(file);
      else if (stat.isFile() && isMachO(file)) result.push(file);
    }
  }
  if (fs.existsSync(root)) visit(root);
  return result.sort((a, b) => b.split(path.sep).length - a.split(path.sep).length || a.localeCompare(b));
}

module.exports = async function afterPack(context) {
  if (context.electronPlatformName !== "darwin") return;
  const publicRelease = process.env.MATHTUTOR_PUBLIC_RELEASE === "1";
  const identity = process.env.CSC_NAME || "";
  if (!publicRelease) {
    process.stdout.write("  • native Resources signing skipped  reason=unsigned local build\n");
    return;
  }
  if (!identity) throw new Error("MATHTUTOR_PUBLIC_RELEASE=1 requires explicit CSC_NAME");
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  const resources = path.join(app, "Contents", "Resources");
  const files = filesUnder(resources);
  for (const file of files) {
    execFileSync("codesign", [
      "--force", "--sign", identity, "--options", "runtime", "--timestamp", file,
    ], { stdio: "pipe" });
    execFileSync("codesign", ["--verify", "--strict", file], { stdio: "pipe" });
  }
  process.stdout.write(`  • signed bundled native Resources  count=${files.length}\n`);
};
