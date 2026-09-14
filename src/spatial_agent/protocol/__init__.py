"""Protocol subpackage: shared v1 types for the Mac app, gateway and mocks."""

from spatial_agent.protocol.envelope import (
    ERROR_CODES,
    Envelope,
    Goal,
    InitialPose,
    OperationState,
    StopState,
    TERMINAL_STATES,
    error_envelope,
    ok_envelope,
)

__all__ = [
    "ERROR_CODES",
    "Envelope",
    "Goal",
    "InitialPose",
    "OperationState",
    "StopState",
    "TERMINAL_STATES",
    "error_envelope",
    "ok_envelope",
]
