const { spawn } = require("node:child_process");

function browserDevEnvironment(env) {
  for (const key of ["NODE_ENV", "MATHTUTOR_ENVIRONMENT"]) {
    if (env[key] && env[key] !== "development") {
      throw new Error(`${key}=${env[key]}: 浏览器开发入口仅支持 development。生产部署请使用 npm run start。`);
    }
  }
  return { ...env, NODE_ENV: "development", MATHTUTOR_ENVIRONMENT: "development", MATHTUTOR_BROWSER_DEV: "1" };
}

module.exports = { browserDevEnvironment };
if (require.main === module) {
  const child = spawn(process.execPath, [require.resolve("next/dist/bin/next"), "dev", "--hostname", "127.0.0.1", ...process.argv.slice(2)], {
    stdio: "inherit", env: browserDevEnvironment(process.env),
  });
  for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.kill(signal));
  child.on("error", error => { console.error(error.message); process.exitCode = 1; });
  child.on("exit", code => { process.exitCode = code ?? 1; });
}
