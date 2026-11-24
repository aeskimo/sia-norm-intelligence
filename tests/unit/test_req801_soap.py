"""REQ-801: SIA-Shop-SOAP-Client — Protokoll-Tests gegen lokalen Mock-Server.

1:1-Modell des Java-Self-Tests ``ch.sia.reader.login.LoginProbeSelfTest``
(SIA-Normenassistent): derselbe Mock-Server mit denselben Routing-Regeln
(``srDefault``/``srLizenz``/``srFlaky``/``srDokument``/``srDokumentFlaky``)
und denselben Szenarien (ECHO, Login-OK, Falsches Passwort, unbekannter
Kunde, unbekannte Device-ID, SOAP-Fault, Timeout-Retry, Lizenz-Sink,
Dokument-Download, unbekanntes Produkt, Dokument-Fault, Dokument-Retry).

Reine synthetische Testdaten (G4: keine echten Kunden, Passwörter,
Lizenzschlüssel oder Normtexte). Der Mock antwortet exakt in der
SOAP-1.2-Struktur, die der Client aus ``res.WebService`` erwartet.
"""

from __future__ import annotations

import base64
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

import pytest

from sni.shop.models import DISCARD, LicenseSink, LoginStatus
from sni.shop.providers import SIA
from sni.shop.soap import SOAP_ENVELOPE_NS, SiaSoapClient, _safe

NS = "http://www.redMSoftware.ch/Secure_Webservice"

TEST_LIZENZ_TEXT = "TESTLIZENZ-INHALT-NUR-FUER-SELFTEST"
TEST_LIZENZ_FLAKY = "TESTLIZENZ-FLAKY"
TEST_SRD_TEXT = "TESTSRD-INHALT-NUR-FUER-SELFTEST"

FLAKY_SLEEP_SECONDS = 2.0  # länger als der 1 s Request-Timeout des Flaky-Clients


def _b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _envelope(body: str) -> str:
    return (
        "<soap12:Envelope xmlns:soap12='http://www.w3.org/2003/05/soap-envelope'>"
        f"<soap12:Body>{body}</soap12:Body></soap12:Envelope>"
    )


def _login_response(result_code: str, license_b64: str) -> str:
    return _envelope(
        f"<getLizenzDateiResponse xmlns='{NS}'>"
        f"<returnLogIn_Result>{result_code}</returnLogIn_Result>"
        f"<getLizenzDateiResult>{license_b64}</getLizenzDateiResult>"
        "<returnFehler></returnFehler>"
        "</getLizenzDateiResponse>"
    )


def _document_response(result_code: str, fehler: str, filename: str, srd_b64: str) -> str:
    return _envelope(
        f"<getDocument_ByteResponse xmlns='{NS}'>"
        f"<returnLogIn_Result>{result_code}</returnLogIn_Result>"
        f"<returnFehler>{fehler}</returnFehler>"
        f"<returnFilename>{filename}</returnFilename>"
        f"<getDocument_ByteResult>{srd_b64}</getDocument_ByteResult>"
        "</getDocument_ByteResponse>"
    )


SOAP_FAULT = _envelope(
    "<soap12:Fault><soap12:Code><soap12:Value>Receiver</soap12:Value></soap12:Code>"
    "<soap12:Reason><soap12:Text>Interner Serverfehler (simuliert)</soap12:Text></soap12:Reason>"
    "</soap12:Fault>"
)


class _MockHTTPServer(ThreadingHTTPServer):
    """Trägt eine Referenz auf den Mock-Server (Zugriff über ``handler.server``)."""

    mock: _MockSoapServer


