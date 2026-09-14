"""Unit tests for config validation: hard rejects, capability degradation, isolation."""

import copy
import json
from pathlib import Path

import pytest

from spatial_agent.config.validation import validate_config

TEMPLATE = Path(__file__).resolve().parents[2] / "docs" / "templates" / "runtime.example.json"


def base_config() -> dict:
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    raw.pop("example_only", None)
    raw["profile"] = "mock"
    return raw


def set_section(cfg: dict, section: str, **values) -> dict:
    cfg = copy.deepcopy(cfg)
    cfg[section] = {**cfg.get(section, {}), **values}
    return cfg


# ------------------------------------------------------------------ rejects

def test_rejects_unknown_root_field():
    cfg = base_config() | {"mystery": True}
    report = validate_config(cfg)
    assert not report.valid and any("mystery" in e for e in report.errors)


def test_rejects_unknown_profile():
    report = validate_config(set_section(base_config(), "profile") if False else {**base_config(), "profile": "live"})
    assert not report.valid


def test_rejects_speed_over_first_version_cap():
    report = validate_config(set_section(base_config(), "motion", max_linear_speed_mps=0.5))
    assert not report.valid and any("0.1" in e for e in report.errors)


def test_rejects_non_finite_speed():
    cfg = json.loads(json.dumps(set_section(base_config(), "motion", max_linear_speed_mps=1e999)))
    report = validate_config(cfg)
    assert not report.valid


def test_rejects_incoherent_lease():
    report = validate_config(set_section(base_config(), "motion", lease_period_ms=1000, lease_timeout_ms=500))
    assert not report.valid


def test_rejects_resume_motion_after_restart():
    report = validate_config(set_section(base_config(), "tasks", resume_motion_after_restart=True))
    assert not report.valid


def test_rejects_memory_without_map_scoping():
    report = validate_config(set_section(base_config(), "memory", require_map_id=False))
    assert not report.valid


def test_rejects_silent_model_fallback():
    report = validate_config(set_section(base_config(), "planner", allow_silent_model_fallback=True))
    assert not report.valid


def test_rejects_hardware_motion_without_measured_facts():
    cfg = {**base_config(), "profile": "hardware"}
    cfg["motion"] = {**cfg["motion"], "enabled": True}
    report = validate_config(cfg)
    assert not report.valid
    joined = " ".join(report.errors)
    for missing in ("session_file", "footprint_m", "wheelbase_m", "min_turning_radius_m", "map_id"):
        assert missing in joined


def test_rejects_replay_with_motion_enabled():
    cfg = {**base_config(), "profile": "replay"}
    cfg["motion"] = {**cfg["motion"], "enabled": True}
    report = validate_config(cfg)
    assert not report.valid and any("replay" in e for e in report.errors)


def test_mock_profile_rejects_non_loopback_gateway():
    report = validate_config(set_section(base_config(), "robot", gateway_url="http://192.168.0.100:8765"))
    assert not report.valid and any("loopback" in e for e in report.errors)


def test_valid_mock_template_config_passes():
    report = validate_config(base_config())
    assert report.valid, report.errors
    assert report.config.profile.value == "mock"


# ------------------------------------------------------------- degradation

def test_perception_without_calibration_degrades():
    report = validate_config(set_section(base_config(), "perception", enabled=True, calibration_id=None))
    assert report.valid
    caps = {c.name: c for c in report.capabilities}
    assert caps["perception"].state == "degraded"
    assert "calibration_id" in caps["perception"].reason


def test_planner_without_model_degrades():
    report = validate_config(set_section(base_config(), "planner", enabled=True, model_id=None))
    assert report.valid
    caps = {c.name: c for c in report.capabilities}
    assert caps["planner"].state == "degraded"


def test_planner_without_api_key_env_degrades():
    report = validate_config(
        set_section(base_config(), "planner", enabled=True, model_id="deepseek-chat"),
        environment={"DEEPSEEK_API_KEY": ""},
    )
    assert report.valid
    caps = {c.name: c for c in report.capabilities}
    assert caps["planner"].state == "degraded"
    assert "DEEPSEEK_API_KEY" in caps["planner"].reason


def test_template_example_only_is_not_usable_for_run():
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    report = validate_config(raw)
    assert report.valid  # structurally fine
    assert report.as_dict()["usable_for_run"] is False  # but example_only


def test_no_fake_values_substituted():
    report = validate_config(base_config())
    assert report.config.map.map_id is None
    assert report.config.motion.wheelbase_m is None
    assert report.config.robot.robot_id is None


def test_hardware_motion_with_all_measured_facts_is_valid():
    cfg = {**base_config(), "profile": "hardware"}
    cfg["robot"] = {**cfg["robot"], "robot_id": "wheeltec-001", "gateway_url": "http://127.0.0.1:8765"}
    cfg["motion"] = {
        **cfg["motion"], "enabled": True, "session_file": "configs/local/session.json",
        "footprint_m": [0.5, 0.4], "wheelbase_m": 0.3, "min_turning_radius_m": 0.6,
    }
    cfg["map"] = {**cfg["map"], "map_id": "a" * 64, "manifest": "configs/maps/lab.json"}
    report = validate_config(cfg)
    assert report.valid, report.errors
