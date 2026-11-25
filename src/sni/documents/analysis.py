"""Dokumenten-Analyse-Pipeline (REQ-804, ADR-0011).

1:1-Port von ``ch.sia.integration.DocumentAnalysisPipeline`` und
``ch.sia.assistant.search.DocumentIndexingService`` (Java-Referenz):
entschlüsseltes PDF → lokale Extraktion → Volltextindex → optionale
Embeddings/Vektoren → verschlüsselter Index-Snapshot.

Abweichungen (dokumentiert):

- Extraktions-Engine: ``get_extractor()`` (OQ-010-Gate: pypdfium2
  primär, pdfminer.six Gegenkandidat) statt des Java-``pdftotext``.
- Byte-Buffer-Zeroing entfällt: Python-Bytes sind unveränderlich; die
  PDF-Bytes verbleiben im verschlüsselten Session-Cache (G4).
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass

from sni.extract.engines import PdfTextExtractor, get_extractor
from sni.models.embedding import DocumentEmbeddingService, OllamaEmbeddingProvider
from sni.search.fulltext import LocalFullTextIndex
from sni.search.hybrid import HybridSearch
from sni.search.page_source import PageSource
from sni.search.vectors import LocalVectorIndex
from sni.shop.catalog_xml import StandardDocument
from sni.state.index_cache import EncryptedIndexCache, IndexCacheEntry

#: Java 1:1: Ollama nur auf Loopback, Standard-Port.
OLLAMA_URL = "http://127.0.0.1:11434"


def _noop(_message: str) -> None:
    """Progress verwerfen (Java: ``ignored -> {}``)."""


@dataclass(frozen=True, slots=True)
class TextIndexResult:
    """Volltext-Indexierung (Java: ``DocumentIndexingService.Result``)."""

    document_id: str
    indexed_pages: int


@dataclass(frozen=True, slots=True)
class PipelineIndexResult:
    """Pipeline-Ergebnis (Java: ``DocumentAnalysisPipeline.IndexResult``)."""

    document_id: str
    pages: int
    embeddings_ready: bool
    message: str


class DocumentIndexingService:
    """Orchestriert PDF-Textextraktion und atomaren Austausch im lokalen Index."""

    def __init__(self, extractor: PdfTextExtractor, index: LocalFullTextIndex) -> None:
        self._extractor = extractor
        self._index = index

    def index(self, document_id: str, standard: str, edition: str, pdf: bytes) -> TextIndexResult:
        pages = self._extractor.extract(document_id, standard, edition, pdf)
        if not pages:
            raise RuntimeError("PDF enthält keinen extrahierbaren Text")
        self._index.replace(document_id, pages)
        return TextIndexResult(document_id, len(pages))

    def delete(self, document_id: str) -> None:
        self._index.delete(document_id)


class DocumentAnalysisPipeline:
    """Brücke vom entschlüsselten PDF zu lokaler Extraktion, Indizes und RAG.

    Über :meth:`attach_index_cache` können die Indizes zusätzlich
    verschlüsselt auf Disk abgelegt werden, damit ein Neustart kein
    vollständiges Re-Indexieren erfordert. Die PDF-Dateien selbst
    bleiben ausschliesslich im Sitzungscache (G4).
    """

    def __init__(self, extractor: PdfTextExtractor | None = None) -> None:
        self._full_text = LocalFullTextIndex()
        self._vectors = LocalVectorIndex()
        self._extractor = extractor if extractor is not None else get_extractor()
        self._text_index = DocumentIndexingService(self._extractor, self._full_text)
        self._embeddings: DocumentEmbeddingService | None = None
        self._hybrid: HybridSearch | None = None
        self._cache: EncryptedIndexCache | None = None

    # ------------------------------------------------------------------ Konfiguration

    def attach_index_cache(self, cache: EncryptedIndexCache) -> None:
        """Schaltet die verschlüsselte Index-Persistenz ein (ohne Schlüssel inaktiv)."""
        self._cache = cache

    @property
    def hybrid(self) -> HybridSearch | None:
        """Hybrid-Suche (nur nach erfolgreicher Vektor-Indexierung bzw. Wiederherstellung)."""
        return self._hybrid

    @property
    def hybrid_ready(self) -> bool:
        return self._hybrid is not None

    # ------------------------------------------------------------------ Indexierung

    def pages(self, document_id: str) -> tuple[PageSource, ...]:
        """Volltextseiten einer indexierten Norm (Basis für den Semantik-Export)."""
        return self._full_text.pages(document_id)

    def index(
        self,
        document: StandardDocument,
        pdf: bytes,
        embedding_model: str,
        progress: Callable[[str], None] | None = None,
    ) -> PipelineIndexResult:
        """Indexiert das PDF und meldet die Fortschrittsschritte an ``progress``.

        ``embedding_model`` leer → nur Volltextindex (``FULLTEXT_READY``).
        Wirft ``RuntimeError`` bei textlosem PDF (OQ-015 → Status ERROR).
        """
        report: Callable[[str], None] = progress if progress is not None else _noop
        result = self._text_index.index(document.product_id, document.number, document.year, pdf)
        report(f"Volltextindex: {result.indexed_pages} Seiten von {document.number}")
        ready = False
        message = "Volltextindex bereit"
        active_model = ""
        model = embedding_model.strip()
        if model:
            provider = OllamaEmbeddingProvider(OLLAMA_URL, model)
            if provider.available():
                self._embeddings = DocumentEmbeddingService(provider, self._vectors)
                extracted = self._extractor.extract(
                    document.product_id, document.number, document.year, pdf
                )
                self._embeddings.index(extracted, report)
                self._hybrid = HybridSearch(self._full_text, self._embeddings)
                ready = True
                active_model = model
                message = "Volltext- und Vektorindex bereit"
            else:
                message = "Volltextindex bereit; lokaler Embeddingdienst nicht erreichbar"
        self.save_to_cache(document, active_model)
        return PipelineIndexResult(result.document_id, result.indexed_pages, ready, message)

    # ------------------------------------------------------------------ Cache

    def save_to_cache(self, document: StandardDocument, embedding_model: str) -> None:
        """Persistiert den aktuellen Index-Snapshot verschlüsselt.

        Ohne Cache oder ohne Schlüssel ist dies eine leere Operation;
        Persistenzfehler bleiben für den Benutzer unsichtbar (Java 1:1).
        """
        if self._cache is None or not self._cache.available():
            return
        try:
            pages = self._full_text.pages(document.product_id)
            if not pages:
                return
            entries = self._vectors.entries(document.product_id)
            model = "" if not entries else (embedding_model.strip() if embedding_model else "")
            self._cache.save(IndexCacheEntry(document, tuple(pages), model, tuple(entries)))
        except Exception:
            pass  # Persistenzfehler bleiben für den Benutzer unsichtbar.

    def load_cached_entry(self, product_id: str) -> IndexCacheEntry | None:
        """Lädt den Cache-Eintrag (inkl. Metadaten) für eine Produkt-ID."""
        if self._cache is None or not self._cache.available():
            return None
        try:
            return self._cache.load(product_id)
        except Exception:
            return None

    def cached_document_ids(self) -> list[str]:
        """Produkt-IDs, die im (verschlüsselten) Cache vorliegen."""
        if self._cache is None:
            return []
        return self._cache.list()

    def restore_from_cache(
        self, entry: IndexCacheEntry | None, active_embedding_model: str
    ) -> PipelineIndexResult | None:
        """Stellt eine Norm aus einem Cache-Eintrag wieder her, ohne das PDF zu laden.

        Der Volltext wird immer wiederhergestellt; die Vektoren nur dann,
        wenn das gespeicherte Embedding-Modell mit dem aktiven
        übereinstimmt.
        """
        if entry is None:
            return None
        try:
            if entry.pages:
                self._full_text.replace(entry.document.product_id, entry.pages)
            vectors_ready = False
            message = "Volltextindex aus Cache wiederhergestellt"
            if (
                entry.vectors
                and active_embedding_model
                and active_embedding_model == entry.embedding_model
            ):
                self._vectors.replace_document(entry.document.product_id, entry.vectors)
                if self._embeddings is None:
                    self._embeddings = DocumentEmbeddingService(
                        OllamaEmbeddingProvider(OLLAMA_URL, active_embedding_model),
                        self._vectors,
                    )
                self._hybrid = HybridSearch(self._full_text, self._embeddings)
                vectors_ready = True
                message = "Volltext- und Vektorindex aus Cache wiederhergestellt"
            elif entry.vectors:
                message = (
                    "Volltextindex aus Cache wiederhergestellt; "
                    "Embedding-Modell hat sich geändert (nur Volltext)"
                )
            return PipelineIndexResult(
                entry.document.product_id, len(entry.pages), vectors_ready, message
            )
        except Exception:
            return None

    # ------------------------------------------------------------------ Aufräumen

    def delete(self, document_id: str) -> None:
        """Entfernt Volltext-, Vektor- und Cache-Eintrag einer Norm."""
        self._text_index.delete(document_id)
        if self._embeddings is not None:
            self._embeddings.delete(document_id)
        else:
            self._vectors.delete_document(document_id)
        if self._cache is not None:
            with contextlib.suppress(Exception):
                # Cache-Datei entfernen scheitert: In-Memory-Löschung bleibt wirksam.
                self._cache.delete(document_id)

    def close(self) -> None:
        """Indizes sind im Arbeitsspeicher; Cache-Dateien bleiben auf Disk."""
