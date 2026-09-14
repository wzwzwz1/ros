"""Configuration validation and capability resolution.

Rules (development-requirements.md §4, acceptance.md P0-CONFIG):

- Structural problems (unknown fields, bad enums, non-finite values, incoherent
  safety limits) are hard errors -> config rejected, exit 2.
- A capability that is enabled but lacks its prerequisites is *degraded* with an
  explicit reason; fake values are never substituted.
- In the hardware profile, motion enabled without the measured physical facts
  (session, footprint, wheelbase, turning radius, map) is a hard error.
- In the replay profile motion must stay disabled: replay never sends targets.
- In the mock profile the gateway URL must be loopback: the mock profile may
  never reach a real robot (P0-ISOLATION).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from pydantic import ValidationError

from spatial_agent.config.schema import FIRST_VERSION_MAX_LINEAR_SPEED_MPS, Profile, RuntimeConfig
from spatial_agent.logging_utils import sha256_json

CAPABILITY_IMPLEMENTED_FROM = {"motion": "P1", "perception": "P2", "planner": "P4", "voice": "P5"}
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "127.0.0.2", "[::1]"}


@dataclass
class CapabilityStatus:
    name: str
    state: str  # available | degraded | unavailable
    reason: str | None = None

    def as_dict(self) -> dict:
        return {"name": self.name, "state": self.state, "reason": self.reason}


@dataclass
class ValidationReport:
    config: RuntimeConfig | None
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    capabilities: list[CapabilityStatus] = field(default_factory=list)
    config_sha256: str | None = None
    raw: dict | None = None

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "capabilities": [c.as_dict() for c in self.capabilities],
            "config_sha256": self.config_sha256,
            "profile": self.config.profile.value if self.config else None,
            "example_only": self.config.example_only if self.config else None,
            "usable_for_run": bool(
                self.valid and self.config is not None and not self.config.example_only
            ),
        }


def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _parse_config(raw: dict) -> tuple[RuntimeConfig | None, list[str]]:
    try:
        return RuntimeConfig.model_validate(raw), []
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "<root>"
            errors.append(f"{loc}: {err['msg']}")
        return None, errors


def _is_loopback(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host in _LOOPBACK_HOSTS


def validate_config(raw: dict, *, environment: dict[str, str] | None = None) -> ValidationReport:
    """Validate a raw config dict. Never raises; always returns a report."""
    env = os.environ if environment is None else environment
    config_sha = sha256_json(raw)
    config, errors = _parse_config(raw)
    if config is None:
        return ValidationReport(config=None, valid=False, errors=errors, config_sha256=config_sha, raw=raw)

    warnings: list[str] = []

    # --- cross-field and profile rules (hard errors) ---
    if config.motion.max_linear_speed_mps > FIRST_VERSION_MAX_LINEAR_SPEED_MPS:
        errors.append(
            f"motion.max_linear_speed_mps: first version caps at "
            f"{FIRST_VERSION_MAX_LINEAR_SPEED_MPS} m/s, got {config.motion.max_linear_speed_mps}"
        )
    if config.motion.lease_timeout_ms < config.motion.lease_period_ms:
        errors.append(
            "motion.lease_timeout_ms must be >= motion.lease_period_ms "
            f"({config.motion.lease_timeout_ms} < {config.motion.lease_period_ms})"
        )
    if config.tasks.resume_motion_after_restart:
        errors.append("tasks.resume_motion_after_restart must be false: old motion tasks never auto-resume")
    if not config.memory.require_map_id:
        errors.append("memory.require_map_id must be true: objects are always map-scoped")
    if not config.memory.preserve_observations:
        errors.append("memory.preserve_observations must be true: raw observations are never dropped")
    if config.planner.allow_silent_model_fallback:
        errors.append("planner.allow_silent_model_fallback must be false: silent model switch is forbidden")

    if config.profile is Profile.REPLAY and config.motion.enabled:
        errors.append("profile=replay must not enable motion: replay never sends targets to hardware")

    if config.profile is Profile.MOCK and not _is_loopback(config.robot.gateway_url):
        errors.append(
            "profile=mock requires a loopback robot.gateway_url "
            f"(got {config.robot.gateway_url!r}): the mock profile never reaches a real robot"
        )

    if config.profile is Profile.HARDWARE and config.motion.enabled:
        missing = []
        if not config.motion.session_file:
            missing.append("motion.session_file")
        if not config.motion.footprint_m:
            missing.append("motion.footprint_m (measured)")
        if config.motion.wheelbase_m is None:
            missing.append("motion.wheelbase_m (measured)")
        if config.motion.min_turning_radius_m is None:
            missing.append("motion.min_turning_radius_m (measured)")
        if not config.map.manifest or not config.map.map_id:
            missing.append("map.map_id and map.manifest (frozen map)")
        if missing:
            errors.append(
                "hardware profile with motion.enabled=true is missing measured prerequisites: "
                + ", ".join(missing)
            )

    if config.robot.ssh_host and config.profile is Profile.MOCK:
        warnings.append("robot.ssh_host is ignored while profile=mock")

    # --- capability resolution (degrade with reasons; never fabricate) ---
    capabilities: list[CapabilityStatus] = []
    impl_phase = CAPABILITY_IMPLEMENTED_FROM

    if config.motion.enabled and config.profile is not Profile.MOCK and errors:
        capabilities.append(CapabilityStatus("motion", "unavailable", "configuration errors above must be fixed first"))
    elif not config.motion.enabled:
        capabilities.append(CapabilityStatus("motion", "unavailable", "motion.enabled=false"))
    else:
        capabilities.append(CapabilityStatus("motion", "available", f"mock/hardware launch from {impl_phase['motion']}"))

    if not config.perception.enabled:
        capabilities.append(CapabilityStatus("perception", "unavailable", "perception.enabled=false"))
    elif config.perception.calibration_id is None:
        capabilities.append(CapabilityStatus("perception", "degraded", "perception.calibration_id is not set"))
    else:
        capabilities.append(CapabilityStatus("perception", "degraded", f"perception implementation arrives in {impl_phase['perception']}"))

    if not config.planner.enabled:
        capabilities.append(CapabilityStatus("planner", "unavailable", "planner.enabled=false"))
    elif config.planner.model_id is None:
        capabilities.append(CapabilityStatus("planner", "degraded", "planner.model_id is not set"))
    elif not env.get(config.planner.api_key_env):
        capabilities.append(
            CapabilityStatus("planner", "degraded", f"environment variable {config.planner.api_key_env} is not set")
        )
    else:
        capabilities.append(CapabilityStatus("planner", "degraded", f"planner implementation arrives in {impl_phase['planner']}"))

    if not config.voice.enabled:
        capabilities.append(CapabilityStatus("voice", "unavailable", "voice.enabled=false"))
    else:
        capabilities.append(CapabilityStatus("voice", "degraded", f"voice implementation arrives in {impl_phase['voice']}"))

    return ValidationReport(
        config=config,
        valid=not errors,
        errors=errors,
        warnings=warnings,
        capabilities=capabilities,
        config_sha256=config_sha,
        raw=raw,
    )


def validate_config_file(path: Path, *, environment: dict[str, str] | None = None) -> ValidationReport:
    raw = load_json(path)
    return validate_config(raw, environment=environment)
