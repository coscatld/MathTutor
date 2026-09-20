"""Run the repository's supported cross-platform verification commands."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = PROJECT_ROOT) -> None:
    print(f"[check] {cwd.name}: {' '.join(command)}", flush=True)
    # Verification must not depend on a writable global telemetry config.
    # Scope this to child processes; do not modify the user's preferences.
    env = dict(os.environ, NEXT_TELEMETRY_DISABLED="1")
    subprocess.run(command, cwd=cwd, check=True, env=env)


def main() -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm is required to run frontend and desktop checks")
    run([sys.executable, "-m", "pytest", "tests", "desktop/tests"])
    run([npm, "test"], cwd=PROJECT_ROOT / "web")
    run([npm, "run", "build"], cwd=PROJECT_ROOT / "web")
    run([npm, "run", "test:contracts"], cwd=PROJECT_ROOT / "desktop")
    print("[check] cross-platform source verification: PASS", flush=True)
    if os.environ.get("MATHTUTOR_PYTHON_RUNTIME", "").strip():
        run([npm, "run", "test:distribution"], cwd=PROJECT_ROOT / "desktop")
    else:
        reason = "Distribution: SKIPPED / NOT APPLICABLE — target packaging runtime not provisioned"
        print(f"[check] {reason}", flush=True)
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(summary, "a", encoding="utf-8") as output:
                output.write(f"\n{reason}\n")


if __name__ == "__main__":
    main()
