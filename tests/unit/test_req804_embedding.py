"""REQ-804: Lokale Embeddings (Port von ``EmbeddingSelfTest``,
Java-Referenz).

Vektorindex (Kosinus-Rangfolge, Scope-Filter, Löschung) und der
Ollama-Embedding-Provider gegen einen lokalen Mock-Server (09 §12);
externe Endpunkte sind blockiert.
"""

from __future__ import annotations

import pytest

from sni.models.embedding import OllamaEmbeddingProvider
from sni.search.page_source import PageSource
from sni.search.vectors import LocalVectorIndex, VectorEntry
from tests.conftest import loopback_server


def _vector_index() -> LocalVectorIndex:
    index = LocalVectorIndex()
    p1 = PageSource("d1", "SIA X", "2026", 1, "1", "Bauherrschaft Projektziele")
    p2 = PageSource("d1", "SIA X", "2026", 2, "2", "Nachweise Ausschreibung")
    index.replace_document("d1", [VectorEntry(p1, (1, 0)), VectorEntry(p2, (0, 1))])
    return index


def test_req804_vector_index_replaced_and_ranked() -> None:
    index = _vector_index()
    assert index.document_count() == 1
    hits = index.search((0.9, 0.1), set(), 2, 0)
    assert hits[0].source.page == 1


def test_req804_vector_index_scope_filter_and_delete() -> None:
    index = _vector_index()
    assert index.search((1, 0), {"fremd"}, 2, 0) == []
    index.delete_document("d1")
    assert index.document_count() == 0


def test_req804_vector_index_mismatched_documents_rejected() -> None:
    index = LocalVectorIndex()
    foreign = PageSource("d2", "SIA X", "2026", 1, "1", "Fremd.")
    with pytest.raises(ValueError, match="Vektoren gehören zu anderem Dokument"):
        index.replace_document("d1", [VectorEntry(foreign, (1, 0))])


def test_req804_vector_index_inconsistent_dimension_rejected() -> None:
    index = LocalVectorIndex()
    p1 = PageSource("d1", "SIA X", "2026", 1, "1", "Ein")
    p2 = PageSource("d1", "SIA X", "2026", 2, "2", "Zwei")
    with pytest.raises(ValueError, match="Uneinheitliche Vektordimension"):
        index.replace_document("d1", [VectorEntry(p1, (1, 0)), VectorEntry(p2, (1, 0, 1))])


def test_req804_ollama_provider_embed_via_local_server() -> None:
    captured: list[bytes] = []

    def tags_handler(_body: bytes) -> tuple[int, str]:
        return 200, "{}"

    def embed_handler(body: bytes) -> tuple[int, str]:
        captured.append(body)
        return 200, '{"model":"test","embeddings":[[1.0,0.0],[0.0,1.0]]}'

    with loopback_server({"/api/tags": tags_handler, "/api/embed": embed_handler}) as server:
        provider = OllamaEmbeddingProvider(server.url, "embed-test")
        assert provider.available() is True
        assert provider.model_id() == "ollama:embed-test"
        vectors = provider.embed(["Erster", "Zweiter"])
    assert len(vectors) == 2
    assert len(vectors[0]) == 2
    assert b"Erster" in captured[0]
    assert b"Zweiter" in captured[0]


def test_req804_ollama_provider_remote_blocked() -> None:
    with pytest.raises(PermissionError, match="Nur lokale Embeddingendpunkte erlaubt"):
        OllamaEmbeddingProvider("https://example.com", "x")
    with pytest.raises(PermissionError, match="Nur lokale Embeddingendpunkte erlaubt"):
        OllamaEmbeddingProvider("http://10.0.0.1:11434", "x")


def test_req804_ollama_provider_model_validation() -> None:
    with pytest.raises(ValueError, match="Ungültiges Embeddingmodell"):
        OllamaEmbeddingProvider("http://127.0.0.1:11434", "bad model!")
    with pytest.raises(ValueError, match="Ungültiges Embeddingmodell"):
        OllamaEmbeddingProvider("http://127.0.0.1:11434", "m" * 201)


def test_req804_ollama_provider_available_false_when_down() -> None:
    provider = OllamaEmbeddingProvider("http://127.0.0.1:1", "embed-test")
    assert provider.available() is False
