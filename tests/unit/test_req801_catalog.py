"""REQ-801: Lizenz-XML → Produkt-Katalog (``sni.shop.catalog_xml``).

1:1-Tests des Java-Ports von ``ch.sia.reader.product.catalog.CatalogParser``
plus ``StandardDocument`` (SIA-Normenassistent). Toleranz-Verhalten (Feld-
Fallbacks, Überspringen ohne ID, Datums-Formate) und Normalisierung
(trim, Sprache groß) werden mit synthetischen Lizenz-XMLs geprüft
(G4: keine echten Kunden, Lizenzschlüssel oder Normtexte).
"""

from __future__ import annotations

from datetime import date

import pytest

from sni.shop.catalog_xml import (
    CatalogResult,
    StandardDocument,
    parse_license_catalog,
)
from sni.shop.decrypt import SiaShopError

FULL_XML = """<?xml version="1.0"?>
<dsSecureReaderLizenz>
  <Konfiguration>
    <SRD_KEY>synthetisch</SRD_KEY>
    <SRD_IV>synthetisch</SRD_IV>
  </Konfiguration>
  <Produkt>
    <ID>prod-0001</ID>
    <Produktnummer>SIA 101</Produktnummer>
    <Bezeichnung>Testnorm A</Bezeichnung>
    <Beschreibung>Synthetische Testnorm (G4).</Beschreibung>
    <Stichworte>Test, Norm</Stichworte>
    <Sprach_Code>de</Sprach_Code>
    <Jahr>2026</Jahr>
    <Revision>1</Revision>
    <Liz_Von>2026-01-01</Liz_Von>
    <Liz_Bis>2027-01-01</Liz_Bis>
    <Dateiname>101_2020_dSIA.srd</Dateiname>
    <Recht_View>ja</Recht_View>
    <Recht_Print>1</Recht_Print>
    <Recht_CopyPaste>true</Recht_CopyPaste>
  </Produkt>
  <Produkt>
    <ID>prod-0002</ID>
    <Produktnummer>VSS 200</Produktnummer>
    <Bezeichnung>Testnorm B</Bezeichnung>
    <Sprache_Code>fr</Sprache_Code>
    <Datum_VON>01.02.2025</Datum_VON>
    <Datum_BIS></Datum_BIS>
    <Dateiname_Original>200_2019_dVSS.srd</Dateiname_Original>
    <Recht_Print>nein</Recht_Print>
  </Produkt>
</dsSecureReaderLizenz>
"""

DATE_XML = """<?xml version="1.0"?>
<dsSecureReaderLizenz>
  <Produkt><ID>p1</ID><Liz_Von>2026-11-24 12:00:00</Liz_Von></Produkt>
  <Produkt><ID>p2</ID><Liz_Bis>31.02.2026</Liz_Bis></Produkt>
  <Produkt><ID>p3</ID><Liz_Von>definitiv-kaputt</Liz_Von></Produkt>
</dsSecureReaderLizenz>
"""

NS_XML = """<?xml version="1.0"?>
<dsSecureReaderLizenz xmlns="http://www.redMSoftware.ch/Lizenz">
  <Produkt>
    <ID>ns-0001</ID>
    <Bezeichnung>Namespace-Test</Bezeichnung>
  </Produkt>
</dsSecureReaderLizenz>
"""

NESTED_XML = """<?xml version="1.0"?>
<dsSecureReaderLizenz>
  <Produkt>
    <ID>n-1</ID>
    <Beschreibung>Aussen<Jahr>999</Jahr></Beschreibung>
  </Produkt>
</dsSecureReaderLizenz>
"""

MIXED_XML = """<?xml version="1.0"?>
<dsSecureReaderLizenz>
  <Produkt><ID>ok-1</ID><Bezeichnung>Gut</Bezeichnung></Produkt>
  <Produkt><Bezeichnung>Ohne ID</Bezeichnung></Produkt>
  <Produkt><ID>ok-2</ID><Bezeichnung>Auch gut</Bezeichnung></Produkt>
</dsSecureReaderLizenz>
"""


def _doc(
    valid_from: date | None = None,
    valid_until: date | None = None,
    product_id: str = "p",
    **fields: object,
) -> StandardDocument:
    base: dict[str, object] = {
        "product_id": product_id,
        "number": "",
        "title": "",
        "description": "",
        "keywords": "",
        "language": "",
        "year": "",
        "revision": "",
        "valid_from": valid_from,
        "valid_until": valid_until,
        "remote_filename": "",
        "view_allowed": True,
        "print_allowed": False,
        "copy_allowed": False,
    }
    base.update(fields)
    return StandardDocument(**base)  # type: ignore[arg-type]


