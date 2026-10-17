"use strict";

const { execFileSync, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { verifyApplication } = require("./verify-macos-signature.cjs");

function verifyDmg(file, { requireDeveloperId = false } = {}) {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-dmg-signature-"));
  const volume = path.join(work, "volume");
  fs.mkdirSync(volume);
  let mounted = false;
  try {
    execFileSync("hdiutil", ["verify", file], { stdio: "pipe" });
    execFileSync("hdiutil", ["attach", "-nobrowse", "-readonly", "-mountpoint", volume, file], { stdio: "pipe" });
    mounted = true;
    const app = path.join(volume, "MathTutor.app");
    const signature = verifyApplication(app, { requireDeveloperId });
    const assessment = spawnSync("spctl", ["--assess", "--type", "execute", "--verbose=4", app], { encoding: "utf8" });
    if (assessment.error) throw assessment.error;
    const report = {
      schema_version: 1, generated_at: new Date().toISOString(), artifact: path.basename(file),
      sha256: crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex"),
      disk_image_integrity: "PASS", readonly_dmg: true, signature,
      gatekeeper: {
        status: assessment.status === 0 ? "PASS" : "FAIL",
        exit_code: assessment.status,
        diagnostic: (assessment.stderr || assessment.stdout).replaceAll(app, "MathTutor.app").trim(),
      },
    };
    fs.writeFileSync(`${file}.signature.json`, JSON.stringify(report, null, 2) + "\n");
    if (requireDeveloperId && assessment.status !== 0) throw new Error("Signed release failed Gatekeeper assessment");
    return report;
  } finally {
    try {
      if (mounted) execFileSync("hdiutil", ["detach", volume], { stdio: "pipe" });
    } finally {
      // Never recursively remove a volume if detach failed.
      if (!mounted || !fs.existsSync(path.join(volume, "MathTutor.app"))) fs.rmSync(work, { recursive: true, force: true });
    }
  }
}

module.exports = async function artifactBuildCompleted(event) {
  if (process.platform !== "darwin" || !event.file?.endsWith(".dmg")) return;
  const result = verifyDmg(event.file, { requireDeveloperId: process.env.MATHTUTOR_PUBLIC_RELEASE === "1" });
  process.stdout.write(`  • readonly DMG signature verified  integrity=PASS gatekeeper=${result.gatekeeper.status}\n`);
};
module.exports.verifyDmg = verifyDmg;
if (require.main === module) {
  try { process.stdout.write(JSON.stringify(verifyDmg(path.resolve(process.argv[2])), null, 2) + "\n"); }
  catch (error) { process.stderr.write(String(error.stderr || error.message) + "\n"); process.exitCode = 1; }
}
