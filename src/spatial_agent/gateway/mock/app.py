"""Mock robot gateway (P0.4): full v1 navigation/safety semantics in simulation.

- Every response carries the envelope plus header ``X-Spatial-Source: mock`` and
  ``data.source == "mock"`` so mock output can never be mistaken for a robot.
- Simulates navigation lifecycle, safety arm/lease/stop latching, idempotency,
  WS event stream with after_seq replay, and fault injection (timeout, failure,
  stream break, rejection).
- The ``/__mock/*`` admin namespace exists only for tests and is always
  loopback-bound; it is never part of the robot contract.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Header, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from spatial_agent import PROTOCOL_VERSION
from spatial_agent.protocol.envelope import (
    ERROR_CODES,
    Goal,
    InitialPose,
    OperationState,
    StopState,
    error_envelope,
    ok_envelope,
)

MOCK_ROBOT_ID = "mock-robot-001"
MOCK_MAP_ID = "mock-map-0000000000000000000000000000000000000000000000000000000000000"[:64]


@dataclass
class MockSettings:
    token: str = "mock-token"
    map_id: str = MOCK_MAP_ID
    lease_timeout_ms: float = 2000.0
    nav_travel_time_s: float = 1.0  # simulated travel duration for a successful goal
    event_sink: Any = None  # optional callable(dict) for JSONL logging


@dataclass
class Operation:
    operation_id: str
    map_id: str
    goal: dict
    session_id: str
    timeout_s: float
    state: OperationState = OperationState.ACCEPTED
    created_monotonic: float = field(default_factory=time.monotonic)
    deadline_monotonic: float = 0.0
    progress: float = 0.0
    error: dict | None = None
    idempotency_key: str | None = None
    request_fingerprint: str | None = None
    stop_evidence: dict | None = None
    _task: asyncio.Task | None = field(default=None, repr=False)


class MockGatewayState:
    def __init__(self, settings: MockSettings):
        self.settings = settings
        self.armed = False
        self.stop_latched = False
        self.session_id: str | None = None
        self.lease_sequence = 0
        self.lease_renewed_monotonic: float | None = None
        self.operations: dict[str, Operation] = {}
        self.events: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.localization_valid = True
        self.initial_pose_set = False
        self.faults: dict[str, Any] = {}
        self.mock_session_id = "mock-session-001"

    # --- events ---
    def emit(self, event: str, **fields: Any) -> dict:
        record = {
            "seq": len(self.events) + 1,
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z",
            "source": "mock",
            "robot_id": MOCK_ROBOT_ID,
            "event": event,
            **fields,
        }
        self.events.append(record)
        if self.settings.event_sink is not None:
            try:
                self.settings.event_sink(record)
            except Exception:
                pass
        for q in list(self.subscribers):
            q.put_nowait(record)
        return record

    # --- guards ---
    def lease_age_ms(self) -> float | None:
        if self.lease_renewed_monotonic is None:
            return None
        return (time.monotonic() - self.lease_renewed_monotonic) * 1000.0

    def lease_valid(self) -> bool:
        age = self.lease_age_ms()
        return age is not None and age <= self.settings.lease_timeout_ms

    def active_operation(self) -> Operation | None:
        for op in self.operations.values():
            if op.state in (OperationState.ACCEPTED, OperationState.RUNNING):
                return op
        return None


def create_app(settings: MockSettings | None = None) -> FastAPI:
    settings = settings or MockSettings()
    state = MockGatewayState(settings)
    app = FastAPI(title="Spatial Agent Mock Gateway", docs_url=None, redoc_url=None)
    app.state.mock = state

    def _source_marker(data: Any) -> Any:
        if isinstance(data, dict):
            return {"source": "mock", **data}
        return data

    def _respond(data: Any, request_id: str | None, status_code: int = 200):
        payload = ok_envelope(_source_marker(data), request_id=request_id).model_dump()
        return JSONResponse(payload, status_code=status_code, headers={"X-Spatial-Source": "mock"})

    def _reject(code: str, message: str, request_id: str | None, retryable: bool = False,
                status_code: int = 400, details: dict | None = None):
        payload = error_envelope(code, message, retryable=retryable, details=details, request_id=request_id).model_dump()
        return JSONResponse(payload, status_code=status_code, headers={"X-Spatial-Source": "mock"})

    def _authorized(authorization: str | None) -> bool:
        return authorization == f"Bearer {settings.token}"

    # ------------------------------------------------------------------ health
    @app.get("/health")
    def health():
        return _respond({"status": "ok", "robot_id": MOCK_ROBOT_ID, "stop_latched": state.stop_latched}, None)

    @app.get("/v1/capabilities")
    def capabilities(authorization: str | None = Header(default=None)):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", None, status_code=401)
        return _respond(
            {
                "robot_id": MOCK_ROBOT_ID,
                "ros": {"distro": "humble", "mock": True},
                "actions": ["navigation"],
                "sensors": ["lidar_mock", "rgbd_mock", "odom_mock"],
                "supported_formats": {"rgbd": [], "audio": []},
                "implemented_phases": {"navigation": "P1", "observations": "P2", "audio": "P5"},
            },
            None,
        )

    @app.get("/v1/status")
    def status(authorization: str | None = Header(default=None)):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", None, status_code=401)
        active = state.active_operation()
        blocking = []
        if state.stop_latched:
            blocking.append("STOP_LATCHED")
        if not state.armed:
            blocking.append("NOT_ARMED")
        if not state.localization_valid:
            blocking.append("LOCALIZATION_INVALID")
        return _respond(
            {
                "robot_id": MOCK_ROBOT_ID,
                "components": {
                    "navigation": "ok",
                    "localization": "ok" if state.localization_valid else "invalid",
                    "lidar": "ok",
                    "rgbd": "not_implemented_until_P2",
                },
                "map_id": settings.map_id,
                "active_operation_id": active.operation_id if active else None,
                "armed": state.armed,
                "stop_latched": state.stop_latched,
                "lease_age_ms": state.lease_age_ms(),
                "blocked_reasons": blocking,
            },
            None,
        )

    @app.get("/v1/pose")
    def pose(authorization: str | None = Header(default=None)):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", None, status_code=401)
        return _respond(
            {
                "pose": {"x_m": 0.0, "y_m": 0.0, "yaw_rad": 0.0},
                "frame": "map",
                "map_id": settings.map_id,
                "ros_stamp_ns": time.time_ns(),
                "covariance_diagonal_m2": [0.01, 0.01, 0.02],
                "localization_valid": state.localization_valid,
                "validity_reason": None if state.localization_valid else "injected by mock fault",
            },
            None,
        )

    @app.post("/v1/localization/initial-pose")
    def initial_pose(body: InitialPose, authorization: str | None = Header(default=None), request_id: str | None = Header(default=None, alias="X-Request-Id")):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", request_id, status_code=401)
        if state.armed or state.active_operation():
            return _reject("CONFLICT", "initial pose is only allowed while disarmed and idle", request_id, status_code=409)
        state.initial_pose_set = True
        state.localization_valid = True
        state.emit("initial_pose_set", x_m=body.x_m, y_m=body.y_m, yaw_rad=body.yaw_rad)
        return _respond({"accepted": True}, request_id)

    # -------------------------------------------------------------- navigation
    def _nav_guards(request_id: str | None, map_id: str | None):
        if state.faults.get("reject_next", 0) > 0:
            state.faults["reject_next"] -= 1
            return _reject("ROBOT_UNREACHABLE", "injected by mock fault", request_id, retryable=True, status_code=503)
        if state.stop_latched:
            return _reject("STOP_LATCHED", "stop is latched; explicit re-arm required", request_id)
        if not state.armed:
            return _reject("NOT_ARMED", "navigation requires an armed gateway", request_id)
        if not state.lease_valid():
            return _reject("LEASE_EXPIRED", "no fresh control lease", request_id)
        if not state.localization_valid:
            return _reject("LOCALIZATION_INVALID", "localization is invalid", request_id)
        if map_id != settings.map_id:
            return _reject("MAP_MISMATCH", f"map_id {map_id!r} does not match loaded map", request_id)
        return None

    @app.post("/v1/navigation/plan")
    def plan(body: dict, authorization: str | None = Header(default=None), request_id: str | None = Header(default=None, alias="X-Request-Id")):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", request_id, status_code=401)
        guarded = _nav_guards(request_id, body.get("map_id"))
        if guarded is not None:
            return guarded
        try:
            Goal.model_validate(body.get("goal") or {})
        except Exception as exc:
            return _reject("INVALID_ARGUMENT", f"invalid goal: {exc}", request_id)
        path = [{"x_m": 0.0, "y_m": 0.0}, {"x_m": body["goal"]["x_m"], "y_m": body["goal"]["y_m"]}]
        length = abs(float(body["goal"]["x_m"])) + abs(float(body["goal"]["y_m"]))
        return _respond({"path": path, "length_m": round(length, 3), "feasible": True, "final_state": "feasible"}, request_id)

    @app.post("/v1/navigation/goals")
    async def submit_goal(body: dict, authorization: str | None = Header(default=None),
                          request_id: str | None = Header(default=None, alias="X-Request-Id"),
                          idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", request_id, status_code=401)
        if not idempotency_key:
            return _reject("INVALID_ARGUMENT", "Idempotency-Key header is required", request_id)
        map_id = body.get("map_id")
        session_id = body.get("session_id")
        if not session_id:
            return _reject("INVALID_ARGUMENT", "session_id is required", request_id)
        try:
            goal = Goal.model_validate(body.get("goal") or {})
        except Exception as exc:
            return _reject("INVALID_ARGUMENT", f"invalid goal: {exc}", request_id)
        timeout_s = body.get("timeout_s")
        if not isinstance(timeout_s, (int, float)) or timeout_s <= 0:
            return _reject("INVALID_ARGUMENT", "timeout_s must be a positive number", request_id)

        guarded = _nav_guards(request_id, map_id)
        if guarded is not None:
            return guarded

        # Idempotency: same key + same body -> original operation; same key +
        # different body -> 409 (interface-contracts.md §1).
        fingerprint = f"{map_id}|{goal.model_dump_json()}|{session_id}|{timeout_s}"
        for op in state.operations.values():
            if op.idempotency_key == idempotency_key and op.session_id == session_id:
                if op.request_fingerprint == fingerprint:
                    return _respond(
                        {"operation_id": op.operation_id, "status": op.state.value, "deduplicated": True}, request_id
                    )
                return _reject("CONFLICT", "same Idempotency-Key with different body", request_id, status_code=409)

        if state.active_operation():
            return _reject("NAV_BUSY", "another navigation is active; cancel it first", request_id, status_code=409)

        op = Operation(
            operation_id=f"nav-{uuid.uuid4().hex[:12]}",
            map_id=map_id,
            goal=goal.model_dump(),
            session_id=session_id,
            timeout_s=float(timeout_s),
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
        )
        op.deadline_monotonic = op.created_monotonic + op.timeout_s
        state.operations[op.operation_id] = op
        state.emit("navigation_accepted", operation_id=op.operation_id, goal=op.goal)
        op._task = asyncio.create_task(_run_navigation(op))
        return JSONResponse(
            ok_envelope(_source_marker({"operation_id": op.operation_id, "status": op.state.value}), request_id).model_dump(),
            status_code=202,
            headers={"X-Spatial-Source": "mock"},
        )

    async def _run_navigation(op: Operation):
        await asyncio.sleep(0.05)
        op.state = OperationState.RUNNING
        state.emit("navigation_running", operation_id=op.operation_id)
        fault = state.faults.get("navigation")
        travel = settings.nav_travel_time_s
        fail_immediately = fault == "navigation_fail"
        hang = fault == "navigation_timeout"
        steps = 5
        for i in range(1, steps + 1):
            if hang and i == 3:
                # Simulated stall: stop emitting progress; the deadline check
                # below turns the operation into TIMED_OUT.
                while time.monotonic() < op.deadline_monotonic:
                    await asyncio.sleep(0.02)
                op.state = OperationState.TIMED_OUT
                op.error = {"code": "TIMEOUT", "message": "navigation exceeded its deadline (mock fault)"}
                state.emit("navigation_timed_out", operation_id=op.operation_id)
                return
            await asyncio.sleep(travel / steps)
            if fail_immediately and i == 2:
                op.state = OperationState.FAILED
                op.error = {"code": "NAV_FAILED", "message": "injected by mock fault"}
                state.emit("navigation_failed", operation_id=op.operation_id)
                return
            op.progress = i / steps
            state.emit("navigation_progress", operation_id=op.operation_id, progress=op.progress)
        op.state = OperationState.SUCCEEDED
        state.emit("navigation_succeeded", operation_id=op.operation_id)

    def _get_op(op_id: str, request_id: str | None) -> Operation | JSONResponse:
        op = state.operations.get(op_id)
        if op is None:
            return _reject("INVALID_ARGUMENT", f"unknown operation {op_id!r}", request_id, status_code=404)
        return op

    def _op_payload(op: Operation) -> dict:
        data = {
            "operation_id": op.operation_id,
            "status": op.state.value,
            "progress": op.progress,
            "map_id": op.map_id,
            "goal": op.goal,
            "error": op.error,
            "last_event_seq": len(state.events),
        }
        if op.state in (OperationState.CANCELED, OperationState.SUCCEEDED, OperationState.FAILED, OperationState.TIMED_OUT):
            data["stop_evidence"] = op.stop_evidence or _fresh_stop_evidence()
        return data

    def _fresh_stop_evidence() -> dict:
        return {
            "state": StopState.STATIONARY.value,
            "command_zero_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "stationary_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "odometry_speed_mps": 0.0,
            "source": "mock",
        }

    @app.get("/v1/operations/{op_id}")
    def get_operation(op_id: str, authorization: str | None = Header(default=None), request_id: str | None = Header(default=None, alias="X-Request-Id")):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", request_id, status_code=401)
        op = _get_op(op_id, request_id)
        if isinstance(op, JSONResponse):
            return op
        return _respond(_op_payload(op), request_id)

    @app.get("/v1/operations/by-key/{key}")
    def get_operation_by_key(key: str, authorization: str | None = Header(default=None), request_id: str | None = Header(default=None, alias="X-Request-Id")):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", request_id, status_code=401)
        for op in state.operations.values():
            if op.idempotency_key == key:
                return _respond(_op_payload(op), request_id)
        return _reject("INVALID_ARGUMENT", f"no operation for key {key!r}", request_id, status_code=404)

    @app.post("/v1/operations/{op_id}/cancel")
    async def cancel_operation(op_id: str, authorization: str | None = Header(default=None), request_id: str | None = Header(default=None, alias="X-Request-Id")):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", request_id, status_code=401)
        op = _get_op(op_id, request_id)
        if isinstance(op, JSONResponse):
            return op
        if op.state in (OperationState.ACCEPTED, OperationState.RUNNING):
            if op._task is not None:
                op._task.cancel()
            op.state = OperationState.CANCELED
            op.stop_evidence = _fresh_stop_evidence()
            state.emit("navigation_canceled", operation_id=op.operation_id)
        return _respond(_op_payload(op), request_id)

    # ------------------------------------------------------------------ safety
    @app.post("/v1/safety/arm")
    def arm(body: dict, authorization: str | None = Header(default=None), request_id: str | None = Header(default=None, alias="X-Request-Id")):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", request_id, status_code=401)
        session_id = body.get("session_id")
        if not session_id:
            return _reject("INVALID_ARGUMENT", "session_id is required", request_id)
        if session_id != state.mock_session_id:
            return _reject("INVALID_ARGUMENT", f"unknown session {session_id!r} for mock gateway", request_id)
        if not state.localization_valid:
            return _reject("LOCALIZATION_INVALID", "cannot arm with invalid localization", request_id)
        if state.stop_latched:
            if not body.get("clear_stop"):
                return _reject("STOP_LATCHED", "stop is latched; re-arm requires clear_stop=true", request_id)
            state.stop_latched = False
            state.emit("stop_cleared")
        state.armed = True
        state.session_id = session_id
        state.emit("armed", session_id=session_id)
        return _respond({"armed": True}, request_id)

    @app.post("/v1/safety/lease")
    def lease(body: dict, authorization: str | None = Header(default=None), request_id: str | None = Header(default=None, alias="X-Request-Id")):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", request_id, status_code=401)
        session_id = body.get("session_id")
        sequence = body.get("sequence")
        if not session_id or not isinstance(sequence, int):
            return _reject("INVALID_ARGUMENT", "session_id and integer sequence are required", request_id)
        if not state.armed or state.session_id != session_id:
            return _reject("NOT_ARMED", "lease requires an armed gateway with the same session", request_id)
        if sequence <= state.lease_sequence:
            return _reject("LEASE_EXPIRED", f"stale lease sequence {sequence} (last {state.lease_sequence})", request_id)
        state.lease_sequence = sequence
        state.lease_renewed_monotonic = time.monotonic()
        return _respond({"lease_sequence": sequence, "lease_timeout_ms": settings.lease_timeout_ms}, request_id)

    @app.post("/v1/safety/stop")
    async def stop(body: dict, authorization: str | None = Header(default=None), request_id: str | None = Header(default=None, alias="X-Request-Id")):
        if not _authorized(authorization):
            return _reject("AUTH_FAILED", "missing or invalid bearer token", request_id, status_code=401)
        reason = body.get("reason") or "unspecified"
        stop_id = f"stop-{uuid.uuid4().hex[:12]}"
        # stop always re-executes: cancel any active navigation, latch, disarm.
        active = state.active_operation()
        if active is not None:
            if active._task is not None:
                active._task.cancel()
            active.state = OperationState.CANCELED
            active.stop_evidence = _fresh_stop_evidence()
            state.emit("navigation_canceled", operation_id=active.operation_id, reason="safety_stop")
        state.armed = False
        state.stop_latched = True
        state.lease_renewed_monotonic = None
        state.emit("safety_stop", stop_id=stop_id, reason=reason)
        return _respond(
            {
                "stop_id": stop_id,
                "state": StopState.COMMAND_ZERO.value,
                "stop_latched": True,
                "canceled_operation_id": active.operation_id if active else None,
            },
            request_id,
        )

    # ------------------------------------------------------- P2+ capabilities
    @app.post("/v1/observations/capture")
    def capture(request_id: str | None = Header(default=None, alias="X-Request-Id")):
        return _reject("CAPABILITY_UNAVAILABLE", "RGB-D capture arrives in P2", request_id, status_code=501)

    # ----------------------------------------------------------------- events
    @app.websocket("/v1/events")
    async def events(ws: WebSocket, after_seq: int = Query(default=0)):
        if ws.query_params.get("token") != settings.token:
            await ws.close(code=4401)
            return
        await ws.accept()
        queue: asyncio.Queue = asyncio.Queue()
        state.subscribers.add(queue)
        try:
            for record in state.events:
                if record["seq"] > after_seq:
                    await ws.send_json(record)
            last_sent = max(after_seq, len(state.events))
            while True:
                record = await queue.get()
                if record["seq"] > last_sent:
                    await ws.send_json(record)
                    last_sent = record["seq"]
        except WebSocketDisconnect:
            pass
        finally:
            state.subscribers.discard(queue)

    # ------------------------------------------------------------ mock admin
    @app.post("/__mock/faults")
    async def inject_faults(body: dict):
        kind = body.get("kind")
        if kind == "navigation_fail":
            state.faults["navigation"] = "navigation_fail"
        elif kind == "navigation_timeout":
            state.faults["navigation"] = "navigation_timeout"
        elif kind == "navigation_clear":
            state.faults.pop("navigation", None)
        elif kind == "reject_next":
            state.faults["reject_next"] = int(body.get("count", 1))
        elif kind == "stream_break":
            for q in list(state.subscribers):
                q.put_nowait({"seq": len(state.events) + 1, "event": "__stream_break__", "source": "mock"})
            state.subscribers.clear()
            state.emit("stream_broken_by_fault")
        elif kind == "localization_invalid":
            state.localization_valid = False
            state.emit("localization_invalidated_by_fault")
        elif kind == "clear":
            state.faults.clear()
            state.localization_valid = True
        else:
            return _reject("INVALID_ARGUMENT", f"unknown fault kind {kind!r}", None)
        state.emit("fault_injected", kind=kind)
        return _respond({"faults": dict(state.faults)}, None)

    @app.get("/__mock/state")
    def mock_state():
        return _respond(
            {
                "armed": state.armed,
                "stop_latched": state.stop_latched,
                "operations": {k: v.state.value for k, v in state.operations.items()},
                "faults": dict(state.faults),
                "event_count": len(state.events),
                "error_codes_known": sorted(ERROR_CODES),
            },
            None,
        )

    return app
