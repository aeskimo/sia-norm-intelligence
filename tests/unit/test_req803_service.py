"""REQ-801/803: Produkt-Service (``sni.shop.service``).

1:1-Tests des Java-Ports von ``ch.sia.reader.product.service.
SiaProductService`` plus ``ch.sia.reader.product.session``
(``LicenseSession``, ``SessionCredentials``): Login mit .mro-Dekodierung
und Katalog, Download mit .srd-Dekodierung und PDF-Signaturcheck,
Protokoll-Fehlercodes 1:1, Zeroing beim Schliessen. Vollkette mit
synthetischen .mro/.srd (G4: keine echten Kunden, Schlüssel oder Normtexte).
"""

from __future__ import annotations

import base64

import pytest

from sni.shop.catalog import CatalogStore
from sni.shop.models import LoginResult, LoginStatus
from sni.shop.service import (
    LicenseSession,
    SessionCredentials,
    SiaProductService,
)
from tests.conftest import (
    LICENSE_XML,
    FakeSoapClient,
    document_result_failure,
    document_result_ok,
    login_result_failure,
    login_result_ok,
    make_mro,
    make_pdf,
    make_srd,
)

SRD_KEY_IV = ("k1234567", "i1234567")


def _service(client: FakeSoapClient) -> SiaProductService:
    return SiaProductService(CatalogStore(), lambda: client)


def _logged_in(
    client: FakeSoapClient, customer: str = "kunde1"
) -> tuple[SiaProductService, LicenseSession, SessionCredentials]:
    service = _service(client)
    credentials = SessionCredentials(customer, "geheim", "dev-1")
    outcome = service.login(credentials)
    assert outcome.success and outcome.session is not None
    return service, outcome.session, credentials


# ------------------------------------------------------------------ Login


def test_req803_service_login_success_populates_catalog() -> None:
    client = FakeSoapClient(login_result_ok(), make_mro(LICENSE_XML))
    service = _service(client)
    credentials = SessionCredentials("  kunde1 ", "geheim", " dev-1 ")

    outcome = service.login(credentials)

    assert outcome.success
    assert outcome.message == "1 Katalogwarnungen"  # Produkt ohne ID
    assert outcome.catalog_size == 2
    assert outcome.session is not None
    assert service.catalog.by_id("prod-101") is not None
    doc_102 = service.catalog.by_id("prod-102")
    assert doc_102 is not None
    assert doc_102.view_allowed is False
    # Java: Credentials bleiben bei Erfolg in der Session.
    assert not credentials.closed
    assert credentials.password_copy() == "geheim"
    assert credentials.customer == "kunde1"  # trim
    assert credentials.device_id == "dev-1"


def test_req803_service_login_failure_passes_protocol_code_1_to_1() -> None:
    client = FakeSoapClient(
        login_result_failure(LoginStatus.INVALID_PASSWORD, "Passwort ist falsch.")
    )
    service = _service(client)
    credentials = SessionCredentials("kunde1", "geheim", "dev-1")

    outcome = service.login(credentials)

    # G6: Protokoll-Fehlercode 1:1 (Java: safe(r) = "STATUS: ...").
    assert not outcome.success
    assert outcome.message == "INVALID_PASSWORD: Passwort ist falsch."
    assert outcome.catalog_size == 0
    assert outcome.session is None
    assert credentials.closed  # Java: credentials.close() bei Fehlschlag


def test_req803_service_login_transport_failure_with_diagnostic() -> None:
    client = FakeSoapClient(
        LoginResult(
            False,
            0,
            LoginStatus.UNKNOWN_SERVER_CODE,
            None,
            None,
            0,
            5,
            "Zeitüberschreitung beim Warten auf die Serverantwort.",
            2,
        )
    )
    outcome = _service(client).login(SessionCredentials("kunde1", "geheim", "dev-1"))
    assert not outcome.success
    assert (
        outcome.message
        == "UNKNOWN_SERVER_CODE: Zeitüberschreitung beim Warten auf die Serverantwort."
    )


def test_req803_service_login_missing_detail_renders_null_like_java() -> None:
    # Java-String-Konkatenation rendert null als "null" (1:1).
    client = FakeSoapClient(
        LoginResult(False, 500, LoginStatus.UNKNOWN_SERVER_CODE, None, None, 0, 5, None, 1)
    )
    outcome = _service(client).login(SessionCredentials("kunde1", "geheim", "dev-1"))
    assert outcome.message == "UNKNOWN_SERVER_CODE: null"


def test_req803_service_login_malformed_mro_returns_error() -> None:
    client = FakeSoapClient(login_result_ok(), b"kein-zip")
    service = _service(client)
    credentials = SessionCredentials("kunde1", "geheim", "dev-1")

    outcome = service.login(credentials)

    assert not outcome.success
    assert outcome.message.startswith("SiaShopError:")
    assert outcome.session is None
    assert credentials.closed  # Java: catch → credentials.close()


def test_req803_service_login_ok_message_without_warnings() -> None:
    no_id_block = "  <Produkt>\n    <Bezeichnung>Ohne ID</Bezeichnung>\n  </Produkt>\n"
    xml = LICENSE_XML.replace(no_id_block, "")
    client = FakeSoapClient(login_result_ok(), make_mro(xml))
    outcome = _service(client).login(SessionCredentials("kunde1", "geheim", "dev-1"))
    assert outcome.success and outcome.message == "OK"