class _MockSoapServer:
    """Lokaler SOAP-Mock, Routing 1:1 nach ``LoginProbeSelfTest`` (Java)."""

    def __init__(self) -> None:
        self.last_login_request: str | None = None
        self.last_document_request: str | None = None
        self._flaky_logins = 0
        self._flaky_documents = 0

        self._httpd = _MockHTTPServer(("127.0.0.1", 0), _MockHandler)
        self._httpd.mock = self
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        port = self._httpd.server_address[1]
        self.base = f"http://127.0.0.1:{port}/Secure_Webservice/"

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def route(self, path: str, request: str) -> tuple[int, str]:
        if path.endswith("srDefault.asmx"):
            return 200, _envelope(
                f"<ECHOResponse xmlns='{NS}'><ECHOResult>alive</ECHOResult></ECHOResponse>"
            )
        if path.endswith("srEchoNoResult.asmx"):
            return 200, _envelope(f"<ECHOResponse xmlns='{NS}'></ECHOResponse>")
        if path.endswith("srLizenz.asmx"):
            self.last_login_request = request
            if "<Passwort>fault</Passwort>" in request:
                return 200, SOAP_FAULT
            if ">UNKNOWN<" in request:
                return 200, _login_response("Fail_NO_User", "")
            if "<Passwort>wrong</Passwort>" in request:
                return 200, _login_response("Fail_Wrong_PWD", "")
            if "<Device_ID>DEV-UNKNOWN</Device_ID>" in request:
                return 200, _login_response("Unkown_Device_ID", "")
            return 200, _login_response("OK", _b64(TEST_LIZENZ_TEXT))
        if path.endswith("srLizenz500.asmx"):
            return 500, "<html>Internal Server Error</html>"
        if path.endswith("srFlaky.asmx"):
            self._flaky_logins += 1
            if self._flaky_logins == 1:
                time.sleep(FLAKY_SLEEP_SECONDS)
            return 200, _login_response("OK", _b64(TEST_LIZENZ_FLAKY))
        if path.endswith("srDokument.asmx"):
            self.last_document_request = request
            if "<aProdukt_ID>prod-fault</aProdukt_ID>" in request:
                return 200, SOAP_FAULT
            if "<aProdukt_ID>prod-unknown</aProdukt_ID>" in request:
                return 200, _document_response(
                    "Fail_Unknown_Produkt",
                    "Produkt nicht gefunden oder nicht lizenziert.",
                    "",
                    "",
                )
            return 200, _document_response("OK", "", "test.srd", _b64(TEST_SRD_TEXT))
        if path.endswith("srDokumentFlaky.asmx"):
            self._flaky_documents += 1
            if self._flaky_documents == 1:
                time.sleep(FLAKY_SLEEP_SECONDS)
            return 200, _document_response("OK", "", "test.srd", _b64(TEST_SRD_TEXT))
        return 404, "unbekannter Pfad"


class _MockHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 — http.server-Konvention
        length = int(self.headers.get("Content-Length", 0))
        request = self.rfile.read(length).decode("utf-8")
        mock = cast(_MockHTTPServer, self.server).mock
        status, body = mock.route(self.path, request)
        payload = body.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/soap+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Client hat zuvor den Timeout erzwungen (Flaky-Test)

    def log_message(self, format: str, *args: object) -> None:
        pass  # Test-Logausgabe unterdrücken


@pytest.fixture(scope="module")
def mock() -> Iterator[_MockSoapServer]:
    server = _MockSoapServer()
    yield server
    server.stop()


def _client(
    mock: _MockSoapServer,
    connect_timeout: float = 5.0,
    request_timeout: float = 5.0,
    login_endpoint: str = "srLizenz.asmx",
    echo_endpoint: str = "srDefault.asmx",
    document_endpoint: str | None = "srDokument.asmx",
) -> SiaSoapClient:
    base = mock.base
    return SiaSoapClient(
        echo_endpoint=base + echo_endpoint,
        login_endpoint=base + login_endpoint,
        document_endpoint=None if document_endpoint is None else base + document_endpoint,
        namespace_url=NS,
        app_name="SIA-Reader-PythonSelfTest",
        connect_timeout=connect_timeout,
        request_timeout=request_timeout,
    )


# ---------------------------------------------------------------- ECHO


def test_req801_echo_success(mock: _MockSoapServer) -> None:
    result = _client(mock).echo()
    assert result.is_success
    assert result.raw_server_code == "alive"
    assert result.transport_ok
    assert result.attempts == 1