def test_req801_catalog_full_product_parsed() -> None:
    result: CatalogResult = parse_license_catalog(FULL_XML)
    assert len(result.documents) == 2
    assert result.warnings == ()

    doc = result.documents[0]
    assert doc.product_id == "prod-0001"
    assert doc.number == "SIA 101"
    assert doc.title == "Testnorm A"
    assert doc.description == "Synthetische Testnorm (G4)."
    assert doc.keywords == "Test, Norm"
    assert doc.language == "DE"  # Java: toUpperCase(Locale.ROOT)
    assert doc.year == "2026"
    assert doc.revision == "1"
    assert doc.valid_from == date(2026, 1, 1)
    assert doc.valid_until == date(2027, 1, 1)
    assert doc.remote_filename == "101_2020_dSIA.srd"
    assert doc.view_allowed is True  # "ja"
    assert doc.print_allowed is True  # "1"
    assert doc.copy_allowed is True  # "true"


def test_req801_catalog_fallback_field_names() -> None:
    result = parse_license_catalog(FULL_XML)
    doc = result.documents[1]
    assert doc.product_id == "prod-0002"
    assert doc.language == "FR"  # Sprache_Code (alternativer Feldname)
    assert doc.valid_from == date(2025, 2, 1)  # Datum_VON, dt. Format
    assert doc.valid_until is None  # leeres Datum_BIS
    assert doc.remote_filename == "200_2019_dVSS.srd"  # Dateiname_Original
    assert doc.view_allowed is True  # Feld fehlt → Fallback true
    assert doc.print_allowed is False  # "nein" → kein True-Wert
    assert doc.copy_allowed is False  # Feld fehlt → Fallback false


def test_req801_catalog_date_formats_and_truncation() -> None:
    result = parse_license_catalog(DATE_XML)
    p1, p2, p3 = result.documents
    # >10 Zeichen: auf 10 gekürzt (Java: substring(0, 10)).
    assert p1.valid_from == date(2026, 11, 24)
    # Ungültiges Datum (31.02.) → None, kein Fehler (Java: date() null).
    assert p2.valid_until is None
    assert p3.valid_from is None


def test_req801_catalog_product_without_id_skipped_with_warning() -> None:
    result = parse_license_catalog(MIXED_XML)
    assert [d.product_id for d in result.documents] == ["ok-1", "ok-2"]
    assert result.warnings == ("Produkt 1 ohne ID übersprungen",)


def test_req801_catalog_namespaced_products_found() -> None:
    result = parse_license_catalog(NS_XML)
    assert len(result.documents) == 1
    assert result.documents[0].product_id == "ns-0001"
    assert result.documents[0].title == "Namespace-Test"


def test_req801_catalog_only_direct_children_read() -> None:
    # Java text() liest nur DIREKTE Kinder — verschachtelte Namen zählen
    # nicht als Feld.
    result = parse_license_catalog(NESTED_XML)
    assert result.documents[0].year == ""
    assert "999" in result.documents[0].description


def test_req801_catalog_malformed_xml_raises() -> None:
    with pytest.raises(SiaShopError, match="ungültiges XML"):
        parse_license_catalog("<dsSecureReaderLizenz><Produkt>")


def test_req801_catalog_doctype_rejected() -> None:
    xml = '<!DOCTYPE foo SYSTEM "http://evil.example/x"><dsSecureReaderLizenz/>'
    with pytest.raises(SiaShopError, match="DOCTYPE"):
        parse_license_catalog(xml)


def test_req801_standard_document_rejects_blank_id() -> None:
    with pytest.raises(ValueError, match="product_id"):
        _doc(product_id="   ")


def test_req801_standard_document_valid_on_boundaries() -> None:
    doc = _doc(valid_from=date(2026, 1, 1), valid_until=date(2026, 12, 31))
    assert not doc.valid_on(date(2025, 12, 31))
    assert doc.valid_on(date(2026, 1, 1))  # untere Grenze inclusive
    assert doc.valid_on(date(2026, 7, 15))
    assert doc.valid_on(date(2026, 12, 31))  # obere Grenze inclusive
    assert not doc.valid_on(date(2027, 1, 1))

    open_doc = _doc()
    assert open_doc.valid_on(date(1999, 1, 1))
    assert open_doc.valid_on(date(2999, 12, 31))


def test_req801_standard_document_searchable_text() -> None:
    doc = _doc(
        number="SIA 101",
        title="Testnorm",
        description="Beschreibung",
        keywords="a, b",
        language="de",
        year="2026",
        revision="2",
    )
    assert doc.searchable_text() == "sia 101 testnorm beschreibung a, b de 2026 2"


def test_req801_standard_document_trims_and_uppercases() -> None:
    doc = StandardDocument(
        product_id="  p-1  ",
        number=" SIA 101 ",
        title="Test",
        description="",
        keywords="",
        language=" de ",
        year="",
        revision="",
        valid_from=None,
        valid_until=None,
        remote_filename="  x.srd ",
        view_allowed=True,
        print_allowed=False,
        copy_allowed=False,
    )
    assert doc.product_id == "p-1"
    assert doc.number == "SIA 101"
    assert doc.language == "DE"
    assert doc.remote_filename == "x.srd"
