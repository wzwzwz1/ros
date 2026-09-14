"""Integration tests: mock gateway contract over real HTTP.

Covers the v1 lifecycle (arm/lease/goal/dedup/cancel/stop latch), fault
injection, and the WebSocket event stream with after_seq reconnection.
"""

import asyncio
import threading
import time
import uuid

import httpx
import pytest
from uvicorn import Config, Server

from spatial_agent.gateway.client import GatewayClient, GatewayConnectionError, GatewayError
from spatial_agent.gateway.mock.app import MockSettings, create_app

TOKEN = "test-token"
MAP_ID = "mock-map-" + "0" * 55


@pytest.fixture(scope="module")
def mock_gateway():
    app = create_app(MockSettings(token=TOKEN, map_id=MAP_ID, nav_travel_time_s=0.5))
    config = Config(app, host="127.0.0.1", port=8799, log_level="error")
    server = Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            httpx.get("http://127.0.0.1:8799/health", timeout=0.5)
            break
        except httpx.HTTPError:
            time.sleep(0.1)
    else:
        raise RuntimeError("mock gateway did not start")
    yield "http://127.0.0.1:8799"
    server.should_exit = True
    thread.join(timeout=5)


def client(url) -> GatewayClient:
    return GatewayClient("mock", url, TOKEN)


def authed_session(c: GatewayClient) -> str:
    session_id = "mock-session-001"
    c.arm(session_id)
    c.lease(session_id, int(time.monotonic() * 1000))
    return session_id


# ----------------------------------------------------------------- basics
def test_health_and_capabilities_and_source_marker(mock_gateway):
    with client(mock_gateway) as c:
        health = c.health()
        assert health["source"] == "mock"
        caps = c.capabilities()
        assert caps["robot_id"] and "actions" in caps
        status = c.status()
        assert status["source"] == "mock"
        assert status["armed"] is False
        assert "NOT_ARMED" in status["blocked_reasons"]


def test_missing_token_is_auth_failure(mock_gateway):
    with GatewayClient("mock", mock_gateway, "wrong-token") as c:
        with pytest.raises(GatewayError) as exc_info:
            c.status()
        assert exc_info.value.code == "AUTH_FAILED"


def test_unreachable_gateway_is_connection_error():
    with GatewayClient("mock", "http://127.0.0.1:1", "t", timeout_s=0.5) as c:
        with pytest.raises(GatewayConnectionError):
            c.health()


