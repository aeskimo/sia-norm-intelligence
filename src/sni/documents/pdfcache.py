"""Sitzungs-PDF-Cache (REQ-803).

1:1-Port von ``ch.sia.reader.product.storage.SessionDocumentCache``:
sitzungsgebundener AES-256-GCM-Zwischenspeicher für entschlüsselte
PDFs. Der Sitzungsschlüssel wird beim Konstruieren erzeugt und beim
Schliessen verworfen; jeder Eintrag wird mit frischem 12-Byte-Nonce,
128-Bit-Tag und ``AAD = Dokument-ID`` (UTF-8) verschlüsselt.

Zeroing: Java überschreibt die Nonce-/Ciphertext-Bytearrays mit Nullen
(``Arrays.fill``). Die Python-Äquivalente ist die In-Place-Überschreibung
der ``bytearray``-Puffer plus das Loslassen der prozessinternen Referenz
(„bytes"-Immunität). G4: Der Sitzungsschlüssel verlässt den Prozess nie.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

#: Java: ``id.matches("[A-Za-z0-9._-]{1,160}")`` (Volle-Übereinstimmung).
_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,160}")
_NONCE_LENGTH = 12  # Java: GCMParameterSpec(128, 12-Byte-Nonce); cryptography: Tag = 128 Bit


class SessionCacheError(RuntimeError):
    """Cache geschlossen oder Verschlüsselung fehlgeschlagen.

    Java: ``IllegalStateException`` („Cache geschlossen",
    „Cache-Verschlüsselung fehlgeschlagen").
    """


class CacheIntegrityError(Exception):
    """Eintrag beschädigt — GCM-Entschlüsselung fehlgeschlagen.

    Java: ``SecurityException("Cache beschädigt")``.
    """


@dataclass(slots=True)
class _Entry:
    """Interne Cache-Position (Java: ``record Entry(byte[] nonce, byte[] ciphertext)``)."""

    nonce: bytearray
    ciphertext: bytearray


def _require_id(document_id: str) -> None:
    """Java: ``requireId`` — Regex 1:1, sonst ``IllegalArgumentException``."""
    if _ID_RE.fullmatch(document_id) is None:
        raise ValueError("Ungültige Dokument-ID")


class SessionDocumentCache:
    """Sitzungsgebundener AES-GCM-Zwischenspeicher (Java: ``SessionDocumentCache``)."""

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._key: bytes | None = AESGCM.generate_key(256)  # Java: KeyGenerator "AES" 256
        self._lock = threading.RLock()  # Java: synchronized-Methoden

    # ------------------------------------------------------------------ öffentlich

    def put(self, document_id: str, pdf: bytes) -> None:
        """Java: ``put`` — AES-256-GCM, AAD = Dokument-ID, frischer 12-Byte-Nonce."""
        with self._lock:
            key = self._require_open()
            _require_id(document_id)
            try:
                nonce = bytearray(os.urandom(_NONCE_LENGTH))  # Java: SecureRandom.nextBytes
                aesgcm = AESGCM(key)
                encrypted = aesgcm.encrypt(bytes(nonce), pdf, document_id.encode("utf-8"))
                ciphertext = bytearray(encrypted)
                self._wipe(self._entries.pop(document_id, None))
                self._entries[document_id] = _Entry(nonce, ciphertext)
            except Exception as exc:  # noqa: BLE001 — Java: catch (Exception e)
                raise SessionCacheError("Cache-Verschlüsselung fehlgeschlagen") from exc

    def get(self, document_id: str) -> bytes | None:
        """Java: ``get`` — None, wenn der Eintrag fehlt (``Optional.empty``)."""
        with self._lock:
            key = self._require_open()
            _require_id(document_id)
            entry = self._entries.get(document_id)
            if entry is None:
                return None
            try:
                return AESGCM(key).decrypt(
                    bytes(entry.nonce), bytes(entry.ciphertext), document_id.encode("utf-8")
                )
            except Exception as exc:  # noqa: BLE001 — Java: catch (Exception x)
                raise CacheIntegrityError("Cache beschädigt") from exc

    def contains(self, document_id: str) -> bool:
        """Java: ``contains``."""
        with self._lock:
            self._require_open()
            _require_id(document_id)
            return document_id in self._entries

    def size(self) -> int:
        """Java: ``size``."""
        with self._lock:
            self._require_open()
            return len(self._entries)

    def delete(self, document_id: str) -> None:
        """Java: ``delete`` — Eintrag entfernen mit Zeroing (fehlt = no-op)."""
        with self._lock:
            self._require_open()
            _require_id(document_id)
            self._wipe(self._entries.pop(document_id, None))

    def close(self) -> None:
        """Java: ``close`` — alle Einträge wipen, Sitzungsschlüssel verwerfen."""
        with self._lock:
            for entry in self._entries.values():
                self._wipe(entry)
            self._entries.clear()
            self._key = None

    def __enter__(self) -> SessionDocumentCache:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # ------------------------------------------------------------------ intern

    def _require_open(self) -> bytes:
        """Java: ``ensure`` — wirft, wenn der Cache geschlossen ist."""
        key = self._key
        if key is None:
            raise SessionCacheError("Cache geschlossen")
        return key

    @staticmethod
    def _wipe(entry: _Entry | None) -> None:
        """Java: ``wipe`` — Nonce und Ciphertext in-place mit Nullen überschreiben."""
        if entry is None:
            return
        entry.nonce[:] = b"\x00" * len(entry.nonce)
        entry.ciphertext[:] = b"\x00" * len(entry.ciphertext)
