"""Seal completed offline evidence; refuses incomplete validation logs."""
import hashlib
import json
import re
from build_offline_math_review import ROOT, OUT, FIXTURES, read, write, check_history


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    budget = check_history()
    expectations = {
        "backend_final": ("full-backend-final.log", "1389 passed, 11 skipped"),
        "targeted": ("targeted-final-source.log", "57 passed"),
        "web": ("web.log", "# pass 164"),
        "desktop": ("desktop.log", "# pass 44"),
    }
    validation = {}
    for name,(filename,result) in expectations.items():
        path=OUT/filename
        assert result in path.read_text(encoding="utf-8",errors="replace"),filename
        validation[name]=dict(log=filename,result=result,sha256=digest(path))
    paths=list((ROOT/"src").rglob("*.py"))
    paths += [ROOT/name for name in ["pyproject.toml","desktop/package.json","desktop/package-lock.json",
        "web/package.json","web/package-lock.json","web/next.config.js",
        "web/components/common/MarkdownRenderer.tsx","web/components/common/math-normalization.ts",
        "scripts/offline_math_conditions.py","scripts/offline_answer_annotations.py",
        "scripts/build_offline_math_review.py","scripts/offline_network_guard.py","scripts/render_offline_replays.mjs",
        "scripts/finalize_offline_evidence.py","tests/test_offline_math_conditions.py","tests/test_continuation_integrity.py",
        "tests/test_turn_completion.py","tests/test_live_delivery_replay.py","tests/test_release_config.py"]]
    paths += [p for p in FIXTURES.rglob("*") if p.is_file()]
    files={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(paths)}
    aggregate=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    parent=read(ROOT/"artifacts/delivery-regression-20260920/source-manifest.json")
    changed=[p for p,h in files.items() if p.startswith("src/") and p in parent["files"] and parent["files"][p]!=h]
    write(OUT/"source-manifest.json",dict(version="0.4.2",files=files,aggregate_sha256=aggregate,
        parent_version="0.4.1",parent_aggregate_sha256=parent["aggregate_sha256"],changed_production_files=changed,
        caveat="Includes preexisting working-tree state; only changed_production_files identifies this round's production delta"))
    write(OUT/"validation.json",dict(version="0.4.2",source_aggregate_sha256=aggregate,tests=validation,
        rendering=read(OUT/"render-check.json"),
        interrupted=dict(log="full-backend.log",status="INTERRUPTED_NOT_PASS",
            reason="Added unclosed-formula boundary regression; final source tested again in full-backend-final.log"),
        real_provider_calls=0,budget=budget,budget_byte_unchanged=True,
        history_files_verified=len(read(OUT/"history-lock.json")),
        live_quality="NOT_REEVALUATED",prompt_change_live_validation="NOT_RUN",human_review="PENDING",
        package="NOT_REBUILT",old_installer_evidence_reused=False))
    manifest={p.relative_to(OUT).as_posix():digest(p) for p in sorted(OUT.rglob("*"))
        if p.is_file() and p.name!="evidence-manifest.json"}
    for filename in manifest:
        body=(OUT/filename).read_text(encoding="utf-8",errors="replace")
        assert not re.search(r"sk-[A-Za-z0-9]{20,}",body),f"Credential-like data in {filename}"
    write(OUT/"evidence-manifest.json",manifest)
    print(f"0.4.2 sealed: {len(manifest)} artifacts; source {aggregate}; 0 live calls; history/budget unchanged")


if __name__=="__main__":
    main()
