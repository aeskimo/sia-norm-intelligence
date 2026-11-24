"""REQ-803: Lokale Dokument-Registry (``sni.documents.registry``).

1:1-Tests des Java-Ports von ``ch.sia.integration`` (``LocalDocument-
Registry``, ``LocalDocumentState``, ``LocalDocumentStatus``): Statusfluss
``CACHED→INDEXING→FULLTEXT_READY/HYBRID_READY/ERROR``, Listener-
Benachrichtigung, Einfügeordnung (LinkedHashMap) und Validierung.
Synthetische Testdaten (G4).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sni.documents.registry import (
    LocalDocumentRegistry,
    LocalDocumentState,
    LocalDocumentStatus,
)
from sni.shop.catalog_xml import StandardDocument


def _doc(product_id: str = "p-1", **fields: object) -> StandardDocument:
    base: dict[str, object] = {
        "product_id": product_id,
        "number": "SIA 101",
        "title": "Testnorm",
        "description": "",
        "keywords": "",
        "language": "DE",
        "year": "2026",
        "revision": "1",
        "valid_from": None,
        "valid_until": None,
        "remote_filename": "101.srd",
        "view_allowed": True,
        "print_allowed": False,
        "copy_allowed": False,
    }
    base.update(fields)
    return StandardDocument(**base)  # type: ignore[arg-type]


def test_req803_registry_status_labels_1_to_1() -> None:
    # Java: label() — exakte Anzeigenamen.
    assert LocalDocumentStatus.CACHED.label == "Heruntergeladen"
    assert LocalDocumentStatus.INDEXING.label == "Indexierung läuft"
    assert LocalDocumentStatus.FULLTEXT_READY.label == "Volltext bereit"
    assert LocalDocumentStatus.HYBRID_READY.label == "KI-bereit"
    assert LocalDocumentStatus.ERROR.label == "Fehler"


def test_req803_registry_state_cached_default() -> None:
    state = LocalDocumentState.cached(_doc())
    assert state.status is LocalDocumentStatus.CACHED
    assert state.indexed_pages == 0
    assert state.embeddings_ready is False
    assert state.detail == "PDF im verschlüsselten Sitzungscache"
    assert state.updated_at is not None and state.updated_at.tzinfo is not None


def test_req803_registry_state_normalization_and_validation() -> None:
    state = LocalDocumentState(_doc(), LocalDocumentStatus.ERROR, 0, False)
    assert state.detail == ""  # Java: null → ""
    assert state.updated_at is not None  # Java: null → Instant.now()

    now = datetime.now(UTC)
    state2 = LocalDocumentState(_doc(), LocalDocumentStatus.ERROR, 3, False, "x", now)
    assert state2.detail == "x"
    assert state2.updated_at is now
    assert state2.indexed_pages == 3

    with pytest.raises(ValueError, match="indexedPages darf nicht negativ sein"):
        LocalDocumentState(_doc(), LocalDocumentStatus.ERROR, -1, False)


def test_req803_registry_status_flow() -> None:
    registry = LocalDocumentRegistry()
    document = _doc("p1")

    registry.cached(document)
    state = registry.get("p1")
    assert state is not None and state.status is LocalDocumentStatus.CACHED

    registry.indexing(document)
    state = registry.get("p1")
    assert state is not None and state.status is LocalDocumentStatus.INDEXING
    assert state.detail == "Lokale Verarbeitung läuft"

    registry.indexed(document, pages=12, embeddings=False, detail="12 Seiten indexiert")
    state = registry.get("p1")
    assert state is not None and state.status is LocalDocumentStatus.FULLTEXT_READY
    assert state.indexed_pages == 12
    assert state.embeddings_ready is False
    assert state.detail == "12 Seiten indexiert"

    registry.indexed(document, pages=12, embeddings=True, detail="mit Embeddings")
    state = registry.get("p1")
    assert state is not None and state.status is LocalDocumentStatus.HYBRID_READY
    assert state.embeddings_ready is True

    registry.error(document, "Extraktion fehlgeschlagen")
    state = registry.get("p1")
    assert state is not None and state.status is LocalDocumentStatus.ERROR
    assert state.detail == "Extraktion fehlgeschlagen"
    assert state.indexed_pages == 0


def test_req803_registry_remove_and_get_missing() -> None:
    registry = LocalDocumentRegistry()
    registry.cached(_doc("p1"))
    assert registry.get("unbekannt") is None
    registry.remove("unbekannt")  # no-op (Java: Map.remove == null)
    registry.remove("p1")
    assert registry.get("p1") is None
    assert registry.all() == []


def test_req803_registry_all_preserves_insertion_order() -> None:
    registry = LocalDocumentRegistry()
    registry.cached(_doc("b"))
    registry.cached(_doc("a"))
    registry.cached(_doc("c"))
    assert [s.document.product_id for s in registry.all()] == ["b", "a", "c"]
    # Aktualisierung behält die Einfügeposition (Java: LinkedHashMap).
    registry.cached(_doc("a", title="Aktualisiert"))
    states = registry.all()
    assert [s.document.product_id for s in states] == ["b", "a", "c"]
    assert states[1].document.title == "Aktualisiert"


def test_req803_registry_all_is_defensive_copy() -> None:
    registry = LocalDocumentRegistry()
    registry.cached(_doc("p1"))
    snapshot = registry.all()
    snapshot.clear()
    assert len(registry.all()) == 1  # Java: List.copyOf


def test_req803_registry_listen_immediate_and_on_change() -> None:
    registry = LocalDocumentRegistry()
    registry.cached(_doc("vorher"))
    seen: list[list[LocalDocumentState]] = []
    registry.listen(seen.append)
    assert len(seen) == 1 and len(seen[0]) == 1  # Java: sofortiger Aufruf

    registry.cached(_doc("nachher"))
    assert len(seen) == 2
    assert [s.document.product_id for s in seen[1]] == ["vorher", "nachher"]

    registry.remove("vorher")
    assert [s.document.product_id for s in seen[2]] == ["nachher"]


def test_req803_registry_multiple_listeners_all_notified() -> None:
    registry = LocalDocumentRegistry()
    first: list[int] = []
    second: list[int] = []
    registry.listen(lambda snapshot: first.append(len(snapshot)))
    registry.listen(lambda snapshot: second.append(len(snapshot)))
    registry.cached(_doc("p1"))
    assert first == [0, 1]
    assert second == [0, 1]
