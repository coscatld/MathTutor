// Offline rendering probe using production normalizeMath and the same Markdown
// plugins/options as MarkdownRenderer. No browser, network or model calls.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "web/package.json"));
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const load = async name => (await import(pathToFileURL(require.resolve(name)).href)).default;
const [Markdown, gfm, math, katex] = await Promise.all([
  "react-markdown", "remark-gfm", "remark-math", "rehype-katex",
].map(load));
const { normalizeMath } = require(path.join(root, "web/dist/node-tests/components/common/math-normalization.js"));
const out = path.join(root, "artifacts/offline-math-042");
const rows = JSON.parse(readFileSync(path.join(out, "continuation-replays.json"), "utf8"));
const directory = path.join(out, "rendered-replays");
mkdirSync(directory, { recursive: true });
const checks = [];
for (const row of rows) {
  const content = renderToStaticMarkup(React.createElement(Markdown, {
    skipHtml: true, remarkPlugins: [gfm, math],
    rehypePlugins: [[katex, { strict: false, trust: false, throwOnError: false }]],
  }, normalizeMath(row.replay_final)));
  if (!content.includes("续写接缝待核对")) throw Error("Boundary notice missing after rendering");
  if (row.case_id === "degenerate:c0" && !content.includes("一正一负")) throw Error("Generated error hidden after rendering");
  const filename = row.case_id.replace(":", "-") + ".html";
  writeFileSync(path.join(directory, filename), "<!doctype html><meta charset='utf-8'>" + content);
  checks.push({ case_id: row.case_id, boundary_notice_visible: true,
    mathematical_error_preserved: row.case_id === "degenerate:c0" ? true : null,
    rendered_file: "rendered-replays/" + filename, rendered_chars: content.length });
}
writeFileSync(path.join(out, "render-check.json"), JSON.stringify({
  version: "0.4.2", method: "production normalization + matching Markdown/KaTeX pipeline; static DOM check, not browser screenshot", checks,
}, null, 2));
console.log(`${checks.length} saved-answer rendering checks passed`);
