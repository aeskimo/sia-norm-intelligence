"""In-Memory-Katalog (REQ-801/803).

1:1-Port von ``ch.sia.reader.product.catalog.CatalogStore``:
threadsicherer MVP-Katalog; Persistenz folgt als austauschbarer Adapter.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import date

from sni.shop.catalog_xml import StandardDocument

_DEFAULT_LIMIT = 50
_MAX_LIMIT = 500


class CatalogStore:
    """Threadsicherer MVP-Katalog (Java: ``CatalogStore``)."""

    def __init__(self) -> None:
        self._by_id: dict[str, StandardDocument] = {}
        self._lock = threading.RLock()

    def replace_all(self, documents: Sequence[StandardDocument]) -> None:
        """Java: ``replaceAll`` — komplette Ersetzung (Login)."""
        with self._lock:
            self._by_id.clear()
            for document in documents:
                self._by_id[document.product_id] = document

    def by_id(self, document_id: str) -> StandardDocument | None:
        """Java: ``byId``."""
        with self._lock:
            return self._by_id.get(document_id)

    def size(self) -> int:
        with self._lock:
            return len(self._by_id)

    def all(self) -> list[StandardDocument]:
        """Alle Produkte in Einfügeordnung (App-Erweiterung, 09 §6.2: Katalog-Tabelle)."""
        with self._lock:
            return list(self._by_id.values())

    def search(
        self,
        text: str | None,
        language: str | None,
        valid_only: bool,
        limit: int,
    ) -> list[StandardDocument]:
        """Java: ``search`` — Teilzeichenkette, Sprache, Gültigkeit, Score-Sortierung.

        Limit-Regel 1:1: ``limit < 1`` → 50, sonst ``min(limit, 500)``.
        """
        with self._lock:
            q = (text or "").strip().lower()
            lang = (language or "").strip().upper()
            docs = [d for d in self._by_id.values() if not q or q in d.searchable_text()]
            docs = [d for d in docs if not lang or d.language == lang]
            today = date.today()
            docs = [d for d in docs if not valid_only or d.valid_on(today)]
            docs.sort(key=lambda d: (-_score(d, q), d.number, d.title))
            effective = _DEFAULT_LIMIT if limit < 1 else min(limit, _MAX_LIMIT)
            return docs[:effective]


def _score(document: StandardDocument, q: str) -> int:
    """Java: ``score`` — Nummer-Treffer wiegen mehr als Titel-Treffer."""
    n = document.number.lower()
    t = document.title.lower()
    if n == q:
        return 100
    if n.startswith(q):
        return 80
    if t.startswith(q):
        return 60
    if q in n:
        return 50
    if q in t:
        return 40
    return 10
