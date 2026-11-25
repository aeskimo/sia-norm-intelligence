"""REQ-804: Hybrid-Suche via Reciprocal Rank Fusion (Port von
``HybridSearchSelfTest``, Java-Referenz).

Beide Beine (lexikalisch + semantisch) laufen gegen denselben
Dokumentscope; Synonyme werden nur über den Vektorbein gefunden
(Java-Mock 1:1: Synonym-Texte → (1,0), sonst → (0,1)).
"""

from __future__ import annotations

from collections.abc import Sequence

from sni.models.embedding import DocumentEmbeddingService
from sni.search.fulltext import LocalFullTextIndex
from sni.search.hybrid import HybridSearch
from sni.search.page_source import PageSource
from sni.search.vectors import LocalVectorIndex

_SYNONYMS = ("Bauherrschaft", "Auftraggeber", "Projektziele")


class _MockProvider:
    """Embedding-Mock (Java 1:1): Synonym-Texte → (1,0), sonst (0,1)."""

    def model_id(self) -> str:
        return "mock"

    def available(self) -> bool:
        return True

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        return [
            (1.0, 0.0) if any(syn in text for syn in _SYNONYMS) else (0.0, 1.0) for text in texts
        ]


def _setup() -> HybridSearch:
    p1 = PageSource("d", "SIA X", "2026", 1, "1", "Bauherrschaft Projektziele")
    p2 = PageSource("d", "SIA X", "2026", 2, "2", "Auftraggeber bestimmt Zielsetzung")
    full_text = LocalFullTextIndex()
    full_text.replace("d", [p1, p2])
    semantic = DocumentEmbeddingService(_MockProvider(), LocalVectorIndex())
    semantic.index([p1, p2])
    return HybridSearch(full_text, semantic)


def test_req804_hybrid_hits_present() -> None:
    hits = _setup().search("Bauherrschaft Projektziele", {"d"}, 10)
    assert len(hits) == 2


def test_req804_hybrid_evidence_marks_combined() -> None:
    hits = _setup().search("Bauherrschaft Projektziele", {"d"}, 10)
    assert any(hit.evidence == "LEXICAL_AND_SEMANTIC" for hit in hits)


def test_req804_hybrid_semantic_synonym_hit() -> None:
    hits = _setup().search("Bauherrschaft Projektziele", {"d"}, 10)
    assert any(hit.source.page == 2 for hit in hits)


def test_req804_hybrid_source_reference_preserved() -> None:
    hits = _setup().search("Bauherrschaft Projektziele", {"d"}, 10)
    assert hits[0].source.standard == "SIA X"
    assert hits[0].source.source_id().startswith("d:p")


def test_req804_hybrid_search_for_rag_adapter() -> None:
    hits = _setup().search_for_rag("Bauherrschaft Projektziele", {"d"}, 10)
    assert len(hits) == 2
    assert all(hit.snippet for hit in hits)
