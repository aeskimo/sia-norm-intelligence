#!/usr/bin/env python3
"""CI-Binary-Such-Probe P1 (nur Linux/Xvfb): feuert ``activate`` bei
einem plainen ``Gtk.Application``?

Exakt derselbe Form wie pywebview's GTK-Backend (``webview/platforms/
gtk.py``: ``gtk.Application.new(None, 0)`` ohne application_id,
``connect('activate', ...)`` + ``run()`` ohne argv), aber ohne
pywebview und ohne PyInstaller — reines PyGObject. Isoliert, ob die
GHA-Linux-Umgebung (Xvfb + D-Bus-Session-Bus) GtkApplication-Instanzen
überhaupt aktivieren kann (Diagnose 2026-11-25, Run 45514306284:
Main-Thread in ``Gio.Application.run`` (C-Frame, Zeile 139), 0
Gtk-Fenster, 0 WebKit-Prozesse, kein Traceback).

Das Heartbeat-Log (alle 5 s) trennt "langsame Init" von "echtem Hang":
- ``ACTIVATE FIRED nach X s`` mit grossem X → Init ist langsam,
  Deadline-Problem (kein Packaging-Fehler).
- Watchdog ohne activate → echter Block in register/startup (GTK-Init
  o. ä. unter Xvfb).

Aufruf:  xvfb-run --auto-servernum python3 packaging/ci_gtk_probe.py
Exit 0 = ``activate`` gefeuert + Fenster gezeigt.
Exit 1 = Watchdog: Zustand unklar, Details im Log.
"""

from __future__ import annotations

import os
import sys
import threading
import time

WATCHDOG_SECONDS = 45.0

ENV_VARS = (
    "DISPLAY",
    "DBUS_SESSION_BUS_ADDRESS",
    "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE",
    "WAYLAND_DISPLAY",
    "GDK_BACKEND",
)


def _dump_env() -> None:
    for var in ENV_VARS:
        print(f"[P1] env {var}={os.environ.get(var)!r}", file=sys.stderr, flush=True)


def main() -> int:
    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk

    _dump_env()
    print(
        "[P1] Gtk.Application.new(None, 0) + connect('activate') + run() …",
        file=sys.stderr,
        flush=True,
    )

    start = time.monotonic()
    state = {"fired": False}

    def _heartbeat() -> None:
        for tick in range(1, 12):
            time.sleep(5)
            print(
                f"[P1] heartbeat t={tick * 5}s fired={state['fired']}",
                file=sys.stderr,
                flush=True,
            )

    heartbeat = threading.Thread(target=_heartbeat, daemon=True)
    heartbeat.start()

    def _watchdog() -> None:
        print(
            f"[P1] Watchdog ({WATCHDOG_SECONDS:.0f} s): fired={state['fired']} → os._exit(1)",
            file=sys.stderr,
            flush=True,
        )
        os._exit(1)

    watchdog = threading.Timer(WATCHDOG_SECONDS, _watchdog)
    watchdog.daemon = True
    watchdog.start()

    def _quit() -> bool:
        app.quit()
        return False

    def on_activate(_application: Gtk.Application) -> None:
        state["fired"] = True
        elapsed = time.monotonic() - start
        print(f"P1: ACTIVATE FIRED nach {elapsed:.1f} s", flush=True)
        # Wie pywebview (gtk.py:79): ApplicationWindow mit application=_app.
        window = Gtk.ApplicationWindow(application=app)
        window.set_title("sni-p1-probe")
        window.show_all()
        print(f"P1: window visible={window.get_visible()}", flush=True)
        GLib.timeout_add(2000, _quit)

    app = Gtk.Application.new(None, 0)
    app.connect("activate", on_activate)
    # Identisch zu pywebview (gtk.py:779): ``_app.run()`` ohne argv.
    app.run()

    print(f"P1: RUN RETURNED (fired={state['fired']})", flush=True)
    return 0 if state["fired"] else 1


if __name__ == "__main__":
    sys.exit(main())
