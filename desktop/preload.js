"use strict";

const { contextBridge } = require("electron");

/**
 * Minimal desktop API surface for the renderer.
 *
 * The ONLY capability exposed is a marker that the app is running inside the
 * desktop shell. Everything else (API keys, documents, memory, offers) flows
 * through the existing HTTP/WS bridge — the renderer never talks to Electron
 * for business data. No key material, no filesystem, no dialogs: a file pick
 * is triggered by the renderer via the Python bridge, which asks the shell's
 * loopback endpoint on the user's explicit click.
 */
contextBridge.exposeInMainWorld("desktopAPI", {
  isDesktop: true,
  platform: process.platform,
});
