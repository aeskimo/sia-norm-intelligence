"""PDF-Textextraktion der Analyse-Pipeline (REQ-804, ADR-0011, OQ-010).

Vertrag 1:1 zu ``ch.sia.assistant.search.PdfTextExtractor`` (Java-
Referenz): ``extract(documentId, standard, edition, pdf) -> list[
PageSource]``. Zwei austauschbare Engines (OQ-010):

- ``Pypdfium2Extractor`` — Primär-Engine (pypdfium2, Binaries im Wheel)
- ``PdfminerExtractor``  — Gegenkandidat (pdfminer.six)

Die Seitennormalisierung (Form-Feed-Paginen, ``\\r\\n`` → ``\\n``,
Ziffern-Abschnittserkennung) ist die gemeinsame Funktion ``pages``
(1:1-Port von ``PdftotextExtractor.pages``).
"""

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

__all__ = [
    "DEFAULT_ENGINE",
    "PdfTextExtractor",
    "PdfminerExtractor",
    "Pypdfium2Extractor",
    "detect_section",
    "get_extractor",
    "pages",
    "require_pdf",
]
