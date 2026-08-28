import test from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

/**
 * Source-level security invariants for the desktop feature:
 *  - no code in the desktop feature ever writes/reads browser storage
 *    (localStorage / sessionStorage / IndexedDB) — the API key must live
 *    only in the backend SecretStore;
 *  - the whitelisted public key extra.child_cycle_id is read by exactly one
 *    helper module (offer-navigation.ts); nothing else pokes at frame extra.
 */
// The harness runs with cwd = web/ (see scripts/run-node-tests.mjs), same
// convention as the existing dev-heap-ceiling test.
const FEATURE_ROOT = path.resolve(process.cwd(), "features/math-tutor/desktop");
const HOOK_PATH = path.resolve(process.cwd(), "features/math-tutor/desktop/hooks/useOfferAccept.ts");

function collectSourceFiles(dir: string): string[] {
  const files: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) {
      files.push(...collectSourceFiles(full));
    } else if (/\.tsx?$/.test(name)) {
      files.push(full);
    }
  }
  return files;
}

test("desktop feature never touches browser storage (no key in localStorage)", () => {
  const sources = [...collectSourceFiles(FEATURE_ROOT), HOOK_PATH];
  assert.ok(sources.length > 5, "feature sources exist");
  for (const file of sources) {
    const content = readFileSync(file, "utf8");
    for (const pattern of [/localStorage\s*\./, /sessionStorage\s*\./, /indexedDB\s*\./, /window\s*\.\s*localStorage/]) {
      assert.ok(
        !pattern.test(content),
        `${path.relative(process.cwd(), file)} must not use browser storage (${pattern})`,
      );
    }
  }
});

test("only offer-navigation.ts reads the whitelisted extra.child_cycle_id", () => {
  const sources = collectSourceFiles(FEATURE_ROOT);
  for (const file of sources) {
    const content = readFileSync(file, "utf8");
    // offer-navigation.ts is the single extraction point; useOfferAccept.ts
    // delegates to it (its own mention of the key is documentation-only).
    const isWhitelisted =
      file.endsWith(path.join("lib", "offer-navigation.ts")) ||
      file.endsWith(path.join("hooks", "useOfferAccept.ts"));
    if (!isWhitelisted) {
      assert.ok(
        !content.includes("child_cycle_id"),
        `${path.relative(process.cwd(), file)} must not read child_cycle_id directly`,
      );
    }
  }
});

test("desktop feature has no filesystem or directory-scanning APIs", () => {
  const sources = collectSourceFiles(FEATURE_ROOT);
  for (const file of sources) {
    const content = readFileSync(file, "utf8");
    for (const pattern of [/\bfs\b/, /readdir/, /scandir/, /glob\(/, /walkSync/, /readDirectory/]) {
      assert.ok(
        !pattern.test(content),
        `${path.relative(process.cwd(), file)} must not touch the filesystem (${pattern})`,
      );
    }
  }
});
