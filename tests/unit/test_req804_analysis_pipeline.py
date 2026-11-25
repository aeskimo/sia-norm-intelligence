"""REQ-804: Dokumenten-Analyse-Pipeline (Port von ``M2PipelineSelfTest``
und ``M2HybridPipelineSelfTest``, Java-Referenz).

Volltext-Indexierung eines synthetischen PDF (2 Seiten), textloses
PDF → Fehler, Embedding-Modell down → Volltext-Nachricht, Ollama-Mock
(Loopback) → Vektorindex, Cache-Roundtrip inkl. Modellwechsel und
Löschung, Keyless-Passivmodus.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sni.documents.analysis import DocumentAnalysisPipeline
from sni.search.page_source import PageSource
from sni.search.vectors import VectorEntry
from sni.shop.catalog_xml import StandardDocument
from sni.state.index_cache import EncryptedIndexCache, IndexCacheEntry
from tests.conftest import loopback_server, make_pdf

PDF = make_pdf([["3.1 Wasserhaltung", "Die Dichtung muss dicht sein."], ["3.2 Detailabdichtung"]])


class _StaticKeys:
    def __init__(self, key: bytes | None) -> None:
        self._key = key

    def load(self) -> bytes:
        if self._key is None:
            raise RuntimeError("kein Schlüssel")
        return self._key

    def available(self) -> bool:
        return self._key is not None


class _FailingLoadKeys:
    """``available()`` ja, ``load()`` wirft → Cache-Fehler bleibt unsichtbar."""

    def load(self) -> bytes:
        raise RuntimeError("load schlägt fehl")

    def available(self) -> bool:
        return True


def _document() -> StandardDocument:
    return StandardDocument(
        "synthetic-1",
        "SIA TEST",
        "Synthetische Testnorm",
        "",
        "Projektziele Nachweise",
        "D",
        "2026",
        "1",
        None,
        date(2099, 12, 31),
        "sample-standard.pdf",
        True,
        False,
        False,
    )


def _cache(tmp_path: Path, key: bytes | None = bytes(range(1, 33))) -> EncryptedIndexCache:
    return EncryptedIndexCache(tmp_path / "index", _StaticKeys(key))


# ------------------------------------------------------------------ Indexierung


def test_req804_pipeline_index_fulltext_only() -> None:
    pipeline = DocumentAnalysisPipeline()
    result = pipeline.index(_document(), PDF, "")
    assert result.pages == 2
    assert result.embeddings_ready is False
    assert result.message == "Volltextindex bereit"
    assert result.document_id == "synthetic-1"
    assert [page.page for page in pipeline.pages("synthetic-1")] == [1, 2]
    pipeline.close()


def test_req804_pipeline_index_textless_pdf_raises() -> None:
    pipeline = DocumentAnalysisPipeline()
    with pytest.raises(RuntimeError, match="PDF enthält keinen extrahierbaren Text"):
        pipeline.index(_document(), make_pdf([[]]), "")
    assert pipeline.pages("synthetic-1") == ()
    pipeline.close()


def test_req804_pipeline_embedding_down_with_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("sni.documents.analysis.OLLAMA_URL", "http://127.0.0.1:1")
    pipeline = DocumentAnalysisPipeline()
    messages: list[str] = []
    result = pipeline.index(_document(), PDF, "embed-test", progress=messages.append)
    assert result.embeddings_ready is False
    assert result.message == "Volltextindex bereit; lokaler Embeddingdienst nicht erreichbar"
    assert messages == ["Volltextindex: 2 Seiten von SIA TEST"]
    pipeline.close()


def test_req804_pipeline_index_with_ollama_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def tags_handler(_body: bytes) -> tuple[int, str]:
        return 200, "{}"

    def embed_handler(_body: bytes) -> tuple[int, str]:
        return 200, '{"model":"embed-test","embeddings":[[1.0,0.0],[0.0,1.0]]}'

    with loopback_server({"/api/tags": tags_handler, "/api/embed": embed_handler}) as server:
        monkeypatch.setattr("sni.documents.analysis.OLLAMA_URL", server.url)
        pipeline = DocumentAnalysisPipeline()
        messages: list[str] = []
        result = pipeline.index(_document(), PDF, "embed-test", progress=messages.append)
    assert result.embeddings_ready is True
    assert result.message == "Volltext- und Vektorindex bereit"
    assert pipeline.hybrid_ready is True
    assert messages[0] == "Volltextindex: 2 Seiten von SIA TEST"
    assert any(message.startswith("Embeddings: ") for message in messages)
    pipeline.close()


def test_req804_pipeline_delete(tmp_path: Path) -> None:
    pipeline = DocumentAnalysisPipeline()
    pipeline.attach_index_cache(_cache(tmp_path))
    pipeline.index(_document(), PDF, "")
    pipeline.delete("synthetic-1")
    assert pipeline.pages("synthetic-1") == ()
    assert not _cache(tmp_path).exists("synthetic-1")
    pipeline.close()


# ------------------------------------------------------------------ Cache


def test_req804_pipeline_cache_roundtrip(tmp_path: Path) -> None:
    document = _document()
    cache = _cache(tmp_path)
    first = DocumentAnalysisPipeline()
    first.attach_index_cache(cache)
    result = first.index(document, PDF, "")
    assert result.pages == 2
    assert cache.exists("synthetic-1") is True

    second = DocumentAnalysisPipeline()
    second.attach_index_cache(cache)
    restored = second.restore_from_cache(second.load_cached_entry("synthetic-1"), "")
    assert restored is not None
    assert restored.pages == 2
    assert restored.embeddings_ready is False  # Keine Vektoren gespeichert.
    assert restored.message == "Volltextindex aus Cache wiederhergestellt"
    assert [page.page for page in second.pages("synthetic-1")] == [1, 2]

    second.delete("synthetic-1")
    assert second.load_cached_entry("synthetic-1") is None
    assert cache.exists("synthetic-1") is False
    first.close()
    second.close()


def test_req804_pipeline_cache_keyless_stays_passive(tmp_path: Path) -> None:
    pipeline = DocumentAnalysisPipeline()
    pipeline.attach_index_cache(_cache(tmp_path, key=None))
    result = pipeline.index(_document(), PDF, "")
    assert result.message == "Volltextindex bereit"
    assert not (tmp_path / "index").exists()  # Kein Klartext auf Disk (G4).
    assert pipeline.load_cached_entry("synthetic-1") is None
    pipeline.close()


def test_req804_pipeline_cache_error_invisible(tmp_path: Path) -> None:
    pipeline = DocumentAnalysisPipeline()
    pipeline.attach_index_cache(EncryptedIndexCache(tmp_path / "index", _FailingLoadKeys()))
    result = pipeline.index(_document(), PDF, "")  # Cache-Fehler darf nicht brechen.
    assert result.message == "Volltextindex bereit"
    assert not (tmp_path / "index").exists()
    pipeline.close()


def test_req804_pipeline_restore_with_matching_model(tmp_path: Path) -> None:
    document = _document()
    entry = IndexCacheEntry(
        document,
        (
            PageSource("synthetic-1", "SIA TEST", "2026", 1, "1", "Bauherrschaft Projektziele"),
            PageSource("synthetic-1", "SIA TEST", "2026", 2, "2", "Auftraggeber Zielsetzung"),
        ),
        "embed-test",
        (
            VectorEntry(
                PageSource("synthetic-1", "SIA TEST", "2026", 1, "1", "Bauherrschaft Projektziele"),
                (1.0, 0.0),
            ),
            VectorEntry(
                PageSource("synthetic-1", "SIA TEST", "2026", 2, "2", "Auftraggeber Zielsetzung"),
                (0.0, 1.0),
            ),
        ),
    )
    pipeline = DocumentAnalysisPipeline()
    pipeline.attach_index_cache(_cache(tmp_path))
    restored = pipeline.restore_from_cache(entry, "embed-test")
    assert restored is not None
    assert restored.embeddings_ready is True
    assert pipeline.hybrid_ready is True
    assert restored.message == "Volltext- und Vektorindex aus Cache wiederhergestellt"
    pipeline.close()


def test_req804_pipeline_restore_model_change_fulltext_only(tmp_path: Path) -> None:
    document = _document()
    page = PageSource("synthetic-1", "SIA TEST", "2026", 1, "1", "Bauherrschaft Projektziele")
    entry = IndexCacheEntry(
        document,
        (page,),
        "embed-test",
        (VectorEntry(page, (1.0, 0.0)),),
    )
    pipeline = DocumentAnalysisPipeline()
    pipeline.attach_index_cache(_cache(tmp_path))
    restored = pipeline.restore_from_cache(entry, "anderes-modell")
    assert restored is not None
    assert restored.embeddings_ready is False
    assert pipeline.hybrid_ready is False
    assert "Embedding-Modell hat sich geändert" in restored.message
    assert len(pipeline.pages("synthetic-1")) == 1  # Volltext ist wieder da.
    pipeline.close()


def test_req804_pipeline_restore_none_entry(tmp_path: Path) -> None:
    pipeline = DocumentAnalysisPipeline()
    pipeline.attach_index_cache(_cache(tmp_path))
    assert pipeline.restore_from_cache(None, "embed-test") is None
    assert pipeline.cached_document_ids() == []
    pipeline.close()
