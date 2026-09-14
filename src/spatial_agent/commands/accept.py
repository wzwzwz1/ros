"""`accept --phase P0`: frozen gate execution with evidence (acceptance.md §4).

Modes:
- `--mode mock` executes P0-BOOT / P0-ISOLATION / P0-CONFIG / P0-REPORT. The
  returned exit code covers exactly this requested scope; P0-ENV (hardware
  read-only) is reported as out-of-scope and the aggregated phase_gate_status
  stays BLOCKED until hardware evidence exists.
- `--mode hardware` executes P0-ENV: Mac local inventory plus a read-only robot
  inventory attempt. Unreachable robot => BLOCKED (exit 3), never a fake pass.

Trials are appended to trials.jsonl and never rewritten; the suite manifest is
frozen before execution with the expected outcome of every trial.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from spatial_agent import __version__
from spatial_agent.config.validation import validate_config
from spatial_agent.gateway.client import GatewayClient, MockIsolationError
from spatial_agent.inventory.mac_facts import collect_mac_inventory, finalize_inventory_hash
from spatial_agent.inventory.robot_ssh import collect_robot_inventory
from spatial_agent.logging_utils import EventLogger, now_utc_iso, sha256_json
from spatial_agent.reporting.completeness import check_report
from spatial_agent.reporting.report import (
    append_trial,
    new_run_id,
    redact_config,
    write_evidence_manifest,
    write_summary_md,
)
from spatial_agent.versioning import get_code_version

P0_MOCK_CASES = ("P0-BOOT", "P0-ISOLATION", "P0-CONFIG", "P0-REPORT")
P0_REQUIRED_CASES = ("P0-ENV", "P0-BOOT", "P0-ISOLATION", "P0-CONFIG", "P0-REPORT")


def _cli(repo_root: Path, *args: str, timeout_s: float = 300) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "spatial_agent.cli", *args],
        cwd=repo_root, capture_output=True, text=True, timeout=timeout_s,
    )
    return proc.returncode, (proc.stdout + "\n" + proc.stderr).strip()


# ----------------------------------------------------------------- P0-BOOT
def gate_boot(run_dir: Path, repo_root: Path, logger: EventLogger) -> dict:
    trials = []
    for cycle in (1, 2):
        trial = {"trial_id": f"P0-BOOT-cycle{cycle}", "case_id": "P0-BOOT",
                 "expected_outcome": "bootstrap+up+down succeed, no leaked processes, reproducible"}
        steps = {}
        ok = True
        for cmd in (["bootstrap", "--target", "mac"], ["up", "--profile", "mock"], ["status"], ["down"]):
            code, out = _cli(repo_root, *cmd, timeout_s=180)
            steps[" ".join(cmd)] = code
            logger.emit("boot_gate_step", cycle=cycle, cmd=" ".join(cmd), exit_code=code)
            if code != 0:
                ok = False
                trial["failure"] = f"{' '.join(cmd)} exited {code}: {out[-400:]}"
                break
        if ok:
            code, out = _cli(repo_root, "down")
            status_json = {}
            try:
                status_json = json.loads(out[out.index("{"):]) if "{" in out else {}
            except (ValueError, IndexError):
                pass
            leaked = status_json.get("leaked_processes", [])
            if leaked:
                ok = False
                trial["failure"] = f"leaked processes after down: {leaked}"
        trial["ok"] = ok
        trial["steps_exit_codes"] = steps
        append_trial(run_dir, trial)
        trials.append(trial)
        logger.emit("boot_gate_trial", cycle=cycle, ok=ok)
    passed = sum(1 for t in trials if t["ok"])
    status = "PASS" if passed == 2 else ("FAIL" if passed > 0 else "FAIL")
    return {
        "case_id": "P0-BOOT", "mode": "mock", "required": True, "motion": False,
        "status": status, "trial_count": 2, "passed_trials": passed,
        "failed_trials": 2 - passed,
        "metrics": [{"name": "idempotent_cycles_passed", "value": passed, "kind": "count"},
                    {"name": "required_cycles", "value": 2, "kind": "count"}],
        "evidence_paths": ["trials.jsonl", "events.jsonl"],
        "reason": "bootstrap/up/status/down executed twice; both cycles must succeed with no leaked processes",
    }


# ------------------------------------------------------------- P0-ISOLATION
ISOLATION_CASES = [
    ("robot-lan-ip", {"robot": {"gateway_url": "http://192.168.0.100:8765"}}),
    ("robot-hostname", {"robot": {"gateway_url": "http://wheeltec.local:8765"}}),
    ("other-lan", {"robot": {"gateway_url": "http://10.0.0.5:8765"}}),
    ("public-endpoint", {"robot": {"gateway_url": "https://api.deepseek.com"}}),
    ("robot-ip-with-motion", {"robot": {"gateway_url": "http://192.168.0.100:8765"}, "motion": {"enabled": True}}),
]


def _base_config() -> dict:
    template = Path(__file__).resolve().parents[3] / "docs" / "templates" / "runtime.example.json"
    raw = json.loads(template.read_text(encoding="utf-8"))
    raw.pop("example_only", None)
    raw["profile"] = "mock"
    return raw


def gate_isolation(run_dir: Path, logger: EventLogger) -> dict:
    trials = []
    for name, overrides in ISOLATION_CASES:
        raw = _base_config()
        for section, values in overrides.items():
            raw.setdefault(section, {}).update(values)
        report = validate_config(raw)
        rejected_by_validation = not report.valid
        client_rejected = False
        try:
            GatewayClient("mock", raw["robot"]["gateway_url"], token="mock-token")
        except MockIsolationError:
            client_rejected = True
        ok = rejected_by_validation and client_rejected
        trial = {
            "trial_id": f"P0-ISOLATION-{name}", "case_id": "P0-ISOLATION",
            "expected_outcome": "config rejected AND client construction refused",
            "ok": ok,
            "rejected_by_validation": rejected_by_validation,
            "client_rejected": client_rejected,
            "validation_errors": report.errors if not rejected_by_validation else None,
        }
        append_trial(run_dir, trial)
        trials.append(trial)
        logger.emit("isolation_trial", name=name, ok=ok)
    passed = sum(1 for t in trials if t["ok"])
    return {
        "case_id": "P0-ISOLATION", "mode": "mock", "required": True, "motion": False,
        "status": "PASS" if passed == len(trials) else "FAIL",
        "trial_count": len(trials), "passed_trials": passed, "failed_trials": len(trials) - passed,
        "metrics": [{"name": "hardware_target_injections_rejected", "value": passed, "kind": "count"},
                    {"name": "injections_total", "value": len(trials), "kind": "count"}],
        "evidence_paths": ["trials.jsonl"],
        "reason": "5 hardware-target configurations injected into the mock profile; all must be refused by "
                  "config validation and by the client isolation guard",
    }


# ---------------------------------------------------------------- P0-CONFIG
def _config_cases() -> list[dict]:
    base = _base_config()
    cases: list[dict] = []
    add = cases.append
    add({"name": "invalid-profile", "raw": {**base, "profile": "real"}, "expect": "reject"})
    add({"name": "unknown-root-field", "raw": {**base, "not_a_field": 1}, "expect": "reject"})
    add({"name": "nan-speed", "raw": {**base, "motion": {**base["motion"], "max_linear_speed_mps": float("nan")}},
         "expect": "reject"})
    add({"name": "speed-over-cap", "raw": {**base, "motion": {**base["motion"], "max_linear_speed_mps": 0.5}},
         "expect": "reject"})
    add({"name": "lease-incoherent", "raw": {**base, "motion": {**base["motion"], "lease_period_ms": 1000, "lease_timeout_ms": 500}},
         "expect": "reject"})
    add({"name": "resume-motion-after-restart", "raw": {**base, "tasks": {**base["tasks"], "resume_motion_after_restart": True}},
         "expect": "reject"})
    add({"name": "memory-without-map-scoping", "raw": {**base, "memory": {**base["memory"], "require_map_id": False}},
         "expect": "reject"})
    add({"name": "hardware-motion-without-session", "raw": {**base, "profile": "hardware",
                                                            "motion": {**base["motion"], "enabled": True, "session_file": None}},
         "expect": "reject"})
    add({"name": "replay-with-motion", "raw": {**base, "profile": "replay", "motion": {**base["motion"], "enabled": True}},
         "expect": "reject"})
    add({"name": "mock-with-hardware-gateway", "raw": {**base, "robot": {**base["robot"], "gateway_url": "http://192.168.0.100:8765"}},
         "expect": "reject"})
    add({"name": "perception-without-calibration", "raw": {**base, "perception": {**base["perception"], "enabled": True, "calibration_id": None}},
         "expect": "degrade:perception"})
    add({"name": "planner-without-model", "raw": {**base, "planner": {**base["planner"], "enabled": True, "model_id": None}},
         "expect": "degrade:planner"})
    add({"name": "planner-without-api-key", "raw": {**base, "planner": {**base["planner"], "enabled": True, "model_id": "deepseek-chat"}},
         "expect": "degrade:planner", "env": {"DEEPSEEK_API_KEY": ""}})
    add({"name": "voice-enabled", "raw": {**base, "voice": {**base["voice"], "enabled": True}}, "expect": "degrade:voice"})
    add({"name": "template-config", "raw": json.loads(
            (Path(__file__).resolve().parents[3] / "docs" / "templates" / "runtime.example.json").read_text(encoding="utf-8")),
         "expect": "template"})
    return cases


PLANTED_SECRET = "dummy-secret-value-do-not-leak-12345"


def gate_config(run_dir: Path, logger: EventLogger) -> dict:
    trials = []
    for case in _config_cases():
        env = {"PATH": os.environ.get("PATH", ""), "DEEPSEEK_API_KEY": PLANTED_SECRET}
        env.update(case.get("env", {}))
        report = validate_config(case["raw"], environment=env)
        report_json = json.dumps(report.as_dict(), ensure_ascii=False)
        expect = case["expect"]
        if expect == "reject":
            ok = not report.valid and bool(report.errors)
        elif expect == "template":
            ok = report.valid and report.config is not None and not report.as_dict()["usable_for_run"]
        else:
            cap = expect.split(":", 1)[1]
            caps = {c["name"]: c for c in report.capabilities}
            ok = report.valid and caps.get(cap, {}).get("state") in ("degraded", "unavailable")
        secret_leaked = PLANTED_SECRET in report_json
        ok = ok and not secret_leaked
        trial = {
            "trial_id": f"P0-CONFIG-{case['name']}", "case_id": "P0-CONFIG",
            "expected_outcome": expect, "ok": ok,
            "valid": report.valid, "errors": report.errors,
            "capabilities": {c["name"]: c["state"] for c in report.capabilities},
            "secret_leaked": secret_leaked,
        }
        append_trial(run_dir, trial)
        trials.append(trial)
        logger.emit("config_trial", name=case["name"], ok=ok)
    passed = sum(1 for t in trials if t["ok"])
    return {
        "case_id": "P0-CONFIG", "mode": "mock", "required": True, "motion": False,
        "status": "PASS" if passed == len(trials) else "FAIL",
        "trial_count": len(trials), "passed_trials": passed, "failed_trials": len(trials) - passed,
        "metrics": [{"name": "config_samples", "value": len(trials), "kind": "count"},
                    {"name": "samples_correctly_rejected_or_degraded", "value": passed, "kind": "count"}],
        "evidence_paths": ["trials.jsonl"],
        "reason": ">=10 malformed/prerequisite-missing config samples; each must be rejected or degraded with an "
                  "explicit reason, never silently filled; planted secret must not leak into output",
    }


# ---------------------------------------------------------------- P0-REPORT
def _malformed_reports() -> list[dict]:
    def base_report():
        return {
            "schema_version": "1.0", "run_id": "run-example", "phase": "P0",
            "requested_modes": ["mock"], "run_status": "PASS", "phase_gate_status": "PASS",
            "blockers": [], "missing_required_cases": [], "cases": [],
        }

    def case(case_id="P0-BOOT", mode="mock", status="PASS", trial_count=2, passed=2, failed=0, evidence=None, required=True):
        return {"case_id": case_id, "mode": mode, "status": status, "required": required,
                "trial_count": trial_count, "passed_trials": passed, "failed_trials": failed,
                "evidence_paths": evidence if evidence is not None else ["trials.jsonl"], "reason": "ok"}

    cases = []
    add = cases.append
    r = base_report(); r["cases"] = [case(trial_count=0, passed=0), case("P0-ENV", "hardware", "BLOCKED", 0, 0, 0, [], reason="robot offline"), case("P0-ISOLATION"), case("P0-CONFIG"), case("P0-REPORT")]
    add({"name": "pass-with-zero-trials", "report": r})
    r = base_report(); r["cases"] = [case(evidence=[]), case("P0-ENV", "hardware", "BLOCKED", 0, 0, 0, [], reason="robot offline"), case("P0-ISOLATION"), case("P0-CONFIG"), case("P0-REPORT")]
    add({"name": "pass-without-evidence", "report": r})
    r = base_report(); r["cases"] = [case(), case("P0-ENV", "hardware", "BLOCKED", 0, 0, 0, [], reason="robot offline"), case("P0-ISOLATION"), case("P0-CONFIG"), case("P0-REPORT")]
    add({"name": "gate-pass-with-blocked-case", "report": r})
    r = base_report(); r["requested_modes"] = ["mock"]
    r["cases"] = [case(), case(mode="hardware", trial_count=1, passed=1), case("P0-ISOLATION"), case("P0-CONFIG"), case("P0-REPORT")]
    add({"name": "mode-not-requested", "report": r})
    r = base_report(); r["cases"] = [case(), case("P0-ISOLATION"), case("P0-CONFIG"), case("P0-REPORT")]
    r["missing_required_cases"] = ["P0-ENV"]
    add({"name": "missing-env-case", "report": r})
    r = base_report(); r["cases"] = [case(passed=1, failed=1), case("P0-ENV", "hardware", "BLOCKED", 0, 0, 0, [], reason="robot offline"), case("P0-ISOLATION"), case("P0-CONFIG"), case("P0-REPORT")]
    add({"name": "pass-with-failures", "report": r})
    # a legitimate FAIL report must remain generable (coherent, not PASS)
    r = base_report(); r["run_status"] = "FAIL"; r["phase_gate_status"] = "FAIL"
    r["cases"] = [case(status="FAIL", passed=1, failed=1, reason="injected failure documented"), case("P0-ENV", "hardware", "BLOCKED", 0, 0, 0, [], reason="robot offline"), case("P0-ISOLATION"), case("P0-CONFIG"), case("P0-REPORT")]
    add({"name": "legitimate-fail-is-coherent", "report": r, "expect_coherent": True})
    return cases


def gate_report(run_dir: Path, logger: EventLogger) -> dict:
    trials = []
    for case in _malformed_reports():
        problems = check_report(case["report"])
        expect_coherent = case.get("expect_coherent", False)
        ok = (not problems) if expect_coherent else bool(problems)
        trial = {
            "trial_id": f"P0-REPORT-{case['name']}", "case_id": "P0-REPORT",
            "expected_outcome": "coherent" if expect_coherent else "must-not-PASS / violations detected",
            "ok": ok, "violations": problems,
        }
        append_trial(run_dir, trial)
        trials.append(trial)
        logger.emit("report_trial", name=case["name"], ok=ok)
    passed = sum(1 for t in trials if t["ok"])
    return {
        "case_id": "P0-REPORT", "mode": "mock", "required": True, "motion": False,
        "status": "PASS" if passed == len(trials) else "FAIL",
        "trial_count": len(trials), "passed_trials": passed, "failed_trials": len(trials) - passed,
        "metrics": [{"name": "report_samples", "value": len(trials), "kind": "count"}],
        "evidence_paths": ["trials.jsonl"],
        "reason": "malformed reports (missing evidence/trials, gate-pass with blockers, mode confusion) must all be "
                  "rejected; a legitimate FAIL/BLOCKED report must remain generable",
    }


# ------------------------------------------------------------------- P0-ENV
def gate_env(run_dir: Path, repo_root: Path, logger: EventLogger, *, attempt_robot: bool) -> dict:
    mac_inventory = finalize_inventory_hash(
        collect_mac_inventory(repo_root, deepseek_base_url="https://api.deepseek.com")
    )
    (run_dir / "environment.json").write_text(json.dumps(mac_inventory, ensure_ascii=False, indent=2), encoding="utf-8")

    robot_result = None
    if attempt_robot:
        host = user = None
        config_path = repo_root / "configs" / "local" / "runtime.json"
        if config_path.exists():
            cr = validate_config_file(config_path)
            if cr.config:
                host, user = cr.config.robot.ssh_host, cr.config.robot.ssh_user
        if host and user:
            robot_result = collect_robot_inventory(host, user)
        else:
            robot_result = {"kind": "robot_inventory_readonly", "status": "BLOCKED",
                            "blocker": "no robot ssh target configured in runtime config", "reachable": False}
        (run_dir / "robot-inventory.json").write_text(json.dumps(robot_result, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.emit("env_gate_robot_attempt", reachable=robot_result.get("reachable"))

    evidence = ["environment.json"]
    if robot_result is not None:
        evidence.append("robot-inventory.json")

    if not attempt_robot:
        status = "BLOCKED"
        reason = ("P0-ENV requires hardware read-only evidence (Mac + robot). This run requested mode=mock only; "
                  "robot inventory was not attempted. Re-run `accept --phase P0 --mode hardware` with the robot online.")
    elif robot_result is None or not robot_result.get("reachable"):
        status = "BLOCKED"
        reason = (f"robot read-only inventory unavailable: {(robot_result or {}).get('blocker', 'not attempted')}. "
                  "Mac local inventory was collected. Bring the robot online with key-based SSH and re-run "
                  "`accept --phase P0 --mode hardware`.")
    else:
        status = "PASS"
        reason = "Mac local inventory and robot read-only inventory both collected."

    append_trial(run_dir, {
        "trial_id": "P0-ENV-inventory", "case_id": "P0-ENV",
        "expected_outcome": "Mac inventory + robot read-only inventory with identity, versions, disk, interfaces",
        "ok": status == "PASS", "status": status,
        "mac_inventory_hash": mac_inventory.get("hash_of_this_document"),
        "robot_reachable": (robot_result or {}).get("reachable"),
    })
    return {
        "case_id": "P0-ENV", "mode": "hardware", "required": True, "motion": False,
        "status": status, "trial_count": 1,
        "passed_trials": 1 if status == "PASS" else 0,
        "failed_trials": 0,
        "evidence_paths": evidence,
        "reason": reason,
    }


# ---------------------------------------------------------------- main entry
def accept_p0(repo_root: Path, logger: EventLogger, *, mode: str) -> tuple[int, dict]:
    if mode not in ("mock", "hardware"):
        return 2, {"ok": False, "error": f"unknown mode {mode!r} for P0 (use mock|hardware)"}
    if mode == "hardware":
        return _accept_p0_hardware(repo_root, logger)
    return _accept_p0_mock(repo_root, logger)


def _accept_p0_mock(repo_root: Path, logger: EventLogger) -> tuple[int, dict]:
    started = now_utc_iso()
    run_id = new_run_id("P0")
    run_dir = repo_root / "artifacts" / "acceptance" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.emit("accept_start", run_id=run_id, mode="mock")

    code_version = get_code_version(repo_root).as_dict()
    config_path = repo_root / "configs" / "local" / "runtime.json"
    config_raw = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else None
    (run_dir / "config.redacted.json").write_text(
        json.dumps(redact_config(config_raw) if config_raw else {}, ensure_ascii=False, indent=2), encoding="utf-8")

    suite_manifest = {
        "schema_version": "1.0",
        "suite_id": f"p0-mock-{run_id}",
        "phase": "P0",
        "primary_mode": "mock",
        "dependencies": [],
        "frozen_at_utc": started,
        "code_release": code_version,
        "config_sha256": sha256_json(config_raw) if config_raw else None,
        "random_seed": 0,
        "case_ids": list(P0_MOCK_CASES),
        "thresholds": {
            "boot_cycles_required": 2,
            "isolation_injections_required": 5,
            "minimum_config_samples": 10,
            "minimum_report_samples": 5,
            "behavior_gates": "all trials must pass (no statistical tolerance in P0)",
        },
        "trials": [
            {"trial_id": "P0-BOOT-cycle1", "case_id": "P0-BOOT", "expected_outcome": "pass"},
            {"trial_id": "P0-BOOT-cycle2", "case_id": "P0-BOOT", "expected_outcome": "pass"},
            *[{"trial_id": f"P0-ISOLATION-{name}", "case_id": "P0-ISOLATION", "expected_outcome": "reject"}
              for name, _ in ISOLATION_CASES],
            *[{"trial_id": f"P0-CONFIG-{c['name']}", "case_id": "P0-CONFIG",
               "expected_outcome": c["expect"]} for c in _config_cases()],
            *[{"trial_id": f"P0-REPORT-{c['name']}", "case_id": "P0-REPORT",
               "expected_outcome": "coherent" if c.get("expect_coherent") else "violation"} for c in _malformed_reports()],
        ],
        "trial_required_fields": ["trial_id", "case_id", "expected_outcome"],
        "notes": "Frozen before execution. P0-ENV (hardware read-only) is out of mock scope and reported separately.",
    }
    (run_dir / "suite-manifest.json").write_text(json.dumps(suite_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    cases = [
        gate_boot(run_dir, repo_root, logger),
        gate_isolation(run_dir, logger),
        gate_config(run_dir, logger),
        gate_report(run_dir, logger),
        gate_env(run_dir, repo_root, logger, attempt_robot=False),
    ]
    finished = now_utc_iso()
    run_status = "PASS" if all(c["status"] == "PASS" for c in cases if c["mode"] == "mock") else (
        "FAIL" if any(c["status"] == "FAIL" for c in cases if c["mode"] == "mock") else "BLOCKED")
    env_case = next(c for c in cases if c["case_id"] == "P0-ENV")
    blockers = []
    if env_case["status"] != "PASS":
        blockers.append(f"P0-ENV hardware read-only evidence missing: {env_case['reason']}")
    gate_status = "PASS" if (run_status == "PASS" and not blockers) else ("FAIL" if run_status == "FAIL" else "BLOCKED")

    report = {
        "schema_version": "1.0",
        "run_id": run_id,
        "phase": "P0",
        "requested_modes": ["mock"],
        "run_status": run_status,
        "phase_gate_status": gate_status,
        "started_at_utc": started,
        "finished_at_utc": finished,
        "code": code_version,
        "deployment": {"mac_release": f"local-mock-{__version__}", "robot_release": None},
        "identity": {"robot_id": None, "map_id": None, "calibration_id": None, "session_id": None},
        "artifacts": {
            "suite_manifest": "suite-manifest.json",
            "environment": "environment.json",
            "config_redacted": "config.redacted.json",
            "trials": "trials.jsonl",
            "events": "events.jsonl",
            "evidence_manifest": "evidence.sha256",
        },
        "cases": cases,
        "linked_prior_runs": [],
        "missing_required_cases": [],
        "blockers": blockers,
        "next_actions": [
            "Run `./scripts/project accept --phase P0 --mode hardware` with the robot online and key-based SSH "
            "configured to collect P0-ENV hardware read-only evidence; only then can phase_gate_status become PASS.",
        ],
        "operator_measurements": [],
        "api_usage": {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost": None, "currency": None,
                      "price_checked_at": None},
    }
    violations = check_report(report)
    report["self_check_violations"] = violations
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_summary_md(run_dir, report)
    write_evidence_manifest(run_dir)
    exit_code = 0 if run_status == "PASS" and not violations else 1
    logger.emit("accept_done", run_id=run_id, run_status=run_status, phase_gate_status=gate_status)
    return exit_code, {"ok": exit_code == 0, "run_id": run_id, "run_dir": str(run_dir),
                       "run_status": run_status, "phase_gate_status": gate_status,
                       "self_check_violations": violations}


def _accept_p0_hardware(repo_root: Path, logger: EventLogger) -> tuple[int, dict]:
    started = now_utc_iso()
    run_id = new_run_id("P0")
    run_dir = repo_root / "artifacts" / "acceptance" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    logger.emit("accept_start", run_id=run_id, mode="hardware")
    code_version = get_code_version(repo_root).as_dict()
    env_case = gate_env(run_dir, repo_root, logger, attempt_robot=True)
    finished = now_utc_iso()
    status = env_case["status"]
    report = {
        "schema_version": "1.0",
        "run_id": run_id,
        "phase": "P0",
        "requested_modes": ["hardware"],
        "run_status": status,
        "phase_gate_status": status,
        "started_at_utc": started,
        "finished_at_utc": finished,
        "code": code_version,
        "deployment": {"mac_release": f"local-readonly-{__version__}", "robot_release": None},
        "identity": {"robot_id": None, "map_id": None, "calibration_id": None, "session_id": None},
        "artifacts": {"environment": "environment.json", "trials": "trials.jsonl", "events": "events.jsonl",
                      "evidence_manifest": "evidence.sha256",
                      "robot_inventory": "robot-inventory.json" if (run_dir / "robot-inventory.json").exists() else None},
        "cases": [env_case],
        "linked_prior_runs": [],
        "missing_required_cases": [c for c in P0_REQUIRED_CASES if c != "P0-ENV"],
        "blockers": [] if status == "PASS" else [env_case["reason"]],
        "next_actions": ["Pair this hardware run with a mock run (`accept --phase P0 --mode mock`) covering "
                         "P0-BOOT/ISOLATION/CONFIG/REPORT; both must pass for phase_gate_status=PASS."],
        "operator_measurements": [],
        "api_usage": {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost": None, "currency": None,
                      "price_checked_at": None},
    }
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_summary_md(run_dir, report)
    write_evidence_manifest(run_dir)
    exit_code = 0 if status == "PASS" else 3
    logger.emit("accept_done", run_id=run_id, run_status=status)
    return exit_code, {"ok": exit_code == 0, "run_id": run_id, "run_dir": str(run_dir),
                       "run_status": status, "phase_gate_status": status, "blockers": report["blockers"]}
