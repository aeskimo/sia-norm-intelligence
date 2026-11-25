"""REQ-802: Keyring-3-OS-Interop (ADR-0011 Punkt 7, 09 §10.1).

macOS: Java-Keychain-Einträge (geschrieben via ``security``-Binary —
derselbe Weg wie Java ``SecurityCommand``) müssen unter gleichem
Service/Account lesbar sein. Verifiziert deterministisch ohne
Benutzerauswirkung:

- Eintrag per ``security add-generic-password`` anlegen (Java-Wege
  1:1), per ``security find-generic-password`` unter gleichem
  Service/Account zurücklesen (Java-Lesezugriff 1:1).
- Python-Seite: das ``keyring``-Backend dieser Umgebung ist das
  macOS-Keychain-Backend (dieselbe Security-Framework-API, gleicher
  Service/Account). Der erste Cross-App-Zugriff von ``keyring`` auf
  einen von ``security`` angelegten Eintrag löst im
  Produktivbetrieb die einmalige macOS-ACL-Bestätigung aus
  («Immer erlauben») — ein macOS-Verhalten, kein App-Code.

Windows/Linux: dokumentierte Abwesenheit — die Java-App hatte dort
keinen Store (``available() == false``), es gibt keine Java-Einträge.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys

import keyring
import pytest
from keyring.errors import NoKeyringError

from sni.secrets.keyring_store import ACCOUNT_STATE_KEY, SERVICE

_MACOS_KEYRING_MODULE = "keyring.backends.macOS"


def _security(args: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["security", *args], capture_output=True, text=True, timeout=timeout)


@pytest.mark.skipif(
    sys.platform != "darwin",
    reason="Java-Keyring-Store existierte nur auf macOS (Windows/Linux: dokumentierte Abwesenheit)",
)
def test_req802_java_keychain_entry_readable_same_service_account() -> None:
    # Python-Seite: macOS-Keychain-Backend vorhanden (Read-Pfad der App).
    try:
        backend = keyring.get_keyring()
    except NoKeyringError as exc:
        pytest.skip(f"keyring-Backend nicht verfügbar in dieser Umgebung: {exc}")
    if not type(backend).__module__.startswith(_MACOS_KEYRING_MODULE):
        pytest.skip(f"keyring nutzt kein macOS-Backend: {type(backend).__module__}")

    secret = base64.b64encode(os.urandom(32)).decode("ascii")
    # Sicherheit: einen bereits vorhandenen Eintrag (echter
    # Statusschlüssel) niemals überschreiben oder löschen.
    existing = _security(["find-generic-password", "-s", SERVICE, "-a", ACCOUNT_STATE_KEY, "-w"])
    if existing.returncode == 0:
        pytest.skip("Eintrag state-key existiert bereits — echten Schlüssel nicht antasten")
    # Java-Schreibweg (SecurityCommand.runWithSecret): -w <wert> als Argument.
    add = _security(
        ["add-generic-password", "-U", "-s", SERVICE, "-a", ACCOUNT_STATE_KEY, "-w", secret]
    )
    if add.returncode != 0:
        pytest.skip(f"macOS-Keychain nicht verfügbar: {(add.stderr or add.stdout).strip()}")
    try:
        # Java-Leseweg (SecurityCommand.run): -s <service> -a <account> -w.
        find = _security(["find-generic-password", "-s", SERVICE, "-a", ACCOUNT_STATE_KEY, "-w"])
        assert find.returncode == 0, f"security find fehlgeschlagen: {find.stderr.strip()}"
        assert find.stdout.strip() == secret
    finally:
        _security(["delete-generic-password", "-s", SERVICE, "-a", ACCOUNT_STATE_KEY])
