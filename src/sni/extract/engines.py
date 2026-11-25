"""PDF-Textextraktions-Engines (REQ-804, ADR-0011, OQ-010).

Vertrag 1:1 zu ``ch.sia.assistant.search.PdfTextExtractor``; die
Seitenaufbereitung ist 1:1 zu ``ch.sia.assistant.search.
PdftotextExtractor.pages``: Form-Feed trennt die Seiten, ``\\r\\n`` wird
zu ``\\n`` normalisiert, leere Seiten fallen weg, pro Seite wird die
erste Ziffern-Zeile als Abschnittserkennung verwendet.

Engines (OQ-010): ``Pypdfium2Extractor`` (primär) und
``PdfminerExtractor`` (Gegenkandidat). Beide liefern den rohen
Seitentext, ``pages`` baut daraus ``PageSource``-Einträge.
"""

from __future__ import annotations

import re
from io import BytesIO
from typing import Protocol

import pdfminer.high_level
import pypdfium2

from sni.search.page_source import PageSource

#: OQ-010: pypdfium2 ist die Primär-Engine, pdfminer.six der Gegenkandidat.
DEFAULT_ENGINE = "pypdfium2"

# Java: text.split("\\R") — Python ``splitlines`` deckt dieselbe
# Grenze ab (\\n, \\r, \\r\\n, \\x85, \\u2028, \\u2029, \\x0b, \\x0c).
_SECTION_RE = re.compile(r"[0-9]+(?:\.[0-9]+){0,4}(?:\s+.*)?")


class PdfTextExtractor(Protocol):
    """Austauschbare PDF-Textextraktion (Java-Vertrag 1:1)."""

    def extract(
        self, document_id: str, standard: str, edition: str, pdf: bytes
    ) -> list[PageSource]: ...


def require_pdf(pdf: bytes) -> None:
    """Java ``requirePdf``: Signatur ``%PDF-`` prüfen (1:1)."""
    if len(pdf) < 5 or pdf[:5] != b"%PDF-":
        raise ValueError("Keine gültige PDF-Signatur")


def detect_section(text: str) -> str:
    """Java ``detectSection``: erste Ziffern-Zeile → Ziffern-Präfix (1:1)."""
    for line in text.splitlines():
        stripped = line.strip()
        if _SECTION_RE.fullmatch(stripped) is not None:
            space = stripped.find(" ")
            return stripped if space < 0 else stripped[:space]
    return ""


def pages(document_id: str, standard: str, edition: str, extracted: str) -> list[PageSource]:
    """Java ``PdftotextExtractor.pages``: Form-Feed-Split + Normalisierung (1:1)."""
    out: list[PageSource] = []
    for i, raw in enumerate(extracted.split("\f")):
        text = raw.replace("\r\n", "\n").strip()
        if text:
            out.append(
                PageSource(document_id, standard, edition, i + 1, detect_section(text), text)
            )
    return out


class Pypdfium2Extractor:
    """Primär-Engine (OQ-010): pypdfium2, Binaries im Wheel.

    Liefert pro Seite das Layout-Text (``get_text_range``); Zeilen
    getrennt durch ``\\r\\n``, Wörter durch ein Leerzeichen.
    """

    def extract(
        self, document_id: str, standard: str, edition: str, pdf: bytes
    ) -> list[PageSource]:
        require_pdf(pdf)
        try:
            parts: list[str] = []
            doc = pypdfium2.PdfDocument(pdf)
            try:
                for page in doc:
                    textpage = page.get_textpage()
                    try:
                        parts.append(textpage.get_text_range())
                    finally:
                        textpage.close()
            finally:
                doc.close()
        except Exception as exc:
            raise RuntimeError(f"PDF-Textextraktion fehlgeschlagen: {exc}") from exc
        return pages(document_id, standard, edition, "\f".join(parts))


class PdfminerExtractor:
    """Gegenkandidat (OQ-010): pdfminer.six.

    Liefert Text mit ``\\n``-Zeilen und Form-Feed an den
    Seitenenden (auch nach der letzten Seite; leeres Rest-Element
    fällt in ``pages`` weg).
    """

    def extract(
        self, document_id: str, standard: str, edition: str, pdf: bytes
    ) -> list[PageSource]:
        require_pdf(pdf)
        try:
            extracted = pdfminer.high_level.extract_text(BytesIO(pdf))
        except Exception as exc:
            raise RuntimeError(f"PDF-Textextraktion fehlgeschlagen: {exc}") from exc
        return pages(document_id, standard, edition, extracted or "")


def get_extractor(engine: str = DEFAULT_ENGINE) -> PdfTextExtractor:
    """Erzeugt die Extraktions-Engine nach Name (Default: pypdfium2)."""
    if engine == "pypdfium2":
        return Pypdfium2Extractor()
    if engine == "pdfminer":
        return PdfminerExtractor()
    raise ValueError(f"Unbekannte Extraktionsengine {engine!r} (erlaubt: 'pypdfium2', 'pdfminer')")
