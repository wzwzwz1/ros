"""Unit tests for manifest validators (P0.7)."""

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from spatial_agent.manifests import (
    LEVEL_INVALID,
    LEVEL_TEMPLATE,
    LEVEL_VALID,
    validate_map_manifest,
    validate_models_lock,
    validate_session,
    validate_suite,
)

TEMPLATES = Path(__file__).resolve().parents[2] / "docs" / "templates"


def load(name: str) -> dict:
    return json.loads((TEMPLATES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- map
def test_map_template_is_template_level():
    level, _ = validate_map_manifest(load("map-manifest.example.json"))
    assert level == LEVEL_TEMPLATE


def _valid_map() -> dict:
    doc = load("map-manifest.example.json")
    doc.pop("example_only")
    doc.update(
        map_id="a" * 64,
        image_path="maps/lab.pgm", image_sha256="b" * 64,
        yaml_path="maps/lab.yaml", yaml_sha256="c" * 64,
        resolution_m_per_pixel=0.05, origin_xy_yaw=[0.0, 0.0, 0.0],
        coordinate_frame_version="v1", localization_mode="amcl",
        allowed_area_polygon_map_m=[[0, 0], [5, 0], [5, 5], [0, 5]],
    )
    return doc


def test_valid_map_manifest():
    level, problems = validate_map_manifest(_valid_map())
    assert level == LEVEL_VALID, problems


def test_map_rejects_placeholder_zero_hash():
    doc = _valid_map()
    doc["map_id"] = "0" * 64
    level, problems = validate_map_manifest(doc)
    assert level == LEVEL_INVALID
    assert any("map_id" in p for p in problems)


def test_map_rejects_bad_polygon():
    doc = _valid_map()
    doc["allowed_area_polygon_map_m"] = [[0, 0], [1, 1]]
    assert validate_map_manifest(doc)[0] == LEVEL_INVALID


# ------------------------------------------------------------------ session
def test_session_template_is_template_level():
    level, _ = validate_session(load("session.example.json"))
    assert level == LEVEL_TEMPLATE


def _valid_session() -> dict:
    doc = load("session.example.json")
    doc.pop("example_only")
    now = datetime.now(UTC)
    doc.update(
        session_id="sess-1", robot_id="wheeltec-001", map_id="a" * 64,
        config_sha256="d" * 64, operator="user", operator_confirmation_source="in-person confirmation",
        confirmed_at_utc=now.isoformat().replace("+00:00", "Z"),
        expires_at_utc=(now + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
    )
    return doc


def test_valid_session_for_arm():
    doc = _valid_session()
    doc.update(
        operator_present_confirmed=True, test_area_clear_confirmed=True,
        physical_stop_method="lift + power switch", physical_stop_reachability_confirmed=True,
        allowed_area_polygon_map_m=[[0, 0], [5, 0], [5, 5], [0, 5]],
        allowed_case_ids=["P1-NAV"], max_linear_speed_mps=0.1,
    )
    level, problems = validate_session(doc, for_arm=True)
    assert level == LEVEL_VALID, problems


def test_session_for_arm_requires_physical_facts():
    doc = _valid_session()  # all physical confirmations missing/false
    level, problems = validate_session(doc, for_arm=True)
    assert level == LEVEL_INVALID
    for fragment in ("operator_present_confirmed", "physical_stop_method", "test_area_clear_confirmed"):
        assert any(fragment in p for p in problems)


def test_session_expired_cannot_arm():
    doc = _valid_session()
    past = datetime.now(UTC) - timedelta(hours=2)
    doc["confirmed_at_utc"] = (past - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    doc["expires_at_utc"] = past.isoformat().replace("+00:00", "Z")
    doc.update(operator_present_confirmed=True, test_area_clear_confirmed=True,
               physical_stop_method="switch", physical_stop_reachability_confirmed=True,
               allowed_area_polygon_map_m=[[0, 0], [1, 0], [1, 1], [0, 1]], allowed_case_ids=["P1-NAV"])
    level, problems = validate_session(doc, for_arm=True)
    assert level == LEVEL_INVALID and any("expired" in p for p in problems)


def test_session_span_cannot_exceed_max_duration():
    doc = _valid_session()
    now = datetime.now(UTC)
    doc["confirmed_at_utc"] = now.isoformat().replace("+00:00", "Z")
    doc["expires_at_utc"] = (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
    level, problems = validate_session(doc)
    assert any("max_duration_minutes" in p for p in problems)


# -------------------------------------------------------------------- suite
def test_suite_template_is_template_level():
    level, _ = validate_suite(load("suite-manifest.example.json"))
    assert level == LEVEL_TEMPLATE


def test_suite_with_empty_trials_is_never_valid():
    doc = load("suite-manifest.example.json")
    doc.pop("example_only")
    doc.update(
        suite_id="s1", phase="P3", primary_mode="hardware", frozen_at_utc="2026-09-14T00:00:00Z",
        code_release="abc123", config_sha256="e" * 64, random_seed=42,
        case_ids=["P3-TASK"], thresholds={"minimum_trials": 10},
        trial_required_fields=["trial_id", "case_id", "expected_outcome"],
        trials=[],
    )
    level, problems = validate_suite(doc)
    assert level == LEVEL_INVALID
    assert any("empty trials" in p for p in problems)


def test_suite_missing_trial_fields_invalid():
    doc = load("suite-manifest.example.json")
    doc.pop("example_only")
    doc.update(
        suite_id="s2", phase="P3", primary_mode="hardware", frozen_at_utc="2026-09-14T00:00:00Z",
        code_release="abc123", config_sha256="e" * 64, random_seed=42,
        case_ids=["P3-TASK"], thresholds={"minimum_trials": 1},
        trial_required_fields=["trial_id", "case_id", "expected_outcome"],
        trials=[{"trial_id": "t1"}],
    )
    level, problems = validate_suite(doc)
    assert level == LEVEL_INVALID
    assert any("trial[0]" in p for p in problems)


# ------------------------------------------------------------- models lock
def test_models_lock_template_is_template_level():
    level, _ = validate_models_lock(load("models-lock.example.json"))
    assert level == LEVEL_TEMPLATE


def test_models_lock_zero_hash_placeholder_rejected():
    doc = load("models-lock.example.json")
    doc.pop("example_only")
    doc["models"] = [{
        "logical_name": "chair_detector", "model_id": "yolo11n", "downloaded": True, "verified": True,
        "files": [{"path": "models/yolo11n.onnx", "size_bytes": 10, "sha256": "0" * 64}],
    }]
    level, problems = validate_models_lock(doc)
    assert level == LEVEL_INVALID
    assert any("placeholder" in p for p in problems)


def test_models_lock_verified_requires_downloaded():
    doc = load("models-lock.example.json")
    doc.pop("example_only")
    doc["models"] = [{"logical_name": "x", "model_id": "y", "downloaded": False, "verified": True, "files": []}]
    level, problems = validate_models_lock(doc)
    assert any("verified=true requires downloaded" in p for p in problems)
