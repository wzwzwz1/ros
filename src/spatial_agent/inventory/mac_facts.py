"""Mac-side read-only inventory (P0-ENV mac part).

Collects platform, resource, dependency, clock and network facts without
modifying anything. Network checks are single-attempt with short timeouts and
never scan for hosts.
"""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from spatial_agent.logging_utils import sha256_json


def _run(cmd: list[str], timeout_s: float = 10) -> dict:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
        return {"cmd": cmd, "returncode": result.returncode, "stdout": result.stdout.strip(),
                "stderr": result.stderr.strip()[:2000]}
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return {"cmd": cmd, "returncode": None, "error": f"{type(exc).__name__}: {exc}"}


def _tcp_reachable(host: str, port: int, timeout_s: float = 2.0) -> dict:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return {"host": host, "port": port, "reachable": True}
    except OSError as exc:
        return {"host": host, "port": port, "reachable": False, "error": f"{type(exc).__name__}"}


def _tls_reachable(url: str, timeout_s: float = 5.0) -> dict:
    """DNS + TCP + TLS handshake only. No credentials are sent or required."""
    import ssl

    parsed = urlparse(url)
    host, port = parsed.hostname, parsed.port or 443
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout_s) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                cert = tls.getpeercert()
        subject = None
        if cert:
            # subject looks like ((('commonName', 'host'),), ...) — flatten pairs
            pairs = [pair for rdn in cert.get("subject", ()) for pair in rdn]
            subject = {str(k): str(v) for k, v in pairs}
        return {"url": url, "tls_ok": True, "subject": subject}
    except OSError as exc:
        return {"url": url, "tls_ok": False, "error": f"{type(exc).__name__}"}


def _locked_dependency_versions(python_exe: str) -> dict:
    result = _run([python_exe, "-m", "pip", "list", "--format=freeze"], timeout_s=30)
    versions = {}
    if result.get("returncode") == 0:
        for line in result["stdout"].splitlines():
            if "==" in line:
                name, ver = line.split("==", 1)
                versions[name.strip().lower()] = ver.strip()
    return versions


def collect_mac_inventory(repo_root: Path, *, robot_host: str | None = None,
                          deepseek_base_url: str = "https://api.deepseek.com") -> dict:
    mem_bytes: int | None = None
    if sys.platform == "darwin":
        try:
            mem_bytes = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout.strip())
        except (ValueError, OSError):
            mem_bytes = None
    disk = shutil.disk_usage(repo_root)
    python_exe = str(repo_root / ".venv" / "bin" / "python") if (repo_root / ".venv" / "bin" / "python").exists() else sys.executable

    network: dict = {"interfaces": []}
    if sys.platform == "darwin":
        iface_list = _run(["ifconfig", "-l"], timeout_s=5)
        network["interfaces"] = iface_list.get("stdout", "").split()
    network["deepseek_tls"] = _tls_reachable(deepseek_base_url)
    if robot_host:
        network["robot_ssh_tcp"] = _tcp_reachable(robot_host, 22)
    else:
        network["robot_ssh_tcp"] = {"host": None, "reachable": None, "note": "no robot host configured"}

    utc_now = datetime.now(UTC)
    return {
        "kind": "mac_inventory",
        "collected_at_utc": utc_now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "mac_version": _run(["sw_vers", "-productVersion"]).get("stdout") if sys.platform == "darwin" else None,
        },
        "resources": {
            "memory_total_bytes": mem_bytes,
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
        },
        "python": {
            "venv_python": python_exe,
            "version": platform.python_version(),
            "locked_dependencies": _locked_dependency_versions(python_exe),
        },
        "tools": {
            "uv": _run(["uv", "--version"]).get("stdout"),
            "git": _run(["git", "--version"]).get("stdout"),
        },
        "clock": {
            "utc_now": utc_now.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "monotonic_available": True,
        },
        "network": network,
        "config_sha256_placeholder": None,
        "hash_of_this_document": None,
    }


def finalize_inventory_hash(inventory: dict) -> dict:
    inventory = dict(inventory)
    inventory.pop("hash_of_this_document", None)
    inventory["hash_of_this_document"] = sha256_json(inventory)
    return inventory
