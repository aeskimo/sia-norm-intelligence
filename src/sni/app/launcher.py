"""Launcher (M8.1, REQ-800): ``python -m sni.app`` — 3 Modi.

- Default: Fenster (pywebview; macOS: GUI im Main-Thread)
- ``--browser``: UI im Standardbrowser
- ``--headless``: nur API (uvicorn; ``--port``/``PORT``/8000) — für CI/Tests

Alle Modi: nur Loopback (G4). Fenster/Browser: zufälliger freier Port +
Session-Token vom Launcher an die UI (REQ-816). Headless: fester Port für
Reproduzierbarkeit in der CI; das Token wird auf stdout ausgegeben.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import threading
import webbrowser

import uvicorn

from sni.app.security import new_session_token
from sni.app.server import HOST, build_app, pick_free_port, start_server_thread, ui_url
from sni.state.migrate import migrate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI-Argumente: ``--browser``, ``--headless``, ``--port``."""
    parser = argparse.ArgumentParser(
        prog="python -m sni.app",
        description="SIA-Normenassistent (Consumer App, M8)",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="UI im Standardbrowser öffnen statt im Fenster",
    )
    parser.add_argument("--headless", action="store_true", help="nur API (ohne UI); für CI/Tests")
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="fester Port (Headless-Modus; Default: PORT-Umgebungsvariable oder 8000)",
    )
    return parser.parse_args(argv)


def resolve_headless_port(port: int | None) -> int:
    """Headless: ``--port`` > ``PORT``-Umgebung > 8000 (REQ-816: kein Zufallsport in der CI)."""
    if port is not None:
        return port
    env = os.environ.get("PORT")
    if env is not None and env.isdigit():
        return int(env)
    return 8000


def run_headless(args: argparse.Namespace) -> int:
    """Headless-Modus: uvicorn im Main-Thread (Signalhandling)."""
    port = resolve_headless_port(args.port)
    token = new_session_token()
    app = build_app(mode="headless", port=port, sia_token=token)
    print(f"SIA-Normenassistent API: http://{HOST}:{port}", flush=True)
    print(f"sia_token: {token}", flush=True)
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
    return 0


def run_browser(args: argparse.Namespace) -> int:
    """Browser-Modus: Server im Hintergrund-Thread, UI im Standardbrowser."""
    port = pick_free_port()
    token = new_session_token()
    app = build_app(mode="browser", port=port, sia_token=token)
    server = start_server_thread(app, port)
    print(f"SIA-Normenassistent UI: {ui_url(port, token)}", flush=True)
    webbrowser.open(ui_url(port, token))
    with contextlib.suppress(KeyboardInterrupt):
        threading.Event().wait()  # bis Ctrl+C (Browser-Tab ist extern)
    server.should_exit = True
    return 0


def run_window(args: argparse.Namespace) -> int:
    """Fenster-Modus: pywebview im Main-Thread (macOS), Server im Hintergrund-Thread."""
    port = pick_free_port()
    token = new_session_token()
    app = build_app(mode="window", port=port, sia_token=token)
    server = start_server_thread(app, port)
    print(f"SIA-Normenassistent UI: {ui_url(port, token)}", flush=True)
    try:
        import webview  # lazy: nur im Fenster-Modus nötig
    except ImportError as exc:
        raise SystemExit(
            "pywebview ist nicht installiert (Fenster-Modus). Benutze --browser oder --headless."
        ) from exc
    webview.create_window("SIA-Normenassistent", ui_url(port, token), width=1200, height=800)
    webview.start()
    server.should_exit = True
    return 0


def main(argv: list[str] | None = None) -> int:
    """Einstiegspunkt für ``python -m sni.app``."""
    args = parse_args(argv)
    report = migrate()  # Java-Stand → Python-Zielzustand, vor dem Server (ADR-0011 Punkt 7)
    if report.workspace_problem is not None:
        print(f"Hinweis: {report.workspace_problem}", file=sys.stderr)
    if args.headless:
        return run_headless(args)
    if args.browser:
        return run_browser(args)
    return run_window(args)
