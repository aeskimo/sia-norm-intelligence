"""Credentials & Statusschlüssel im OS-Keyring (REQ-802, ADR-0009).

Cross-platform-Port von ``ch.sia.integration.persistence`` (Java-Referenz:
``CredentialStore``, ``GibbApiKeyStore``, ``KeychainStateKeyProvider``,
``SecurityCommand``). Geklammert bleibt 1:1:

- Service ``ch.sia.normenassistent``, Accounts ``sia-login``,
  ``gibb-api-key``, ``state-key`` — gleiches Layout wie Java, daher sind
  Einträge auf macOS zwischen Java- und Python-App gegenseitig lesbar
  (Migration, REQ-802).
- Payload-Formate 1:1:
  - ``sia-login``:    ``b64url(customer)|b64url(password)`` (URL-safe,
    ohne Padding)
  - ``gibb-api-key``: ``b64url(key)`` (URL-safe, ohne Padding)
  - ``state-key``:    Standard-Base64 der 32 rohen Schlüsselbytes

Backends:
- Nativ: ``keyring``-Bibliothek (macOS Keychain, Windows Credential
  Manager, Linux Secret Service/KWallet).
- Fake (3-OS-Test): ``SIA_FAKE_KEYCHAIN=<Verzeichnis>`` → dateibasierter
  Store ``<dir>/<service>/<account>`` — 1:1 zum gefakten ``security``-
  Binary im Java-Testskript (``run-all-tests.command``).
- Fallback ohne Secret-Service: das ``keyring``-File-Backend (niedrige
  Priorität) → ``backend_kind() == "file"``; /settings zeigt die sichtbare
  Warnung (verminderter Schutz, ADR-0009).
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import keyring

#: Keyring-Service, identisch zu Java (``CredentialStore.SERVICE``).
SERVICE = "ch.sia.normenassistent"
#: SIA-Login-Zugangsdaten (Java: ``CredentialStore.ACCOUNT``).
ACCOUNT_SIA_LOGIN = "sia-login"
#: gibb-API-Key (Java: ``GibbApiKeyStore.ACCOUNT``).
ACCOUNT_GIBB_API_KEY = "gibb-api-key"
#: 256-Bit-Statusschlüssel (Java: ``KeychainStateKeyProvider.ACCOUNT``).
ACCOUNT_STATE_KEY = "state-key"
#: Env-Variablen-Name des dateibasierten Fake-Keyrings (wie im Java-Testskript).
FAKE_KEYCHAIN_ENV = "SIA_FAKE_KEYCHAIN"

#: Maximale Länge eines gibb-API-Keys (Java: ``GibbApiKeyStore.store``).
GIBB_KEY_MAX_LENGTH = 4000
#: Länge des Statusschlüssels in Bytes (AES-256, Java: 32).
STATE_KEY_LENGTH = 32


class KeyringError(RuntimeError):
    """Basis-Fehler der Keyring-Operationen (REQ-802)."""


class KeyringUnavailableError(KeyringError):
    """Kein verwertbarer Keyring-Backend vorhanden."""


class StateKeyError(KeyringError):
    """Statusschlüssel fehlt oder ist ungültig (Länge/Format)."""


class KeyringBackend(Protocol):
    """Abstraktion über das konkrete Secret-Store-Backend (Test-Injection)."""

    @property
    def kind(self) -> str:
        """``"fake" | "native" | "file" | "none"``."""

    def get(self, service: str, account: str) -> str | None:
        """Payload lesen; ``None``, wenn der Eintrag nicht existiert."""

    def set(self, service: str, account: str, payload: str) -> None:
        """Payload schreiben (überschreibt bestehende Einträge, Java: -U)."""

    def delete(self, service: str, account: str) -> None:
        """Eintrag löschen (fehlend = gewünschter Endzustand)."""


class LibraryKeyringBackend:
    """``keyring``-Bibliothek: natives Secret Store oder File-Fallback."""

    @property
    def kind(self) -> str:
        try:
            backend = keyring.get_keyring()
        except Exception:
            return "none"
        priority = float(getattr(backend, "priority", 0.0) or 0.0)
        if priority >= 2.0:
            return "native"
        if priority >= 1.0:
            return "file"  # keyring-File-Backend ohne Secret Service
        return "none"

    def get(self, service: str, account: str) -> str | None:
        return keyring.get_password(service, account)

    def set(self, service: str, account: str, payload: str) -> None:
        keyring.set_password(service, account, payload)

    def delete(self, service: str, account: str) -> None:
        keyring.delete_password(service, account)


class FakeFileKeyringBackend:
    """Dateibasierter Fake-Keyring (3-OS-Test) via ``SIA_FAKE_KEYCHAIN``.

    Layout 1:1 zum gefakten ``security``-Binary im Java-Testskript:
    ein File pro Eintrag unter ``<root>/<service>/<account>``;
    nicht vorhanden → ``None`` (Java: ``find-generic-password`` exit 44).
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    @property
    def kind(self) -> str:
        return "fake"

    def _path(self, service: str, account: str) -> Path:
        return self._root / service / account

    def get(self, service: str, account: str) -> str | None:
        path = self._path(service, account)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def set(self, service: str, account: str, payload: str) -> None:
        path = self._path(service, account)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")

    def delete(self, service: str, account: str) -> None:
        self._path(service, account).unlink(missing_ok=True)


