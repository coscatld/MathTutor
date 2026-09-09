"use strict";

/** Bootstrap Next standalone inside Electron's background UtilityProcess.
 *
 * UtilityProcess receives its custom environment after Node has initialized
 * module search paths. Refreshing them here makes the packaged vendor_modules
 * directory available without launching the app executable a second time.
 */

const Module = require("node:module");
const path = require("node:path");

const server = process.argv[2];
if (!server) throw new Error("Missing packaged frontend server path.");

Module._initPaths();
process.chdir(process.env.MATHTUTOR_WEB_CWD || path.dirname(server));
require(server);
