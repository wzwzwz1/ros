"""Structured JSONL event logging with mandatory secret redaction.

Every event line carries: ts_utc, trace_id, component, event plus optional
task_id / operation_id / error fields (development-requirements.md §6).
Values whose keys look secret-bearing are redacted before serialization; this
module is the single choke point so callers cannot accidentally leak them.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_SECRET_KEY_RE = re.compile(
    r"(password|passwd|secret|token|authorization|api[-_]?key|credential)", re.IGNORECASE
)
_REDACTED = "[REDACTED]"


def now_utc_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def monotonic_ms() -> float:
    return time.monotonic() * 1000.0


def new_trace_id() -> str:
    return uuid.uuid4().hex


def redact(value: Any) -> Any:
    """Recursively redact secret-looking values. Applied to every event payload."""
    if isinstance(value, dict):
        return {
            k: (_REDACTED if _SECRET_KEY_RE.search(str(k)) else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(payload: Any) -> str:
    """Stable hash of a JSON-serializable object (canonical, sorted keys)."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class EventLogger:
    """Append-only JSONL event writer. Never raises on logging failure."""

    def __init__(self, path: Path | None = None, component: str = "app"):
        self.path = path
        self.component = component
        self.trace_id = new_trace_id()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, *, level: str = "info", **fields: Any) -> None:
        record = redact(
            {
                "ts_utc": now_utc_iso(),
                "trace_id": self.trace_id,
                "component": self.component,
                "level": level,
                "event": event,
                "pid": os.getpid(),
                **fields,
            }
        )
        line = json.dumps(record, ensure_ascii=False, default=str)
        if self.path is not None:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                print(line, file=sys.stderr)
        else:
            print(line, file=sys.stderr)


class RedactingStdoutWriter:
    """Wraps a text stream, redacting secret-looking values written via emit()."""

    def __init__(self, stream=None):
        self.stream = stream if stream is not None else sys.stdout

    def emit_line(self, payload: dict) -> None:
        print(json.dumps(redact(payload), ensure_ascii=False), file=self.stream)
