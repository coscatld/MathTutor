"use strict";

const crypto = require("node:crypto");

function validBridgeHeader(value, secret) {
  return typeof value === "string" && Boolean(secret) &&
    Buffer.byteLength(value) === Buffer.byteLength(secret) &&
    crypto.timingSafeEqual(Buffer.from(value), Buffer.from(secret));
}

/** Keep a trailing prefix so credentials split across pipe chunks stay private. */
function secretRedactor(secret, output) {
  let pending = "";
  return {
    write(chunk) {
      pending += String(chunk);
      if (secret) pending = pending.split(secret).join("[redacted]");
      const count = Math.max(0, pending.length - Math.max(0, secret.length - 1));
      if (count) output(pending.slice(0, count));
      pending = pending.slice(count);
    },
    end() {
      if (pending) output(pending.split(secret).join("[redacted]"));
      pending = "";
    },
  };
}

function httpOrigin(value) {
  try {
    const parsed = new URL(value);
    if (parsed.protocol === "ws:") parsed.protocol = "http:";
    if (parsed.protocol === "wss:") parsed.protocol = "https:";
    return parsed.origin;
  } catch { return ""; }
}

function rendererHeaders(details, webContentsId, frontendOrigin, secret) {
  const headers = { ...details.requestHeaders };
  for (const name of Object.keys(headers)) {
    if (name.toLowerCase() === "x-mathtutor-bridge") delete headers[name];
  }
  const originHeader = Object.entries(headers).find(([name]) => name.toLowerCase() === "origin")?.[1];
  const trusted = details.webContentsId === webContentsId &&
    httpOrigin(details.frame?.url) === frontendOrigin &&
    httpOrigin(details.url) === frontendOrigin &&
    new URL(details.url).pathname.startsWith("/api/") &&
    (originHeader === undefined || originHeader === frontendOrigin);
  if (trusted) headers["X-MathTutor-Bridge"] = secret;
  return headers;
}

module.exports = { validBridgeHeader, rendererHeaders, secretRedactor };
