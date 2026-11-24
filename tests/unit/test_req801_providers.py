"""REQ-801: Provider-Profile (SIA/VSS/PHGR/SWKI) — 1:1-Port von
``ch.sia.reader.login.ProviderProfile``."""

from __future__ import annotations

from sni.shop.providers import PHGR, SIA, SOAP_NAMESPACE, SOAP_SERVER_PATH, SWKI, VSS


def test_req801_provider_sia_fields_and_urls() -> None:
    assert SIA.app_name == "SIA-Reader"
    assert SIA.soap_server == "shop.sia.ch"
    assert (
        SIA.endpoint("https", "srDefault") == "https://shop.sia.ch/Secure_Webservice/srDefault.asmx"
    )
    assert (
        SIA.endpoint("https", "srLizenz") == "https://shop.sia.ch/Secure_Webservice/srLizenz.asmx"
    )
    assert SIA.namespace_url() == "http://www.redMSoftware.ch/Secure_Webservice"


def test_req801_provider_all_four_mandants() -> None:
    assert SIA.soap_server == "shop.sia.ch"
    assert VSS.soap_server == "www.vss.ch"
    assert PHGR.soap_server == "doksi.exigo.ch"
    assert SWKI.soap_server == "shop.swki.ch"
    for profile in (SIA, VSS, PHGR, SWKI):
        assert profile.soap_server_path == SOAP_SERVER_PATH
        assert profile.soap_namespace == SOAP_NAMESPACE
        assert profile.endpoint("https", "srDokument").endswith(
            "/Secure_Webservice/srDokument.asmx"
        )
