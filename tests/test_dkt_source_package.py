"""Bundled shadow-only DKT package: integrity, numeric parity, shadow policy, shipping."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from mathtutor.learning.knowledge_tracing import StudentStateService
from mathtutor.learning.knowledge_tracing.model_package import BUNDLED_PACKAGE, SourceModelPackage, load_bundled
from mathtutor.learning.knowledge_tracing.schema import metadata

ROOT = Path(__file__).resolve().parents[1]
FROZEN_SHA256 = "d30fb23c69ce995874ad6466d7a32ec41accca2f6afcebe2e62dd3603a3c03a4"


def _float64_reference(payload, events, queries):
    """Independent of the product loader: explicit float64 PyTorch LSTM cell."""
    w = {k: np.asarray(v, dtype=np.float64) for k, v in payload["state_dict"].items()}
    n = int(payload["config"]["hidden_size"])
    t = float(payload["calibration"]["temperature"])
    h, c, out = np.zeros(n), np.zeros(n), []
    for event, query in zip(events, queries):
        logit = w["head.weight"][0] @ np.concatenate([h, query]) + w["head.bias"][0]
        out.append(1 / (1 + np.exp(-logit / t)))
        x = np.tanh(w["event_projection.weight"] @ event + w["event_projection.bias"])
        z = w["lstm.weight_ih_l0"] @ x + w["lstm.bias_ih_l0"] + w["lstm.weight_hh_l0"] @ h + w["lstm.bias_hh_l0"]
        i, f, g, o = (1 / (1 + np.exp(-z[:n])), 1 / (1 + np.exp(-z[n:2 * n])), np.tanh(z[2 * n:3 * n]),
                      1 / (1 + np.exp(-z[3 * n:])))
        c = f * c + i * g
        h = o * np.tanh(c)
    return out


def _copy_package(tmp_path):
    target = tmp_path / "package"
    shutil.copytree(BUNDLED_PACKAGE, target)
    return target


def test_bundled_package_is_the_frozen_research_model_in_shadow_mode():
    package = load_bundled()
    raw = (BUNDLED_PACKAGE / "model.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == FROZEN_SHA256
    assert package.identity["model_sha256"] == FROZEN_SHA256
    assert package.mode == "shadow" and package.controls_teaching is False
    assert package.target_coverage == "unsupported_target"
    manifest = json.loads((BUNDLED_PACKAGE / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["policy"]["serving_mode"] == "shadow"
    assert manifest["policy"]["target_domain_validated"] is False


def test_product_loader_matches_an_independent_reference_on_random_sequences():
    package = load_bundled()
    payload = json.loads((BUNDLED_PACKAGE / "model.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(20260929)
    events = [rng.normal(size=package.event_size) for _ in range(40)]
    queries = [np.eye(package.item_size)[rng.integers(package.item_size)] for _ in range(40)]
    actual = package.run_sequence(events, queries)
    expected = _float64_reference(payload, events, queries)
    np.testing.assert_allclose(actual, expected, atol=1e-5)


def test_mathtutor_skills_are_never_covered_by_the_source_vocabulary():
    package = load_bundled()
    assert not package.covers(["linear_isolation"])
    assert not {"linear_isolation", "distributive_law"} & package.skill_vocabulary


@pytest.mark.parametrize("damage", ["bytes", "format", "shape", "nonfinite", "temperature", "self_check", "escape"])
def test_damaged_packages_are_rejected(tmp_path, damage):
    target = _copy_package(tmp_path)
    manifest_path, model_path = target / "manifest.json", target / "model.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload = json.loads(model_path.read_text(encoding="utf-8"))
    if damage == "bytes":
        model_path.write_bytes(model_path.read_bytes().replace(b"0", b"1", 1))
    else:
        if damage == "format":
            payload["format"] = "something_else"
        elif damage == "shape":
            payload["state_dict"]["head.bias"] = [0.0, 0.0]
        elif damage == "nonfinite":
            payload["state_dict"]["head.bias"] = [1e39]
        elif damage == "temperature":
            payload["calibration"]["temperature"] = 50.0
        elif damage == "self_check":
            manifest["self_check"]["expected_probabilities"][0] += 0.01
        elif damage == "escape":
            manifest["model"]["file"] = "../model.json"
        if damage not in {"self_check", "escape"}:
            raw = json.dumps(payload).encode("utf-8")
            model_path.write_bytes(raw)
            manifest["model"].update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises((ValueError, KeyError, OSError)):
        SourceModelPackage(target)


@pytest.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tracking.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


def _context(**overrides):
    return {"session_id": "session", "cycle_id": "cycle", "problem_id": "problem", "problem_revision": "revision",
            "item_family_id": "linear", "skill_ids": ["linear_isolation"], **overrides}


@pytest.mark.asyncio
async def test_service_uses_the_trained_checkpoint_for_mapped_skills(engine, tmp_path):
    service = StudentStateService(engine, tmp_path / "missing" / "model.npz", source_package=BUNDLED_PACKAGE)
    assert service.source_model_status == "shadow" and service.dkt_mode == "shadow"
    assert service.source_model.controls_teaching is False
    forecast = await service.prepare_prediction("alice", prediction_id="presentation:cycle",
                                                at_presentation=True, **_context())
    frozen = forecast["frozen_forecast"]
    assert frozen["probability_source"] == "assist2009_trained_dkt"
    assert frozen["coverage_status"] == "mapped_source_skills"
    assert isinstance(frozen["probability"], float) and 0 < frozen["probability"] < 1
    assert frozen["controls_teaching"] is True and frozen["learning_effect_verified"] is False
    assert frozen["source_skill_ids"] == ["311", "312"]
    assert frozen["shadow_model"]["model_sha256"] == FROZEN_SHA256
    assert frozen["shadow_model"]["controls_teaching"] is False
    assert forecast["policy_source"] == "evidence_tracker_v2" and forecast["shadow_probability"] is None
    unmapped = await service.prepare_prediction(
        "alice", prediction_id="presentation:other", at_presentation=True,
        **_context(cycle_id="other", skill_ids=["quadratic_discriminant"], item_family_id="quadratic"))
    assert unmapped["frozen_forecast"]["probability"] is None
    assert unmapped["frozen_forecast"]["controls_teaching"] is False
    event = await service.record_attempt("alice", **_context(), assessment_id="a1", attempt_id="a1",
                                         correctness="incorrect", prediction_id="presentation:cycle")
    assert event.evidence_kind == "independent"
    moved = await service.prepare_prediction(
        "alice", prediction_id="presentation:next", at_presentation=True,
        **_context(cycle_id="next", problem_id="next-problem"))
    assert abs(moved["frozen_forecast"]["probability"] - frozen["probability"]) > 1e-6
    assert moved["frozen_forecast"]["history_updates"] == 1
    summary = await service.summary("alice")
    assert summary["dkt_mode"] == "shadow" and summary["dkt_controls_teaching"] is True
    assert summary["dkt_teaching_scope"] == "mapped_assist2009_skills"
    assert summary["learning_effect_verified"] is False
    assert summary["dkt_source_model"]["package_id"] == BUNDLED_PACKAGE.name


@pytest.mark.asyncio
async def test_broken_bundled_package_falls_back_without_blocking_learning(engine, tmp_path):
    target = _copy_package(tmp_path)
    (target / "model.json").write_bytes(b"{}")
    service = StudentStateService(engine, source_package=target)
    assert service.source_model is None and service.dkt_mode == "not_trained"
    assert service.source_model_status == "unavailable_fallback"
    event = await service.record_attempt("alice", **_context(), assessment_id="a1", attempt_id="a1", correctness="correct")
    assert event.evidence_kind == "independent"
    assert (await service.summary("alice"))["dkt_source_model"]["status"] == "unavailable_fallback"


def test_product_wires_the_bundled_package():
    source = (ROOT / "src/mathtutor/api/product_state.py").read_text(encoding="utf-8")
    assert "source_package=BUNDLED_PACKAGE" in source


def test_model_assets_and_numpy_ship_with_the_desktop_package():
    allowlist = json.loads((ROOT / "desktop/package_allowlist.json").read_text(encoding="utf-8"))
    assert "numpy" in allowlist["python_runtime"]["required_import_roots"]
    assert "numpy" not in allowlist["python_runtime"]["forbidden_feature_packages"]
    assert "learning/knowledge_tracing/assets/*/*.json" in allowlist["python_source"]["include"]
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dependencies = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert '"numpy' in dependencies
