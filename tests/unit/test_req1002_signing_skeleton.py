"""M10 (REQ-1002): CI-Signing-Gerüst (ohne Credentials).

Der Signing-Pfad selbst läuft in der CI nur, wenn die Flags
``vars.MACOS_SIGNING_ENABLED`` / ``vars.WINDOWS_SIGNING_ENABLED``
gesetzt sind (plus die zugehörigen Secrets). Diese Tests sichern das
Gerüst: die Skripte existieren und sind syntaktisch gültig, und die CI
enthält die bedingten Signing-Steps zwischen Build und Smoke.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SCRIPTS = (
    REPO_ROOT / "packaging" / "sign" / "macos_sign.sh",
    REPO_ROOT / "packaging" / "sign" / "windows_sign.sh",
)


def _bash() -> str | None:
    """Bash-Pfad für die Syntaxprüfung; ``None`` → Check wird übersprungen.

    Windows: explizit Git-Bash nehmen. Der PATH-``bash`` ist auf GHA-
    Windows-Runnern teils der WSL-Stub (``C:\\Windows\\System32``),
    der ohne installierte Distribution nicht funktioniert — der CI-
    Step selbst nutzt Git-Bash (``C:\\Program Files\\Git\\bin\\bash.EXE``,
    s. Step-Logs), und der ist auf den Runnern standardmässig da.
    """
    if os.name != "nt":
        return "bash"
    git_bash = Path(r"C:\Program Files\Git\bin\bash.EXE")
    return str(git_bash) if git_bash.exists() else None


def test_req1002_signing_scripts_exist_and_compile() -> None:
    for script in SCRIPTS:
        assert script.is_file(), f"{script} fehlt"
    bash = _bash()
    if bash is None:
        pytest.skip("Git-Bash nicht verfügbar (Windows ohne Git-Installation)")
    for script in SCRIPTS:
        subprocess.run([bash, "-n", str(script)], check=True)


def test_req1002_signing_scripts_fail_fast_without_env() -> None:
    # Ohne Signing-Env-Variablen brechen die Skripte mit sauberem
    # Fehler ab (vor jeder OS-spezifischen Aktion) — Cross-Platform,
    # weil der Env-Check vor security/codesign/signtool steht.
    bash = _bash()
    if bash is None:
        pytest.skip("Git-Bash nicht verfügbar (Windows ohne Git-Installation)")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("MACOS_SIGNING", "WINDOWS_SIGNING", "APPLE_"))
    }
    for script in SCRIPTS:
        proc = subprocess.run(
            [bash, str(script), "dummy-target"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert proc.returncode != 0, f"{script} ohne Env-Variablen nicht abgebrochen"
        assert "fehlt" in proc.stdout + proc.stderr


def test_req1002_ci_has_conditional_signing_steps() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "MACOS_SIGNING_ENABLED" in text
    assert "WINDOWS_SIGNING_ENABLED" in text
    assert "packaging/sign/macos_sign.sh" in text
    assert "packaging/sign/windows_sign.sh" in text


def test_req1002_signing_runs_before_smoke() -> None:
    # Das signierte Artefact ist das, was der Smoke startet: die
    # Signing-Steps müssen vor dem Launch-Smoke-Step stehen. (Anker:
    # Step-Definition, nicht der Job-Kommentar.)
    text = CI.read_text(encoding="utf-8")
    smoke = text.index('- name: "Launch-Smoke')
    assert text.index("packaging/sign/macos_sign.sh") < smoke
    assert text.index("packaging/sign/windows_sign.sh") < smoke
