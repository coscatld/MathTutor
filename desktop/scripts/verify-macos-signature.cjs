"use strict";

// Integrity verification is separate from Gatekeeper publisher trust. An
// ad-hoc signature may pass this check while spctl still rejects distribution.
const { execFileSync, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { filesUnder } = require("./after-pack-macos.cjs");

function verifyApplication(app, { requireDeveloperId = false } = {}) {
  execFileSync("codesign", ["--verify", "--deep", "--strict", app], { stdio: "pipe" });
  if (!fs.existsSync(path.join(app, "Contents", "_CodeSignature", "CodeResources"))) {
    throw new Error("Application resource seal is missing");
  }
  // codesign writes display data to stderr, unlike verification output.
  const display = spawnSync("codesign", ["--display", "--verbose=2", app], { encoding: "utf8" });
  if (display.status !== 0) throw new Error("Cannot inspect application signature");
  const info = display.stdout + display.stderr;
  const developerId = /^Authority=Developer ID Application:/m.test(info) && /^TeamIdentifier=(?!not set).+/m.test(info);
  if (requireDeveloperId && !developerId) throw new Error("Developer ID Application signature required");
  const native = filesUnder(path.join(app, "Contents", "Resources"));
  for (const file of native) {
    execFileSync("codesign", ["--verify", "--strict", file], { stdio: "pipe" });
  }
  return {
    status: "PASS", identity: developerId ? "DEVELOPER_ID" : "AD_HOC",
    native_resources_verified: native.length,
    // Only a separate Gatekeeper assessment can establish distribution trust.
  };
}

module.exports = { verifyApplication };
if (require.main === module) {
  try { process.stdout.write(JSON.stringify(verifyApplication(path.resolve(process.argv[2])), null, 2) + "\n"); }
  catch (error) { process.stderr.write(String(error.stderr || error.message) + "\n"); process.exitCode = 1; }
}
