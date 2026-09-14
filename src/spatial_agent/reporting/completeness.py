"""Acceptance-report completeness rules (P0-REPORT).

A report claiming PASS must be backed by trials and evidence; the phase gate
cannot pass while a required case is missing, blocked, or evidenced only by a
different mode. These checks are deliberately conservative: any doubt means
"cannot be PASS".
"""

from __future__ import annotations

REQUIRED_P0_CASES = ("P0-ENV", "P0-BOOT", "P0-ISOLATION", "P0-CONFIG", "P0-REPORT")
VALID_STATUSES = ("PASS", "FAIL", "BLOCKED", "NOT_RUN", "SKIP")
VALID_MODES = ("mock", "replay", "hardware", "api-live")


def check_report(report: dict) -> list[str]:
    """Return a list of violations. An empty list means the report is coherent.

    Note: coherent does not mean PASS — it means the statuses that are claimed
    are backed by the report's own content.
    """
    problems: list[str] = []
    cases = report.get("cases")
    if not isinstance(cases, list) or not cases:
        return ["report has no cases"]

    requested_modes = report.get("requested_modes") or []
    seen_case_ids: set[str] = set()

    for i, case in enumerate(cases):
        prefix = f"cases[{i}]"
        case_id = case.get("case_id")
        if not case_id:
            problems.append(f"{prefix}: missing case_id")
            continue
        seen_case_ids.add(case_id)
        status = case.get("status")
        mode = case.get("mode")
        trial_count = case.get("trial_count", 0)
        passed = case.get("passed_trials", 0)
        failed = case.get("failed_trials", 0)
        evidence = case.get("evidence_paths") or []
        reason = case.get("reason")

        if status not in VALID_STATUSES:
            problems.append(f"{prefix} ({case_id}): invalid status {status!r}")
        if mode not in VALID_MODES:
            problems.append(f"{prefix} ({case_id}): invalid mode {mode!r}")
        elif requested_modes and mode not in requested_modes:
            problems.append(f"{prefix} ({case_id}): mode {mode!r} is not in requested_modes {requested_modes}")

        if status == "PASS":
            if not isinstance(trial_count, int) or trial_count < 1:
                problems.append(f"{prefix} ({case_id}): PASS requires trial_count >= 1")
            if passed != trial_count or failed != 0:
                problems.append(
                    f"{prefix} ({case_id}): PASS requires passed_trials == trial_count and zero failures "
                    f"(passed={passed}, failed={failed}, trials={trial_count})"
                )
            if not evidence:
                problems.append(f"{prefix} ({case_id}): PASS requires non-empty evidence_paths")
            if not reason:
                problems.append(f"{prefix} ({case_id}): PASS requires a reason/summary")
            for metric in case.get("metrics", []) or []:
                if "value" not in metric or ("unit" not in metric and metric.get("kind") != "count"):
                    problems.append(f"{prefix} ({case_id}): metrics need value and unit")
        elif status == "FAIL" and not reason:
            problems.append(f"{prefix} ({case_id}): FAIL requires a reason")
        elif status == "SKIP":
            if case.get("required", True):
                problems.append(f"{prefix} ({case_id}): required cases cannot be SKIP")
            if not reason:
                problems.append(f"{prefix} ({case_id}): SKIP requires justification")

    # Phase-gate aggregation rules.
    gate = report.get("phase_gate_status")
    missing = [c for c in report.get("missing_required_cases", [])]
    for req in report.get("_required_case_ids", REQUIRED_P0_CASES):
        if req not in seen_case_ids and req not in missing:
            missing.append(req)
    if report.get("_required_case_ids") is None and report.get("phase") == "P0":
        for req in REQUIRED_P0_CASES:
            if req not in seen_case_ids and req not in missing and req not in [c.get("case_id") for c in cases]:
                missing.append(req)
    blockers = report.get("blockers") or []

    case_by_id = {c.get("case_id"): c for c in cases if c.get("case_id")}
    required_statuses = [
        case_by_id[c].get("status")
        for c in report.get("_required_case_ids", REQUIRED_P0_CASES)
        if c in case_by_id
    ]
    all_required_pass = bool(required_statuses) and all(s == "PASS" for s in required_statuses)

    if gate == "PASS":
        if missing:
            problems.append(f"phase_gate_status=PASS but required cases are missing: {missing}")
        if not all_required_pass:
            problems.append(f"phase_gate_status=PASS but required case statuses are {required_statuses}")
        if blockers:
            problems.append(f"phase_gate_status=PASS while blockers exist: {blockers}")
        # P0-ENV must exist as hardware-mode evidence for the phase gate to pass.
        env_case = case_by_id.get("P0-ENV")
        if env_case is not None and env_case.get("mode") != "hardware":
            problems.append("phase_gate_status=PASS requires P0-ENV with mode=hardware (robot read-only evidence)")

    # run_status consistency for the requested scope.
    run_status = report.get("run_status")
    if run_status == "PASS" and requested_modes:
        in_scope = [c for c in cases if c.get("mode") in requested_modes and c.get("required", True)]
        if not in_scope:
            problems.append("run_status=PASS but no required cases in the requested modes")
        elif any(c.get("status") != "PASS" for c in in_scope):
            problems.append("run_status=PASS but some in-scope required cases are not PASS")

    return problems