def default_backend() -> KeyringBackend:
    """Fake-Backend (Env) oder die ``keyring``-Bibliothek."""
    fake = os.environ.get(FAKE_KEYCHAIN_ENV, "").strip()
    if fake:
        return FakeFileKeyringBackend(Path(fake).expanduser())
    return LibraryKeyringBackend()


def current_backend_kind() -> str:
    """Typ des Default-Backends — für /settings (Warnung bei ``"file"``)."""
    return default_backend().kind


def _b64url_nopad(value: str) -> str:
    """Java: ``Base64.getUrlEncoder().withoutPadding()`` (UTF-8)."""
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def _unb64url(value: str) -> bytes:
    """Java: ``Base64.getUrlDecoder()`` (toleriert fehlendes Padding)."""
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


@dataclass(frozen=True, slots=True)
class StoredCredentials:
    """SIA-Login-Zugangsdaten (Java: ``CredentialStore.StoredCredentials``)."""

    customer: str
    password: str


class SialLoginStore:
    """SIA-Login-Zugangsdaten (Java: ``CredentialStore``).

    Nur explizit vom Benutzer ausgelöst (Merken-Checkbox); wird nie ohne
    Einwilligung gespeichert.
    """

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        self._backend = backend if backend is not None else default_backend()

    @property
    def is_available(self) -> bool:
        """Java: ``isMac()`` — Python: jeder verwertbare Backend (ADR-0009)."""
        return self._backend.kind != "none"

    def load(self) -> StoredCredentials | None:
        """Java: ``load()`` — ``None`` bei Abwesenheit oder Fehler (stille)."""
        try:
            payload = self._backend.get(SERVICE, ACCOUNT_SIA_LOGIN)
        except Exception:
            return None
        if payload is None:
            return None
        payload = payload.strip()
        if not payload:
            return None
        customer_b64, sep, password_b64 = payload.partition("|")
        if not sep:
            return None
        try:
            customer = _unb64url(customer_b64).decode("utf-8")
            password = _unb64url(password_b64).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return None
        return StoredCredentials(customer=customer, password=password)

    def store(self, customer: str, password: str) -> None:
        """Java: ``store()`` — wirft, wenn kein Backend verfügbar ist."""
        if not self.is_available:
            raise KeyringUnavailableError("Zugangsdaten-Ablage ist nicht verfügbar")
        payload = f"{_b64url_nopad(customer)}|{_b64url_nopad(password)}"
        self._backend.set(SERVICE, ACCOUNT_SIA_LOGIN, payload)

    def remove(self) -> None:
        """Java: ``remove()`` — still (nicht vorhanden = Ziel-Zustand)."""
        with contextlib.suppress(Exception):
            self._backend.delete(SERVICE, ACCOUNT_SIA_LOGIN)


