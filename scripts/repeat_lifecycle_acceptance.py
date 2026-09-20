"""Fixed repeat schedule; retain every outcome and before/after source digest."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "lifecycle-repair" / os.environ.get("MATHTUTOR_REPEAT_ID", "schedule-1")


def digest():
    names = subprocess.check_output(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    hashes = {}
    for name in sorted(set(names)):
        path = ROOT / name
        if name and not name.startswith(("artifacts/", "docs/")) and path.is_file():
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(), hashes


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    targeted = ["tests/test_windows_runtime_ownership.py", "tests/test_transaction_cancellation.py",
                "tests/test_desktop_bridge.py::test_document_pick_cancelled_and_unsupported",
                "tests/test_phase5_e2e_offer_flow.py", "tests/test_phase6_main_integration.py"]
    schedule = [dict(id=f"targeted-{i:02}", args=targeted) for i in range(1, 21)]
    schedule += [dict(id=f"full-{i}", args=["tests/"]) for i in range(1, 4)]
    initial, files = digest()
    (OUT / "schedule.json").write_text(json.dumps(dict(schedule=schedule, source_digest=initial,
        files=files, policy="Run every declared repetition once; retain failures; no universal safety claim"), indent=2), encoding="utf-8")
    env = dict(os.environ, MATHTUTOR_LIFECYCLE_TRACE="1", PYTHONUTF8="1")
    for run in schedule:
        before, _ = digest()
        start = time.time()
        command = [sys.executable, "-m", "pytest", *run["args"], "-q", "-p", "no:randomly",
                   "--tb=long", f"--log-file={OUT / (run['id'] + '-trace.log')}"]
        with (OUT / (run["id"] + ".log")).open("w", encoding="utf-8") as log:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        after, _ = digest()
        row = dict(id=run["id"], exit_code=result.returncode, seconds=round(time.time()-start, 2),
                   source_digest_before=before, source_digest_after=after, unchanged=before == after == initial)
        with (OUT / "results.jsonl").open("a", encoding="utf-8") as file:
            file.write(json.dumps(row) + "\n")
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    main()
