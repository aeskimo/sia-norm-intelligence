#!/usr/bin/env python3
"""REQ-817 Packaging-Smoke: minimales „Hello Window“ (PyInstaller + pywebview).

Wird in der CI (ci.yml → packaging-smoke) auf ubuntu/macos/windows als
PyInstaller-onefile gebaut und gestartet. Das Packaging-Risiko
(PyInstaller + pywebview, WKWebView/WebView2/WebKit2GTK) fällt so in
Woche 1 auf, nicht nach fünf Feature-Steps.

Auto-Schliessen für die CI: Umgebungsvariable ``SIA_HELLO_WINDOW_SECONDS``
(z. B. 5). Der Timer wartet auf das Shown-Event des Backends (dasselbe
Signal, auf das ``window.destroy()`` selbst wartet), schliesst dann das
Fenster und setzt einen harten Backstop-Exit, falls der Destroy-Pfad
des Backends nicht ausläuft (bekanntes Problem: GTK/Xvfb in CI).
Ohne Variable: Fenster bleibt offen bis zum manuellen Schliessen.
Exit-Code 0 = Build + Start erfolgreich; Exit-Code 1 = Fenster wurde
nicht angezeigt (echter Packaging-Fehler).
"""

from __future__ import annotations

import os
import sys
import threading

HTML = (
    "<!doctype html><html lang='de'><head><meta charset='utf-8'>"
    "<style>body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;"
    "display:grid;place-items:center;height:100vh;margin:0;background:#F5F5F7}"
    "div{text-align:center;color:#1D1D1F}</style></head><body><div>"
    "<h1 style='font-size:20px;margin:0 0 8px'>SIA-Normenassistent</h1>"
    "<p style='color:#6E6E73;margin:0'>Packaging-Smoke (REQ-817): "
    "PyInstaller + pywebview OK.</p></div></body></html>"
)


def _diagnose() -> None:
    """Best-effort-Diagnose, wenn das Shown-Event nie kommt (CI: Xvfb/GTK).

    Zeigt, wo der Main-Thread steht (Init-Hang vs. laufender Main-Loop)
    und ob WebKit-Prozesse existieren — das entscheidet über die
    Root-Cause-Klassifikation.
    """
    try:
        import sys
        import traceback

        frames = sys._current_frames()
        main = next((t for t in threading.enumerate() if t.name == "MainThread"), None)
        if main is not None and main.ident in frames:
            stack = traceback.format_stack(frames[main.ident])
            print(
                "[diag] Main-Thread-Stack (letzte Frames):\n" + "".join(stack[-8:]),
                file=sys.stderr,
                flush=True,
            )
    except Exception as e:
        print("[diag] Stack-Dump fehlgeschlagen:", repr(e), file=sys.stderr, flush=True)
    try:
        import subprocess

        out = subprocess.run(
            ["pgrep", "-af", "WebKitWebProcess|WebKitNetworkProcess"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        procs = (out.stdout or "").strip()
        print("[diag] WebKit-Prozesse:", procs or "(keine)", file=sys.stderr, flush=True)
    except Exception as e:
        print("[diag] pgrep fehlgeschlagen:", repr(e), file=sys.stderr, flush=True)
    try:
        from gi.repository import Gtk

        toplevels = Gtk.Window.list_toplevels()
        print(f"[diag] Gtk-Top-Level-Fenster: {len(toplevels)}", file=sys.stderr, flush=True)
        for w in toplevels:
            print(
                f"[diag]   {type(w).__name__} visible={w.get_visible()} "
                f"mapped={w.get_mapped()} title={w.get_title()!r}",
                file=sys.stderr,
                flush=True,
            )
    except Exception as e:
        print("[diag] Gtk-Inspektion nicht möglich:", repr(e), file=sys.stderr, flush=True)


def _auto_close(window) -> None:
    """CI-Auto-Schliessen: Shown-Event abwarten, dann destroy + Backstop.

    Das Shown-Event (Backend-spezifisch, z. B. GTK/WebKit
    ``notify::visible``) kann unter CI langsam kommen (kalte GTK-Init,
    Xvfb). Deshalb wird nicht einmalig 5 s gewartet, sondern gepollt,
    bis ``SIA_HELLO_WINDOW_SHOWN_WAIT`` (Default 30 s) — ein langsamer,
    aber funktionierender Init darf keinen falschen Negativ-Befund
    liefern (Binary-Such 2026-11-25, Linux/Xvfb).

    Ohne das Shown-Event würde ``window.destroy()`` nach 20 s in einem
    Neben-Thread stillschweigend ``WebViewException`` werfen und die App
    für immer weiterlaufen (CI-Hang, beobachtet 2026-11-24 Linux/Xvfb).
    """
    import time

    def _backstop() -> None:
        print("[packaging-smoke] destroy lief nicht aus → Backstop os._exit(0)", file=sys.stderr)
        os._exit(0)

    shown_wait = float(os.environ.get("SIA_HELLO_WINDOW_SHOWN_WAIT", "30"))
    deadline = time.monotonic() + shown_wait
    shown = False
    while time.monotonic() < deadline:
        if window.events.shown.wait(1):
            shown = True
            break

    if shown:
        print("[packaging-smoke] Fenster angezeigt → window.destroy()", file=sys.stderr)
        # Daemon-Thread: Wenn die App normal beendet, stirbt der Backstop
        # mit dem Prozess. Er feuert nur, wenn was wirklich hängen bleibt.
        backstop = threading.Timer(15, _backstop)
        backstop.daemon = True
        backstop.start()
        window.destroy()
    else:
        print(
            "[packaging-smoke] Fenster wurde nicht angezeigt → Diagnose + os._exit(1)",
            file=sys.stderr,
            flush=True,
        )
        _diagnose()
        os._exit(1)


def main() -> int:
    import webview  # lazy: hier ist pywebview garantiert installiert (Build-Dep)

    seconds = float(os.environ.get("SIA_HELLO_WINDOW_SECONDS", "0"))
    window = webview.create_window("SIA-Normenassistent", html=HTML, width=640, height=400)
    if seconds > 0:
        # Erst nach `seconds` (Main-Loop muss voll laufen, sonst greift
        # destroy nicht), dann Shown-Event prüfen, destroy + Backstop.
        threading.Timer(seconds, _auto_close, args=(window,)).start()
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
