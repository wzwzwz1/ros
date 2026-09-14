"""Unit tests for the v1 protocol envelope."""

import pytest
from pydantic import ValidationError

from spatial_agent.protocol.envelope import (
    ERROR_CODES,
    Envelope,
    Goal,
    error_envelope,
    ok_envelope,
)


def test_ok_envelope_shape():
    env = ok_envelope({"a": 1}, request_id="req-1")
    assert env.ok is True and env.error is None and env.data == {"a": 1}
    assert env.schema_version == "1.0"


def test_error_envelope_has_known_code_and_fields():
    env = error_envelope("NOT_ARMED", "gateway is not armed", retryable=False, details={"x": 1})
    assert env.ok is False and env.data is None
    assert env.error["code"] == "NOT_ARMED"
    assert set(env.error) == {"code", "message", "retryable", "details"}


def test_unknown_error_code_becomes_internal():
    env = error_envelope("NOT_A_REAL_CODE", "x")
    assert env.error["code"] == "INTERNAL"


def test_envelope_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Envelope(ok=True, sneaky=1)


def test_envelope_rejects_unknown_error_field():
    with pytest.raises(ValidationError):
        Envelope(ok=False, error={"code": "TIMEOUT", "message": "m", "bogus": 1})


def test_goal_rejects_non_finite():
    with pytest.raises(ValidationError):
        Goal(x_m=float("nan"), y_m=0.0, yaw_rad=0.0)


def test_goal_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        Goal(x_m=1.0, y_m=0.0, yaw_rad=0.0, z_m=0.0)


def test_error_code_set_is_frozen_contract():
    required = {
        "INVALID_ARGUMENT", "CAPABILITY_UNAVAILABLE", "ROBOT_UNREACHABLE", "NOT_ARMED", "LEASE_EXPIRED",
        "STOP_LATCHED", "NAV_BUSY", "MAP_MISMATCH", "LOCALIZATION_INVALID", "TF_UNAVAILABLE", "SENSOR_STALE",
        "DEPTH_INVALID", "NO_SAFE_GOAL", "TARGET_NOT_FOUND", "VERIFICATION_FAILED", "NAV_FAILED", "TIMEOUT",
        "CANCELED", "MODEL_UNAVAILABLE", "BUDGET_EXCEEDED", "RESTART_INTERRUPTED",
    }
    assert required.issubset(ERROR_CODES)
