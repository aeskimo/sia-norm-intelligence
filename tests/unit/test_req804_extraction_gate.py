"""REQ-804: PDF-Extraktions-Gate (ADR-0011, OQ-010).

Gate laut ADR-0011: Beide Extraktions-Engines (``pypdfium2`` primär,
``pdfminer.six`` Gegenkandidat) müssen ein synthetisches Test-PDF (G4)
korrekt extrahieren: Ziffern-Abschnittserkennungsrate 100 % gegen die
Ground-Truth-Fixture, korrekte Seitennummern und Quellen-IDs.
Textlose Seiten dürfen keine Einträge liefern (→ Pipeline-Fehler,
OQ-015). Default-Engine ist ``pypdfium2``.
"""

from __future__ import annotations

import pytest

from sni.extract.engines import (
    DEFAULT_ENGINE,
    PdfminerExtractor,
    PdfTextExtractor,
    Pypdfium2Extractor,
    detect_section,
    get_extractor,
    pages,
    require_pdf,
)
from tests.conftest import make_pdf

#: Ground-Truth-Fixture: Seiten mit führender Ziffer (1:1-Abschnitt).
SECTIONED_PDF: list[list[str]] = [
    ["3.1 Wasserhaltung", "Die Dichtung muss dicht sein.", "Ziele werden geprüft."],
    ["3.2.4 Detailabdichtung", "Detailabdichtung nach Zielwerten."],
]
SECTIONED_TRUTH = ("3.1", "3.2.4")


@pytest.fixture(params=["pypdfium2", "pdfminer"], ids=["pypdfium2", "pdfminer"])
def engine(request: pytest.FixtureRequest) -> PdfTextExtractor:
    return get_extractor(request.param)


def test_req804_gate_engines_extract_all_pages(engine: PdfTextExtractor) -> None:
    pdf = make_pdf(SECTIONED_PDF)
    extracted = engine.extract("doc-1", "SIA TEST", "2026", pdf)
    assert [page.page for page in extracted] == [1, 2]
    assert [page.section for page in extracted] == list(SECTIONED_TRUTH)
    assert "Die Dichtung muss dicht sein." in extracted[0].text
    assert "Detailabdichtung nach Zielwerten." in extracted[1].text
    assert extracted[0].source_id() == "doc-1:p1:s3.1"
    assert extracted[1].source_id() == "doc-1:p2:s3.2.4"
    assert extracted[0].standard == "SIA TEST"
    assert extracted[0].edition == "2026"


def test_req804_gate_section_detection_rate_100_percent(engine: PdfTextExtractor) -> None:
    extracted = engine.extract("doc-1", "SIA TEST", "2026", make_pdf(SECTIONED_PDF))
    pairs = list(zip(extracted, SECTIONED_TRUTH, strict=True))
    assert pairs
    detected = sum(page.section == truth for page, truth in pairs)
    assert detected / len(pairs) == 1.0  # Erkennungsrate 100 %


def test_req804_gate_default_engine_is_pypdfium2() -> None:
    assert DEFAULT_ENGINE == "pypdfium2"
    assert isinstance(get_extractor(), Pypdfium2Extractor)
    assert isinstance(get_extractor("pypdfium2"), Pypdfium2Extractor)
    assert isinstance(get_extractor("pdfminer"), PdfminerExtractor)
    with pytest.raises(ValueError, match="Unbekannte Extraktionsengine"):
        get_extractor("pdftotext")


def test_req804_gate_non_pdf_signature_rejected(engine: PdfTextExtractor) -> None:
    with pytest.raises(ValueError, match="Keine gültige PDF-Signatur"):
        engine.extract("x", "", "", bytes((1, 2, 3)))
    with pytest.raises(ValueError, match="Keine gültige PDF-Signatur"):
        require_pdf(b"%PD")
    require_pdf(b"%PDF-1.4")  # gültige Signatur: keine Ausnahme


def test_req804_gate_textless_pages_yield_no_entries(engine: PdfTextExtractor) -> None:
    assert engine.extract("d", "S", "E", make_pdf([[]])) == []
    mixed = engine.extract("d", "S", "E", make_pdf([["3.1 Text"], []]))
    assert [page.page for page in mixed] == [1]


def test_req804_pages_normalization_and_numbering() -> None:
    extracted = pages("d", "S", "E", "abc\r\n1.2 Foo\r\nbar\f\fxyz")
    assert [(page.page, page.section, page.text) for page in extracted] == [
        (1, "1.2", "abc\n1.2 Foo\nbar"),
        (3, "", "xyz"),
    ]


def test_req804_detect_section_variants() -> None:
    assert detect_section("2.3.4 Text") == "2.3.4"
    assert detect_section("  12  ") == "12"
    assert detect_section("keine ziffer") == ""
    assert detect_section("1.2.3.4.5 fünf Punkte") == "1.2.3.4.5"
    assert detect_section("1.2.3.4.5.6 sechs Punkte") == ""
    assert detect_section("5.1.2.3.4 max vier Punkte") == "5.1.2.3.4"
    assert detect_section("erste Zeile\n5.1 später") == "5.1"
    assert detect_section("") == ""
