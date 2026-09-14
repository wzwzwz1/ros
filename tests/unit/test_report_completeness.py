"""Unit tests for report completeness rules (P0-REPORT)."""

import copy

from spatial_agent.reporting.completeness import check_report


def passing_case(case_id="P0-BOOT", mode="mock"):
    return {
        "case_id": case_id, "mode": mode, "required": True, "status": "PASS",
        "trial_count": 2, "passed_trials": 2, "failed_trials": 0,
        "evidence_paths": ["trials.jsonl"], "reason": "ok",
    }


def env_case(status="PASS"):
    return {
        "case_id": "P0-ENV", "mode": "hardware", "required": True, "status": status,
        "trial_count": 1, "passed_trials": 1 if status == "PASS" else 0, "failed_trials": 0,
        "evidence_paths": ["environment.json", "robot-inventory.json"], "reason": "collected",
    }


def base_report():
    return {
        "schema_version": "1.0", "run_id": "run-x", "phase": "P0",
        "requested_modes": ["mock"], "run_status": "PASS", "phase_gate_status": "PASS",
        "missing_required_cases": [], "blockers": [],
        "cases": [
            passing_case(),
            env_case(),
            passing_case("P0-ISOLATION"),
            passing_case("P0-CONFIG"),
            passing_case("P0-REPORT"),
        ],
    }


def test_fully_evidenced_report_has_no_violations():
    assert check_report(base_report()) == []


def test_pass_with_zero_trials_rejected():
    report = base_report()
    report["cases"][0]["trial_count"] = 0
    report["cases"][0]["passed_trials"] = 0
    assert any("trial_count" in p for p in check_report(report))


def test_pass_with_failures_rejected():
    report = base_report()
    report["cases"][0]["failed_trials"] = 1
    report["cases"][0]["passed_trials"] = 1
    assert any("zero failures" in p for p in check_report(report))


def test_pass_without_evidence_rejected():
    report = base_report()
    report["cases"][0]["evidence_paths"] = []
    assert any("evidence" in p for p in check_report(report))


def test_gate_pass_with_blockers_rejected():
    report = base_report()
    report["blockers"] = ["robot offline"]
    assert any("blockers" in p for p in check_report(report))


def test_gate_pass_with_missing_required_case_rejected():
    report = base_report()
    report["cases"] = [c for c in report["cases"] if c["case_id"] != "P0-ENV"]
    assert any("P0-ENV" in p for p in check_report(report))


def test_gate_pass_with_blocked_env_rejected():
    report = base_report()
    report["cases"][1]["status"] = "BLOCKED"
    problems = check_report(report)
    assert any("required case statuses" in p for p in problems)


def test_gate_pass_with_mock_env_mode_rejected():
    report = base_report()
    report["cases"][1]["mode"] = "mock"
    assert any("P0-ENV" in p and "hardware" in p for p in check_report(report))


def test_case_mode_outside_requested_modes_rejected():
    report = base_report()
    report["cases"][1]["mode"] = "replay"
    assert any("requested_modes" in p for p in check_report(report))


def test_required_case_cannot_be_skip():
    report = base_report()
    report["cases"][2]["status"] = "SKIP"
    assert any("SKIP" in p for p in check_report(report))


def test_optional_skip_with_reason_is_coherent():
    report = base_report()
    report["cases"].append({
        "case_id": "P0-EXTRA", "mode": "mock", "required": False, "status": "SKIP",
        "trial_count": 0, "passed_trials": 0, "failed_trials": 0,
        "evidence_paths": [], "reason": "out of P0 scope",
    })
    assert check_report(report) == []


def test_legitimate_fail_report_is_coherent():
    report = base_report()
    report["run_status"] = "FAIL"
    report["phase_gate_status"] = "FAIL"
    report["cases"][0].update(status="FAIL", passed_trials=1, failed_trials=1, reason="documented failure")
    report["blockers"] = ["robot offline"]
    assert check_report(report) == []


def test_fail_without_reason_rejected():
    report = base_report()
    report["cases"][0].update(status="FAIL", passed_trials=1, failed_trials=1, reason=None)
    report["cases"][0].pop("reason")
    assert any("FAIL requires a reason" in p for p in check_report(report))


def test_run_status_pass_requires_all_in_scope_pass():
    report = base_report()
    report["cases"][2]["status"] = "FAIL"
    report["cases"][2].update(passed_trials=4, failed_trials=1, reason="one injection leaked")
    assert any("run_status=PASS" in p for p in check_report(report))


def test_empty_case_list_rejected():
    report = base_report()
    report["cases"] = []
    assert check_report(report) == ["report has no cases"]
