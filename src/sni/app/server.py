"""App-Server (M8.1, REQ-800): Zusammensetzen der Kern-API zur Consumer-App.

Schichten-Regel (03_ARCHITECTURE.md): ``sni.app`` hängt von ``sni.api``
ab — nicht umgekehrt. Die Kern-API (``create_app``) bleibt unverändert;
dieses Modul legt die Static-UI, den App-Router (``/v1/status``) und die
Sicherheitsschicht (REQ-816) darüber.
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.request
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from sni.api.main import create_app
from sni.app.api import router as app_router
from sni.app.security import LoopbackSecurityMiddleware

STATIC_DIR = Path(__file__).parent / "static"
HOST = "127.0.0.1"  # G4: nur Loopback


def build_app(
    db_path: Path | None = None,
    knowledge_dir: Path | None = None,
    rules_dir: Path | None = None,
    *,
    sia_token: str | None = None,
    mode: str = "window",
    port: int = 0,
) -> FastAPI:
    """Kern-API + Static-UI + App-Router; mit Token: Sicherheitsschicht (REQ-816)."""
    app = create_app(db_path=db_path, knowledge_dir=knowledge_dir, rules_dir=rules_dir)
    app.state.app_mode = mode
    app.state.app_port = port

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(app_router, prefix="/v1")
    if sia_token is not None:
        app.add_middleware(LoopbackSecurityMiddleware, sia_token=sia_token)
    return app


def pick_free_port() -> int:
    """Freier Loopback-Port für diesen Start (REQ-816: kein Port-Konflikt)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def ui_url(port: int, token: str) -> str:
    """UI-Start-URL; das Token per Query (EventSource kann keine Header, REQ-816)."""
    return f"http://{HOST}:{port}/?sia_token={token}"


def wait_ready(port: int, timeout: float = 15.0) -> None:
    """Warten, bis ``/healthz`` auf ``127.0.0.1:<port>`` antwortet (sonst RuntimeError)."""
    url = f"http://{HOST}:{port}/healthz"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as res:
                if res.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.1)
    raise RuntimeError(f"App-API nicht bereit nach {timeout:.0f} s (Port {port})")


def start_server_thread(app: FastAPI, port: int) -> uvicorn.Server:
    """uvicorn im Hintergrund-Thread; liefert den Server (Stop via ``should_exit``).

    Thread nötig, weil auf macOS die GUI (pywebview) im Main-Thread laufen
    muss (09_CONSUMER_APP.md §3).
    """
    config = uvicorn.Config(app, host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True, name="sni-uvicorn").start()
    wait_ready(port)
    return server
