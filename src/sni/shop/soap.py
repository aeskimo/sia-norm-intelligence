"""SIA-Shop-SOAP-Client (REQ-801): ECHO/getLizenzDatei/getDocument_Byte.

1:1-Port von ``ch.sia.reader.login.SiaSoapClient`` (SOAP 1.2 via httpx,
Namespace ``http://www.redMSoftware.ch/Secure_Webservice``).

WICHTIGER PROTOKOLL-BEFUND (echter Testlauf 03.09.2026, Java-Klassenkommentar):
Wenn zwischen zwei Aufrufen eine mehrsekündige Nutzerinteraktion (z. B.
manuelle Passworteingabe) liegt, kann eine intern gepoolte TCP/TLS-
Verbindung von einer Middlebox (Proxy/Firewall/Load Balancer) als "idle"
verworfen worden sein, ohne dass der Client das bemerkt — der nächste
Request auf dieser Verbindung "verhungert" dann bis zum Timeout. Deshalb:

- frische Verbindung pro Aufruf (kein Pooling/Keep-Alive),
- automatischer EINZIGER Retry (500 ms Pause) bei Transport-Timeout —
  für ``login()``, ``echo()`` **und** ``get_document()`` (der
  Dokument-Download folgt stets einer solchen interaktiven Pause).
"""

from __future__ import annotations

import base64
import binascii
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable

import httpx

from sni.shop.models import (
    DISCARD,
    DocumentResult,
    LicenseSink,
    LoginResult,
    LoginStatus,
)
from sni.shop.providers import ProviderProfile

#: SOAP 1.2 Envelope-Namespace (Java: ``SOAP_ENVELOPE_NS``).
SOAP_ENVELOPE_NS = "http://www.w3.org/2003/05/soap-envelope"

#: Pause zwischen erstem und zweitem Versuch (Java: ``Thread.sleep(500)``).
RETRY_PAUSE_SECONDS = 0.5

#: Java-Runtime-Marker der Referenzumgebung, 1:1 zu
#: ``SiaSoapClient.post``: ``"OS:" + System.getProperty("os.name") +
#: "  Java:" + java.version + " (" + java.vendor + ")"`` — auf macOS
#: lautet ``os.name`` «Mac OS X», der Runner ist temurin-25. Präfix
#: bleibt ``{app_name}/reconstructed`` (identisch in beiden Ports).
#: Das Portal stellt das Legacy-SRD-Wrapping nachweislich nur für die
#: Java-Referenz-Identifikation aus (Benutzerbefund 25.11.2026:
#: gleicher Kunde + gleiche Geräte-ID, Python-UA → anderes,
#: nicht-legacy Schlüsselmaterial, FPA-identisch über Geräte-IDs).
_JAVA_OS_MARKER = "OS:Mac OS X  Java:25.0.3 (Eclipse Adoptium)"

_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)
_PASSWORD_RE = re.compile(r"(?i)(passwort|password)=[^&\s]+")


def _xml_escape(value: str) -> str:
    """Die fünf Standard-XML-Entities (Java: ``xml()``)."""
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _safe(message: str | None) -> str:
    """Fehlertext mit Passwort-Maskierung (Java: ``safe()``)."""
    if message is None:
        return "ohne Detail"
    return _PASSWORD_RE.sub(r"\1=***", message)


def _ms_since(t0_ns: int) -> int:
    return (time.monotonic_ns() - t0_ns) // 1_000_000


def _is_timeout_like(diagnostic: str | None) -> bool:
    return diagnostic is not None and (
        "Zeitüberschreitung" in diagnostic or "Timeout" in diagnostic
    )


def _first_text(root: ET.Element, local_name: str) -> str | None:
    """Text des ersten Elements mit lokalem Namen, namespace-agnostisch.

    Entspricht ``getElementsByTagNameNS("*", name)`` der Java-Referenz.
    """
    for element in root.iter():
        tag = element.tag
        if isinstance(tag, str) and tag.rsplit("}", 1)[-1] == local_name:
            return "".join(element.itertext())
    return None


def _has_element(root: ET.Element, local_name: str) -> bool:
    for element in root.iter():
        tag = element.tag
        if isinstance(tag, str) and tag.rsplit("}", 1)[-1] == local_name:
            return True
    return False


def _parse_response(body: str) -> ET.Element:
    """Serverantwort-Parser mit XXE-Guard (Java: ``disallow-doctype-decl=true``
    plus deaktivierte externe Entitäten)."""
    if _DOCTYPE_RE.search(body):
        raise ValueError("DOCTYPE-Deklaration in der Serverantwort nicht erlaubt")
    return ET.fromstring(body)


