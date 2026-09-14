"""Mock gateway launcher: `python -m spatial_agent.gateway.mock.server`.

Runs uvicorn bound to loopback only, with an optional JSONL event sink so
acceptance runs can capture gateway events as evidence.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import uvicorn

from spatial_agent.gateway.mock.app import MockSettings, create_app
from spatial_agent.logging_utils import EventLogger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the mock robot gateway (loopback only)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", default="mock-token")
    parser.add_argument("--events", default=None, help="JSONL path for gateway events")
    args = parser.parse_args(argv)

    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"refusing to bind mock gateway to non-loopback host {args.host!r}", file=sys.stderr)
        return 2

    sink = None
    if args.events:
        logger = EventLogger(Path(args.events), component="mock_gateway")
        sink = logger.emit
    app = create_app(MockSettings(token=args.token, event_sink=sink))
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