def test_req801_echo_missing_result_element(mock: _MockSoapServer) -> None:
    result = _client(mock, echo_endpoint="srEchoNoResult.asmx").echo()
    assert not result.is_success
    assert result.transport_ok
    assert result.status is LoginStatus.UNKNOWN_SERVER_CODE
    assert result.diagnostic == "Antwort enthielt kein ECHOResult-Element."


# ---------------------------------------------------------------- Login


def test_req801_login_ok(mock: _MockSoapServer) -> None:
    result = _client(mock).login("123456", "good", "DEV-OK")
    assert result.is_success
    assert result.status is LoginStatus.SUCCESS
    assert result.raw_server_code == "OK"
    assert result.license_file_base64_length > 0
    assert result.attempts == 1


def test_req801_login_wrong_password(mock: _MockSoapServer) -> None:
    result = _client(mock).login("123456", "wrong", "DEV-OK")
    assert not result.is_success
    assert result.transport_ok
    assert result.status is LoginStatus.INVALID_PASSWORD
    assert result.raw_server_code == "Fail_Wrong_PWD"
    assert result.license_file_base64_length == 0


def test_req801_login_unknown_customer(mock: _MockSoapServer) -> None:
    result = _client(mock).login("UNKNOWN", "good", "DEV-OK")
    assert not result.is_success
    assert result.status is LoginStatus.INVALID_CUSTOMER_NUMBER
    assert result.raw_server_code == "Fail_NO_User"


def test_req801_login_unknown_device(mock: _MockSoapServer) -> None:
    result = _client(mock).login("123456", "good", "DEV-UNKNOWN")
    assert not result.is_success
    assert result.status is LoginStatus.UNKNOWN_DEVICE
    # Server-Typo "Unkown" wird 1:1 übernommen (G6).
    assert result.raw_server_code == "Unkown_Device_ID"


def test_req801_login_soap_fault(mock: _MockSoapServer) -> None:
    result = _client(mock).login("123456", "fault", "DEV-OK")
    assert not result.is_success
    assert result.transport_ok
    assert result.http_status == 200
    assert result.status is LoginStatus.UNKNOWN_SERVER_CODE
    assert result.raw_server_code == "SOAP_FAULT"
    assert result.server_message == "Interner Serverfehler (simuliert)"
    assert result.diagnostic == "Server lieferte einen SOAP-Fault statt einer Fachantwort."


def test_req801_login_http_500_is_transport_failure(mock: _MockSoapServer) -> None:
    result = _client(mock, login_endpoint="srLizenz500.asmx").login("123456", "good", "DEV-OK")
    assert not result.is_success
    assert not result.transport_ok
    assert result.http_status == 500
    assert result.diagnostic == "Server antwortete mit HTTP 500"
    # Kein Retry: nur Timeout-Diagnosen werden wiederholt (Java-Verhalten).
    assert result.attempts == 1


def test_req801_login_flaky_then_ok_retry(mock: _MockSoapServer) -> None:
    client = _client(mock, connect_timeout=2.0, request_timeout=1.0, login_endpoint="srFlaky.asmx")
    result = client.login("123456", "good", "DEV-OK")
    assert result.is_success
    assert result.attempts == 2
    assert result.diagnostic is None


def test_req801_login_with_sink_receives_decoded_bytes(mock: _MockSoapServer) -> None:
    sink = LicenseSink()
    result = _client(mock).login("123456", "good", "DEV-OK", sink)
    assert result.is_success
    assert sink.has_data
    assert sink.bytes is not None
    assert sink.bytes.decode("utf-8") == TEST_LIZENZ_TEXT
    sink.wipe()
    assert not sink.has_data


def test_req801_discard_sink_is_noop(mock: _MockSoapServer) -> None:
    result = _client(mock).login("123456", "good", "DEV-OK", DISCARD)
    assert result.is_success
    assert not DISCARD.has_data


