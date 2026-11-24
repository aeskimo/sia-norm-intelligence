"""REQ-800: Launcher-Boot — echtes uvicorn auf 127.0.0.1 (Hintergrund-Thread, freier Port)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from sni.app.server import HOST, build_app, pick_free_port, start_server_thread


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[tuple[str, str]]:
    """App auf echtem Loopback-Port (Browser-Modus); liefert (base_url, token)."""
    port = pick_free_port()
    app = build_app(
        db_path=tmp_path / "catalog.db",
        knowledge_dir=tmp_path / "extracted",
        rules_dir=tmp_path / "rules",
        sia_token="live-token",
        mode="browser",
        port=port,
    )
    server = start_server_thread(app, port)
    try:
        yield f"http://{HOST}:{port}", "live-token"
    finally:
        server.should_exit = True


def test_req800_live_api_serves_ui_and_status(live_server: tuple[str, str]) -> None:
    # Given die App auf einem freien Port When UI und Status abgefragt
    # Then erreichbar (UI und API same-origin auf 127.0.0.1, kein CORS)
    base, token = live_server
    with httpx.Client(base_url=base, timeout=5.0) as client:
        assert client.get("/healthz").status_code == 200
        res = client.get("/")
        assert res.status_code == 200
        assert "SIA-Normenassistent" in res.text
        assert client.get("/static/sia.css").status_code == 200
        res = client.get("/v1/status", headers={"x-sia-token": token})
        assert res.status_code == 200
        data = res.json()
        assert data["mode"] == "browser"
        assert data["port"] == int(base.rsplit(":", 1)[1])


def test_req800_live_api_enforces_token(live_server: tuple[str, str]) -> None:
    # Given die App gelauncht When /v1 ohne Token Then 401 (REQ-816)
    base, _ = live_server
    with httpx.Client(base_url=base, timeout=5.0) as client:
        assert client.get("/v1/status").status_code == 401
