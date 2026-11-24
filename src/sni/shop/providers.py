"""Mandanten-Profile des SIA-Shop-SOAP-Ports (REQ-801).

1:1-Port von ``ch.sia.reader.login.ProviderProfile`` (rekonstruiert aus dem
Konstruktor von ``res.Config`` in SIA-Reader.jar, Bytecode 2015). Der
statische DES-Schlüssel ist für alle vier Mandanten identisch (siehe
:mod:`sni.shop.decrypt`).

⚠ ``srDokument.asmx`` wurde in früheren Testläufen nie separat geprüft —
nur aus dem 2015er-Bytecode abgeleitet (Java-Kommentar,
``EndpointDiscovery``).
"""

from __future__ import annotations

from dataclasses import dataclass

#: Pfadpräfix aller Service-Endpunkte (res.Config, alle Mandanten).
SOAP_SERVER_PATH = "Secure_Webservice/"
#: SOAP-Namespace (res.Config, alle Mandanten).
SOAP_NAMESPACE = "www.redMSoftware.ch/Secure_Webservice"


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    """Mandanten-Konfiguration (Java: ``ProviderProfile``-Enum-Eintrag)."""

    app_name: str
    soap_server: str
    soap_server_path: str = SOAP_SERVER_PATH
    soap_namespace: str = SOAP_NAMESPACE

    def endpoint(self, scheme: str, service_name: str) -> str:
        """Endpoint-URL (Java: ``endpoint(scheme, serviceName)``)."""
        return f"{scheme}://{self.soap_server}/{self.soap_server_path}{service_name}.asmx"

    def namespace_url(self) -> str:
        """SOAP-Namespace-URL (Java: ``namespaceUrl()``)."""
        return f"http://{self.soap_namespace}"


#: SIA-Reader (shop.sia.ch) — real bestätigt durch Testlauf 03.09.2026.
SIA = ProviderProfile(app_name="SIA-Reader", soap_server="shop.sia.ch")
#: VSS-Reader (www.vss.ch).
VSS = ProviderProfile(app_name="VSS-Reader", soap_server="www.vss.ch")
#: phGR-Reader (doksi.exigo.ch).
PHGR = ProviderProfile(app_name="phGR-Reader", soap_server="doksi.exigo.ch")
#: SWKI-Reader (shop.swki.ch).
SWKI = ProviderProfile(app_name="SWKI-Reader", soap_server="shop.swki.ch")
