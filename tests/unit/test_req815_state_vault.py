"""REQ-815: Verschlüsselter Status-Store SIASST1 (Port von
``EncryptedStateVault``, Java-Referenz).

Roundtrip, kein Klartext auf Disk, Manipulations-/Format-Abweisung,
atomares Schreiben ohne Reste, Keyless-Fehler.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from sni.state.keys import StateKeyProvider
from sni.state.vault import MAGIC, NONCE_LENGTH, TAG_LENGTH, EncryptedStateVault, StateFormatError

KEY = bytes((7,) * 32)


class _StaticKeys:
    """Test-Schlüsselquelle (Java-Referenz: Lambda-Provider)."""

    def __init__(self, key: bytes | None) -> None:
        self._key = key

    def load(self) -> bytes:
        if self._key is None:
            raise RuntimeError("kein Schlüssel")
        return self._key

    def available(self) -> bool:
        return self._key is not None


def _vault(tmp_path: Path, key: bytes | None = KEY) -> EncryptedStateVault:
    return EncryptedStateVault(tmp_path / "workspace.state", _StaticKeys(key))


def test_req815_vault_roundtrip(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    assert vault.exists() is False
    vault.save(b"vertraulicher Zustand")
    assert vault.exists() is True
    assert vault.load() == b"vertraulicher Zustand"


def test_req815_vault_no_plaintext_on_disk(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    vault.save("Nassräume qwen3:8b".encode())
    raw = vault.file.read_bytes()
    assert "Nassräume".encode() not in raw
    assert b"qwen3:8b" not in raw
    # Formatbindung: Magic + 12-Byte-Nonce + GCM-Tag (>= 16).
    assert raw[: len(MAGIC)] == MAGIC
    assert len(raw) >= len(MAGIC) + NONCE_LENGTH + TAG_LENGTH


def test_req815_vault_tamper_rejected(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    vault.save(b"geheim")
    raw = bytearray(vault.file.read_bytes())
    raw[-1] ^= 1
    vault.file.write_bytes(bytes(raw))
    with pytest.raises(InvalidTag):
        vault.load()


def test_req815_vault_wrong_key_rejected(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    vault.save(b"geheim")
    other = EncryptedStateVault(vault.file, _StaticKeys(bytes((9,) * 32)))
    with pytest.raises(InvalidTag):
        other.load()


def test_req815_vault_too_short_rejected(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    vault.file.parent.mkdir(parents=True, exist_ok=True)
    vault.file.write_bytes(MAGIC + b"\x00" * 10)
    with pytest.raises(StateFormatError, match="Statusdatei zu kurz"):
        vault.load()


def test_req815_vault_bad_magic_rejected(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    vault.file.parent.mkdir(parents=True, exist_ok=True)
    vault.file.write_bytes(b"XXXXXXX" + b"\x00" * (NONCE_LENGTH + TAG_LENGTH))
    with pytest.raises(StateFormatError, match="Ungültiges Statusformat"):
        vault.load()


def test_req815_vault_keyless_save_fails(tmp_path: Path) -> None:
    vault = _vault(tmp_path, key=None)
    with pytest.raises(RuntimeError, match="kein Schlüssel"):
        vault.save(b"nichts")
    assert vault.exists() is False


def test_req815_vault_atomic_no_leftovers(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    vault.save(b"einmal")
    vault.save(b"zweimal")
    names = [p.name for p in vault.file.parent.iterdir()]
    assert names == ["workspace.state"]  # Keine .sia-state-*.tmp-Reste.


def test_req815_vault_delete(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    vault.save(b"geheim")
    assert vault.exists() is True
    vault.delete()
    assert vault.exists() is False
    vault.delete()  # Zweite Löschung: still (Ziel-Zustand bereits erreicht).


def test_req815_vault_load_missing_file(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    with pytest.raises(FileNotFoundError):
        vault.load()


def test_req815_vault_key_provider_protocol() -> None:
    # Statische Typprüfung: _StaticKeys erfüllt das StateKeyProvider-Protokoll.
    keys: StateKeyProvider = _StaticKeys(KEY)
    assert keys.available() is True
    assert keys.load() == KEY
