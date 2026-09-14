"""`bootstrap --target mac`: create the reproducible local environment.

Idempotent by design (P0-BOOT runs it twice): every step is safe to repeat —
uv sync is content-addressed, config generation only fills gaps, and no global
system state is touched.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from spatial_agent import __version__
from spatial_agent.logging_utils import EventLogger, now_utc_iso, sha256_json

REQUIRED_PYTHON = (3, 11)


def generate_local_config(repo_root: Path) -> Path | None:
    """Create configs/local/runtime.json from the committed template if missing.

    Returns the config path when a file exists afterwards, None on failure.
    """
    local_dir = repo_root / "configs" / "local"
    local_path = local_dir / "runtime.json"
    if local_path.exists():
        return local_path
    template_path = repo_root / "docs" / "templates" / "runtime.example.json"
    if not template_path.exists():
        return None
    raw = json.loads(template_path.read_text(encoding="utf-8"))
    raw.pop("example_only", None)
    raw["profile"] = "mock"
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return local_path


def bootstrap_mac(repo_root: Path, logger: EventLogger) -> dict:
    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str = "") -> None:
        steps.append({"step": name, "ok": ok, "detail": detail})
        logger.emit("bootstrap_step", step=name, ok=ok, detail=detail)

    # 1. platform check
    import platform

    machine = platform.machine()
    platform_ok = sys.platform == "darwin"
    step("platform_check", platform_ok, f"sys.platform={sys.platform} machine={machine}")

    # 2. uv-managed Python 3.11 + locked dependencies
    venv_python = repo_root / ".venv" / "bin" / "python"
    if not venv_python.exists():
        result = subprocess.run(["uv", "sync"], cwd=repo_root, capture_output=True, text=True, timeout=600)
        step("uv_sync", result.returncode == 0, (result.stderr or result.stdout)[-500:])
    else:
        result = subprocess.run(["uv", "sync", "--frozen"], cwd=repo_root, capture_output=True, text=True, timeout=600)
        step("uv_sync_frozen", result.returncode == 0, (result.stderr or result.stdout)[-500:])

    if venv_python.exists():
        ver_out = subprocess.run([str(venv_python), "-c", "import platform;print(platform.python_version())"],
                                 capture_output=True, text=True)
        version = ver_out.stdout.strip()
        ok = version.startswith(f"{REQUIRED_PYTHON[0]}.{REQUIRED_PYTHON[1]}")
        step("python_version", ok, f"venv python {version}")
    else:
        step("python_version", False, ".venv not created; uv sync failed")

    # 3. core imports
    if venv_python.exists():
        probe = subprocess.run(
            [str(venv_python), "-c", "import pydantic, fastapi, httpx, uvicorn, pytest; print('ok')"],
            capture_output=True, text=True,
        )
        step("core_imports", probe.returncode == 0, probe.stdout.strip() or probe.stderr.strip()[-200:])
    else:
        step("core_imports", False, "no venv")

    # 4. directory layout that P0 actually uses (no empty fake packages)
    for rel in ("artifacts/run", "artifacts/inventory", "configs/local"):
        (repo_root / rel).mkdir(parents=True, exist_ok=True)
    step("directories", True, "artifacts/run, artifacts/inventory, configs/local")

    # 5. local config from template (idempotent)
    config_path = generate_local_config(repo_root)
    step("local_config", config_path is not None, str(config_path) if config_path else "template missing")

    ok = all(s["ok"] for s in steps)
    evidence = {
        "kind": "bootstrap_evidence",
        "ts_utc": now_utc_iso(),
        "version": __version__,
        "ok": ok,
        "steps": steps,
        "config_sha256": sha256_json(json.loads(config_path.read_text())) if config_path else None,
    }
    out_dir = repo_root / "artifacts" / "bootstrap"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "bootstrap-latest.json"
    out_file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.emit("bootstrap_done", ok=ok)
    return evidence