class GibbApiKeyStore:
    """gibb-API-Key (Java: ``GibbApiKeyStore``). Nur explizit (Einstellungen)."""

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        self._backend = backend if backend is not None else default_backend()

    @property
    def is_available(self) -> bool:
        return self._backend.kind != "none"

    def load(self) -> str | None:
        """Java: ``load()`` — ``None`` bei Abwesenheit oder Fehler (stille)."""
        try:
            payload = self._backend.get(SERVICE, ACCOUNT_GIBB_API_KEY)
        except Exception:
            return None
        if payload is None:
            return None
        payload = payload.strip()
        if not payload:
            return None
        try:
            return _unb64url(payload).decode("utf-8")
        except (binascii.Error, ValueError, UnicodeDecodeError):
            return None

    def store(self, key: str) -> None:
        """Java: ``store()`` — Validierung 1:1 (leer / > 4000 Zeichen)."""
        if not self.is_available:
            raise KeyringUnavailableError("Keychain-Ablage ist nicht verfügbar")
        if not key.strip():
            raise ValueError("API-Schlüssel darf nicht leer sein")
        if len(key) > GIBB_KEY_MAX_LENGTH:
            raise ValueError("API-Schlüssel zu lang")
        self._backend.set(SERVICE, ACCOUNT_GIBB_API_KEY, _b64url_nopad(key))

    def remove(self) -> None:
        """Java: ``remove()`` — still (nicht vorhanden = Ziel-Zustand)."""
        with contextlib.suppress(Exception):
            self._backend.delete(SERVICE, ACCOUNT_GIBB_API_KEY)


class StateKeyStore:
    """256-Bit-Statusschlüssel (Java: ``KeychainStateKeyProvider``).

    Standard-Base64 der 32 rohen Bytes — gleiches Account-Layout und
    -Format wie Java (gegenseitig lesbar).
    """

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        self._backend = backend if backend is not None else default_backend()

    @property
    def is_available(self) -> bool:
        return self._backend.kind != "none"

    def has_key(self) -> bool:
        """Java: ``available()`` — prüft ohne zu laden (wirft nie)."""
        try:
            self.load()
            return True
        except KeyringError:
            return False

    def load(self) -> bytes:
        """Liefert die 32 rohen Bytes; wirft bei Abwesenheit/Ungültigkeit."""
        try:
            payload = self._backend.get(SERVICE, ACCOUNT_STATE_KEY)
        except Exception as exc:
            raise KeyringUnavailableError("Keyring-Backend nicht erreichbar") from exc
        if payload is None or not payload.strip():
            raise StateKeyError("Kein Statusschlüssel im Keyring hinterlegt")
        try:
            raw = base64.b64decode(payload.strip(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise StateKeyError("Statusschlüssel im Keyring ist kein gültiges Base64") from exc
        if len(raw) != STATE_KEY_LENGTH:
            raise StateKeyError("Statusschlüssel im Keyring muss 32 Bytes lang sein")
        return raw

    def store(self, key: bytes) -> None:
        """Java: ``store(keyB64)`` — Python übernimmt die rohen 32 Bytes."""
        if not self.is_available:
            raise KeyringUnavailableError("Keychain-Ablage ist nicht verfügbar")
        if len(key) != STATE_KEY_LENGTH:
            raise ValueError("Statusschlüssel muss 32 Bytes lang sein")
        payload = base64.b64encode(key).decode("ascii")
        self._backend.set(SERVICE, ACCOUNT_STATE_KEY, payload)

    def remove(self) -> None:
        """Java: ``remove()`` — still (nicht vorhanden = Ziel-Zustand)."""
        with contextlib.suppress(Exception):
            self._backend.delete(SERVICE, ACCOUNT_STATE_KEY)
