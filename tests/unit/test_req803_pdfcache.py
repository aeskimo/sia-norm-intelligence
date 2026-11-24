"""REQ-803: Sitzungs-PDF-Cache (``sni.documents.pdfcache``).

1:1-Tests des Java-Ports von ``ch.sia.reader.product.storage.
SessionDocumentCache``: AES-256-GCM mit AAD = Dokument-ID, Zeroing bei
Delete/Close, Verhalten des geschlossenen Caches, ID-Validierung und
Thread-Sicherheit. Reine synthetische Testdaten (G4: kein Norminhalt).
"""

from __future__ import annotations

import threading

import pytest

from sni.documents.pdfcache import (
    CacheIntegrityError,
    SessionCacheError,
    SessionDocumentCache,
)

PDF = b"%PDF-1.4\n%Synthetisches Test-PDF (G4)\n%%EOF\n"


def test_req803_pdfcache_put_get_roundtrip() -> None:
    with SessionDocumentCache() as cache:
        cache.put("p-0001", PDF)
        assert cache.get("p-0001") == PDF
        assert cache.contains("p-0001") is True
        assert cache.size() == 1


def test_req803_pdfcache_get_missing_returns_none() -> None:
    with SessionDocumentCache() as cache:
        assert cache.get("fehlend") is None
        assert cache.contains("fehlend") is False
        cache.delete("fehlend")  # no-op (Java: entries.remove == null)
        assert cache.size() == 0


def test_req803_pdfcache_overwrite_replaces_entry() -> None:
    with SessionDocumentCache() as cache:
        cache.put("p1", PDF)
        cache.put("p1", PDF + b"%v2")
        assert cache.size() == 1
        assert cache.get("p1") == PDF + b"%v2"


def test_req803_pdfcache_aad_binds_entry_to_document_id() -> None:
    # AAD = Dokument-ID: ein Eintrag unter ID A ist unter ID B nicht
    # entschlüsselbar (GCM-Authentifizierung schlägt fehl).
    with SessionDocumentCache() as cache:
        cache.put("alpha", PDF)
        cache.put("beta", PDF)
        entries = cache._entries  # Whitebox: Einträge tauschen
        entries["alpha"], entries["beta"] = entries["beta"], entries["alpha"]
        with pytest.raises(CacheIntegrityError, match="Cache beschädigt"):
            cache.get("alpha")


def test_req803_pdfcache_tampered_ciphertext_raises_integrity() -> None:
    with SessionDocumentCache() as cache:
        cache.put("p1", PDF)
        entry = cache._entries["p1"]  # Whitebox: Ciphertext manipulieren
        entry.ciphertext[0] ^= 0xFF
        with pytest.raises(CacheIntegrityError, match="Cache beschädigt"):
            cache.get("p1")


def test_req803_pdfcache_delete_removes_and_wipes() -> None:
    with SessionDocumentCache() as cache:
        cache.put("p1", PDF)
        entry = cache._entries["p1"]  # Whitebox: Zeroing nachweisen
        cache.delete("p1")
        assert cache.get("p1") is None
        # Java: Arrays.fill(nonce, 0) / Arrays.fill(ciphertext, 0).
        assert all(byte == 0 for byte in entry.nonce)
        assert all(byte == 0 for byte in entry.ciphertext)


def test_req803_pdfcache_close_wipes_all_and_blocks_access() -> None:
    cache = SessionDocumentCache()
    cache.put("p1", PDF)
    entry = cache._entries["p1"]
    cache.close()
    assert all(byte == 0 for byte in entry.ciphertext)
    for action in (
        lambda: cache.put("p2", PDF),
        lambda: cache.get("p2"),
        lambda: cache.contains("p2"),
        lambda: cache.size(),
        lambda: cache.delete("p2"),
    ):
        with pytest.raises(SessionCacheError, match="Cache geschlossen"):
            action()
    cache.close()  # idempotent (Java: zweites close() ist no-op)


def test_req803_pdfcache_rejects_invalid_ids() -> None:
    with SessionDocumentCache() as cache:
        for bad in ("", "   ", "mit leerstelle", "x" * 161, "umläut", "a/b"):
            with pytest.raises(ValueError, match="Ungültige Dokument-ID"):
                cache.put(bad, PDF)
            with pytest.raises(ValueError, match="Ungültige Dokument-ID"):
                cache.get(bad)


def test_req803_pdfcache_accepts_id_at_boundary_160() -> None:
    with SessionDocumentCache() as cache:
        boundary = "a" * 160  # Java: {1,160} inclusive
        cache.put(boundary, PDF)
        assert cache.get(boundary) == PDF
        cache.put("a.b-c_160", PDF)  # Punkte, Bindestriche, Unterstriche erlaubt
        assert cache.contains("a.b-c_160")
        assert cache.size() == 2


def test_req803_pdfcache_thread_safety_smoke() -> None:
    with SessionDocumentCache() as cache:
        errors: list[Exception] = []

        def worker(thread_id: int) -> None:
            try:
                for i in range(50):
                    document_id = f"p{thread_id}-{i}"
                    payload = PDF + str(i).encode("ascii")
                    cache.put(document_id, payload)
                    assert cache.get(document_id) == payload
            except Exception as exc:  # noqa: BLE001 — Test-Sammlung
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert errors == []
        assert cache.size() == 200
