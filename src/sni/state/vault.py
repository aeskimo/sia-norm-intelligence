"""Verschlüsselter Status-Store SIASST1 (REQ-815, ADR-0011).

1:1-Port von ``ch.sia.integration.persistence.EncryptedStateVault``
(Java-Referenz): AES-256-GCM, AAD = MAGIC (Formatbindung), 12-Byte-Nonce
je Speicherung, atomarer Austausch via Temp-Datei + ``os.replace``,
Puffer-Bereinigung nach Nutzung.

In Python dient das Format nur zum **Import** des Java-Stands
(``workspace.state``, REQ-815); der Python-Zielzustand ist
``workspace.json`` (non-secret, 09 §9.1).
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from sni.state.keys import StateKeyProvider

#: Datei-Magic (Java 1:1, byte-identisch): ``SIASST1``.
MAGIC = b"SIASST1"
#: AES-GCM-Nonce-Länge (Java: ``GCMParameterSpec(128, …)`` mit 12 Bytes).
NONCE_LENGTH = 12
#: AES-GCM-Authentifizierungstag (128 Bit).
TAG_LENGTH = 16


class StateFormatError(RuntimeError):
    """Statusdatei zu kurz oder falsches Format (Java: SecurityException)."""


class EncryptedStateVault:
    """AES-256-GCM-Dateispeicher mit atomarem Austausch und Formatbindung."""

    def __init__(self, file: Path, keys: StateKeyProvider) -> None:
        self._file = file.resolve()
        self._keys = keys

    @property
    def file(self) -> Path:
        return self._file

    def exists(self) -> bool:
        return self._file.is_file()

    def save(self, plain: bytes) -> None:
        key = self._keys.load()
        nonce = os.urandom(NONCE_LENGTH)
        payload = MAGIC + nonce + AESGCM(key).encrypt(nonce, plain, MAGIC)
        self._file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".sia-state-", suffix=".tmp", dir=self._file.parent)
        try:
            with os.fdopen(fd, "wb") as tmp:
                tmp.write(payload)
            os.replace(tmp_name, self._file)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                os.remove(tmp_name)
            raise
        # Python-Bytes sind unveränderlich; «Zeroing» = Referenz freigegeben.
        del key, payload

    def load(self) -> bytes:
        payload = self._file.read_bytes()
        try:
            if len(payload) < len(MAGIC) + NONCE_LENGTH + TAG_LENGTH:
                raise StateFormatError("Statusdatei zu kurz")
            if payload[: len(MAGIC)] != MAGIC:
                raise StateFormatError("Ungültiges Statusformat")
            nonce = payload[len(MAGIC) : len(MAGIC) + NONCE_LENGTH]
            data = payload[len(MAGIC) + NONCE_LENGTH :]
            # Manipulation → cryptography wirft InvalidTag (Java: AEADBadTagException).
            return AESGCM(self._keys.load()).decrypt(nonce, data, MAGIC)
        finally:
            del payload

    def delete(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._file.unlink()
