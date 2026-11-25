"""REQ-814/REQ-800: UI-Gerüst — statische Dateien und Design-Baseline.

Prüft, dass das UI-Gerüst (M8.1) die Baseline trägt: 6 Views,
SIA-Design-Tokens (Light + Dark via prefers-color-scheme), CSP,
Session-Token-Handling und volle Offline-Fähigkeit (keine externen
Resources).
"""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sni" / "app" / "static"

VIEWS = ("catalog", "norms", "assistant", "intelligence", "models", "settings")


def _read(name: str) -> str:
    assert (STATIC / name).is_file(), f"UI-Datei fehlt: {name}"
    return (STATIC / name).read_text(encoding="utf-8")


def test_req814_index_has_all_six_views() -> None:
    # Given die UI When geladen Then alle 6 Views (Java-Tabs) existieren
    html = _read("index.html")
    for view in VIEWS:
        assert f'href="#/{view}"' in html, f"Nav-Link #{view} fehlt"
        assert f'id="view-{view}"' in html, f"View-Sektion {view} fehlt"


def test_req814_index_is_deutsch_and_has_csp() -> None:
    # Given die UI When geladen Then Deutsch + CSP default-src 'self'
    html = _read("index.html")
    assert 'lang="de"' in html
    assert "Content-Security-Policy" in html and "default-src 'self'" in html


def test_req814_index_status_rows_are_live_regions() -> None:
    # Given die UI When geladen Then Statuszeilen sind aria-live (Barrierefreiheit)
    html = _read("index.html")
    assert html.count('aria-live="polite"') >= len(VIEWS)


def test_req814_css_has_sia_design_tokens() -> None:
    # Given das Design-System When geprüft Then SIA-Tokens (Java-Palette)
    css = _read("sia.css")
    for token in (
        "--window: #F5F5F7",
        "--surface: #FFFFFF",
        "--text: #1D1D1F",
        "--accent: #0066E6",
        "--radius-card: 12px",
    ):
        assert token in css, f"Token fehlt: {token}"


def test_req814_css_has_dark_mode() -> None:
    # Given das Design-System When Dark Mode Then prefers-color-scheme mit
    # DARK-Palette (wie SiaDesign in Java)
    css = _read("sia.css")
    assert "prefers-color-scheme: dark" in css
    assert "--window: #1E1E1E" in css
    assert "--text: #F2F2F7" in css


def test_req814_js_shows_login_diagnostic() -> None:
    # Given ein Login-Fehler mit G4-sicherer Diagnose When die UI den
    # Fehler zeigt Then ist die Diagnose (eingereichte Werte ohne
    # Passwort-Bytes) neben der Fehlermeldung sichtbar.
    js = _read("app.js")
    assert "err.diagnostic = data.diagnostic || null;" in js
    assert 'msg += " — " + err.diagnostic;' in js


def test_req814_js_prefills_device_id_like_java() -> None:
    # Given das Login-Formular (1:1 Java NormenAssistentApp:
    # "SIA-APP-" + UUID.randomUUID()) When die UI geladen Then ist die
    # Geräte-ID präbefüllt (die alte App generierte sie pro Start).
    js = _read("app.js")
    assert 'deviceField = $("login-device")' in js
    assert '"SIA-APP-" + crypto.randomUUID()' in js


def test_req814_js_handles_session_token_in_memory() -> None:
    # Given die UI-Logik When gestartet Then Token kommt aus der URL und
    # wird an API-Requests übergeben (REQ-816)
    js = _read("app.js")
    assert 'params.get("sia_token")' in js
    assert '"x-sia-token": siaToken' in js
    # Token wird aus der Adressleiste entfernt
    assert "history.replaceState" in js


def test_req814_norms_view_exposes_analyze() -> None:
    # Given 09 §5.1 (Aktionen der Normen-View: Öffnen, Analysieren, Entfernen)
    # When die UI geprüft Then ist der API-Endpunkt REQ-804 auch in der UI
    # verfügbar («Analysieren»-Button pro Dokument) und die Job-Zeile zeigt
    # Analyse-Jobs (download + analyze) an.
    js = _read("app.js")
    assert 'data-analyze="' in js, "«Analysieren»-Button fehlt in der Normen-View"
    assert "/analyze" in js, "Analyse-Endpunkt nicht in der UI verdrahtet"
    assert 'j.kind === "download" || j.kind === "analyze"' in js


def test_req814_assistant_has_model_dropdown() -> None:
    # Given das Antwortmodell pro Ansicht wählbar sein soll (User-Wunsch)
    # When die UI geprüft Then trägt die Assistent-View ein Antwortmodell-
    # Dropdown, das den gewählten Wert in die globalen Einstellungen
    # (generation_model bzw. gibb_model je Provider) zurückspielt.
    html = _read("index.html")
    js = _read("app.js")
    assert 'id="ask-model"' in html, "Antwortmodell-Dropdown fehlt in der Assistent-View"
    assert "refreshAskModelSelect" in js
    assert "gibb_model" in js and "generation_model" in js


def test_req814_help_covers_all_work_views() -> None:
    # Given die Bereichshilfe When geprüft Then jeder Arbeitsbereich (ohne
    # die Onboarding-View, die selbst die Hilfe ist) hat einen Eintrag mit
    # Kurz-Hinweis (tip) und Volltext (sections).
    js = _read("help.js")
    for view in VIEWS:
        assert f"{view}: {{" in js, f"Hilfe-Eintrag für '{view}' fehlt"
    assert js.count("tip:") == len(VIEWS)
    assert js.count("sections:") == len(VIEWS)


def test_req814_help_panel_hooked_into_router() -> None:
    # Given die Bereichshilfe verdrahtet When die UI geladen Then lädt
    # index.html help.js und der Hash-Router ruft pro View
    # SiaHelp.init(view) auf (Erstbesuchs-Hinweis + Hilfe-Button).
    html = _read("index.html")
    js = _read("app.js")
    assert '<script src="/static/help.js"></script>' in html
    assert "SiaHelp.init(view)" in js


def test_req814_ui_is_fully_offline() -> None:
    # Given die UI (G4/CSP) When geprüft Then keine externen Resources
    for name in ("index.html", "sia.css", "app.js", "help.js"):
        content = _read(name)
        for line in content.splitlines():
            assert "http://" not in line and "https://" not in line, (
                f"Externe Resource in {name}: {line.strip()[:60]}"
            )
