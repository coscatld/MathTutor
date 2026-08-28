"""Production-import resolution contract for the package source allowlist."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


REPO = Path(__file__).resolve().parents[2]
AUDIT = REPO / "desktop" / "scripts" / "audit-package-surface.py"


def test_allowlisted_staging_tree_resolves_all_product_imports() -> None:
    completed = subprocess.run(
        [sys.executable, str(AUDIT), "--repo", str(REPO), "--python", sys.executable],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["status"] == "PASS"
    assert result["migration_db_exists"] is True
    assert result["forbidden_selected"] == []
    assert result["artifact_measurement_status"] == "PENDING_FINAL_REPACKAGE"
    observed = result["observed_runtime_modules"]
    assert "mathtutor.api.product_app" in observed
    assert "mathtutor.infrastructure.verifier_worker" in observed
    assert "mathtutor.release_probe" in observed
    assert all(name == "mathtutor" or name.startswith("mathtutor.") for name in observed)


def test_allowlist_records_unmeasured_final_artifact_honestly() -> None:
    policy = json.loads(
        (REPO / "desktop" / "package_allowlist.json").read_text(encoding="utf-8")
    )
    assert policy["policy"].startswith("default-deny")
    assert policy["production_entrypoints"] == [
        "mathtutor.standalone:create_standalone_app",
        "mathtutor.api.product_app:create_math_tutor_app_from_runtime",
        "mathtutor.infrastructure.verifier_worker",
        "mathtutor.release_probe",
    ]
    assert "python-app/deeptutor" in policy["forbidden_artifact_paths"]
    assert "python-app/mathtutor/legacy" in policy["forbidden_artifact_paths"]
