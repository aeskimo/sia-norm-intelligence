"""REQ-817: Packaging-Smoke — Hello-Window-Skript und CI-Matrix (3 OS).

Der eigentliche Smoke (PyInstaller-Build + Start) läuft in der CI
(ci.yml → Job ``packaging-smoke``). Diese Tests sichern, dass das Skript
und die CI-Matrix vorhanden und konsistent bleiben.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HELLO = REPO_ROOT / "packaging" / "hello_window.py"
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def test_req817_hello_window_script_exists_and_compiles() -> None:
    # Given das Packaging-Skript When kompiliert Then syntaktisch gültig
    assert HELLO.is_file(), "packaging/hello_window.py fehlt"
    text = HELLO.read_text(encoding="utf-8")
    compile(text, str(HELLO), "exec")


def test_req817_hello_window_supports_auto_close() -> None:
    # Given das Packaging-Skript When geprüft Then Auto-Schliessen für die CI
    text = HELLO.read_text(encoding="utf-8")
    assert "SIA_HELLO_WINDOW_SECONDS" in text
    assert "webview.create_window" in text and "webview.start()" in text


def test_req817_ci_has_packaging_smoke_on_three_os() -> None:
    # Given die CI When geprüft Then packaging-smoke-Job mit Matrix auf 3 OS
    text = CI.read_text(encoding="utf-8")
    assert "packaging-smoke" in text
    for os_name in ("ubuntu-latest", "macos-latest", "windows-latest"):
        assert os_name in text, f"OS fehlt in der CI-Matrix: {os_name}"
    # Linux braucht WebKit2GTK + Xvfb für den Start im Runner
    assert "libwebkit2gtk" in text
    assert "xvfb" in text.lower()
    # Auto-Schliessen ist in der CI gesetzt
    assert "SIA_HELLO_WINDOW_SECONDS" in text


def test_req817_ci_smoke_builds_with_pyinstaller() -> None:
    # Given die CI When packaging-smoke Then PyInstaller-onefile-Build
    text = CI.read_text(encoding="utf-8")
    assert "pyinstaller" in text.lower()
    assert re.search(r"pyinstaller\s+--onefile", text, re.IGNORECASE)
    assert "packaging/hello_window.py" in text
