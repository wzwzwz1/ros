"""Typed client for the robot gateway (real or mock).

Errors from the gateway surface as GatewayError with the envelope's error code;
connection failures surface as GatewayConnectionError so callers can
distinguish "robot unreachable" from "gateway rejected the request".
"""

from __future__ import annotations

import httpx

from spatial_agent.config.schema import Profile
from spatial_agent.gateway.isolation import build_client
from spatial_agent.protocol.envelope import Envelope


class GatewayError(RuntimeError):
    def __init__(self, code: str, message: str, retryable: bool = False, details: dict | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = details or {}


class GatewayConnectionError(RuntimeError):
    pass


class GatewayClient:
    def __init__(self, profile: Profile | str, base_url: str, token: str, timeout_s: float = 5.0):
        self.profile = Profile(profile)
        self.base_url = base_url
        self._client = build_client(self.profile, base_url, token, timeout_s=timeout_s)

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _request(self, method: str, path: str, *, json_body: dict | None = None,
                 headers: dict | None = None, params: dict | None = None) -> Envelope:
        try:
            resp = self._client.request(method, path, json=json_body, headers=headers, params=params)
        except httpx.HTTPError as exc:
            raise GatewayConnectionError(f"gateway unreachable at {self.base_url}: {exc}") from exc
        try:
            payload = resp.json()
        except ValueError as exc:
            raise GatewayConnectionError(f"gateway returned non-JSON response: HTTP {resp.status_code}") from exc
        envelope = Envelope.model_validate(payload)
        if not envelope.ok:
            err = envelope.error or {}
            raise GatewayError(
                err.get("code", "INTERNAL"),
                err.get("message", "unknown error"),
                retryable=bool(err.get("retryable")),
                details=err.get("details"),
            )
        return envelope

    # --- P0 read-only surface ---
    def health(self) -> dict:
        return self._request("GET", "/health").data or {}

    def capabilities(self) -> dict:
        return self._request("GET", "/v1/capabilities").data or {}

    def status(self) -> dict:
        return self._request("GET", "/v1/status").data or {}

    def pose(self) -> dict:
        return self._request("GET", "/v1/pose").data or {}

    # --- navigation / safety (implemented by gateway; P0 mock, P1 real) ---
    def submit_goal(self, goal: dict, *, map_id: str, session_id: str, timeout_s: float,
                    idempotency_key: str, trace_id: str) -> dict:
        return self._request(
            "POST", "/v1/navigation/goals",
            json_body={"map_id": map_id, "goal": goal, "session_id": session_id, "timeout_s": timeout_s,
                       "trace_id": trace_id},
            headers={"Idempotency-Key": idempotency_key},
        ).data or {}

    def operation(self, operation_id: str) -> dict:
        return self._request("GET", f"/v1/operations/{operation_id}").data or {}

    def operation_by_key(self, key: str) -> dict:
        return self._request("GET", f"/v1/operations/by-key/{key}").data or {}

    def cancel_operation(self, operation_id: str) -> dict:
        return self._request("POST", f"/v1/operations/{operation_id}/cancel").data or {}

    def arm(self, session_id: str) -> dict:
        return self._request("POST", "/v1/safety/arm", json_body={"session_id": session_id}).data or {}

    def lease(self, session_id: str, sequence: int) -> dict:
        return self._request("POST", "/v1/safety/lease", json_body={"session_id": session_id, "sequence": sequence}).data or {}

    def stop(self, reason: str) -> dict:
        # /safety/stop always re-executes: never send an Idempotency-Key.
        return self._request("POST", "/v1/safety/stop", json_body={"reason": reason}).data or {}
