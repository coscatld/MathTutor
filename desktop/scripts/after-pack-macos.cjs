"use strict";

/** Sign every Mach-O shipped outside Electron's normal nested bundles.
 *
 * electron-builder signs the Electron app/helpers after this hook.  The
 * bundled Python runtime and native Node extensions live under Resources and
 * must be signed first, deepest component first. Local builds use complete
 * ad-hoc signatures, never the incomplete linker signature from Electron.
 * Public signed release builds require an explicit CSC_NAME;
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
  const adHoc = process.env.MATHTUTOR_ADHOC_SIGN === "1";
  const identity = publicRelease ? process.env.CSC_NAME || "" : adHoc ? "-" : "";
  if (publicRelease && (!identity || identity === "-" || adHoc)) {
    throw new Error("MATHTUTOR_PUBLIC_RELEASE=1 requires explicit CSC_NAME with a Developer ID identity");
  }
  if (!identity) throw new Error("macOS packaging requires Developer ID or explicit MATHTUTOR_ADHOC_SIGN=1");
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  const resources = path.join(app, "Contents", "Resources");
  const files = filesUnder(resources);
  for (const file of files) {
    execFileSync("codesign", [
      "--force", "--sign", identity,
      ...(adHoc ? ["--timestamp=none"] : ["--options", "runtime", "--timestamp"]), file,
    ], { stdio: "pipe" });
    execFileSync("codesign", ["--verify", "--strict", file], { stdio: "pipe" });
  }
  process.stdout.write(`  • signed bundled native Resources  count=${files.length}\n`);
};

module.exports.filesUnder = filesUnder;
