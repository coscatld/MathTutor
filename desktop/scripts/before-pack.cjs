"use strict";
const path = require("node:path");
const { resolvePackagingPrerequisites } = require("./packaging-prerequisites.cjs");
const { verifyRuntime } = require("./verify-distribution-runtime.cjs");

module.exports = async function beforePack(context) {
  const platform = context.electronPlatformName;
  const arch = typeof context.arch === "string" ? context.arch : require("builder-util").Arch[context.arch];
  if (platform !== process.platform || arch !== process.arch) throw new Error("Packaging requires a matching target-OS/architecture runner and runtime");
  const runtime = resolvePackagingPrerequisites({ platform });
  await verifyRuntime({ runtime, platform, arch });
  const resource = context.packager.config.extraResources.find(item => item.to === "python-runtime");
  if (!resource) throw new Error("Missing python-runtime resource contract");
  resource.from = path.resolve(runtime);
};
