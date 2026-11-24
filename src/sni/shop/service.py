"""Produkt-Service: Login + Download-Orchestrierung (REQ-801/803).

1:1-Port von ``ch.sia.reader.product.service.SiaProductService`` plus
``ch.sia.reader.product.session`` (``LicenseSession``,
``SessionCredentials``) und den Ergebnis-Records.

Zeroing-Äquivalente: Java überschreibt char[]-Puffer mit Nullen
(``Arrays.fill``). Python-Strings/Bytes sind immutabel — die
Entsprechung ist das Loslassen der prozessinternen Referenz; dokumentiert
pro Methode. G4: Schlüssel und Passwort werden nie geloggt.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass

from sni.shop.catalog import CatalogStore
from sni.shop.catalog_xml import parse_license_catalog
from sni.shop.decrypt import decrypt_mro, extract_individual_key_and_iv, srd_decrypt_document
from sni.shop.models import LicenseSink, LoginResult, LoginStatus
from sni.shop.providers import SIA
from sni.shop.soap import SiaSoapClient
from sni.shop.soap import _safe as _mask_diagnostics

#: Produktions-Client-Fabrik (Java: ``new SiaSoapClient(SIA, "https", 10s, 30s)``).
ProductionClientFactory = Callable[[], SiaSoapClient]


def _production_client() -> SiaSoapClient:
    return SiaSoapClient.for_provider(SIA, "https", 10.0, 30.0)


@dataclass(frozen=True, slots=True)
class LoginOutcome:
    """Ergebnis des Logins (Java: ``LoginOutcome``).

    ``status`` ist eine App-Erweiterung (kein Java-Feld): der exakte
    Protokollstatus für die App-API (09 §6.2: Fehler-Codes 1:1, z. B.
    ``Fail_Wrong_PWD``); bei Protokollfehlern ``None``.
    """

    success: bool
    message: str
    catalog_size: int
    session: LicenseSession | None
    status: LoginStatus | None = None


@dataclass(frozen=True, slots=True)
class DocumentOutcome:
    """Ergebnis eines Dokument-Downloads (Java: ``DocumentOutcome``).

    Java liefert ``pdf()`` als Defensive-Copy (Clone) — Python-``bytes``
    sind immutabel, die direkte Referenz ist die Äquivalente.
    """

    success: bool
    filename: str | None
    pdf: bytes | None
    message: str | None

    def wipe(self) -> None:
        """Java: ``wipe()`` (Byte-Nullen) — Python: Referenz loslassen."""
        object.__setattr__(self, "pdf", None)


class SessionCredentials:
    """Kurzlebige Zugangsdaten. Aufrufer müssen ``close()`` verwenden.

    Java: ``SessionCredentials`` (char[]-Passwort, Close-Zeroing).
    """

    def __init__(self, customer: str, password: str, device_id: str) -> None:
        self._customer = customer.strip()
        self._password: str | None = password
        self._device_id = device_id.strip()

    @property
    def customer(self) -> str:
        return self._customer

    @property
    def device_id(self) -> str:
        return self._device_id

    def password_copy(self) -> str:
        """Java: ``passwordCopy()`` — wirft nach ``close()``."""
        if self._password is None:
            raise RuntimeError("Session geschlossen")
        return self._password

    def close(self) -> None:
        """Java: ``close()`` — Passwort-Referenz wird verworfen."""
        self._password = None

    @property
    def closed(self) -> bool:
        return self._password is None


class LicenseSession:
    """Aktive Sitzung mit individuellem SRD-Schlüssel; niemals loggen.

    Java: ``LicenseSession`` (char[]-Key/IV, Close-Zeroing).
    """

    def __init__(self, credentials: SessionCredentials, key: str, iv: str) -> None:
        self._credentials = credentials
        self._key: str | None = key
        self._iv: str | None = iv

    @property
    def credentials(self) -> SessionCredentials:
        return self._credentials

    def key_copy(self) -> str:
        """Java: ``keyCopy()`` — wirft nach ``close()``."""
        if self._key is None:
            raise RuntimeError("Session geschlossen")
        return self._key

    def iv_copy(self) -> str:
        """Java: ``ivCopy()`` — wirft nach ``close()``."""
        if self._iv is None:
            raise RuntimeError("Session geschlossen")
        return self._iv

    def close(self) -> None:
        """Java: ``close()`` — Credentials + Key/IV-Referenzen verworfen."""
        self._credentials.close()
        self._key = None
        self._iv = None


class SiaProductService:
    """Produktadapter um das real verifizierte Legacy-Protokoll.

    Java: ``SiaProductService``. ``client_factory`` ist ein Test-Injektions-
    Punkt (Äquivalente zum Java-Testkonstruktor von ``SiaSoapClient``);
    die Produktions-Factory ist identisch zur Java-Konstante.
    """

    def __init__(
        self,
        catalog: CatalogStore,
        client_factory: ProductionClientFactory | None = None,
    ) -> None:
        self._catalog = catalog
        self._client_factory = client_factory if client_factory is not None else _production_client

    @property
    def catalog(self) -> CatalogStore:
        return self._catalog

    def login(self, credentials: SessionCredentials) -> LoginOutcome:
        """Java: ``login`` — SOAP-Login + .mro-Dekodierung + Katalog."""
        sink = LicenseSink()
        try:
            client = self._client_factory()
            result = client.login(
                credentials.customer, credentials.password_copy(), credentials.device_id, sink
            )
            if not result.is_success:
                credentials.close()
                return LoginOutcome(False, _safe(result), 0, None, result.status)
            raw = sink.bytes
            if raw is None:
                raise ValueError("Lizenzbytes nicht vorhanden")
            xml = decrypt_mro(raw)
            key, iv = extract_individual_key_and_iv(xml)
            parsed = parse_license_catalog(xml)
            self._catalog.replace_all(parsed.documents)
            message = "OK" if not parsed.warnings else f"{len(parsed.warnings)} Katalogwarnungen"
            return LoginOutcome(
                True,
                message,
                self._catalog.size(),
                LicenseSession(credentials, key, iv),
                result.status,
            )
        except Exception as exc:
            credentials.close()
            return LoginOutcome(False, f"{type(exc).__name__}: {_safe_message(exc)}", 0, None)
        finally:
            sink.wipe()

    def download(self, session: LicenseSession, product_id: str) -> DocumentOutcome:
        """Java: ``download`` — getDocument_Byte + .srd-Dekodierung + PDF-Check."""
        document = self._catalog.by_id(product_id)
        if document is None:
            return DocumentOutcome(False, None, None, "Produkt nicht im Katalog")
        if not document.view_allowed:
            return DocumentOutcome(False, None, None, "Anzeige laut Lizenz nicht erlaubt")
        password = session.credentials.password_copy()
        try:
            client = self._client_factory()
            result = client.get_document(
                product_id, session.credentials.customer, password, session.credentials.device_id
            )
            if not result.success:
                # Java: diagnostic != null ? diagnostic : serverMessage
                detail = result.diagnostic
                if detail is None:
                    detail = result.server_message
                return DocumentOutcome(False, result.remote_filename, None, detail)
            b64 = client.take_last_document_base64()
            if b64 is None:
                return DocumentOutcome(False, result.remote_filename, None, "Leerer Dokumentinhalt")
            try:
                srd = base64.b64decode(b64.strip())  # Java: MIME-Decoder (tolerant)
            except (binascii.Error, ValueError) as exc:
                return DocumentOutcome(False, None, None, f"binascii.Error: {_safe_message(exc)}")
            pdf = srd_decrypt_document(srd, session.key_copy(), session.iv_copy())
            if len(pdf) < 4 or pdf[:4] != b"%PDF":
                return DocumentOutcome(
                    False, result.remote_filename, None, "Ungültige PDF-Signatur"
                )
            return DocumentOutcome(True, result.remote_filename, pdf, "OK")
        except Exception as exc:
            return DocumentOutcome(False, None, None, f"{type(exc).__name__}: {_safe_message(exc)}")
        # finally: Java zeroed pwd + srd — Python: Referenzen fallen aus Scope.


def _safe(result: LoginResult) -> str:
    """Java: ``safe(r)`` — „STATUS: diagnostic|serverMessage“.

    Java-String-Konkatenation rendert ein fehlendes Feld als ``null``;
    die Python-Äquivalente ist die explizite Wiedergabe (1:1).
    """
    detail = result.diagnostic if result.diagnostic is not None else result.server_message
    return f"{result.status.name}: {detail if detail is not None else 'null'}"


def _safe_message(exc: BaseException) -> str:
    """Java: ``message(e)`` — mit Passwort-Maskierung (``_safe`` aus soap)."""
    text = str(exc)
    if not text:
        return "ohne Detail"
    return _mask_diagnostics(text)
