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
from pathlib import Path
from typing import Any

import uvicorn

from sni.app import bootstrap
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


def run_headless(args: argparse.Namespace, core_data_dir: Path | None = None) -> int:
    """Headless-Modus: uvicorn im Main-Thread (Signalhandling)."""
    port = resolve_headless_port(args.port)
    token = new_session_token()
    app = build_app(mode="headless", port=port, sia_token=token, core_data_dir=core_data_dir)
    print(f"SIA-Normenassistent API: http://{HOST}:{port}", flush=True)
    print(f"sia_token: {token}", flush=True)
    uvicorn.run(app, host=HOST, port=port, log_level="warning")
    return 0


def run_browser(args: argparse.Namespace, core_data_dir: Path | None = None) -> int:
    """Browser-Modus: Server im Hintergrund-Thread, UI im Standardbrowser."""
    port = pick_free_port()
    token = new_session_token()
    app = build_app(mode="browser", port=port, sia_token=token, core_data_dir=core_data_dir)
    server = start_server_thread(app, port)
    print(f"SIA-Normenassistent UI: {ui_url(port, token)}", flush=True)
    webbrowser.open(ui_url(port, token))
    with contextlib.suppress(KeyboardInterrupt):
        threading.Event().wait()  # bis Ctrl+C (Browser-Tab ist extern)
    server.should_exit = True
    return 0


def _auto_close(window: Any, shown_wait: float, destroy_backstop: float = 15.0) -> None:
    """CI-Auto-Schliessen (REQ-813): Shown-Event abwarten, destroy + Backstop.

    Das Shown-Event kann unter CI langsam kommen (kalte Init, Xvfb); deshalb
    Polling bis ``shown_wait`` statt einmaliges Warten. Ohne Shown-Event wirft
    ``window.destroy()`` im Neben-Thread stillschweigend und die App läuft
    ewig weiter (CI-Hang) — daher ``os._exit`` mit 1 (Pattern:
    ``packaging/hello_window.py``).
    """
    import time

    def _backstop() -> None:
        print("[window] destroy lief nicht aus → Backstop os._exit(0)", file=sys.stderr)
        os._exit(0)

    deadline = time.monotonic() + shown_wait
    shown = False
    while time.monotonic() < deadline:
        if window.events.shown.wait(1):
            shown = True
            break
    if shown:
        print("[window] Fenster angezeigt → window.destroy()", file=sys.stderr)
        backstop = threading.Timer(destroy_backstop, _backstop)
        backstop.daemon = True
        backstop.start()
        window.destroy()
    else:
        print(
            "[window] Fenster wurde nicht angezeigt → os._exit(1)",
            file=sys.stderr,
            flush=True,
        )
        os._exit(1)


def run_window(args: argparse.Namespace, core_data_dir: Path | None = None) -> int:
    """Fenster-Modus: pywebview im Main-Thread (macOS), Server im Hintergrund-Thread."""
    port = pick_free_port()
    token = new_session_token()
    app = build_app(mode="window", port=port, sia_token=token, core_data_dir=core_data_dir)
    server = start_server_thread(app, port)
    print(f"SIA-Normenassistent UI: {ui_url(port, token)}", flush=True)
    try:
        import webview  # lazy: nur im Fenster-Modus nötig
    except ImportError as exc:
        raise SystemExit(
            "pywebview ist nicht installiert (Fenster-Modus). Benutze --browser oder --headless."
        ) from exc
    window = webview.create_window(
        "SIA-Normenassistent", ui_url(port, token), width=1200, height=800
    )
    seconds = float(os.environ.get("SIA_WINDOW_SECONDS", "0") or 0)
    if seconds > 0:
        # CI-Smoke (REQ-813): nach `seconds` Shown-Event abwarten, destroy +
        # Backstop (Pattern: packaging/hello_window.py).
        shown_wait = float(os.environ.get("SIA_WINDOW_SHOWN_WAIT", "20"))
        threading.Timer(seconds, _auto_close, args=(window, shown_wait)).start()
    webview.start()
    server.should_exit = True
    return 0


def _frozen_core_data_dir() -> Path | None:
    """M8.6 (REQ-813): frozen App → schreibbaren Kerndaten-Mount säumen.

    Setzt ``SIA_CORE_DATA_DIR`` (Call-time-Defaults von Review/Ingest) und
    liefert das Verzeichnis für ``build_app`` (Katalog/Wissensbasis/Regeln).
    Dev-Modus: None (Kerndaten = ``<repo>/data``).
    """
    if not bootstrap.frozen():
        return None
    core = bootstrap.core_data_dir()
    os.environ["SIA_CORE_DATA_DIR"] = str(core)
    imported = bootstrap.seed_core_data(core, bootstrap.bundle_data_dir())
    print(f"Kerndaten: {core} ({imported} neue Concepts)", flush=True)
    return core


def main(argv: list[str] | None = None) -> int:
    """Einstiegspunkt für ``python -m sni.app``."""
    args = parse_args(argv)
    report = migrate()  # Java-Stand → Python-Zielzustand, vor dem Server (ADR-0011 Punkt 7)
    if report.workspace_problem is not None:
        print(f"Hinweis: {report.workspace_problem}", file=sys.stderr)
    core = _frozen_core_data_dir()
    if args.headless:
        return run_headless(args, core_data_dir=core)
    if args.browser:
        return run_browser(args, core_data_dir=core)
    return run_window(args, core_data_dir=core)
