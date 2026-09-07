"""Run the repository's supported cross-platform verification commands."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = PROJECT_ROOT) -> None:
    print(f"[check] {cwd.name}: {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    npm = shutil.which("npm")
    if npm is None:
        raise SystemExit("npm is required to run frontend and desktop checks")
    run([sys.executable, "-m", "pytest", "tests", "desktop/tests"])
    run([npm, "test"], cwd=PROJECT_ROOT / "web")
    run([npm, "run", "build"], cwd=PROJECT_ROOT / "web")
    run([npm, "run", "test:distribution"], cwd=PROJECT_ROOT / "desktop")


if __name__ == "__main__":
    main()
