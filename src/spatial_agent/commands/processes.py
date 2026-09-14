"""Process lifecycle: `up --profile mock`, `status`, `down`.

- `up` starts only the mock profile in P0 (gateway + Mac app, both loopback).
  Other profiles are NOT_IMPLEMENTED (exit 4, phase P1).
- `down` stops exactly the processes this tool started (recorded in pid files),
  waits for termination, and verifies ports are free — it never touches other
  processes ("不清理他人节点").
- Everything is idempotent: up while running is a no-op, down when down is a
  no-op. P0-BOOT depends on this.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from spatial_agent import __version__
from spatial_agent.config.validation import validate_config_file
from spatial_agent.logging_utils import EventLogger, now_utc_iso

RUN_DIR_NAME = "artifacts/run"
SERVICES = {
    "mock-gateway": {
        "module": "spatial_agent.gateway.mock.server",
        "health_path": "/health",
        "env_token": True,
    },
    "mac-api": {
        "module": "spatial_agent.api.server",
        "health_path": "/health",
        "env_token": False,
    },
}


def _run_dir(repo_root: Path) -> Path:
    path = repo_root / RUN_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pid_file(run_dir: Path, service: str) -> Path:
    return run_dir / f"{service}.pid"


def _read_pid(run_dir: Path, service: str) -> int | None:
    f = _pid_file(run_dir, service)
    if not f.exists():
        return None
    try:
        return int(f.read_text().strip())
    except ValueError:
        return None


def _alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _port_of(url: str) -> int:
    return urlparse(url).port or (443 if urlparse(url).scheme == "https" else 80)


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def up_mock(repo_root: Path, logger: EventLogger, profile: str) -> tuple[int, dict]:
    if profile != "mock":
        return 4, {"ok": False, "error": f"profile {profile!r} is not implemented yet", "phase": "P1",
                  "implemented_phases": ["mock"]}

    config_path = repo_root / "configs" / "local" / "runtime.json"
    if not config_path.exists():
        from spatial_agent.commands.bootstrap import generate_local_config

        generate_local_config(repo_root)
    report = validate_config_file(config_path)
    if not report.valid or report.config is None:
        return 2, {"ok": False, "error": "runtime config invalid", "errors": report.errors}
    config = report.config
    if config.profile.value != "mock":
        return 2, {"ok": False, "error": f"up --profile mock requires a mock runtime config (got {config.profile.value})"}

    run_dir = _run_dir(repo_root)
    venv_python = repo_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return 3, {"ok": False, "error": ".venv missing; run `scripts/project bootstrap --target mac` first"}

    gateway_port = _port_of(config.robot.gateway_url)
    token = os.environ.get(config.robot.gateway_token_env, "mock-token")
    started: dict = {}

    specs = {
        "mock-gateway": {
            "argv": [str(venv_python), "-m", "spatial_agent.gateway.mock.server",
                     "--host", "127.0.0.1", "--port", str(gateway_port), "--token", token,
                     "--events", str(run_dir / "mock-gateway-events.jsonl")],
            "port": gateway_port,
        },
        "mac-api": {
            "argv": [str(venv_python), "-m", "spatial_agent.api.server",
                     "--config", str(config_path), "--repo-root", str(repo_root)],
            "port": config.mac.listen_port,
        },
    }

    for service, spec in specs.items():
        pid = _read_pid(run_dir, service)
        if _alive(pid) and _port_open(spec["port"]):
            started[service] = {"already_running": True, "pid": pid}
            logger.emit("up_already_running", service=service, pid=pid)
            continue
        log_file = run_dir / f"{service}.log"
        with open(log_file, "ab") as logf:
            proc = subprocess.Popen(
                spec["argv"], stdout=logf, stderr=subprocess.STDOUT,
                cwd=repo_root, start_new_session=True,
                stdin=subprocess.DEVNULL,
            )
        (_pid_file(run_dir, service)).write_text(str(proc.pid))
        started[service] = {"pid": proc.pid, "port": spec["port"], "log": str(log_file)}
        logger.emit("up_started", service=service, pid=proc.pid, port=spec["port"])

    # wait for health
    deadline = time.monotonic() + 20
    healthy = {}
    for service, spec in specs.items():
        ok = False
        while time.monotonic() < deadline:
            if _port_open(spec["port"]):
                ok = True
                break
            time.sleep(0.3)
        healthy[service] = ok
        if not ok:
            logger.emit("up_health_failed", service=service)
    all_ok = all(healthy.values())
    logger.emit("up_done", ok=all_ok)
    status_code = 0 if all_ok else 1
    return status_code, {
        "ok": all_ok,
        "profile": "mock",
        "services": started,
        "healthy": healthy,
        "run_dir": str(run_dir),
        "note": "mock profile: no real robot network access; all data is simulated (source=mock)",
    }


def status(repo_root: Path, logger: EventLogger) -> tuple[int, dict]:
    run_dir = _run_dir(repo_root)
    config_path = repo_root / "configs" / "local" / "runtime.json"
    services = {}
    ports = {}
    if config_path.exists():
        report = validate_config_file(config_path)
        if report.config:
            ports["mock-gateway"] = _port_of(report.config.robot.gateway_url)
            ports["mac-api"] = report.config.mac.listen_port
    for service in SERVICES:
        pid = _read_pid(run_dir, service)
        alive = _alive(pid)
        port = ports.get(service)
        http_ok = None
        if alive and port and _port_open(port):
            http_ok = True
        services[service] = {"pid": pid, "process_alive": alive, "port": port, "port_open": _port_open(port) if port else None,
                             "health_ok": http_ok}
    # leaked-process check: module running but no pid file of ours
    leaked = []
    try:
        pgrep = subprocess.run(["pgrep", "-f", "spatial_agent.gateway.mock.server|spatial_agent.api.server"],
                               capture_output=True, text=True)
        known_pids = {s["pid"] for s in services.values() if s["pid"]}
        leaked = [int(p) for p in pgrep.stdout.split() if p.isdigit() and int(p) not in known_pids]
    except (FileNotFoundError, ValueError):
        pass
    result = {
        "ok": True,
        "version": __version__,
        "profile": report.config.profile.value if config_path.exists() and report.config else None,
        "services": services,
        "leaked_processes": leaked,
        "ts_utc": now_utc_iso(),
    }
    return 0, result


def down(repo_root: Path, logger: EventLogger) -> tuple[int, dict]:
    run_dir = _run_dir(repo_root)
    stopped = {}
    for service in SERVICES:
        pid = _read_pid(run_dir, service)
        if pid is None:
            stopped[service] = {"was_running": False}
            continue
        if _alive(pid):
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + 10
            while _alive(pid) and time.monotonic() < deadline:
                time.sleep(0.2)
            if _alive(pid):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                stopped[service] = {"was_running": True, "sigkill": True}
            else:
                stopped[service] = {"was_running": True, "stopped": True}
            logger.emit("down_stopped", service=service, pid=pid)
        else:
            stopped[service] = {"was_running": False, "stale_pidfile": True}
        try:
            _pid_file(run_dir, service).unlink()
        except FileNotFoundError:
            pass

    # verify: ports free, no leaked processes of ours
    time.sleep(0.4)
    config_path = repo_root / "configs" / "local" / "runtime.json"
    ports_free = {}
    if config_path.exists():
        report = validate_config_file(config_path)
        if report.config:
            ports_free["gateway_port"] = not _port_open(_port_of(report.config.robot.gateway_url))
            ports_free["mac_port"] = not _port_open(report.config.mac.listen_port)
    result_status = status(repo_root, logger)[1]
    ok = all(ports_free.values()) and not result_status["leaked_processes"]
    logger.emit("down_done", ok=ok)
    return (0 if ok else 1), {
        "ok": ok,
        "stopped": stopped,
        "ports_free": ports_free,
        "leaked_processes": result_status["leaked_processes"],
    }
