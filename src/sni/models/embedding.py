"""Lokaler Embedding-Service (REQ-804, ADR-0011).

1:1-Port von ``ch.sia.assistant.embedding.DocumentEmbeddingService`` und
``OllamaEmbeddingProvider`` (Java-Referenz; Self-Test
``EmbeddingSelfTest`` als Test-Vorlage):

- Lange Seiten werden in überlappende Textabschnitte zerlegt
  (600 Zeichen, 60 Zeichen Überlappung, Cut an Wortgrenze), damit
  kurze, topische Einheiten statt ganzer Seiten eingebettet werden.
- ``EmbeddingProvider`` ist die austauschbare Schnittstelle (Java 1:1):
  ``model_id``, ``available``, ``embed``.
- ``OllamaEmbeddingProvider``: nur lokales Ollama (Loopback),
  ``/api/embed`` in 32er-Batches, 5-Minuten-Timeout.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence, Set
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from sni.search.page_source import PageSource
from sni.search.vectors import LocalVectorIndex, VectorEntry, VectorHit

#: Erlaubte Zeichen in Embedding-Modell-IDs (Java: ``[A-Za-z0-9._:/-]{1,200}``).
_MODEL_RE = re.compile(r"[A-Za-z0-9._:/-]{1,200}")


class EmbeddingProvider(Protocol):
    """Austauschbare lokale Schnittstelle für Embeddings (Java 1:1)."""

    def model_id(self) -> str: ...

    def available(self) -> bool: ...

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]: ...


class DocumentEmbeddingService:
    """Erstellt Vektoren für ein Dokument (Java 1:1)."""

    #: Maximale Zeichen pro Embedding-Abschnitt; kürzere Seiten bleiben ungeteilt.
    CHUNK_SIZE = 600
    #: Überlappung zwischen zwei aufeinanderfolgenden Abschnitten in Zeichen.
    CHUNK_OVERLAP = 60

    def __init__(self, provider: EmbeddingProvider, index: LocalVectorIndex) -> None:
        self._provider = provider
        self._index = index

    def index(
        self, pages: Sequence[PageSource], progress: Callable[[str], None] | None = None
    ) -> int:
        """Indexiert alle Seiten (per Chunk) und liefert die Chunk-Anzahl."""
        if not pages:
            return 0
        document_id = pages[0].document_id
        if any(page.document_id != document_id for page in pages):
            raise ValueError("Gemischte Dokumente")
        chunks: list[PageSource] = []
        for page in pages:
            chunks.extend(self.chunk(page))
        if not chunks:
            return 0
        if progress is not None:
            progress(f"Embeddings: {len(chunks)} Abschnitte von {len(pages)} Seiten werden erzeugt")
        vectors = self._provider.embed([chunk.text for chunk in chunks])
        entries = [
            VectorEntry(chunk, vector) for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        self._index.replace_document(document_id, entries)
        return len(entries)

    def search(
        self,
        question: str,
        scope: Set[str] | None,
        limit: int,
        minimum: float,
    ) -> list[VectorHit]:
        """Embeddet die Frage und sucht im Vektorindex (Java 1:1)."""
        query_vector = self._provider.embed([question])[0]
        return self._index.search(query_vector, scope, limit, minimum)

    def delete(self, document_id: str) -> None:
        """Entfernt alle Vektoren eines Dokuments."""
        self._index.delete_document(document_id)

    @staticmethod
    def chunk(page: PageSource) -> list[PageSource]:
        """Zerlegt lange Seiten in überlappende Abschnitte (Java 1:1)."""
        text = page.text
        if len(text) <= DocumentEmbeddingService.CHUNK_SIZE:
            return [page]
        out: list[PageSource] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + DocumentEmbeddingService.CHUNK_SIZE)
            if end < len(text):
                # Java lastIndexOf(' ', end) durchsucht position 0..end (inkl.).
                cut = text.rfind(" ", 0, end + 1)
                if cut < start + DocumentEmbeddingService.CHUNK_SIZE // 2:
                    cut = end
                end = cut
            part = text[start:end].strip()
            if part:
                out.append(
                    PageSource(
                        page.document_id, page.standard, page.edition, page.page, page.section, part
                    )
                )
            if end >= len(text):
                break
            start = max(end - DocumentEmbeddingService.CHUNK_OVERLAP, start + 1)
        return out


class OllamaEmbeddingProvider:
    """Lokaler Ollama-Embeddingadapter (Java 1:1; externe Hosts gesperrt)."""

    #: Maximale Text-Anzahl pro /api/embed-Anfrage; grössere Listen in Batches.
    BATCH_SIZE = 32

    def __init__(self, base_url: str, model: str) -> None:
        host = urlparse(base_url).hostname or ""
        if not (host == "127.0.0.1" or host.lower() == "localhost" or host == "::1"):
            raise PermissionError("Nur lokale Embeddingendpunkte erlaubt")
        if _MODEL_RE.fullmatch(model) is None:
            raise ValueError("Ungültiges Embeddingmodell")
        self._base = base_url
        self._model = model

    def model_id(self) -> str:
        return "ollama:" + self._model

    def available(self) -> bool:
        try:
            with httpx.Client(timeout=httpx.Timeout(3.0)) as client:
                response = client.get(urljoin(self._base, "/api/tags"))
            return response.status_code == 200
        except Exception:
            return False

    def embed(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        if not texts:
            return []
        all_vectors: list[tuple[float, ...]] = []
        for i in range(0, len(texts), OllamaEmbeddingProvider.BATCH_SIZE):
            all_vectors.extend(
                self._embed_batch(list(texts[i : i + OllamaEmbeddingProvider.BATCH_SIZE]))
            )
        return all_vectors

    def _embed_batch(self, texts: list[str]) -> list[tuple[float, ...]]:
        with httpx.Client(timeout=httpx.Timeout(300.0, connect=3.0)) as client:
            response = client.post(
                urljoin(self._base, "/api/embed"),
                json={"model": self._model, "input": texts},
                headers={"Content-Type": "application/json"},
            )
        if response.status_code != 200:
            raise RuntimeError(f"Lokaler Embeddingdienst: HTTP {response.status_code}")
        payload: object = response.json()
        embeddings = payload.get("embeddings") if isinstance(payload, dict) else None
        if not isinstance(embeddings, list):
            raise ValueError("Embeddingantwort enthält kein embeddings-Feld")
        vectors: list[tuple[float, ...]] = []
        for item in embeddings:
            if not isinstance(item, list):
                raise ValueError("Embeddingantwort enthält kein embeddings-Feld")
            vectors.append(tuple(float(value) for value in item))
        if len(vectors) != len(texts):
            raise RuntimeError("Anzahl Embeddings stimmt nicht mit Eingaben überein")
        return vectors
