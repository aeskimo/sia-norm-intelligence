"""Quellenreferenz einer indexierten Seite (REQ-804).

1:1-Port von ``ch.sia.assistant.search.PageSource`` (Java-Referenz):
``source_id()`` ist der Merge-Schlüssel von Hybrid-Suche, RAG-Cache
und Index-Codec.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PageSource:
    """Eine indexierte Seite mit Ziffernabschnitt (Java: ``PageSource``)."""

    document_id: str
    standard: str
    edition: str
    page: int
    section: str
    text: str

    def __init__(
        self, document_id: str, standard: str, edition: str, page: int, section: str, text: str
    ) -> None:
        if not document_id.strip():
            raise ValueError("documentId fehlt")
        if page < 1:
            raise ValueError("Seite muss >=1 sein")
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "standard", standard.strip())
        object.__setattr__(self, "edition", edition.strip())
        object.__setattr__(self, "page", page)
        object.__setattr__(self, "section", section.strip())
        object.__setattr__(self, "text", text.strip())

    def source_id(self) -> str:
        """Stabile ID: ``<doc>:p<Seite>[:s<Abschnitt>]`` (Java 1:1)."""
        suffix = "" if not self.section else f":s{self.section}"
        return f"{self.document_id}:p{self.page}{suffix}"
