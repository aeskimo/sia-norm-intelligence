#!/usr/bin/env python3
"""REQ-817 Packaging-Smoke: minimales „Hello Window“ (PyInstaller + pywebview).

Wird in der CI (ci.yml → packaging-smoke) auf ubuntu/macos/windows als
PyInstaller-onefile gebaut und gestartet. Das Packaging-Risiko
(PyInstaller + pywebview, WKWebView/WebView2/WebKit2GTK) fällt so in
Woche 1 auf, nicht nach fünf Feature-Steps.

Auto-Schliessen für die CI: Umgebungsvariable ``SIA_HELLO_WINDOW_SECONDS``
(z. B. 5). Ohne Variable: Fenster bleibt offen bis zum manuellen Schliessen.
Exit-Code 0 = Build + Start erfolgreich.
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


def main() -> int:
    import webview  # lazy: hier ist pywebview garantiert installiert (Build-Dep)

    seconds = float(os.environ.get("SIA_HELLO_WINDOW_SECONDS", "0"))
    window = webview.create_window("SIA-Normenassistent", html=HTML, width=640, height=400)
    if seconds > 0:
        threading.Timer(seconds, window.destroy).start()
    webview.start()
    return 0


if __name__ == "__main__":
    sys.exit(main())
