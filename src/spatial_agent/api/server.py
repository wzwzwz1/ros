"""Mac app launcher: `python -m spatial_agent.api.server`.

Loads a validated runtime config and serves the minimal debug app on loopback.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from spatial_agent.config.validation import validate_config_file
from spatial_agent.versioning import get_code_version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Mac-side Spatial Agent app")
    parser.add_argument("--config", required=True)
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    report = validate_config_file(config_path)
    if not report.valid or report.config is None:
        print("invalid runtime config:", report.errors, flush=True)
        return 2
    if report.config.example_only:
        print("refusing to run with example_only config", flush=True)
        return 2

    repo_root = Path(args.repo_root).resolve()
    code_version = get_code_version(repo_root).as_dict()
    token = os.environ.get(report.config.robot.gateway_token_env, "mock-token")
    from spatial_agent.api.app import create_app

    app = create_app(report.config, gateway_token=token, code_version=code_version)
    host = args.host or report.config.mac.listen_host
    port = args.port or report.config.mac.listen_port
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
