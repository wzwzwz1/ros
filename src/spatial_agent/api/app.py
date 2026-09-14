"""Mac-side HTTP application (P0 minimal surface).

- /health: Mac app health and active profile.
- /v1/status: aggregates gateway status via the (isolated) gateway client.
- /v1/events: contract route reserved for P1; returns CAPABILITY_UNAVAILABLE.
- /: minimal debug page with a prominent mock banner when profile=mock.

The app binds loopback by default and is the only component the browser talks
to; it never exposes the gateway directly (architecture.md §2).
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from spatial_agent import __version__
from spatial_agent.config.schema import Profile, RuntimeConfig
from spatial_agent.gateway.client import GatewayClient, GatewayConnectionError
from spatial_agent.protocol.envelope import error_envelope, ok_envelope


def create_app(config: RuntimeConfig, gateway_token: str, code_version: dict) -> FastAPI:
    app = FastAPI(title="Spatial Agent (Mac)", docs_url=None, redoc_url=None)
    profile = config.profile
    client = GatewayClient(profile, config.robot.gateway_url, gateway_token)

    @app.get("/health")
    def health():
        return ok_envelope(
            {"app": "spatial-agent", "version": __version__, "profile": profile.value, "code": code_version}
        ).model_dump()

    @app.get("/v1/status")
    def status():
        try:
            data = client.status()
            data["mac_app"] = {"version": __version__, "profile": profile.value}
            return ok_envelope(data).model_dump()
        except GatewayConnectionError as exc:
            return error_envelope("ROBOT_UNREACHABLE", str(exc), retryable=True).model_dump()
        except RuntimeError as exc:
            code = getattr(exc, "code", "INTERNAL")
            return error_envelope(code if code in {"CAPABILITY_UNAVAILABLE"} else "INTERNAL", str(exc)).model_dump()

    @app.get("/v1/events")
    def events():
        # Contract route; WebSocket event streaming arrives in P1.
        return JSONResponse(
            error_envelope("CAPABILITY_UNAVAILABLE", "event streaming arrives in P1").model_dump(),
            status_code=501,
        )

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        try:
            status_data = client.status()
            gateway_html = f"""
            <tr><td>armed</td><td>{status_data.get('armed')}</td></tr>
            <tr><td>stop_latched</td><td>{status_data.get('stop_latched')}</td></tr>
            <tr><td>map_id</td><td><code>{status_data.get('map_id')}</code></td></tr>
            <tr><td>active_operation</td><td>{status_data.get('active_operation_id') or '—'}</td></tr>
            """
        except Exception as exc:  # debug page must stay up even without gateway
            gateway_html = f'<tr><td colspan="2">gateway unreachable: {type(exc).__name__}</td></tr>'
        banner = (
            '<div class="banner mock">MOCK 模式 — 非真实机器人，数据全部来自模拟器</div>'
            if profile is Profile.MOCK
            else f'<div class="banner">profile: {profile.value}</div>'
        )
        return HTMLResponse(f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8"><title>Spatial Agent</title>
<style>
body {{ font-family: -apple-system, sans-serif; margin: 2rem; background: #fafafa; }}
.banner {{ padding: .6rem 1rem; border-radius: 6px; margin-bottom: 1rem; background: #eef; }}
.banner.mock {{ background: #fff3cd; border: 1px solid #e0c36a; }}
table {{ border-collapse: collapse; }} td {{ padding: .3rem .8rem; border-bottom: 1px solid #ddd; }}
code {{ font-size: .8em; }}
</style></head><body>
<h1>Spatial Agent <small>v{__version__}</small></h1>
{banner}
<table>{gateway_html}</table>
<p>profile=<b>{profile.value}</b> · gateway=<code>{config.robot.gateway_url}</code></p>
</body></html>""")

    return app
