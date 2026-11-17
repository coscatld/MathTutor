const Module = require("node:module");
const path = require("node:path");

const distRoot = path.join(process.cwd(), "dist", "node-tests");
const originalResolveFilename = Module._resolveFilename;

Module._resolveFilename = function (request, parent, isMain, options) {
  if (typeof request === "string" && request.startsWith("@/")) {
    return originalResolveFilename.call(
      this,
      path.join(distRoot, request.slice(2)),
      parent,
      isMain,
      options,
    );
  }

  return originalResolveFilename.call(this, request, parent, isMain, options);
};

// Node has no layout engine; the production build and browser smoke verify CSS.
Module._extensions[".css"] = function(module) { module.exports = {}; };
