"""Validators for map manifests, field session files, suite manifests and models.lock.

A validator returns (level, problems): level is one of
``valid`` (usable for its purpose), ``template`` (example_only skeleton; fine as
documentation, never usable for a run) or ``invalid``.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

LEVEL_VALID = "valid"
LEVEL_TEMPLATE = "template"
LEVEL_INVALID = "invalid"


def _check(condition: bool, message: str, problems: list[str]) -> None:
    if not condition:
        problems.append(message)


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.match(value))


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def validate_map_manifest(doc: dict) -> tuple[str, list[str]]:
    problems: list[str] = []
    if doc.get("example_only"):
        return LEVEL_TEMPLATE, problems

    _check(_is_sha256(doc.get("map_id")), "map_id must be a sha256 content hash", problems)
    _check(isinstance(doc.get("image_path"), str), "image_path is required", problems)
    _check(_is_sha256(doc.get("image_sha256")), "image_sha256 must be a sha256 hash", problems)
    _check(isinstance(doc.get("yaml_path"), str), "yaml_path is required", problems)
    _check(_is_sha256(doc.get("yaml_sha256")), "yaml_sha256 must be a sha256 hash", problems)
    _check(isinstance(doc.get("frame_id"), str) and doc.get("frame_id"), "frame_id is required", problems)
    resolution = doc.get("resolution_m_per_pixel")
    _check(isinstance(resolution, (int, float)) and resolution > 0, "resolution_m_per_pixel must be > 0", problems)
    origin = doc.get("origin_xy_yaw")
    _check(
        isinstance(origin, list) and len(origin) == 3 and all(isinstance(v, (int, float)) for v in origin),
        "origin_xy_yaw must be [x, y, yaw]",
        problems,
    )
    _check(isinstance(doc.get("coordinate_frame_version"), str) and doc["coordinate_frame_version"],
           "coordinate_frame_version is required", problems)
    _check(doc.get("localization_mode") in ("amcl", "cartographer", "other"),
           "localization_mode must be amcl|cartographer|other", problems)
    polygon = doc.get("allowed_area_polygon_map_m")
    _check(
        isinstance(polygon, list) and len(polygon) >= 3 and all(
            isinstance(p, list) and len(p) == 2 and all(isinstance(v, (int, float)) for v in p) for p in polygon
        ),
        "allowed_area_polygon_map_m must be >=3 [x_m, y_m] points",
        problems,
    )
    if doc.get("initial_pose_method") != "measured_pose_with_covariance":
        problems.append("initial_pose_method must be measured_pose_with_covariance")
    for vp in doc.get("viewpoints", []) or []:
        for req in ("id", "map_id", "x_m", "y_m", "yaw_rad"):
            _check(req in vp, f"viewpoint missing {req}", problems)
    for goal in doc.get("acceptance_goals", []) or []:
        for req in ("id", "map_id", "x_m", "y_m", "yaw_rad"):
            _check(req in goal, f"acceptance_goal missing {req}", problems)
    return (LEVEL_VALID if not problems else LEVEL_INVALID), problems


def validate_session(doc: dict, *, now_utc: datetime | None = None, for_arm: bool = False) -> tuple[str, list[str]]:
    """Validate a field-session file. ``for_arm`` additionally requires all
    physical-confirmation facts (these can never be self-approved by an agent)."""
    problems: list[str] = []
    if doc.get("example_only"):
        return LEVEL_TEMPLATE, problems

    _check(doc.get("mode") == "hardware", "session mode must be hardware", problems)
    _check(isinstance(doc.get("session_id"), str) and doc["session_id"], "session_id is required", problems)
    _check(isinstance(doc.get("robot_id"), str) and doc["robot_id"], "robot_id is required", problems)
    _check(isinstance(doc.get("map_id"), str) and doc["map_id"], "map_id is required", problems)
    _check(_is_sha256(doc.get("config_sha256")), "config_sha256 must be a sha256 hash", problems)
    _check(isinstance(doc.get("operator"), str) and doc["operator"], "operator is required", problems)
    _check(isinstance(doc.get("operator_confirmation_source"), str) and doc["operator_confirmation_source"],
           "operator_confirmation_source is required", problems)

    confirmed = _parse_utc(doc.get("confirmed_at_utc"))
    expires = _parse_utc(doc.get("expires_at_utc"))
    now = now_utc or datetime.now(UTC)
    _check(confirmed is not None, "confirmed_at_utc must be an ISO-8601 UTC timestamp", problems)
    _check(expires is not None, "expires_at_utc must be an ISO-8601 UTC timestamp", problems)
    if confirmed and expires:
        _check(expires > confirmed, "expires_at_utc must be after confirmed_at_utc", problems)
        max_minutes = doc.get("max_duration_minutes")
        if isinstance(max_minutes, (int, float)) and max_minutes > 0:
            span_minutes = (expires - confirmed).total_seconds() / 60
            _check(span_minutes <= max_minutes, f"session span {span_minutes:.0f}min exceeds max_duration_minutes", problems)
        if for_arm:
            _check(now < expires, "session is expired", problems)
    if for_arm:
        _check(doc.get("operator_present_confirmed") is True, "operator_present_confirmed must be true (real on-site fact)", problems)
        _check(doc.get("test_area_clear_confirmed") is True, "test_area_clear_confirmed must be true (real on-site fact)", problems)
        _check(isinstance(doc.get("physical_stop_method"), str) and doc["physical_stop_method"],
               "physical_stop_method is required", problems)
        _check(doc.get("physical_stop_reachability_confirmed") is True,
               "physical_stop_reachability_confirmed must be true", problems)
        polygon = doc.get("allowed_area_polygon_map_m")
        _check(isinstance(polygon, list) and len(polygon) >= 3, "allowed_area_polygon_map_m needs >=3 points", problems)
        _check(isinstance(doc.get("allowed_case_ids"), list) and doc["allowed_case_ids"], "allowed_case_ids is required", problems)
        speed = doc.get("max_linear_speed_mps")
        _check(isinstance(speed, (int, float)) and 0 < speed <= 0.1, "max_linear_speed_mps must be in (0, 0.1]", problems)

    return (LEVEL_VALID if not problems else LEVEL_INVALID), problems


def validate_suite(doc: dict, *, phase_expected: str | None = None) -> tuple[str, list[str]]:
    problems: list[str] = []
    if doc.get("example_only"):
        return LEVEL_TEMPLATE, problems

    _check(isinstance(doc.get("suite_id"), str) and doc["suite_id"], "suite_id is required", problems)
    _check(isinstance(doc.get("phase"), str) and doc["phase"], "phase is required", problems)
    if phase_expected:
        _check(doc.get("phase") == phase_expected, f"phase must be {phase_expected}", problems)
    _check(doc.get("primary_mode") in ("mock", "replay", "hardware", "api-live"),
           "primary_mode must be mock|replay|hardware|api-live", problems)
    _check(_parse_utc(doc.get("frozen_at_utc")) is not None, "frozen_at_utc must be ISO-8601 UTC", problems)
    case_ids = doc.get("case_ids")
    _check(isinstance(case_ids, list) and case_ids, "case_ids must be a non-empty list", problems)
    _check(isinstance(doc.get("random_seed"), int), "random_seed must be an integer", problems)
    thresholds = doc.get("thresholds")
    _check(isinstance(thresholds, dict) and thresholds, "thresholds must be a non-empty object", problems)

    required_fields = doc.get("trial_required_fields") or []
    trials = doc.get("trials")
    if not isinstance(trials, list) or not trials:
        # An empty trials list can never be judged as passed (acceptance.md §1).
        problems.append("trials must be a non-empty list; empty trials are never a pass")
    else:
        for i, trial in enumerate(trials):
            for req in required_fields:
                _check(req in trial, f"trial[{i}] missing required field {req!r}", problems)
    _check(isinstance(doc.get("code_release"), str) and doc["code_release"], "code_release is required", problems)
    _check(_is_sha256(doc.get("config_sha256")), "config_sha256 must be a sha256 hash", problems)
    return (LEVEL_VALID if not problems else LEVEL_INVALID), problems


def validate_models_lock(doc: dict) -> tuple[str, list[str]]:
    problems: list[str] = []
    if doc.get("example_only"):
        return LEVEL_TEMPLATE, problems

    for i, model in enumerate(doc.get("models", []) or []):
        prefix = f"models[{i}]"
        _check(isinstance(model.get("logical_name"), str), f"{prefix}.logical_name is required", problems)
        _check(isinstance(model.get("model_id"), str), f"{prefix}.model_id is required", problems)
        downloaded = model.get("downloaded") is True
        verified = model.get("verified") is True
        files = model.get("files") or []
        if downloaded:
            _check(bool(files), f"{prefix}: downloaded=true requires file entries with real hashes", problems)
            for j, f in enumerate(files):
                fp = f"{prefix}.files[{j}]"
                _check(isinstance(f.get("path"), str) and f["path"], f"{fp}.path is required", problems)
                _check(isinstance(f.get("size_bytes"), int) and f["size_bytes"] > 0, f"{fp}.size_bytes must be > 0", problems)
                sha = f.get("sha256")
                _check(_is_sha256(sha), f"{fp}.sha256 must be a real sha256 hash", problems)
                if isinstance(sha, str) and set(sha) == {"0"}:
                    problems.append(f"{fp}.sha256 must not be a placeholder of zeros")
        if verified and not downloaded:
            problems.append(f"{prefix}: verified=true requires downloaded=true")

    for i, provider in enumerate(doc.get("providers", []) or []):
        prefix = f"providers[{i}]"
        _check(isinstance(provider.get("name"), str), f"{prefix}.name is required", problems)
        if provider.get("tools_verified") and not provider.get("model_id"):
            problems.append(f"{prefix}: tools_verified=true requires model_id recorded from a real capability probe")

    return (LEVEL_VALID if not problems else LEVEL_INVALID), problems


VALIDATORS = {
    "map": validate_map_manifest,
    "session": validate_session,
    "suite": validate_suite,
    "models-lock": validate_models_lock,
}


def validate_document(kind: str, doc: dict, **kwargs) -> tuple[str, list[str]]:
    if kind == "session":
        return validate_session(doc, **kwargs)
    if kind == "suite":
        return validate_suite(doc, **kwargs)
    if kind not in VALIDATORS:
        raise ValueError(f"unknown manifest kind {kind!r}")
    return VALIDATORS[kind](doc, **kwargs)
