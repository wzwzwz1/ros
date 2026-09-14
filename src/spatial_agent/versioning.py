"""Code version identification for reports and status output.

A version is (commit, dirty, diff_sha256). When the working tree is dirty the
exact diff content is hashed so a dirty run is still reproducible/auditable
instead of pretending to be a clean commit (deployment-runbook.md §4).
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CodeVersion:
    commit: str | None
    dirty: bool | None
    diff_sha256: str | None

    def as_dict(self) -> dict:
        return {
            "commit": self.commit,
            "dirty": self.dirty,
            "diff_sha256": self.diff_sha256,
        }

    def label(self) -> str:
        if self.commit is None:
            return "unknown(no-git)"
        suffix = "+dirty" if self.dirty else ""
        return f"{self.commit[:12]}{suffix}"


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout.strip()


def get_code_version(repo_root: Path) -> CodeVersion:
    """Read version facts from the git working tree at repo_root."""
    try:
        commit = _run_git(repo_root, "rev-parse", "HEAD")
        dirty_out = _run_git(repo_root, "status", "--porcelain")
    except (RuntimeError, FileNotFoundError, subprocess.TimeoutExpired):
        return CodeVersion(commit=None, dirty=None, diff_sha256=None)

    if not dirty_out:
        return CodeVersion(commit=commit, dirty=False, diff_sha256=None)

    hasher = hashlib.sha256()
    try:
        diff = _run_git(repo_root, "diff", "HEAD")
        hasher.update(diff.encode("utf-8"))
    except (RuntimeError, subprocess.TimeoutExpired):
        pass
    # Untracked files are part of the dirty state; include names+content hashes.
    untracked = [line[3:] for line in dirty_out.splitlines() if line.startswith("??")]
    for name in sorted(untracked):
        path = repo_root / name
        hasher.update(name.encode("utf-8"))
        try:
            if path.is_file():
                hasher.update(b"\0file\0")
                hasher.update(path.read_bytes())
        except OSError:
            hasher.update(b"\0unreadable\0")
    return CodeVersion(commit=commit, dirty=True, diff_sha256=hasher.hexdigest())
