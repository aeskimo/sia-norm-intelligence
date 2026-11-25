#!/usr/bin/env python3
"""CI-Binary-Such-Probe P1 (nur Linux/Xvfb): feuert ``activate`` bei
einem plainen ``Gtk.Application``?

Exakt derselbe Form wie pywebview's GTK-Backend (``webview/platforms/
gtk.py``: ``gtk.Application.new(None, 0)`` ohne application_id,
``connect('activate', ...)`` + ``run()`` ohne argv), aber ohne
pywebview und ohne PyInstaller — reines PyGObject. Isoliert, ob die
GHA-Linux-Umgebung (Xvfb + D-Bus-Session-Bus) GtkApplication-Instanzen
überhaupt aktivieren kann (Diagnose 2026-11-25, Run 45514306284:
Main-Thread in ``Gio.Application.run``, 0 Gtk-Fenster, 0 WebKit-
Prozesse, kein Traceback).

Aufruf:  xvfb-run --auto-servernum python3 packaging/ci_gtk_probe.py
Exit 0 = ``activate`` gefeuert + Fenster gezeigt.
Exit 1 = Watchdog: Prozess läuft, aber Zustand unklar (Details im Log).
"""

from __future__ import annotations

import os
import sys
import threading

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

    app = Gtk.Application.new(None, 0)
    state = {"fired": False}

    def _quit() -> bool:
        app.quit()
        return False

    def on_activate(_application: Gtk.Application) -> None:
        state["fired"] = True
        print("P1: ACTIVATE FIRED", flush=True)
        # Wie pywebview (gtk.py:79): ApplicationWindow mit application=_app.
        window = Gtk.ApplicationWindow(application=app)
        window.set_title("sni-p1-probe")
        window.show_all()
        print(f"P1: window visible={window.get_visible()}", flush=True)
        GLib.timeout_add(2000, _quit)

    def _watchdog() -> None:
        print(
            f"[P1] Watchdog (20 s): fired={state['fired']} → os._exit(1)",
            file=sys.stderr,
            flush=True,
        )
        os._exit(1)

    watchdog = threading.Timer(20, _watchdog)
    watchdog.daemon = True
    watchdog.start()

    app.connect("activate", on_activate)
    # Identisch zu pywebview (gtk.py:779): ``_app.run()`` ohne argv.
    app.run()

    print(f"P1: RUN RETURNED (fired={state['fired']})", flush=True)
    return 0 if state["fired"] else 1


if __name__ == "__main__":
    sys.exit(main())
