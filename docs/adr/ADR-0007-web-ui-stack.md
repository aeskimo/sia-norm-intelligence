# ADR-0007: Web-UI und Consumer-App-Stack (M8)
- Status: akzeptiert (User-Entscheid 2026-11-24)
- Datum: 2026-11-24
- Kontext: M8 macht den Sidecar zur cross-platform Consumer-App
  (docs/09_CONSUMER_APP.md). Die UI muss auf Windows/macOS/Linux laufen,
  offline-fähig sein (G4), keine Build-Toolchain jenseits von Python
  benötigen und die Kern-API (8 Endpunkte, Verträge stehen) unverändert
  lassen. AGENTS.md §5 erlaubt Laufzeit-Abhängigkeiten nur via ADR.
- Entscheidung:
  - UI = statisches HTML/CSS/JS + **HTMX** (vendor-bundled, keine
    npm/Build-Step), ausgeliefert von derselben FastAPI-App
    (same-origin auf `127.0.0.1` mit zufälligem Port, kein CORS,
    CSP `default-src 'self'`). Interaktives Zusatz-JS (~300 Zeilen
    Vanilla): SSE-Streaming, Job-Polling, pdf.js-Modal.
  - App-Shell = **pywebview** (System-Webview) als Fenster-Modus,
    `--browser` (Standardbrowser) und `--headless` (CI) als Modi;
    Launcher `python -m sni.app` (Main-Thread = Fenster,
    Hintergrund-Thread = uvicorn). User-Entscheid 24.11.2026: kein
    Tray-Icon, keine Multi-Window → pywebview. Die UI ist
    shell-agnostisch (statische Dateien); Tauri bleibt
    Eskalations-Option ohne UI-Rework (OQ-009).
  - **App-API-Sicherheit (REQ-816):** zufälliger freier Port pro Start
    (Fenster-/Browser-Modus); Session-Token vom Launcher an die UI
    (`?sia_token=` oder Header `X-Sia-Token`, Pflicht auf `/v1/*`);
    `Host`-Header muss loopback sein, nicht-same-origin `Origin` wird
    abgelehnt — Schutz gegen CSRF/DNS-Rebinding durch lokale Prozesse
    und Browser-Tabs. Nur `app_mode=True`.
  - Neue **Laufzeit-Abhängigkeiten**: `httpx` (SOAP/Ollama/gibb-Client),
    `cryptography` (AES-256-GCM App-Daten, DES SIA-Protokoll; Version
    gepinnt, da (3-)DES in neueren Versionen als decrepit markiert —
    Known-Answer-Test REQ-801), `pdfminer.six` **und** `pypdfium2`
    (PDF-Textextraktion ohne System-Binary; Fixture-Gate REQ-804
    entscheidet, welche bleibt; die andere wird danach entfernt),
    `keyring` (cross-platform Credentials), `pywebview` (Fenster).
  - **Build-Abhängigkeiten** (keine Laufzeit): `pyinstaller`
    (Installer), `playwright` (UI-Tests, Dev-Extra).
  - Neue App-Endpunkte (sni/app/api.py, nur `app_mode=True`):
    `/v1/status`, `/v1/session/*`, `/v1/catalog`, `/v1/documents*`,
    `/v1/ask` (SSE), `/v1/worksets*`, `/v1/models/ollama*`,
    `/v1/settings`, `/v1/ingest/semantic-export`, `/v1/review/*`
    (ADR-0008), `/v1/jobs`; neue Schemas: `sni:status`,
    `sni:catalog_item`, `sni:local_document`, `sni:job`,
    `sni:workset`, `sni:settings`, `sni:rag_answer`.
  - UI-PDF via **pdf.js** (vendor-bundled) statt OS-Viewer.
  - **Packaging-Smoke früh (REQ-817):** minimale App (Hello Window)
    wird ab M8.1 in der 3-OS-CI gebaut und gestartet, damit das
    Packaging-Risiko (PyInstaller + pywebview, WebView2/WebKitGTK,
    Signing) in Woche 1 auffällt und nicht nach fünf Feature-Steps.
- Konsequenzen:
  - Echter: eine Codebasis, kein 2. Sprach-Team, offline, small footprint.
  - `sni/app` wird oberstes Modul (Schichten-Regel: nur nach unten);
    `sni/api/main.py` erhält nur den `app_mode`-Switch.
  - Windows/WebView2, Linux/WebKitGTK sind Systemvoraussetzungen
    (Doku + `--browser`-Fallback).
- Verworfene Alternativen:
  - **Tauri v2**: poliertere Shell, aber Rust-Toolchain + 2. Build-System
    in einem Python-Repo; bleibt Eskalations-Option (OQ-009).
  - **Electron**: Fussabdruck (100+ MB) unzumutbar für local-first.
  - **SPA (React/Vue + Vite)**: npm-Toolchain + Build-Pipeline +
    Versionssprünge für einen Server-gedrehten Local-Use.
  - **Jinja-Server-Rendern**: kein sauberes Streaming/Interaktivitätsmodell.
  - **PyMuPDF**: AGPL-Lizenz — ausgeschlossen (User-Entscheid
    24.11.2026).
  - **pdftotext/Poppler** als System-Binary: 3× native Pakete,
    Consumer-Installation bruchanfällig (OQ-010).
