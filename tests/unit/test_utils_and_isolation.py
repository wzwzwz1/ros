"""Unit tests: secret redaction, code versioning, mock isolation guard."""

from pathlib import Path

from spatial_agent.gateway.isolation import MockIsolationError, ensure_mock_target_is_loopback
from spatial_agent.logging_utils import EventLogger, redact, sha256_json
from spatial_agent.versioning import get_code_version

import pytest


def test_redact_masks_secret_keys():
    payload = {
        "gateway_token": "abc",
        "nested": {"DEEPSEEK_API_KEY": "k", "ok": "fine", "Authorization-Header": "Bearer x"},
        "items": [{"password": "p"}, {"name": "chair"}],
    }
    out = redact(payload)
    assert out["gateway_token"] == "[REDACTED]"
    assert out["nested"]["DEEPSEEK_API_KEY"] == "[REDACTED]"
    assert out["nested"]["Authorization-Header"] == "[REDACTED]"
    assert out["nested"]["ok"] == "fine"
    assert out["items"][0]["password"] == "[REDACTED]"
    assert out["items"][1]["name"] == "chair"


def test_redact_leaves_non_secret_values_visible():
    assert redact({"robot_id": "wheeltec-001"})["robot_id"] == "wheeltec-001"


def test_event_logger_writes_jsonl(tmp_path: Path):
    log = tmp_path / "events.jsonl"
    EventLogger(log, component="test").emit("something_happened", token="secret", count=3)
    line = log.read_text().strip().splitlines()[-1]
    import json

    record = json.loads(line)
    assert record["event"] == "something_happened"
    assert record["token"] == "[REDACTED]"
    assert record["count"] == 3
    assert record["trace_id"] and record["ts_utc"]


def test_sha256_json_is_stable_regardless_of_key_order():
    assert sha256_json({"a": 1, "b": 2}) == sha256_json({"b": 2, "a": 1})


# ------------------------------------------------------------------ version
def test_code_version_in_git_repo():
    repo = Path(__file__).resolve().parents[2]
    version = get_code_version(repo)
    assert version.commit is not None  # tests run inside the repo
    assert isinstance(version.dirty, bool)
    if version.dirty:
        assert version.diff_sha256 is not None


def test_code_version_outside_git(tmp_path: Path):
    version = get_code_version(tmp_path)
    assert version.commit is None and version.dirty is None


# --------------------------------------------------------------- isolation
@pytest.mark.parametrize("url", [
    "http://192.168.0.100:8765",
    "http://10.1.2.3:8765",
    "http://wheeltec-robot.local:8765",
    "https://api.deepseek.com",
])
def test_mock_refuses_non_loopback(url):
    with pytest.raises(MockIsolationError):
        ensure_mock_target_is_loopback(url)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8765",
    "http://localhost:8765",
    "http://[::1]:8765",
])
def test_mock_allows_loopback(url):
    ensure_mock_target_is_loopback(url)  # must not raise


def test_mock_refuses_non_http_scheme():
    with pytest.raises(MockIsolationError):
        ensure_mock_target_is_loopback("ftp://127.0.0.1:8765")
