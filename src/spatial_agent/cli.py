"""Unified project CLI: ./scripts/project <command> ...

Exit codes (deployment-runbook.md §1):
  0 = requested operation passed
  1 = executed but failed
  2 = argument/config error
  3 = missing prerequisites
  4 = not implemented (the owning phase is reported)

Every command supports --help; --format json emits exactly one JSON document
on stdout (events go to stderr) for machine consumption.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from spatial_agent import __version__
from spatial_agent.logging_utils import EventLogger

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_ARGS = 2
EXIT_PREREQ = 3
EXIT_NOT_IMPLEMENTED = 4

PHASES = ["P0", "P1", "P2", "P3", "P4", "P5"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _not_implemented(phase: str, what: str) -> tuple[int, dict]:
    return EXIT_NOT_IMPLEMENTED, {
        "ok": False,
        "error": f"{what} is not implemented yet",
        "phase": phase,
        "hint": "see docs/phases and the deployment runbook for the owning phase",
    }


# ------------------------------------------------------------------ handlers
def cmd_bootstrap(args, logger: EventLogger) -> tuple[int, dict]:
    if args.target == "mac":
        from spatial_agent.commands.bootstrap import bootstrap_mac

        evidence = bootstrap_mac(_repo_root(), logger)
        return (EXIT_OK if evidence["ok"] else EXIT_FAILED), evidence
    return _not_implemented("P1", "bootstrap --target robot")


def cmd_doctor(args, logger: EventLogger) -> tuple[int, dict]:
    from spatial_agent.commands.doctor import doctor_mac, doctor_robot

    if args.target == "mac":
        return doctor_mac(_repo_root(), logger)
    if not args.read_only:
        return EXIT_ARGS, {"ok": False, "error": "doctor --target robot requires --read-only in P0"}
    return doctor_robot(_repo_root(), logger, host=args.host, user=args.user)


def cmd_config(args, logger: EventLogger) -> tuple[int, dict]:
    repo_root = _repo_root()
    if args.config_command == "validate":
        from spatial_agent.config.validation import validate_config_file

        path = Path(args.file)
        if not path.exists():
            return EXIT_ARGS, {"ok": False, "error": f"config file not found: {path}"}
        report = validate_config_file(path)
        return (EXIT_OK if report.valid else EXIT_ARGS), report.as_dict()
    if args.config_command == "validate-manifest":
        from spatial_agent.manifests import LEVEL_INVALID, validate_document

        if args.kind not in ("map", "session", "suite", "models-lock"):
            return EXIT_ARGS, {"ok": False, "error": f"unknown manifest kind {args.kind!r}"}
        path = Path(args.file)
        if not path.exists():
            return EXIT_ARGS, {"ok": False, "error": f"manifest file not found: {path}"}
        doc = json.loads(path.read_text(encoding="utf-8"))
        kwargs = {"for_arm": bool(args.for_arm)} if args.kind == "session" else {}
        level, problems = validate_document(args.kind, doc, **kwargs)
        return (EXIT_OK if level != LEVEL_INVALID else EXIT_ARGS), {
            "kind": args.kind, "level": level, "problems": problems, "file": str(path),
        }
    return EXIT_ARGS, {"ok": False, "error": "unknown config subcommand"}


def cmd_test(args, logger: EventLogger) -> tuple[int, dict]:
    import subprocess

    if args.level not in ("unit", "integration", "acceptance"):
        return _not_implemented("P1", f"test --level {args.level}")
    if args.level == "integration" and args.profile != "mock":
        return EXIT_ARGS, {"ok": False, "error": "test --level integration requires --profile mock (P0 has no hardware tests)"}
    repo_root = _repo_root()
    test_dir = repo_root / "tests" / args.level
    if not test_dir.exists():
        return EXIT_ARGS, {"ok": False, "error": f"test directory missing: {test_dir}"}
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_dir), "-q", "--no-header"],
        cwd=repo_root, capture_output=True, text=True, timeout=1800,
    )
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-15:])
    return (EXIT_OK if proc.returncode == 0 else EXIT_FAILED), {
        "ok": proc.returncode == 0,
        "level": args.level,
        "pytest_exit_code": proc.returncode,
        "output_tail": tail,
    }


def cmd_up(args, logger: EventLogger) -> tuple[int, dict]:
    from spatial_agent.commands.processes import up_mock

    return up_mock(_repo_root(), logger, profile=args.profile)


def cmd_status(args, logger: EventLogger) -> tuple[int, dict]:
    from spatial_agent.commands.processes import status

    return status(_repo_root(), logger)


def cmd_down(args, logger: EventLogger) -> tuple[int, dict]:
    from spatial_agent.commands.processes import down

    return down(_repo_root(), logger)


def cmd_accept(args, logger: EventLogger) -> tuple[int, dict]:
    if args.phase != "P0":
        return _not_implemented(args.phase, f"accept --phase {args.phase}")
    from spatial_agent.commands.accept import accept_p0

    return accept_p0(_repo_root(), logger, mode=args.mode)


def cmd_stub(args, logger: EventLogger) -> tuple[int, dict]:
    return _not_implemented(args.phase, args.description)


# -------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scripts/project",
        description="Spatial Agent project CLI (P0: bootstrap/doctor/config/test/up/status/down/accept)",
    )
    parser.add_argument("--version", action="version", version=f"spatial-agent {__version__}")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="output format")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("bootstrap", help="create the reproducible environment (P0: --target mac)")
    p.add_argument("--target", choices=("mac", "robot"), default="mac")
    p.set_defaults(func=cmd_bootstrap)

    p = sub.add_parser("doctor", help="read-only environment checks")
    p.add_argument("--target", choices=("mac", "robot"), default="mac")
    p.add_argument("--read-only", action="store_true", help="required for --target robot")
    p.add_argument("--host", default=None, help="robot SSH host override")
    p.add_argument("--user", default=None, help="robot SSH user override")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("config", help="configuration and manifest validation")
    csub = p.add_subparsers(dest="config_command", required=True)
    v = csub.add_parser("validate", help="validate a runtime config")
    v.add_argument("--file", required=True)
    m = csub.add_parser("validate-manifest", help="validate map/session/suite/models-lock documents")
    m.add_argument("--kind", required=True, choices=("map", "session", "suite", "models-lock"))
    m.add_argument("--file", required=True)
    m.add_argument("--for-arm", action="store_true", help="session: require on-site confirmation facts")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("test", help="run offline tests")
    p.add_argument("--level", choices=("unit", "integration", "acceptance"), required=True)
    p.add_argument("--profile", default=None, help="integration tests require --profile mock")
    p.set_defaults(func=cmd_test)

    p = sub.add_parser("up", help="start project services (P0: --profile mock only)")
    p.add_argument("--profile", choices=("mock", "robot-readonly", "robot-live"), default="mock")
    p.set_defaults(func=cmd_up)

    p = sub.add_parser("status", help="show project service status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("down", help="stop project services started by `up`")
    p.set_defaults(func=cmd_down)

    p = sub.add_parser("accept", help="run frozen acceptance gates for a phase")
    p.add_argument("--phase", choices=PHASES, required=True)
    p.add_argument("--mode", choices=("mock", "replay", "hardware", "api-live"), required=True)
    p.add_argument("--session", default=None, help="field session id (required for motion modes, P1+)")
    p.set_defaults(func=cmd_accept)

    stub_specs = [
        ("models", "models fetch/download per model lock", "P2"),
        ("deploy", "robot deployment", "P1"),
        ("tunnel", "SSH tunnel management", "P1"),
        ("session", "field session management", "P1"),
        ("robot", "robot arm/stop control commands", "P1"),
        ("rollback", "robot release rollback", "P1"),
    ]
    for name, desc, phase in stub_specs:
        p = sub.add_parser(name, help=f"[{phase}] {desc} — not implemented yet")
        p.add_argument("rest", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
        p.set_defaults(func=cmd_stub, phase=phase, description=name)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log_path = _repo_root() / "artifacts" / "run" / "cli-events.jsonl"
    logger = EventLogger(log_path, component="cli")
    try:
        exit_code, result = args.func(args, logger)
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001 — CLI boundary: report, never crash silently
        logger.emit("cli_unhandled_error", error=type(exc).__name__, detail=str(exc), level="error")
        exit_code, result = EXIT_FAILED, {"ok": False, "error": f"unhandled {type(exc).__name__}: {exc}"}

    if getattr(args, "format", "text") == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(args.command, exit_code, result)
    return exit_code


def _print_human(command: str, exit_code: int, result: dict) -> None:
    status = {0: "OK", 1: "FAILED", 2: "ARGS/CONFIG ERROR", 3: "BLOCKED", 4: "NOT IMPLEMENTED"}.get(exit_code, "?")
    print(f"[{command}] {status} (exit {exit_code})")
    if not result:
        return
    if exit_code == EXIT_NOT_IMPLEMENTED:
        print(f"  {result.get('error')} — owning phase: {result.get('phase')}")
        return
    for key in ("error", "errors", "blocker"):
        if result.get(key):
            print(f"  {key}: {result[key]}")
    for step in result.get("steps", []) if isinstance(result.get("steps"), list) else []:
        mark = "ok" if step.get("ok") else "FAIL"
        print(f"  [{mark}] {step.get('step')}: {step.get('detail', '')[:100]}")
    for case in result.get("cases", []) if isinstance(result.get("cases"), list) else []:
        print(f"  {case.get('case_id'):<16} {case.get('mode'):<10} {case.get('status'):<8} "
              f"{case.get('passed_trials')}/{case.get('trial_count')}")
    for key in ("run_id", "run_status", "phase_gate_status", "run_dir", "inventory_run", "level",
                "pytest_exit_code", "profile", "healthy", "ports_free", "leaked_processes"):
        if key in result:
            print(f"  {key}: {result[key]}")
    if "valid" in result:
        print(f"  valid: {result['valid']}")
        for cap in result.get("capabilities", []):
            print(f"  capability {cap['name']:<11} {cap['state']:<12} {cap.get('reason') or ''}")
    if "problems" in result:
        print(f"  level: {result.get('level')}")
        for problem in result["problems"]:
            print(f"  ! {problem}")
    if "output_tail" in result and exit_code != 0:
        print(result["output_tail"])


if __name__ == "__main__":
    raise SystemExit(main())
