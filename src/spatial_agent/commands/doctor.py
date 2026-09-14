"""`doctor` commands: read-only environment and robot checks.

doctor --target mac: local hardware/deps/network facts (never modifies).
doctor --target robot --read-only: SSH read-only inventory; unreachable robot
is a BLOCKED result with the attempt saved as evidence (deployment-runbook §3).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from spatial_agent import __version__
from spatial_agent.config.validation import validate_config_file
from spatial_agent.inventory.mac_facts import collect_mac_inventory, finalize_inventory_hash
from spatial_agent.inventory.robot_ssh import collect_robot_inventory
from spatial_agent.inventory.unknowns import build_unknowns_register
from spatial_agent.logging_utils import EventLogger, now_utc_iso


def _write_inventory_run(repo_root: Path, payload: dict) -> Path:
    from spatial_agent.reporting.report import new_run_id

    run_id = new_run_id("INV")
    run_dir = repo_root / "artifacts" / "inventory" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "inventory.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
    )
    return run_dir


def doctor_mac(repo_root: Path, logger: EventLogger) -> tuple[int, dict]:
    config_report = None
    config_path = repo_root / "configs" / "local" / "runtime.json"
    robot_host = None
    deepseek_url = "https://api.deepseek.com"
    if config_path.exists():
        config_report = validate_config_file(config_path)
        if config_report.config:
            robot_host = config_report.config.robot.ssh_host
            if config_report.config.planner.base_url:
                deepseek_url = config_report.config.planner.base_url

    inventory = collect_mac_inventory(repo_root, robot_host=robot_host, deepseek_base_url=deepseek_url)
    inventory["local_runtime_config"] = config_report.as_dict() if config_report else None
    inventory = finalize_inventory_hash(inventory)
    run_dir = _write_inventory_run(repo_root, inventory)
    logger.emit("doctor_mac_done", inventory_run=str(run_dir))

    checks_ok = True
    platform = inventory["platform"]
    if platform["system"] != "Darwin":
        checks_ok = False
    if inventory["resources"]["disk_free_bytes"] < 5 * (1 << 30):
        checks_ok = False  # first-version storage budget headroom for artifacts
    exit_code = 0 if checks_ok else 1
    return exit_code, {"ok": checks_ok, "inventory": inventory, "inventory_run": str(run_dir)}


def doctor_robot(repo_root: Path, logger: EventLogger, *, host: str | None, user: str | None) -> tuple[int, dict]:
    config_path = repo_root / "configs" / "local" / "runtime.json"
    if not host or not user:
        if config_path.exists():
            report = validate_config_file(config_path)
            if report.config:
                host = host or report.config.robot.ssh_host
                user = user or report.config.robot.ssh_user
    if not host or not user:
        return 2, {
            "ok": False,
            "error": "no robot target: pass --host/--user or configure robot.ssh_host/ssh_user",
        }

    inventory = collect_robot_inventory(host, user)
    unknowns = build_unknowns_register()
    payload = {"mac_side": {"collected_at_utc": now_utc_iso(), "version": __version__}, "robot": inventory,
               "unknowns": unknowns}
    run_dir = _write_inventory_run(repo_root, payload)
    logger.emit("doctor_robot_done", reachable=inventory["reachable"], status=inventory["status"])

    if not inventory["reachable"]:
        return 3, {"ok": False, "status": "BLOCKED", "inventory": inventory, "inventory_run": str(run_dir),
                   "blocker": inventory["blocker"]}
    failed = [c["name"] for c in inventory["checks"] if c.get("returncode") not in (0, None)]
    result = {"ok": True, "status": "COLLECTED", "inventory": inventory, "inventory_run": str(run_dir),
              "checks_with_errors": failed}
    return 0, result
