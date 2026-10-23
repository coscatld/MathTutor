"""Require real native TypeScript execution before plugin tests in CI."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main() -> None:
    candidate = shutil.which("node")
    if candidate is None:
        raise SystemExit("Node is required for the native TypeScript plugin checks")
    executable = Path(candidate).resolve(strict=True)
    if any(char in str(executable) for char in "\r\n"):
        raise SystemExit("Node executable path cannot contain newlines")

    with tempfile.TemporaryDirectory(prefix="mathtutor-plugin-node-") as directory:
        source = Path(directory) / "probe.ts"
        source.write_text(
            'import process from "node:process";\n'
            'const value: number = 21;\n'
            'process.stdout.write(JSON.stringify({answer: value * 2, version: process.version}));\n',
            encoding="utf-8",
        )
        # Match the plugin runner's exclusion of injected Node options/modules.
        env = {key: value for key, value in os.environ.items() if key not in {"NODE_OPTIONS", "NODE_PATH"}}
        result = subprocess.run(
            [str(executable), "--experimental-strip-types", str(source)],
            cwd=directory, env=env, check=True, capture_output=True,
            text=True, encoding="utf-8", timeout=10,
        )
        payload = json.loads(result.stdout)
        if not isinstance(payload, dict) or payload.get("answer") != 42 or not isinstance(payload.get("version"), str):
            raise SystemExit("Node failed the native TypeScript execution probe")

    # Publish only after actual typed code executes successfully. Python avoids
    # shell-specific quoting of Windows paths and paths containing spaces.
    if github_env := os.environ.get("GITHUB_ENV"):
        with open(github_env, "a", encoding="utf-8", newline="\n") as output:
            output.write(f"MATHTUTOR_PLUGIN_NODE_EXECUTABLE={executable}\n")
    print(f"[check] native TypeScript: PASS ({payload['version']}, {executable})", flush=True)


if __name__ == "__main__":
    main()