def test_req801_login_request_body_matches_protocol(mock: _MockSoapServer) -> None:
    _client(mock).login("123456", "good", "DEV-OK")
    request = mock.last_login_request
    assert request is not None
    assert f'<getLizenzDatei xmlns="{NS}">' in request
    assert "<Benutzername_or_Kundennummer>123456</Benutzername_or_Kundennummer>" in request
    assert "<Passwort>good</Passwort>" in request
    assert "<Device_ID>DEV-OK</Device_ID>" in request
    assert SOAP_ENVELOPE_NS in request
    assert 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"' in request


def test_req801_login_request_escalates_xml_specials(mock: _MockSoapServer) -> None:
    _client(mock).login("A<B&C", "good", "DEV-OK")
    request = mock.last_login_request
    assert request is not None
    assert "<Benutzername_or_Kundennummer>A&lt;B&amp;C</Benutzername_or_Kundennummer>" in request
    assert "A<B&C" not in request


# ------------------------------------------------------------ Dokument


def test_req801_document_ok(mock: _MockSoapServer) -> None:
    client = _client(mock)
    result = client.get_document("prod-ok", "123456", "good", "DEV-OK")
    assert result.success
    assert result.raw_server_code == "OK"
    assert result.remote_filename == "test.srd"
    assert result.srd_base64_length > 0
    assert result.attempts == 1
    assert client.take_last_document_base64() == _b64(TEST_SRD_TEXT)
    # Einmalige Abholung (Java: takeLastDocumentBase64).
    assert client.take_last_document_base64() is None


def test_req801_document_unknown_product(mock: _MockSoapServer) -> None:
    result = _client(mock).get_document("prod-unknown", "123456", "good", "DEV-OK")
    assert not result.success
    assert result.raw_server_code == "Fail_Unknown_Produkt"
    assert result.server_message == "Produkt nicht gefunden oder nicht lizenziert."
    assert result.remote_filename == ""


def test_req801_document_soap_fault(mock: _MockSoapServer) -> None:
    result = _client(mock).get_document("prod-fault", "123456", "good", "DEV-OK")
    assert not result.success
    assert result.raw_server_code == "SOAP_FAULT"
    assert result.diagnostic is not None


def test_req801_document_flaky_then_ok_retry(mock: _MockSoapServer) -> None:
    client = _client(
        mock, connect_timeout=2.0, request_timeout=1.0, document_endpoint="srDokumentFlaky.asmx"
    )
    result = client.get_document("prod-ok", "123456", "good", "DEV-OK")
    assert result.success
    assert result.attempts == 2


def test_req801_document_request_body_matches_protocol(mock: _MockSoapServer) -> None:
    _client(mock).get_document("prod-ok", "123456", "good", "DEV-OK")
    request = mock.last_document_request
    assert request is not None
    assert f'<getDocument_Byte xmlns="{NS}">' in request
    assert "<aProdukt_ID>prod-ok</aProdukt_ID>" in request
    assert "<Benutzername_or_Kundennummer>123456</Benutzername_or_Kundennummer>" in request
    assert "<Device_ID>DEV-OK</Device_ID>" in request


def test_req801_document_requires_document_endpoint(mock: _MockSoapServer) -> None:
    client = _client(mock, document_endpoint=None)
    with pytest.raises(RuntimeError):
        client.get_document("prod-ok", "123456", "good", "DEV-OK")


# ------------------------------------------------------------ Konstruktor


def test_req801_for_provider_rejects_bad_scheme() -> None:
    with pytest.raises(ValueError, match="scheme"):
        SiaSoapClient.for_provider(SIA, "ftp", 5.0, 5.0)


def test_req801_safe_masks_password_in_diagnostics() -> None:
    assert _safe(None) == "ohne Detail"
    assert _safe("Fehler Passwort=geheim & mehr") == "Fehler Passwort=*** & mehr"


def test_req801_safe_masks_english_password_too() -> None:
    assert _safe("login failed password=abc123 x") == "login failed password=*** x"
