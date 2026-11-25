"""M10 (REQ-1002): CI-Signing-Gerüst (ohne Credentials).

Der Signing-Pfad selbst läuft in der CI nur, wenn die Flags
``vars.MACOS_SIGNING_ENABLED`` / ``vars.WINDOWS_SIGNING_ENABLED``
gesetzt sind (plus die zugehörigen Secrets). Diese Tests sichern das
Gerüst: die Skripte existieren und sind syntaktisch gültig, und die CI
enthält die bedingten Signing-Steps zwischen Build und Smoke.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"
SCRIPTS = (
    REPO_ROOT / "packaging" / "sign" / "macos_sign.sh",
    REPO_ROOT / "packaging" / "sign" / "windows_sign.sh",
)


def test_req1002_signing_scripts_exist_and_compile() -> None:
    for script in SCRIPTS:
        assert script.is_file(), f"{script} fehlt"
        subprocess.run(["bash", "-n", str(script)], check=True)


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
