"""Acceptance run artifact writer (acceptance.md §2).

Creates the frozen run directory layout and the evidence hash manifest. The
writer is append-only within a run: trials.jsonl is appended, never rewritten.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from spatial_agent.logging_utils import now_utc_iso


def new_run_id(phase: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    short = uuid.uuid4().hex[:6]
    return f"{stamp}-{phase}-{short}"


def _dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def redact_config(raw: dict) -> dict:
    """Redact secret-looking values from a config for artifact storage."""
    import copy
    import re

    pattern = re.compile(r"(password|secret|token|authorization|api[-_]?key)", re.IGNORECASE)

    def _walk(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: ("[REDACTED]" if pattern.search(str(k)) else _walk(v)) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v) for v in value]
        return value

    redacted = copy.deepcopy(raw)
    redacted.pop("example_only", None)
    return _walk(redacted)


def write_summary_md(run_dir: Path, report: dict) -> None:
    cases_lines = []
    for case in report.get("cases", []):
        cases_lines.append(
            f"| {case.get('case_id')} | {case.get('mode')} | {case.get('status')} | "
            f"{case.get('passed_trials')}/{case.get('trial_count')} | {case.get('reason', '')[:80]} |"
        )
    content = f"""# 验收总结 {report.get('run_id')}

- 阶段: {report.get('phase')}
- 请求模式: {report.get('requested_modes')}
- run_status: **{report.get('run_status')}**
- phase_gate_status: **{report.get('phase_gate_status')}**
- 代码版本: `{(report.get('code') or {}).get('commit')}` dirty={(report.get('code') or {}).get('dirty')}
- 开始/结束: {report.get('started_at_utc')} / {report.get('finished_at_utc')}

## 用例结果

| Case | 模式 | 状态 | 通过/总数 | 说明 |
|---|---|---|---|---|
{chr(10).join(cases_lines)}

## 阻塞项

{chr(10).join(f'- {b}' for b in (report.get('blockers') or [])) or '- 无'}

## 下一步

{chr(10).join(f'- {a}' for a in (report.get('next_actions') or [])) or '- 无'}
"""
    (run_dir / "summary.md").write_text(content, encoding="utf-8")


def write_evidence_manifest(run_dir: Path) -> str:
    """SHA-256 every regular file in the run dir; writes evidence.sha256."""
    lines = []
    for path in sorted(run_dir.rglob("*")):
        if path.is_file() and path.name != "evidence.sha256":
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            lines.append(f"{digest}  {path.relative_to(run_dir)}")
    manifest = "\n".join(lines) + "\n"
    (run_dir / "evidence.sha256").write_text(manifest, encoding="utf-8")
    return hashlib.sha256(manifest.encode()).hexdigest()


def append_trial(run_dir: Path, record: dict) -> None:
    base = {"ts_utc": now_utc_iso(), "source": "mock"}
    _append_jsonl(run_dir / "trials.jsonl", {**base, **record})


def append_event(run_dir: Path, record: dict) -> None:
    _append_jsonl(run_dir / "events.jsonl", {**record, "ts_utc": record.get("ts_utc") or now_utc_iso()})
