"""REQ-815: Codec + verschlüsselter Index-Cache SIAIDX01 (Port von
``M2IndexCacheSelfTest``, Java-Referenz).

Roundtrip (Float32-Genauigkeit 1e-5), AAD-Bindung an die Produkt-ID,
falscher Schlüssel, Keyless-Passivmodus, Löschung, kein Klartext auf
Disk, Codec-Fehlerfälle.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from sni.search.page_source import PageSource
from sni.search.vectors import VectorEntry
from sni.shop.catalog_xml import StandardDocument
from sni.state.index_cache import (
    MAGIC,
    EncryptedIndexCache,
    IndexCacheCodec,
    IndexCacheEntry,
    stem,
)

KEY = bytes(range(1, 33))


class _StaticKeys:
    def __init__(self, key: bytes | None) -> None:
        self._key = key

    def load(self) -> bytes:
        if self._key is None:
            raise RuntimeError("kein Schlüssel")
        return self._key

    def available(self) -> bool:
        return self._key is not None


def _document() -> StandardDocument:
    return StandardDocument(
        "p42",
        "SIA 42",
        "Testnorm",
        "Beschreibung",
        "Ziele Nachweise",
        "D",
        "2026",
        "2",
        date(2020, 1, 1),
        date(2030, 12, 31),
        "42.srd",
        True,
        False,
        True,
    )


def _entry() -> IndexCacheEntry:
    # Text enthält '|' und '\n' (Java 1:1) → b64url ist zwingend.
    p1 = PageSource("p42", "SIA 42", "2026", 1, "1", "Bauherrschaft\ndefiniert Ziele | äöü")
    p2 = PageSource("p42", "SIA 42", "2026", 2, "2", "Kürzere Seite.")
    v1 = VectorEntry(
        PageSource("p42", "SIA 42", "2026", 1, "1", "Bauherrschaft definiert"),
        (0.5, -0.25, 1.5),
    )
    v2 = VectorEntry(PageSource("p42", "SIA 42", "2026", 1, "2", "Ziele mit äöü"), (-1.0, 2.0, 0.0))
    return IndexCacheEntry(_document(), (p1, p2), "embeddinggemma", (v1, v2))


def _cache(tmp_path: Path, key: bytes | None = KEY) -> EncryptedIndexCache:
    return EncryptedIndexCache(tmp_path / "index", _StaticKeys(key))


def _close(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return len(a) == len(b) and all(abs(x - y) <= 1e-5 for x, y in zip(a, b, strict=True))


# ------------------------------------------------------------------ Codec


def test_req815_index_cache_codec_roundtrip() -> None:
    decoded = IndexCacheCodec().decode(IndexCacheCodec().encode(_entry()))
    assert decoded.document == _document()
    assert decoded.pages == _entry().pages
    assert decoded.embedding_model == "embeddinggemma"
    assert len(decoded.vectors) == 2
    assert _close(decoded.vectors[0].vector, (0.5, -0.25, 1.5))
    assert _close(decoded.vectors[1].vector, (-1.0, 2.0, 0.0))
    assert decoded.vectors[0].source == _entry().vectors[0].source
    assert decoded.vectors[1].source == _entry().vectors[1].source


def test_req815_index_cache_codec_no_plaintext_fields() -> None:
    encoded = IndexCacheCodec().encode(_entry()).decode("utf-8")
    assert encoded.startswith("version=1\n")
    for secret in ("Testnorm", "Bauherrschaft", "äöü"):
        assert secret not in encoded


def test_req815_index_cache_codec_unknown_field_rejected() -> None:
    with pytest.raises(ValueError, match="Unbekanntes Indexcache-Feld"):
        IndexCacheCodec().decode(b"version=1\nfremd=x\n")


def test_req815_index_cache_codec_bad_version_rejected() -> None:
    with pytest.raises(ValueError, match="Unterstütztes Indexcache-Format erwartet"):
        IndexCacheCodec().decode(b"version=2\n")


def test_req815_index_cache_codec_page_count_mismatch_rejected() -> None:
    with pytest.raises(ValueError, match="Seitenanzahl stimmt nicht überein"):
        IndexCacheCodec().decode(b"version=1\npages=1\n")


def test_req815_index_cache_codec_missing_document_rejected() -> None:
    with pytest.raises(ValueError, match="Dokumentenfeld fehlt"):
        IndexCacheCodec().decode(b"version=1\npages=0\nmodel=\nvectors=0\n")


def test_req815_index_cache_codec_doc_incomplete_rejected() -> None:
    with pytest.raises(ValueError, match="Dokumentenfeld unvollständig"):
        IndexCacheCodec().decode(b"version=1\ndoc=a|b\npages=0\nmodel=\nvectors=0\n")


def test_req815_index_cache_stem_sanitizes_and_is_idempotent() -> None:
    assert stem("a/b c d") == "a_b_c_d"
    assert stem("sia101-2020") == "sia101-2020"
    assert stem(stem("x/y")) == stem("x/y")


# ------------------------------------------------------------------ Encrypted cache


def test_req815_index_cache_roundtrip_and_list(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    assert cache.available() is True
    entry = _entry()
    cache.save(entry)
    assert cache.exists("p42") is True
    assert (tmp_path / "index" / "p42.sniidx").is_file()
    loaded = cache.load("p42")
    assert loaded is not None
    assert loaded.document == entry.document
    assert loaded.pages == entry.pages
    assert loaded.embedding_model == "embeddinggemma"
    assert cache.list() == ["p42"]


def test_req815_index_cache_no_plaintext_on_disk(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.save(_entry())
    raw = (tmp_path / "index" / "p42.sniidx").read_bytes()
    assert raw[: len(MAGIC)] == MAGIC
    assert b"Testnorm" not in raw
    assert b"Bauherrschaft" not in raw


def test_req815_index_cache_aad_binds_to_product_id(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.save(_entry())
    (tmp_path / "index" / "p99.sniidx").write_bytes(
        (tmp_path / "index" / "p42.sniidx").read_bytes()
    )
    # Gleiche Datei, anderes Produkt: AAD-Prüfung schlägt fehl.
    with pytest.raises(InvalidTag):
        cache.load("p99")


def test_req815_index_cache_wrong_key_rejected(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.save(_entry())
    wrong = EncryptedIndexCache(tmp_path / "index", _StaticKeys(bytes(b ^ 1 for b in KEY)))
    with pytest.raises(InvalidTag):
        wrong.load("p42")


def test_req815_index_cache_tamper_rejected(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.save(_entry())
    path = tmp_path / "index" / "p42.sniidx"
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(bytes(raw))
    with pytest.raises(InvalidTag):
        cache.load("p42")


def test_req815_index_cache_too_short_rejected(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    (tmp_path / "index").mkdir(parents=True, exist_ok=True)
    (tmp_path / "index" / "p42.sniidx").write_bytes(MAGIC + b"\x00" * 8)
    with pytest.raises(RuntimeError, match="Indexdatei zu kurz"):
        cache.load("p42")


def test_req815_index_cache_passive_without_key(tmp_path: Path) -> None:
    cache = _cache(tmp_path, key=None)
    entry = _entry()
    cache.save(entry)  # Bewusste leere Operation (G4: kein Klartext).
    assert cache.available() is False
    assert cache.exists("p42") is False
    assert cache.load("p42") is None
    assert cache.list() == []
    assert not (tmp_path / "index").exists()


def test_req815_index_cache_delete(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.save(_entry())
    cache.delete("p42")
    assert cache.exists("p42") is False
    cache.delete("p42")  # Zweite Löschung: still.
    assert cache.list() == []


def test_req815_index_cache_list_skips_unreadable(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    cache.save(_entry())
    (tmp_path / "index" / "kaputt.sniidx").write_bytes(b"keine gueltige Datei")
    assert cache.list() == ["p42"]