# ------------------------------------------------------------------ Download


def test_req803_service_download_success_decrypts_pdf() -> None:
    pdf = make_pdf(["SYN 1  Testnorm"])
    client = FakeSoapClient(
        login_result_ok(),
        make_mro(LICENSE_XML),
        document_result_ok("101_2020_dSIA.srd"),
        make_srd("prod-101", pdf),
    )
    service, session, _ = _logged_in(client)

    outcome = service.download(session, "prod-101")

    assert outcome.success
    assert outcome.filename == "101_2020_dSIA.srd"
    assert outcome.pdf == pdf
    assert outcome.message == "OK"


def test_req803_service_download_unknown_product() -> None:
    client = FakeSoapClient(login_result_ok(), make_mro(LICENSE_XML))
    service, session, _ = _logged_in(client)
    outcome = service.download(session, "unbekannt")
    assert not outcome.success
    assert outcome.message == "Produkt nicht im Katalog"
    assert outcome.pdf is None


def test_req803_service_download_view_not_allowed() -> None:
    client = FakeSoapClient(login_result_ok(), make_mro(LICENSE_XML))
    service, session, _ = _logged_in(client)
    outcome = service.download(session, "prod-102")
    assert not outcome.success
    assert outcome.message == "Anzeige laut Lizenz nicht erlaubt"


def test_req803_service_download_diagnostic_wins_over_message() -> None:
    client = FakeSoapClient(
        login_result_ok(),
        make_mro(LICENSE_XML),
        document_result_failure(
            "Fail_Unknown_Produkt", "Produkt unbekannt", "x.srd", "SOAP-Fault-Details"
        ),
    )
    service, session, _ = _logged_in(client)
    outcome = service.download(session, "prod-101")
    assert not outcome.success
    assert outcome.filename == "x.srd"
    assert outcome.message == "SOAP-Fault-Details"  # Java: diagnostic != null ? ...


def test_req803_service_download_server_message_when_no_diagnostic() -> None:
    client = FakeSoapClient(
        login_result_ok(),
        make_mro(LICENSE_XML),
        document_result_failure("Fail_Unknown_Produkt", "Produkt unbekannt", None, None),
    )
    service, session, _ = _logged_in(client)
    outcome = service.download(session, "prod-101")
    assert not outcome.success
    assert outcome.message == "Produkt unbekannt"


def test_req803_service_download_empty_content() -> None:
    client = FakeSoapClient(
        login_result_ok(), make_mro(LICENSE_XML), document_result_ok("x.srd"), None
    )
    service, session, _ = _logged_in(client)
    outcome = service.download(session, "prod-101")
    assert not outcome.success
    assert outcome.filename == "x.srd"
    assert outcome.message == "Leerer Dokumentinhalt"


def test_req803_service_download_invalid_pdf_signature() -> None:
    client = FakeSoapClient(
        login_result_ok(),
        make_mro(LICENSE_XML),
        document_result_ok("x.srd"),
        make_srd("prod-101", b"KEIN-PDF-INHALT"),
    )
    service, session, _ = _logged_in(client)
    outcome = service.download(session, "prod-101")
    assert not outcome.success
    assert outcome.message == "Ungültige PDF-Signatur"
    assert outcome.pdf is None


def test_req803_service_download_srd_decrypt_failure() -> None:
    # Crypted-Payload kein Vielfaches von 8 Byte → SiaShopError (Java: catch).
    bad = make_srd("prod-101", b"", crypted_b64=base64.b64encode(b"0123456789").decode("ascii"))
    client = FakeSoapClient(
        login_result_ok(), make_mro(LICENSE_XML), document_result_ok("x.srd"), bad
    )
    service, session, _ = _logged_in(client)
    outcome = service.download(session, "prod-101")
    assert not outcome.success
    assert outcome.message is not None
    assert outcome.message.startswith("SiaShopError:")


def test_req803_service_download_after_close_raises() -> None:
    client = FakeSoapClient(login_result_ok(), make_mro(LICENSE_XML))
    service, session, _ = _logged_in(client)
    session.close()
    with pytest.raises(RuntimeError, match="Session geschlossen"):
        service.download(session, "prod-101")  # Java: passwordCopy() wirft


# ------------------------------------------------------------------ Session


def test_req803_service_session_credentials_close_zeroing() -> None:
    credentials = SessionCredentials("kunde", "pw", "dev")
    assert credentials.customer == "kunde"
    assert credentials.device_id == "dev"
    assert credentials.password_copy() == "pw"
    credentials.close()
    assert credentials.closed
    with pytest.raises(RuntimeError, match="Session geschlossen"):
        credentials.password_copy()


def test_req803_service_license_session_key_iv_close() -> None:
    key, iv = SRD_KEY_IV
    credentials = SessionCredentials("kunde", "pw", "dev")
    session = LicenseSession(credentials, key, iv)
    assert session.key_copy() == key
    assert session.iv_copy() == iv
    session.close()
    assert credentials.closed  # Java: close() schliesst auch die Credentials
    with pytest.raises(RuntimeError, match="Session geschlossen"):
        session.key_copy()
    with pytest.raises(RuntimeError, match="Session geschlossen"):
        session.iv_copy()
