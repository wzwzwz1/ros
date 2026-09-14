"""Gateway client with mandatory mock-profile isolation.

The mock profile may only talk to loopback endpoints (P0-ISOLATION). This guard
lives in the client itself, so even a hand-edited config cannot make a mock
session touch real hardware: constructing a client with profile=mock and a
non-loopback URL raises instead of connecting.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from spatial_agent.config.schema import Profile


class MockIsolationError(RuntimeError):
    """Raised when a mock-profile connection would target anything non-loopback."""


_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "127.0.0.2"}


def ensure_mock_target_is_loopback(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise MockIsolationError(f"mock profile requires http(s), got scheme {parsed.scheme!r}")
    host = parsed.hostname or ""
    if host not in _LOOPBACK_HOSTS:
        raise MockIsolationError(
            f"mock profile refuses non-loopback target {url!r}: mock sessions never access real hardware"
        )


def build_client(profile: Profile | str, base_url: str, token: str, timeout_s: float = 5.0) -> httpx.Client:
    profile = Profile(profile)
    if profile is Profile.MOCK:
        ensure_mock_target_is_loopback(base_url)
    headers = {"Authorization": f"Bearer {token}"}
    return httpx.Client(base_url=base_url, headers=headers, timeout=timeout_s)