def _transport_failure(http_status: int, elapsed_ms: int, diagnostic: str) -> LoginResult:
    return LoginResult(
        transport_ok=False,
        http_status=http_status,
        status=LoginStatus.UNKNOWN_SERVER_CODE,
        raw_server_code=None,
        server_message=None,
        license_file_base64_length=0,
        elapsed_ms=elapsed_ms,
        diagnostic=diagnostic,
        attempts=1,
    )


def _with_attempts(result: LoginResult, attempts: int) -> LoginResult:
    return LoginResult(
        result.transport_ok,
        result.http_status,
        result.status,
        result.raw_server_code,
        result.server_message,
        result.license_file_base64_length,
        result.elapsed_ms,
        result.diagnostic,
        attempts,
    )


def _with_doc_attempts(result: DocumentResult, attempts: int) -> DocumentResult:
    return DocumentResult(
        result.success,
        result.raw_server_code,
        result.server_message,
        result.remote_filename,
        result.srd_base64_length,
        result.elapsed_ms,
        result.diagnostic,
        attempts,
    )


class SiaSoapClient:
    """Technischer SOAP-Client für den SIA-Shop (Java: ``SiaSoapClient``)."""

    def __init__(
        self,
        echo_endpoint: str,
        login_endpoint: str,
        document_endpoint: str | None,
        namespace_url: str,
        app_name: str,
        connect_timeout: float,
        request_timeout: float,
    ) -> None:
        """Testkonstruktor mit expliziten Endpunkten (Java: Testkonstruktor)."""
        self._echo_endpoint = echo_endpoint
        self._login_endpoint = login_endpoint
        self._document_endpoint = document_endpoint
        self._namespace_url = namespace_url
        self._app_name = app_name
        self._connect_timeout = connect_timeout
        self._request_timeout = request_timeout
        self._last_document_base64: str | None = None

    @classmethod
    def for_provider(
        cls,
        provider: ProviderProfile,
        scheme: str,
        connect_timeout: float,
        request_timeout: float,
    ) -> SiaSoapClient:
        """Produktionskonstruktor (Java: ``SiaSoapClient(provider, scheme, ...)``)."""
        if scheme not in ("https", "http"):
            raise ValueError("scheme muss 'https' oder 'http' sein.")
        return cls(
            echo_endpoint=provider.endpoint(scheme, "srDefault"),
            login_endpoint=provider.endpoint(scheme, "srLizenz"),
            document_endpoint=provider.endpoint(scheme, "srDokument"),
            namespace_url=provider.namespace_url(),
            app_name=provider.app_name,
            connect_timeout=connect_timeout,
            request_timeout=request_timeout,
        )

    # ---------------------------------------------------------------- öffentlich

    def echo(self) -> LoginResult:
        """Erreichbarkeitstest, entspricht ``res.WebService.echo()`` (mit Retry)."""
        body = f'<ECHO xmlns="{_xml_escape(self._namespace_url)}" />'
        return self._with_retry(lambda: self._do_echo_call(body))

    def login(
        self,
        customer_number_or_username: str,
        password: str,
        device_id: str,
        sink: LicenseSink = DISCARD,
    ) -> LoginResult:
        """Login + Lizenzabruf (Java: ``res.WebService.getLizenzdatei``).

        Passwort-Verwerfung: Java überschreibt das übergebene char[] nach
        dem Aufruf (``Arrays.fill(password, '\\0')``). Python-Strings sind
        immutabel — die Zeroing-Äquivalente liegt beim Aufrufer (Referenz
        nicht halten); dieser Client nimmt selbst keine weitere Referenz
        auf das Passwort auf.
        """
        body = (
            f'<getLizenzDatei xmlns="{_xml_escape(self._namespace_url)}">'
            f"<Benutzername_or_Kundennummer>{_xml_escape(customer_number_or_username)}"
            "</Benutzername_or_Kundennummer>"
            f"<Passwort>{_xml_escape(password)}</Passwort>"
            f"<Device_ID>{_xml_escape(device_id)}</Device_ID>"
            "</getLizenzDatei>"
        )
        return self._with_retry(lambda: self._do_login_call(body, sink))

    def get_document(
        self,
        produkt_id: str,
        customer_number_or_username: str,
        password: str,
        device_id: str,
    ) -> DocumentResult:
        """Lädt ein einzelnes Dokument (.srd) — Java: ``res.WebService.getDokument``.

        ``produkt_id`` = Wert des ``<ID>``-Elements im ``<Produkt>``-Knoten
        der Lizenzdatei (NICHT die Produktnummer wie "SIA 101").

        Passwort-Verwerfung siehe :meth:`login` (Java:
        ``Arrays.fill(password, '\\0')`` nach dem Aufruf).
        """
        if self._document_endpoint is None:
            raise RuntimeError("Kein Dokument-Endpunkt konfiguriert für diesen Client.")
        body = (
            f'<getDocument_Byte xmlns="{_xml_escape(self._namespace_url)}">'
            f"<aProdukt_ID>{_xml_escape(produkt_id)}</aProdukt_ID>"
            f"<Benutzername_or_Kundennummer>{_xml_escape(customer_number_or_username)}"
            "</Benutzername_or_Kundennummer>"
            f"<Passwort>{_xml_escape(password)}</Passwort>"
            f"<Device_ID>{_xml_escape(device_id)}</Device_ID>"
            "</getDocument_Byte>"
        )
        return self._with_retry_doc(lambda: self._do_document_call(body))

    def take_last_document_base64(self) -> str | None:
        """Base64 des zuletzt geladenen .srd, einmalig (Java: ``takeLastDocumentBase64``)."""
        value = self._last_document_base64
        self._last_document_base64 = None
        return value

    # ------------------------------------------------------------------ intern

    def _with_retry(self, attempt: Callable[[], LoginResult]) -> LoginResult:
        first = attempt()
        if first.transport_ok or not _is_timeout_like(first.diagnostic):
            return _with_attempts(first, 1)
        time.sleep(RETRY_PAUSE_SECONDS)
        return _with_attempts(attempt(), 2)

    def _with_retry_doc(self, attempt: Callable[[], DocumentResult]) -> DocumentResult:
        first = attempt()
        if (
            first.success
            or first.raw_server_code is not None
            or not _is_timeout_like(first.diagnostic)
        ):
            return _with_doc_attempts(first, 1)
        time.sleep(RETRY_PAUSE_SECONDS)
        return _with_doc_attempts(attempt(), 2)

    def _post(self, endpoint: str, payload_xml: str) -> tuple[int, str]:
        """POSTet die SOAP-1.2-Envelope mit frischer Verbindung (Java: ``post``).

        WICHTIG (Java-Klassenkommentar): frischer Client pro Aufruf —
        gepoolte Verbindungen werden über Nutzerinteraktionen hinweg nicht
        wiederverwendet (beobachtetes Hänge-Problem). Der Overhead eines
        neuen TCP/TLS-Handshakes ist für diesen Use Case vernachlässigbar.
        """
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            "<soap12:Envelope"
            ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
            ' xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f' xmlns:soap12="{SOAP_ENVELOPE_NS}">'
            f"<soap12:Body>{payload_xml}</soap12:Body>"
            "</soap12:Envelope>"
        )
        # Client-Identifikation byte-exakt wie die Java-Referenz
        # (SiaSoapClient.post) — Portal-ROUTING, siehe _JAVA_OS_MARKER.
        user_agent = f"{self._app_name}/reconstructed  {_JAVA_OS_MARKER}"
        timeout = httpx.Timeout(self._request_timeout, connect=self._connect_timeout)
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            response = client.post(
                endpoint,
                content=envelope.encode("utf-8"),
                headers={
                    "Content-Type": "application/soap+xml; charset=utf-8",
                    "User-Agent": user_agent,
                },
            )
        return response.status_code, response.text

    def _do_echo_call(self, payload_xml: str) -> LoginResult:
        t0 = time.monotonic_ns()
        try:
            http_status, body = self._post(self._echo_endpoint, payload_xml)
            elapsed = _ms_since(t0)
            if http_status != 200:
                return _transport_failure(
                    http_status, elapsed, f"Server antwortete mit HTTP {http_status}"
                )
            root = _parse_response(body)
            text = _first_text(root, "ECHOResult")
            ok = text is not None
            return LoginResult(
                transport_ok=True,
                http_status=200,
                status=LoginStatus.SUCCESS if ok else LoginStatus.UNKNOWN_SERVER_CODE,
                raw_server_code=text,
                server_message=None,
                license_file_base64_length=0,
                elapsed_ms=elapsed,
                diagnostic=None if ok else "Antwort enthielt kein ECHOResult-Element.",
                attempts=1,
            )
        except httpx.ConnectTimeout:
            return _transport_failure(
                0, _ms_since(t0), "Zeitüberschreitung beim Verbindungsaufbau (TCP/TLS-Connect)."
            )
        except httpx.TimeoutException:
            return _transport_failure(
                0, _ms_since(t0), "Zeitüberschreitung beim Warten auf die Serverantwort."
            )
        except Exception as exc:  # noqa: BLE001 — Java: catch (Exception e)
            return _transport_failure(0, _ms_since(t0), f"{type(exc).__name__}: {_safe(str(exc))}")

    def _do_login_call(self, body: str, sink: LicenseSink) -> LoginResult:
        t0 = time.monotonic_ns()
        try:
            http_status, response = self._post(self._login_endpoint, body)
            elapsed = _ms_since(t0)
            if http_status != 200:
                return _transport_failure(
                    http_status, elapsed, f"Server antwortete mit HTTP {http_status}"
                )
            root = _parse_response(response)
            if _has_element(root, "Fault"):
                fault_text = _first_text(root, "Text") or "Text der SOAP-Fault nicht lesbar."
                return LoginResult(
                    transport_ok=True,
                    http_status=200,
                    status=LoginStatus.UNKNOWN_SERVER_CODE,
                    raw_server_code="SOAP_FAULT",
                    server_message=fault_text,
                    license_file_base64_length=0,
                    elapsed_ms=elapsed,
                    diagnostic="Server lieferte einen SOAP-Fault statt einer Fachantwort.",
                    attempts=1,
                )
            raw_code = _first_text(root, "returnLogIn_Result")
            error_text = _first_text(root, "returnFehler")
            license_base64 = _first_text(root, "getLizenzDateiResult")
            status = LoginStatus.from_server_code(raw_code)
            lic_len = 0 if license_base64 is None else len(license_base64)

            extra_diagnostic: str | None = None
            if status is LoginStatus.SUCCESS and lic_len == 0:
                extra_diagnostic = "Server meldete OK, aber getLizenzDateiResult war leer."
            elif status is LoginStatus.SUCCESS and license_base64 is not None:
                # Dekodierung erfolgt NUR bei Erfolg und NUR lokal in dem
                # prozessinternen Sink (Java-Kommentar dazu).
                try:
                    sink.accept(base64.b64decode(license_base64.strip()))
                except (binascii.Error, ValueError):
                    extra_diagnostic = (
                        "Lizenzantwort war base64-invalide und konnte nicht dekodiert werden."
                    )

            return LoginResult(
                transport_ok=True,
                http_status=200,
                status=status,
                raw_server_code=raw_code,
                server_message=error_text,
                license_file_base64_length=lic_len,
                elapsed_ms=elapsed,
                diagnostic=extra_diagnostic,
                attempts=1,
            )
        except httpx.ConnectTimeout:
            return _transport_failure(
                0, _ms_since(t0), "Zeitüberschreitung beim Verbindungsaufbau (TCP/TLS-Connect)."
            )
        except httpx.TimeoutException:
            return _transport_failure(
                0, _ms_since(t0), "Zeitüberschreitung beim Warten auf die Serverantwort."
            )
        except Exception as exc:  # noqa: BLE001 — Java: catch (Exception e)
            return _transport_failure(0, _ms_since(t0), f"{type(exc).__name__}: {_safe(str(exc))}")

    def _do_document_call(self, body: str) -> DocumentResult:
        endpoint = self._document_endpoint
        if endpoint is None:
            raise RuntimeError("Kein Dokument-Endpunkt konfiguriert für diesen Client.")
        t0 = time.monotonic_ns()
        try:
            http_status, response = self._post(endpoint, body)
            elapsed = _ms_since(t0)
            if http_status != 200:
                return DocumentResult(
                    False,
                    None,
                    None,
                    None,
                    0,
                    elapsed,
                    f"Server antwortete mit HTTP {http_status}",
                    1,
                )
            root = _parse_response(response)
            if _has_element(root, "Fault"):
                fault_text = _first_text(root, "Text") or "Text der SOAP-Fault nicht lesbar."
                return DocumentResult(
                    False,
                    "SOAP_FAULT",
                    fault_text,
                    None,
                    0,
                    elapsed,
                    "Server lieferte einen SOAP-Fault statt einer Fachantwort.",
                    1,
                )
            raw_code = _first_text(root, "returnLogIn_Result")
            error_text = _first_text(root, "returnFehler")
            filename = _first_text(root, "returnFilename")
            result_base64 = _first_text(root, "getDocument_ByteResult")
            ok = raw_code == "OK"
            self._last_document_base64 = result_base64  # bedingungslos (Java-Zeile 239)
            srd_len = 0 if result_base64 is None else len(result_base64)
            diagnostic = (
                "Server meldete OK, aber getDocument_ByteResult war leer."
                if ok and srd_len == 0
                else None
            )
            return DocumentResult(
                ok, raw_code, error_text, filename, srd_len, elapsed, diagnostic, 1
            )
        except httpx.ConnectTimeout:
            return DocumentResult(
                False,
                None,
                None,
                None,
                0,
                _ms_since(t0),
                "Zeitüberschreitung beim Verbindungsaufbau (TCP/TLS-Connect).",
                1,
            )
        except httpx.TimeoutException:
            return DocumentResult(
                False,
                None,
                None,
                None,
                0,
                _ms_since(t0),
                "Zeitüberschreitung beim Warten auf die Serverantwort.",
                1,
            )
        except Exception as exc:  # noqa: BLE001 — Java: catch (Exception e)
            return DocumentResult(
                False,
                None,
                None,
                None,
                0,
                _ms_since(t0),
                f"{type(exc).__name__}: {_safe(str(exc))}",
                1,
            )