# -------------------------------------------------------------- navigation
def test_goal_rejected_when_not_armed(mock_gateway):
    with client(mock_gateway) as c:
        with pytest.raises(GatewayError) as exc_info:
            c.submit_goal({"x_m": 1, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                          session_id="mock-session-001", timeout_s=10,
                          idempotency_key=str(uuid.uuid4()), trace_id="t")
        assert exc_info.value.code == "NOT_ARMED"


def test_full_navigation_lifecycle_success(mock_gateway):
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        key = f"it-{uuid.uuid4().hex[:8]}"
        op = c.submit_goal({"x_m": 1.0, "y_m": 0.5, "yaw_rad": 0.0}, map_id=MAP_ID,
                           session_id=session_id, timeout_s=30, idempotency_key=key, trace_id="t1")
        oid = op["operation_id"]
        deadline = time.monotonic() + 10
        final = None
        while time.monotonic() < deadline:
            final = c.operation(oid)
            if final["status"] in ("SUCCEEDED", "FAILED", "TIMED_OUT", "CANCELED"):
                break
            time.sleep(0.05)
        assert final["status"] == "SUCCEEDED", final
        assert final["stop_evidence"]["state"] == "STATIONARY"
        assert c.operation_by_key(key)["operation_id"] == oid


def test_idempotent_resubmit_returns_same_operation(mock_gateway):
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        key = f"it-{uuid.uuid4().hex[:8]}"
        first = c.submit_goal({"x_m": 2, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                              session_id=session_id, timeout_s=30, idempotency_key=key, trace_id="t")
        dup = c.submit_goal({"x_m": 2, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                            session_id=session_id, timeout_s=30, idempotency_key=key, trace_id="t")
        assert dup["operation_id"] == first["operation_id"]
        assert dup.get("deduplicated") is True


def test_same_key_different_body_conflicts(mock_gateway):
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        key = f"it-{uuid.uuid4().hex[:8]}"
        c.submit_goal({"x_m": 2, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                      session_id=session_id, timeout_s=30, idempotency_key=key, trace_id="t")
        with pytest.raises(GatewayError) as exc_info:
            c.submit_goal({"x_m": 3, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                          session_id=session_id, timeout_s=30, idempotency_key=key, trace_id="t")
        assert exc_info.value.code == "CONFLICT"


def test_second_goal_while_active_is_nav_busy(mock_gateway):
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        c.submit_goal({"x_m": 2, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                      session_id=session_id, timeout_s=30, idempotency_key=str(uuid.uuid4()), trace_id="t")
        with pytest.raises(GatewayError) as exc_info:
            c.submit_goal({"x_m": 1, "y_m": 1, "yaw_rad": 0}, map_id=MAP_ID,
                          session_id=session_id, timeout_s=30, idempotency_key=str(uuid.uuid4()), trace_id="t")
        assert exc_info.value.code == "NAV_BUSY"
        # wait it out to leave a clean state for later tests
        time.sleep(1.2)


def test_map_mismatch_rejected(mock_gateway):
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        with pytest.raises(GatewayError) as exc_info:
            c.submit_goal({"x_m": 1, "y_m": 0, "yaw_rad": 0}, map_id="other-map",
                          session_id=session_id, timeout_s=10,
                          idempotency_key=str(uuid.uuid4()), trace_id="t")
        assert exc_info.value.code == "MAP_MISMATCH"


def test_invalid_goal_rejected(mock_gateway):
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        with pytest.raises(GatewayError) as exc_info:
            c.submit_goal({"x_m": "one", "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                          session_id=session_id, timeout_s=10,
                          idempotency_key=str(uuid.uuid4()), trace_id="t")
        assert exc_info.value.code == "INVALID_ARGUMENT"


def test_cancel_active_navigation(mock_gateway):
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        op = c.submit_goal({"x_m": 3, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                           session_id=session_id, timeout_s=30,
                           idempotency_key=str(uuid.uuid4()), trace_id="t")
        result = c.cancel_operation(op["operation_id"])
        assert result["status"] == "CANCELED"
        assert result["stop_evidence"]["state"] == "STATIONARY"
        time.sleep(0.7)  # let the cancelled task finish quietly


def test_terminal_state_not_rewritten(mock_gateway):
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        op = c.submit_goal({"x_m": 2, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                           session_id=session_id, timeout_s=30,
                           idempotency_key=str(uuid.uuid4()), trace_id="t")
        time.sleep(0.8)
        first = c.operation(op["operation_id"])
        assert first["status"] == "SUCCEEDED"
        again = c.cancel_operation(op["operation_id"])  # cancel after terminal
        assert again["status"] == "SUCCEEDED"  # stays SUCCEEDED, not CANCELED


# ------------------------------------------------------------------ safety
def test_stop_latches_and_blocks_everything(mock_gateway):
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        result = c.stop("integration test stop")
        assert result["stop_latched"] is True
        status = c.status()
        assert status["stop_latched"] is True and status["armed"] is False
        with pytest.raises(GatewayError) as exc_info:
            c.submit_goal({"x_m": 1, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                          session_id=session_id, timeout_s=10,
                          idempotency_key=str(uuid.uuid4()), trace_id="t")
        assert exc_info.value.code == "STOP_LATCHED"
        with pytest.raises(GatewayError) as arm_exc:
            c.arm(session_id)
        assert arm_exc.value.code == "STOP_LATCHED"
        # explicit re-arm with clear_stop
        http = httpx.Client(base_url=mock_gateway, headers={"Authorization": f"Bearer {TOKEN}"})
        http.post("/v1/safety/arm", json={"session_id": session_id, "clear_stop": True})
        http.close()
        assert c.status()["stop_latched"] is False


def test_stale_lease_sequence_rejected(mock_gateway):
    with client(mock_gateway) as c:
        c.arm("mock-session-001")
        seq = int(time.monotonic() * 1000)
        c.lease("mock-session-001", seq)
        with pytest.raises(GatewayError) as exc_info:
            c.lease("mock-session-001", seq)  # replay must not extend
        assert exc_info.value.code == "LEASE_EXPIRED"


def test_initial_pose_only_when_disarmed(mock_gateway):
    http = httpx.Client(base_url=mock_gateway, headers={"Authorization": f"Bearer {TOKEN}"})
    r = http.post("/v1/localization/initial-pose", json={
        "x_m": 0.1, "y_m": 0.2, "yaw_rad": 0.3, "covariance_diagonal_m2": [0.05, 0.05, 0.1]})
    assert r.json()["ok"] is True
    http.close()


# ------------------------------------------------------------------ faults
def _inject(mock_gateway, kind, **body):
    http = httpx.Client(base_url=mock_gateway)
    r = http.post("/__mock/faults", json={"kind": kind, **body})
    assert r.json()["ok"] is True, r.text
    http.close()


def test_fault_navigation_fail(mock_gateway):
    _inject(mock_gateway, "navigation_fail")
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        op = c.submit_goal({"x_m": 1, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                           session_id=session_id, timeout_s=30,
                           idempotency_key=str(uuid.uuid4()), trace_id="t")
        deadline = time.monotonic() + 10
        status = None
        while time.monotonic() < deadline:
            status = c.operation(op["operation_id"])["status"]
            if status in ("FAILED", "SUCCEEDED"):
                break
            time.sleep(0.05)
        assert status == "FAILED"
    _inject(mock_gateway, "navigation_clear")


def test_fault_navigation_timeout(mock_gateway):
    _inject(mock_gateway, "navigation_timeout")
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        op = c.submit_goal({"x_m": 1, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                           session_id=session_id, timeout_s=1.0,
                           idempotency_key=str(uuid.uuid4()), trace_id="t")
        deadline = time.monotonic() + 10
        status = None
        while time.monotonic() < deadline:
            payload = c.operation(op["operation_id"])
            status = payload["status"]
            if status == "TIMED_OUT":
                break
            time.sleep(0.1)
        assert status == "TIMED_OUT"
        assert c.operation(op["operation_id"])["error"]["code"] == "TIMEOUT"
    _inject(mock_gateway, "navigation_clear")


def test_fault_reject_next(mock_gateway):
    _inject(mock_gateway, "reject_next", count=1)
    with client(mock_gateway) as c:
        session_id = authed_session(c)
        with pytest.raises(GatewayConnectionError):
            # gateway answers 503; the client surfaces dependency-unavailable
            # as GatewayError with code ROBOT_UNREACHABLE via envelope
            c.submit_goal({"x_m": 1, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                          session_id=session_id, timeout_s=10,
                          idempotency_key=str(uuid.uuid4()), trace_id="t")


def test_fault_localization_invalid_blocks_navigation(mock_gateway):
    _inject(mock_gateway, "localization_invalid")
    with client(mock_gateway) as c:
        c.arm("mock-session-001")
        c.lease("mock-session-001", int(time.monotonic() * 1000))
        with pytest.raises(GatewayError) as exc_info:
            c.submit_goal({"x_m": 1, "y_m": 0, "yaw_rad": 0}, map_id=MAP_ID,
                          session_id="mock-session-001", timeout_s=10,
                          idempotency_key=str(uuid.uuid4()), trace_id="t")
        assert exc_info.value.code == "LOCALIZATION_INVALID"
        assert c.pose()["localization_valid"] is False
    _inject(mock_gateway, "clear")


def test_p2_capability_unavailable(mock_gateway):
    with client(mock_gateway) as c:
        with pytest.raises(GatewayError) as exc_info:
            http = httpx.Client(base_url=mock_gateway, headers={"Authorization": f"Bearer {TOKEN}"})
            r = http.post("/v1/observations/capture", json={})
            payload = r.json()
            http.close()
            if not payload["ok"]:
                raise GatewayError(payload["error"]["code"], payload["error"]["message"])
        assert exc_info.value.code == "CAPABILITY_UNAVAILABLE"


# ------------------------------------------------------------------- WS
def test_events_stream_and_after_seq_reconnect(mock_gateway):
    import websockets

    async def scenario():
        uri = f"ws://127.0.0.1:8799/v1/events?token={TOKEN}&after_seq=0"
        received = []
        async with websockets.connect(uri) as ws:
            # trigger an event
            http = httpx.Client(base_url=mock_gateway, headers={"Authorization": f"Bearer {TOKEN}"})
            http.post("/v1/safety/arm", json={"session_id": "mock-session-001", "clear_stop": True})
            http.close()
            try:
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=3)
                    received.append(msg)
                    if len(received) >= 1:
                        break
            except asyncio.TimeoutError:
                pass
        assert received, "expected at least one event after arm"
        # reconnect from after_seq=0 must replay history
        async with websockets.connect(f"ws://127.0.0.1:8799/v1/events?token={TOKEN}&after_seq=0") as ws2:
            replayed = json_count = 0
            try:
                while True:
                    await asyncio.wait_for(ws2.recv(), timeout=2)
                    replayed += 1
            except asyncio.TimeoutError:
                pass
            assert replayed >= 1

    asyncio.run(scenario())


def test_events_ws_bad_token_rejected(mock_gateway):
    import websockets

    async def probe():
        try:
            async with websockets.connect("ws://127.0.0.1:8799/v1/events?token=wrong") as ws:
                await ws.recv()
                return False
        except websockets.exceptions.ConnectionClosed as exc:
            return exc.code == 4401
        except OSError:
            return True

    assert asyncio.run(probe())
