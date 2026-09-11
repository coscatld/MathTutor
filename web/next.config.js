/** @type {import('next').NextConfig} */

function normalizeBoolean(value) {
  return ["1", "true", "yes", "on"].includes(String(value || "").trim().toLowerCase())
    ? "true"
    : "false";
}

const NEXT_PUBLIC_API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ||
  `http://127.0.0.1:${process.env.MATHTUTOR_PORT || "8001"}`;
const NEXT_PUBLIC_AUTH_ENABLED = normalizeBoolean(
  process.env.NEXT_PUBLIC_AUTH_ENABLED ||
    process.env.MATHTUTOR_AUTH_ENABLED ||
    process.env.AUTH_ENABLED ||
    process.env.DEEPTUTOR_AUTH_ENABLED,
);

process.env.NEXT_PUBLIC_API_BASE = NEXT_PUBLIC_API_BASE;
process.env.NEXT_PUBLIC_AUTH_ENABLED = NEXT_PUBLIC_AUTH_ENABLED;

module.exports = {
  distDir: ".next-mathtutor",
  output: "standalone",
  env: {
    NEXT_PUBLIC_APP_VERSION: "0.3.0",
    NEXT_PUBLIC_API_BASE,
    NEXT_PUBLIC_AUTH_ENABLED,
  },
  experimental: {
    proxyClientMaxBodySize: 210 * 1024 * 1024,
  },
};
