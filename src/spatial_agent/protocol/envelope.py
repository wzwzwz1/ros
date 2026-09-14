"""v1 protocol types and error envelope (interface-contracts.md §1, §3)."""

from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from spatial_agent import PROTOCOL_VERSION

# Standard error codes (interface-contracts.md §3). Adding a code is a contract
# change; the mock gateway and client must agree on this set.
ERROR_CODES = frozenset(
    {
        "INVALID_ARGUMENT",
        "CAPABILITY_UNAVAILABLE",
        "ROBOT_UNREACHABLE",
        "NOT_ARMED",
        "LEASE_EXPIRED",
        "STOP_LATCHED",
        "NAV_BUSY",
        "MAP_MISMATCH",
        "LOCALIZATION_INVALID",
        "TF_UNAVAILABLE",
        "SENSOR_STALE",
        "DEPTH_INVALID",
        "NO_SAFE_GOAL",
        "TARGET_NOT_FOUND",
        "VERIFICATION_FAILED",
        "NAV_FAILED",
        "TIMEOUT",
        "CANCELED",
        "MODEL_UNAVAILABLE",
        "BUDGET_EXCEEDED",
        "RESTART_INTERRUPTED",
        "AUTH_FAILED",
        "CONFLICT",
        "INTERNAL",
    }
)


class Envelope(BaseModel):
    """Uniform response envelope for every HTTP response."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = PROTOCOL_VERSION
    request_id: str | None = None
    ok: bool
    data: dict | list | None = None
    error: dict | None = None

    @field_validator("error")
    @classmethod
    def _error_shape(cls, v: dict | None, info) -> dict | None:
        if v is not None:
            allowed = {"code", "message", "retryable", "details"}
            unknown = set(v) - allowed
            if unknown:
                raise ValueError(f"error has unknown fields: {sorted(unknown)}")
            if "code" not in v or v["code"] not in ERROR_CODES:
                raise ValueError(f"error.code must be one of {sorted(ERROR_CODES)}")
        return v


def ok_envelope(data=None, request_id: str | None = None) -> Envelope:
    return Envelope(ok=True, data=data, error=None, request_id=request_id)


def error_envelope(
    code: str,
    message: str,
    *,
    retryable: bool = False,
    details: dict | None = None,
    request_id: str | None = None,
) -> Envelope:
    if code not in ERROR_CODES:
        code = "INTERNAL"
    return Envelope(
        ok=False,
        data=None,
        request_id=request_id,
        error={"code": code, "message": message, "retryable": retryable, "details": details or {}},
    )


class OperationState(StrEnum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"
    TIMED_OUT = "TIMED_OUT"


TERMINAL_STATES = frozenset(
    {OperationState.SUCCEEDED, OperationState.FAILED, OperationState.CANCELED, OperationState.TIMED_OUT}
)


class StopState(StrEnum):
    REQUESTED = "REQUESTED"
    COMMAND_ZERO = "COMMAND_ZERO"
    STATIONARY = "STATIONARY"
    UNCONFIRMED = "UNCONFIRMED"


class Goal(BaseModel):
    """Navigation goal in the map frame (P1 semantics; mock implements them)."""

    model_config = ConfigDict(extra="forbid")

    x_m: float
    y_m: float
    yaw_rad: float

    @field_validator("x_m", "y_m", "yaw_rad")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("goal coordinates must be finite")
        return v


class InitialPose(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x_m: float
    y_m: float
    yaw_rad: float
    covariance_diagonal_m2: list[float] = Field(min_length=3, max_length=3)

    @field_validator("x_m", "y_m", "yaw_rad", "covariance_diagonal_m2")
    @classmethod
    def _finite(cls, v):
        values = v if isinstance(v, list) else [v]
        for item in values:
            if not math.isfinite(item):
                raise ValueError("pose values must be finite")
        return v
