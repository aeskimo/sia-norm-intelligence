"""SIA-Shop-Ergebnis- und Status-Modelle (REQ-801).

1:1-Port von ``ch.sia.reader.login`` (``LoginStatus``, ``LoginResult``,
``DocumentResult``, ``LicenseSink``).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LoginStatus(Enum):
    """Exakte Server-Statuscodes aus ``returnLogIn_Result``.

    Rekonstruiert aus der Auswertungslogik in ``res.Control`` (Java:
    ``LoginStatus``). Die Codes werden 1:1 übernommen — einschliesslich
    des serverseitigen Typos ``Unkown_Device_ID`` (G6: 1:1-Weitergabe).
    """

    SUCCESS = ("OK", "Login erfolgreich, Lizenzdatei wurde geliefert.")
    INVALID_CUSTOMER_NUMBER = ("Fail_NO_User", "Kundennummer wurde nicht gefunden.")
    INVALID_PASSWORD = ("Fail_Wrong_PWD", "Passwort ist falsch.")
    UNKNOWN_DEVICE = ("Unkown_Device_ID", "Geräte-ID ist auf diesem Konto nicht registriert.")
    ACCOUNT_DISABLED = ("Account_disabled", "Konto wurde deaktiviert.")
    ACCOUNT_DELETED = ("Account_deleted", "Konto wurde gelöscht.")
    DEVICE_LIMIT_REACHED = (
        "Max_allowed_Device_IDs",
        "Maximale Anzahl registrierter Geräte erreicht.",
    )
    UNKNOWN_SERVER_CODE = (None, "Unbekannter Servercode — Originaltext wird unten mitgeliefert.")

    def __init__(self, server_code: str | None, description: str) -> None:
        self.server_code = server_code
        self.description = description

    @classmethod
    def from_server_code(cls, code: str | None) -> LoginStatus:
        """Mapping exakt wie Java: unbekannt/None → ``UNKNOWN_SERVER_CODE``."""
        if code is None:
            return cls.UNKNOWN_SERVER_CODE
        for status in cls:
            if code == status.server_code:
                return status
        return cls.UNKNOWN_SERVER_CODE


@dataclass(frozen=True, slots=True)
class LoginResult:
    """Ergebnis eines technischen Login-/Lizenzabruf-Tests (Java: ``LoginResult``)."""

    transport_ok: bool
    http_status: int
    status: LoginStatus
    raw_server_code: str | None
    server_message: str | None
    license_file_base64_length: int
    elapsed_ms: int
    diagnostic: str | None
    attempts: int

    @property
    def is_success(self) -> bool:
        return self.transport_ok and self.status is LoginStatus.SUCCESS


@dataclass(frozen=True, slots=True)
class DocumentResult:
    """Ergebnis eines Dokumenten-Download-Versuchs (Java: ``DocumentResult``)."""

    success: bool
    raw_server_code: str | None
    server_message: str | None
    remote_filename: str | None
    srd_base64_length: int
    elapsed_ms: int
    diagnostic: str | None
    attempts: int


class LicenseSink:
    """Mutable, rein prozessinterner Speicher für dekodierte Lizenz-Bytes.

    Java: ``LicenseSink``. Die Bytes verlassen niemals den Prozess des
    Aufrufers — kein Logging, kein Netzwerkversand, keine
    Textrepräsentation im Ergebnisobjekt. Aufrufer sollte :meth:`wipe`
    aufrufen, sobald die Daten nicht mehr benötigt werden.
    """

    def __init__(self) -> None:
        self._bytes: bytes | None = None

    def accept(self, decoded: bytes) -> None:
        self._bytes = decoded

    @property
    def bytes(self) -> bytes | None:
        return self._bytes

    @property
    def has_data(self) -> bool:
        return self._bytes is not None and len(self._bytes) > 0

    def wipe(self) -> None:
        """Gibt die Referenz frei (Java: Bytes mit Nullen überschreiben).

        Python-``bytes`` sind immutabel — die Zeroing-Äquivalente ist das
        Loslassen der prozessinternen Referenz.
        """
        self._bytes = None


class _DiscardLicenseSink(LicenseSink):
    """No-Op-Sink (Java: ``LicenseSink.DISCARD``)."""

    def accept(self, decoded: bytes) -> None:
        """Bewusst verworfen, keine Speicherung."""


#: No-Op-Sink für Aufrufe, die keine Rohdaten benötigen.
DISCARD = _DiscardLicenseSink()
