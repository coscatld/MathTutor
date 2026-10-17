"use strict";

const path = require("node:path");
const { verifyApplication } = require("./verify-macos-signature.cjs");

module.exports = async function afterSign(context) {
  if (context.electronPlatformName !== "darwin") return;
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  const result = verifyApplication(app, {
    requireDeveloperId: process.env.MATHTUTOR_PUBLIC_RELEASE === "1",
  });
  process.stdout.write(`  • complete application signature verified  nativeResources=${result.native_resources_verified} identity=${result.identity}\n`);
};
