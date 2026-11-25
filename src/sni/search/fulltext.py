"""Lokaler Volltextindex mit invertierter Wortfrequenz (REQ-804).

1:1-Port von ``ch.sia.assistant.search.LocalFullTextIndex`` (Java-
Referenz; Self-Test ``M2InvertedIndexSelfTest`` als Test-Vorlage):

- Normalisierung: NFKC + lowercase (Java ``Locale.ROOT``).
- Token: Zeichenfolgen aus Buchstaben/Zahlen (Java ``[^\\p{L}\\p{N}]+``);
  Python ``re`` kennt keine Unicode-Kategorienklassen, daher manueller
  Scan über ``unicodedata.category`` (exakt gleiches Verhalten).
- Exakter Treffer + Präfix-Fallback (``Ziel`` findet ``Ziele``).
- Score: ``100 · matchedTerms / terms + min(occurrences, 20)``.
- Sortierung: Score absteigend, dann ``source_id`` aufsteigend.
"""

from __future__ import annotations

import bisect
import re
import threading
import unicodedata
from collections.abc import Sequence, Set
from dataclasses import dataclass

from sni.search.page_source import PageSource

_WHITESPACE_RE = re.compile(r"\s+")

#: Max. Treffer pro Suchanfrage (Java: ``limit(min(limit, 100))``).
MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class SearchHit:
    """Volltext-Treffer: Quellenreferenz + Snippet + Score (Java 1:1)."""

    source: PageSource
    snippet: str
    score: float


def _normalize(text: str) -> str:
    """Java: ``Normalizer.normalize(s, NFKC).toLowerCase(Locale.ROOT)``."""
    return unicodedata.normalize("NFKC", text).lower()


def _tokenize(text: str) -> list[str]:
    """Zerlegt wie Java ``split("[^\\p{L}\\p{N}]+")``.

    Buchstaben- und Ziffernkategorien (``L*``/``N*``) bilden Tokens;
    alles andere trennt. Leere Tokens fallen weg (Java: Länge > 1).
    """
    tokens: list[str] = []
    current: list[str] = []
    for char in text:
        if unicodedata.category(char)[0] in ("L", "N"):
            current.append(char)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    return tokens


@dataclass(slots=True)
class _DocIndex:
    """Indexdaten eines Dokuments (Java: innere Klasse ``DocIndex``)."""

    pages: tuple[PageSource, ...]
    normalized: tuple[str, ...]
    term_freq: dict[str, dict[int, int]]
    sorted_terms: tuple[str, ...]


def _prefix_freq(
    term_freq: dict[str, dict[int, int]], sorted_terms: tuple[str, ...], term: str
) -> dict[int, int]:
    """Java ``tailMap(term, true)``: strikt längere, beginngleiche Terme.

    Java ``putAll`` überschreibt bei Seitenkollision (späterer Term
    gewinnt); ``dict.update`` tut dasselbe (1:1).
    """
    merged: dict[int, int] = {}
    for key in sorted_terms[bisect.bisect_left(sorted_terms, term) :]:
        if len(key) == len(term) or not key.startswith(term):
            break
        merged.update(term_freq[key])
    return merged


def _first_key_for(
    term_freq: dict[str, dict[int, int]], sorted_terms: tuple[str, ...], term: str
) -> str:
    """Der tatsächlich indexierte Term (exakt oder erstes Präfix) fürs Snippet."""
    if term in term_freq:
        return term
    start = bisect.bisect_left(sorted_terms, term)
    if start >= len(sorted_terms):
        return term
    key = sorted_terms[start]
    if key == term or not key.startswith(term):
        return term
    return key


def _snip(original: str, normalized: str, term: str) -> str:
    """Java ``snip``: Fenster 70 Zeichen vor / 180 nach dem Treffer."""
    pos = normalized.find(term)
    if pos < 0:
        pos = 0
    start = max(0, pos - 70)
    end = min(len(original), pos + 180)
    middle = _WHITESPACE_RE.sub(" ", original[start:end])
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(original) else ""
    return prefix + middle + suffix


class LocalFullTextIndex:
    """Invertierter Volltextindex (Term → Seite → Vorkommen), thread-sicher."""

    def __init__(self) -> None:
        self._docs: dict[str, _DocIndex] = {}
        self._lock = threading.RLock()

    def replace(self, document_id: str, pages: Sequence[PageSource]) -> None:
        """Indexiert ein Dokument komplett neu (Java: ``replace``)."""
        with self._lock:
            if any(page.document_id != document_id for page in pages):
                raise ValueError("Falsche Dokument-ID")
            normalized: list[str] = []
            term_freq: dict[str, dict[int, int]] = {}
            for index, page in enumerate(pages):
                norm_text = _normalize(page.text)
                normalized.append(norm_text)
                for term in _tokenize(norm_text):
                    if len(term) <= 1:
                        continue
                    per_page = term_freq.setdefault(term, {})
                    per_page[index] = per_page.get(index, 0) + 1
            self._docs[document_id] = _DocIndex(
                pages=tuple(pages),
                normalized=tuple(normalized),
                term_freq=term_freq,
                sorted_terms=tuple(sorted(term_freq)),
            )

    def delete(self, document_id: str) -> None:
        with self._lock:
            self._docs.pop(document_id, None)

    def pages(self, document_id: str) -> tuple[PageSource, ...]:
        """Die indexierten Seiten eines Dokuments (leer, wenn nicht vorhanden)."""
        with self._lock:
            doc = self._docs.get(document_id)
            return doc.pages if doc is not None else ()

    def document_count(self) -> int:
        with self._lock:
            return len(self._docs)

    def search(self, query: str, scope: Set[str] | None, limit: int) -> list[SearchHit]:
        """Sucht in (optional auf ``scope`` beschränkten) Dokumenten."""
        terms: list[str] = []
        for term in _tokenize(_normalize(query)):
            if len(term) > 1 and term not in terms:
                terms.append(term)
        if not terms:
            return []
        hits: list[SearchHit] = []
        with self._lock:
            for document_id, doc in self._docs.items():
                if scope is not None and scope and document_id not in scope:
                    continue
                matched: dict[int, int] = {}
                occurrences: dict[int, int] = {}
                first_key: dict[int, str] = {}
                for term in terms:
                    freq = doc.term_freq.get(term)
                    if freq is None:
                        freq = _prefix_freq(doc.term_freq, doc.sorted_terms, term)
                        if not freq:
                            continue
                    matched_key = _first_key_for(doc.term_freq, doc.sorted_terms, term)
                    for page, count in freq.items():
                        matched[page] = matched.get(page, 0) + 1
                        occurrences[page] = occurrences.get(page, 0) + count
                        first_key.setdefault(page, matched_key)
                for page, term_count in matched.items():
                    source = doc.pages[page]
                    score = 100.0 * term_count / len(terms) + min(occurrences[page], 20)
                    snippet = _snip(
                        source.text, doc.normalized[page], first_key.get(page, terms[0])
                    )
                    hits.append(SearchHit(source, snippet, score))
        hits.sort(key=lambda hit: (-hit.score, hit.source.source_id()))
        return hits[: max(1, min(limit, MAX_LIMIT))]
