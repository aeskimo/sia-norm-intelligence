"""Lizenz-XML → Produkt-Katalog (REQ-801).

1:1-Port von ``ch.sia.reader.product.catalog.CatalogParser`` plus
``ch.sia.reader.product.domain.StandardDocument``: toleranter Parser für
die ``<Produkt>``-Knoten des entschlüsselten Lizenz-XML (Root
``dsSecureReaderLizenz``). Unbekannte/fehlende Felder fallen auf
Defekte zurück, fehlerhafte Produkte werden übersprungen und per
Warnung gemeldet — nie ein harter Fehler (Java: "Toleranter Parser").

Das Ergebnis enthält bewusst KEINE Zugangsdaten, Schlüssel oder
Norminhalte (Java-Klassenkommentar bei ``StandardDocument``).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date

from sni.shop.decrypt import parse_guarded_xml

_DE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_TRUE_WORDS = {"1", "true", "ja", "yes"}


@dataclass(frozen=True, slots=True)
class StandardDocument:
    """Normalisierte Produktsicht ohne Zugangsdaten, Schlüssel oder Norminhalt.

    Java: ``StandardDocument`` (Record mit Compact-Constructor).
    """

    product_id: str
    number: str
    title: str
    description: str
    keywords: str
    language: str
    year: str
    revision: str
    valid_from: date | None
    valid_until: date | None
    remote_filename: str
    view_allowed: bool
    print_allowed: bool
    copy_allowed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "product_id", _clean(self.product_id))
        if not self.product_id:
            raise ValueError("product_id darf nicht leer sein")
        object.__setattr__(self, "number", _clean(self.number))
        object.__setattr__(self, "title", _clean(self.title))
        object.__setattr__(self, "description", _clean(self.description))
        object.__setattr__(self, "keywords", _clean(self.keywords))
        object.__setattr__(self, "language", _clean(self.language).upper())
        object.__setattr__(self, "year", _clean(self.year))
        object.__setattr__(self, "revision", _clean(self.revision))
        object.__setattr__(self, "remote_filename", _clean(self.remote_filename))

    def valid_on(self, other: date) -> bool:
        """Lizenzgültigkeit an ``other`` (Java: ``validOn``; None = offen)."""
        return (self.valid_from is None or other >= self.valid_from) and (
            self.valid_until is None or other <= self.valid_until
        )

    def searchable_text(self) -> str:
        """Suchtext (Java: ``searchableText``)."""
        return " ".join(
            (
                self.number,
                self.title,
                self.description,
                self.keywords,
                self.language,
                self.year,
                self.revision,
            )
        ).lower()


@dataclass(frozen=True, slots=True)
class CatalogResult:
    """Parser-Ergebnis (Java: ``CatalogParser.Result``, Defensive-Copy)."""

    documents: tuple[StandardDocument, ...]
    warnings: tuple[str, ...]


def parse_license_catalog(license_xml: str) -> CatalogResult:
    """Toleranter Parser für ``<Produkt>``-Knoten des Lizenz-XML.

    Java: ``CatalogParser.parse``. Namespace-agnostisch; Produkte ohne ID
    werden übersprungen (Warnung), fehlerhafte Produkte lösen eine Warnung
    statt eines Fehlers aus.
    """
    root = parse_guarded_xml(license_xml.encode("utf-8"), "Lizenz-XML")
    docs: list[StandardDocument] = []
    warnings: list[str] = []
    for i, product in enumerate(_find_all(root, "Produkt")):
        product_id = _child_text(product, "ID")
        if not product_id:
            warnings.append(f"Produkt {i} ohne ID übersprungen")
            continue
        try:
            docs.append(
                StandardDocument(
                    product_id=product_id,
                    number=_child_text(product, "Produktnummer"),
                    title=_child_text(product, "Bezeichnung"),
                    description=_child_text(product, "Beschreibung"),
                    keywords=_child_text(product, "Stichworte"),
                    language=_first(
                        _child_text(product, "Sprach_Code"),
                        _child_text(product, "Sprache_Code"),
                    ),
                    year=_child_text(product, "Jahr"),
                    revision=_child_text(product, "Revision"),
                    valid_from=_parse_date(
                        _first(
                            _child_text(product, "Liz_Von"),
                            _child_text(product, "Datum_VON"),
                        )
                    ),
                    valid_until=_parse_date(
                        _first(
                            _child_text(product, "Liz_Bis"),
                            _child_text(product, "Datum_BIS"),
                        )
                    ),
                    remote_filename=_first(
                        _child_text(product, "Dateiname"),
                        _child_text(product, "Dateiname_Original"),
                    ),
                    view_allowed=_bool(_child_text(product, "Recht_View"), True),
                    print_allowed=_bool(_child_text(product, "Recht_Print"), False),
                    copy_allowed=_bool(_child_text(product, "Recht_CopyPaste"), False),
                )
            )
        except ValueError as exc:
            warnings.append(f"Produkt {i} konnte nicht importiert werden: {type(exc).__name__}")
    return CatalogResult(documents=tuple(docs), warnings=tuple(warnings))


def _find_all(root: ET.Element, local_name: str) -> list[ET.Element]:
    """Alle Elemente mit lokalem Namen, Dokument-Reihenfolge, namespace-agnostisch.

    Entspricht ``getElementsByTagNameNS("*", name)`` der Java-Referenz.
    """
    found: list[ET.Element] = []
    for element in root.iter():
        tag = element.tag
        if isinstance(tag, str) and tag.rsplit("}", 1)[-1] == local_name:
            found.append(element)
    return found


def _child_text(parent: ET.Element, name: str) -> str:
    """Text des ersten DIREKTEN Kind-Elements mit lokalem Namen (Java: ``text``)."""
    for child in parent:
        tag = child.tag
        if not isinstance(tag, str):
            continue
        if tag.rsplit("}", 1)[-1] == name:
            return "".join(child.itertext()).strip()
    return ""


def _first(*values: str) -> str:
    """Erster nicht-leerer Wert, sonst leere Zeichenkette (Java: ``first``)."""
    for value in values:
        if value.strip():
            return value
    return ""


def _bool(value: str, fallback: bool) -> bool:
    """Java: ``bool`` — leer = Fallback, sonst {"1","true","ja","yes"}."""
    if not value:
        return fallback
    return value.lower() in _TRUE_WORDS


def _parse_date(value: str) -> date | None:
    """Java: ``date`` — ISO (JJJJ-MM-TT) oder dt. TT.MM.JJJJ; Fehler = None."""
    if not value.strip():
        return None
    v = value.strip()
    if len(v) > 10:
        v = v[:10]
    try:
        return date.fromisoformat(v)
    except ValueError:
        pass
    match = _DE_RE.fullmatch(v)
    if match:
        try:
            return date(int(match[3]), int(match[2]), int(match[1]))
        except ValueError:
            return None
    return None


def _clean(value: str) -> str:
    """Java: ``clean`` (null → "", trim)."""
    return value.strip()
