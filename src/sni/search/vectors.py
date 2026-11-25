"""Lokaler Vektorindex mit Kosinus-Ähnlichkeit (REQ-804).

1:1-Port von ``ch.sia.assistant.embedding.LocalVectorIndex`` (Java-
Referenz; Self-Test ``EmbeddingSelfTest`` als Test-Vorlage). Reines
Python ohne numpy-Dependency (Consumer-Größen, ADR-0011).
"""

from __future__ import annotations

import math
import threading
from collections.abc import Sequence, Set
from dataclasses import dataclass

from sni.search.page_source import PageSource

#: Max. Treffer pro Suchanfrage (Java: ``limit(min(limit, 100))``).
MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class VectorEntry:
    """Vektor + Quellenreferenz (Java: ``VectorEntry``, Defensive-Copy)."""

    source: PageSource
    vector: tuple[float, ...]

    def __init__(self, source: PageSource, vector: Sequence[float]) -> None:
        if not vector:
            raise ValueError("Vektor fehlt")
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "vector", tuple(float(v) for v in vector))


@dataclass(frozen=True, slots=True)
class VectorHit:
    """Vektor-Treffer (Java: ``VectorHit``)."""

    source: PageSource
    similarity: float


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Kosinus-Ähnlichkeit (Java 1:1; Nullvektor → 0)."""
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class LocalVectorIndex:
    """In-Memory-Vektorindex mit Dokument-Scope, thread-sicher."""

    def __init__(self) -> None:
        self._documents: dict[str, tuple[VectorEntry, ...]] = {}
        self._lock = threading.RLock()

    def replace_document(self, document_id: str, entries: Sequence[VectorEntry]) -> None:
        """Ersetzt die Vektoren eines Dokuments (Dimension muss einheitlich sein)."""
        with self._lock:
            if any(entry.source.document_id != document_id for entry in entries):
                raise ValueError("Vektoren gehören zu anderem Dokument")
            dimension = len(entries[0].vector) if entries else 0
            if any(len(entry.vector) != dimension for entry in entries):
                raise ValueError("Uneinheitliche Vektordimension")
            self._documents[document_id] = tuple(entries)

    def delete_document(self, document_id: str) -> None:
        with self._lock:
            self._documents.pop(document_id, None)

    def document_count(self) -> int:
        with self._lock:
            return len(self._documents)

    def entries(self, document_id: str) -> tuple[VectorEntry, ...]:
        with self._lock:
            return self._documents.get(document_id, ())

    def search(
        self,
        query: Sequence[float],
        scope: Set[str] | None,
        limit: int,
        minimum: float,
    ) -> list[VectorHit]:
        """Kosinus-Ranking ab ``minimum``; Sortierung wie Java (Score, dann sourceId)."""
        if not query:
            return []
        with self._lock:
            hits: list[VectorHit] = []
            for document_id, entries in self._documents.items():
                if scope is not None and scope and document_id not in scope:
                    continue
                for entry in entries:
                    if len(entry.vector) != len(query):
                        continue
                    score = cosine(query, entry.vector)
                    if score >= minimum:
                        hits.append(VectorHit(entry.source, score))
        hits.sort(key=lambda hit: (-hit.similarity, hit.source.source_id()))
        return hits[: max(1, min(limit, MAX_LIMIT))]
