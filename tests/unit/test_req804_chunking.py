"""REQ-804: Seiten-Chunking und Embedding-Batching (Port von
``M2ChunkingSelfTest``, Java-Referenz).

Kurze Seiten bleiben unverändert, lange Seiten werden in Abschnitte
≤ 600 Zeichen mit Überlappung zerlegt (Beginn/Ende erhalten); der
Ollama-Provider arbeitet in Batches zu 32 pro /api/embed-Anfrage.
"""

from __future__ import annotations

import json

from sni.models.embedding import DocumentEmbeddingService, OllamaEmbeddingProvider
from sni.search.page_source import PageSource
from tests.conftest import loopback_server

_LONG_TEXT = " ".join(f"wort{i}" for i in range(200))


def test_req804_chunking_short_page_unchanged() -> None:
    short = PageSource("d", "SIA X", "2026", 1, "1", "Kurze Seite mit normalem Inhalt.")
    assert DocumentEmbeddingService.chunk(short) == [short]


def test_req804_chunking_long_page_split() -> None:
    page = PageSource("d", "SIA X", "2026", 2, "1", _LONG_TEXT)
    chunks = DocumentEmbeddingService.chunk(page)
    assert len(chunks) >= 2
    assert all(len(chunk.text) <= DocumentEmbeddingService.CHUNK_SIZE for chunk in chunks)
    assert chunks[0].text.startswith("wort0")
    assert chunks[-1].text.endswith("wort199")


def test_req804_chunking_overlap() -> None:
    chunks = DocumentEmbeddingService.chunk(PageSource("d", "SIA X", "2026", 2, "1", _LONG_TEXT))
    overlap = False
    for i in range(len(chunks) - 1):
        head = chunks[i + 1].text
        tail = chunks[i].text
        overlap = any(head.startswith(tail[-k:]) for k in range(1, min(len(head), len(tail)) + 1))
        if overlap:
            break
    assert overlap


def test_req804_chunking_exact_boundary_untouched() -> None:
    exact = PageSource("d", "SIA X", "2026", 3, "1", ("w " * 300).strip())
    assert DocumentEmbeddingService.chunk(exact) == [exact]


def test_req804_embedding_batch_size_32() -> None:
    assert OllamaEmbeddingProvider.BATCH_SIZE == 32
    batch_sizes: list[int] = []

    def embed_handler(body: bytes) -> tuple[int, str]:
        payload = json.loads(body.decode("utf-8"))
        texts = payload["input"]
        batch_sizes.append(len(texts))
        vectors = ",".join("[1.0,0.0]" for _ in texts)
        return 200, '{"embeddings":[' + vectors + "]}"

    with loopback_server({"/api/embed": embed_handler}) as server:
        provider = OllamaEmbeddingProvider(server.url, "embed-batch")
        texts = [f"text-{i}" for i in range(33)]
        vectors = provider.embed(texts)
    assert len(vectors) == 33
    assert batch_sizes == [32, 1]


def test_req804_embedding_empty_input() -> None:
    provider = OllamaEmbeddingProvider("http://127.0.0.1:11434", "embed-batch")
    assert provider.embed([]) == []
