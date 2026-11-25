"""Hybrid-Suche: Volltext + Vektoren via Reciprocal Rank Fusion (REQ-804).

1:1-Port von ``ch.sia.assistant.search.HybridSearchService`` (Java-
Referenz; Self-Test ``HybridSearchSelfTest`` als Test-Vorlage).

- Beide Beine holen ``max(20, 3·limit)``.
- Vektorseite: ``DocumentEmbeddingService`` (eigener Vektorindex) mit
  Mindest-Kosinus 0.15; ist der Embeddingdienst nicht erreichbar,
  bleiben die lexikalischen Treffer nutzbar (Java try/catch 1:1).
- Fusion: ``score += 1/(60+Rang+1)`` (0-basierter Rang), Merge-Schlüssel
  ``source_id``; das erst eingefügte Snippet gewinnt (lexikalisch
  zuerst), neue Vektor-Treffer tragen den Chunktext als Snippet.
- ``search_for_rag`` ist der Adapter für ``GroundedQa``.
"""

from __future__ import annotations

from collections.abc import Set
from dataclasses import dataclass

from sni.models.embedding import DocumentEmbeddingService
from sni.search.fulltext import LocalFullTextIndex, SearchHit
from sni.search.page_source import PageSource
from sni.search.vectors import VectorHit

#: Vektor-Treffer unter diesem Kosinus landen im Hybrid-Ergebnis nicht.
VECTOR_MINIMUM = 0.15
#: RRF-Konstante (Java: ``60``).
RRF_K = 60
#: Max. Treffer pro Suchanfrage (Java: ``limit(min(limit, 100))``).
MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class HybridHit:
    """Gemergter Treffer (Java: ``HybridHit``-Record).

    ``evidence`` ist ``LEXICAL`` | ``SEMANTIC`` | ``LEXICAL_AND_SEMANTIC``.
    """

    source: PageSource
    snippet: str
    score: float
    evidence: str


class _Mutable:
    """Fusions-Zwinstand pro sourceId (Java: innere Klasse ``Mutable``)."""

    __slots__ = ("source", "snippet", "score", "lexical", "semantic")

    def __init__(self, source: PageSource, snippet: str) -> None:
        self.source = source
        self.snippet = snippet
        self.score = 0.0
        self.lexical = False
        self.semantic = False


class HybridSearch:
    """Volltext- und Vektorbeine in einem Suchlauf (Java 1:1)."""

    def __init__(self, full_text: LocalFullTextIndex, embeddings: DocumentEmbeddingService) -> None:
        self._full_text = full_text
        self._embeddings = embeddings

    def search(self, query: str, scope: Set[str] | None, limit: int) -> list[HybridHit]:
        """Sucht lexikalisch und semantisch und fusioniert via RRF."""
        fetch = max(20, limit * 3)
        lexical_hits = self._full_text.search(query, scope, fetch)
        try:
            vector_hits: list[VectorHit] = self._embeddings.search(
                query, scope, fetch, VECTOR_MINIMUM
            )
        except Exception:
            # Embeddingdienst nicht erreichbar: lexikalische Treffer bleiben nutzbar.
            vector_hits = []
        fused: dict[str, _Mutable] = {}
        for i, hit in enumerate(lexical_hits):
            mutable = fused.setdefault(hit.source.source_id(), _Mutable(hit.source, hit.snippet))
            mutable.score += 1.0 / (RRF_K + i + 1)
            mutable.lexical = True
        for i, vec_hit in enumerate(vector_hits):
            mutable = fused.setdefault(
                vec_hit.source.source_id(), _Mutable(vec_hit.source, vec_hit.source.text)
            )
            mutable.score += 1.0 / (RRF_K + i + 1)
            mutable.semantic = True
        ordered = sorted(fused.values(), key=lambda m: (-m.score, m.source.source_id()))
        return [
            HybridHit(
                m.source,
                m.snippet,
                m.score,
                "LEXICAL_AND_SEMANTIC"
                if m.lexical and m.semantic
                else "LEXICAL"
                if m.lexical
                else "SEMANTIC",
            )
            for m in ordered[: max(1, min(limit, MAX_LIMIT))]
        ]

    def search_for_rag(self, query: str, scope: Set[str] | None, limit: int) -> list[SearchHit]:
        """Adapterausgabe für GroundedQa (Java: ``searchForRag``)."""
        return [SearchHit(h.source, h.snippet, h.score) for h in self.search(query, scope, limit)]
