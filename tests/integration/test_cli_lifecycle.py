"""Integration test: process lifecycle via the real CLI (up/status/down)."""

import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def run_cli(*args, timeout_s=180):
    return subprocess.run(
        [sys.executable, "-m", "spatial_agent.cli", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout_s,
    )


def ports_open() -> tuple[bool, bool]:
    import socket

    def open_(port):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except OSError:
            return False

    return open_(8765), open_(8080)


def test_up_status_down_cycle_is_clean_and_idempotent():
    # ensure down (clean slate even after a crashed prior test)
    proc = run_cli("down")
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr

    # first up
    proc = run_cli("up", "--profile", "mock", "--format", "json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    gateway_up, api_up = ports_open()
    assert gateway_up and api_up

    # second up is idempotent (no crash, same state)
    proc = run_cli("up", "--profile", "mock", "--format", "json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert all(payload["healthy"].values())

    # status reports both healthy
    proc = run_cli("status", "--format", "json")
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["services"]["mock-gateway"]["health_ok"] is True
    assert payload["services"]["mac-api"]["health_ok"] is True
    assert payload["profile"] == "mock"

    # mock banner must be present on the debug page
    import httpx

    page = httpx.get("http://127.0.0.1:8080/", timeout=5).text
    assert "MOCK" in page and "mock" in page

    # down leaves nothing behind
    proc = run_cli("down", "--format", "json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ports_free"]["gateway_port"] and payload["ports_free"]["mac_port"]
    assert payload["leaked_processes"] == []
    time.sleep(0.3)
    gateway_up, api_up = ports_open()
    assert not gateway_up and not api_up


def test_up_rejects_unimplemented_profiles():
    proc = run_cli("up", "--profile", "robot-live", "--format", "json")
    assert proc.returncode == 4  # not implemented, owning phase reported
    payload = json.loads(proc.stdout)
    assert payload["phase"] == "P1"


def test_cli_exit_code_2_for_missing_config_file():
    proc = run_cli("config", "validate", "--file", "/tmp/does-not-exist-runtime.json")
    assert proc.returncode == 2
