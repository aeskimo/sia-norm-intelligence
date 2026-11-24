"""Lokale Dokument-Registry (REQ-803).

1:1-Port von ``ch.sia.integration`` (``LocalDocumentStatus``,
``LocalDocumentState``, ``LocalDocumentRegistry``): threadsicheres
Statusregister für alle lokal gehaltenen Normen („Meine Normen"-Liste).

Statusfluss: ``CACHED→INDEXING→FULLTEXT_READY/HYBRID_READY/ERROR``
(INDEXING/READY in M8.3 mit der Analyse-Pipeline; ERROR bei Download-/
Verarbeitungsfehlern).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from sni.shop.catalog_xml import StandardDocument


class LocalDocumentStatus(Enum):
    """Sichtbarer lokaler Verarbeitungsstatus einer Norm (Java: ``LocalDocumentStatus``)."""

    CACHED = "Heruntergeladen"
    INDEXING = "Indexierung läuft"
    FULLTEXT_READY = "Volltext bereit"
    HYBRID_READY = "KI-bereit"
    ERROR = "Fehler"

    @property
    def label(self) -> str:
        """Java: ``label()`` — Anzeigename für die UI."""
        return self.value


@dataclass(frozen=True, slots=True)
class LocalDocumentState:
    """Unveränderlicher Statusdatensatz für die Ansicht Meine Normen.

    Java: ``LocalDocumentState`` (Record mit Compact-Constructor).
    """

    document: StandardDocument
    status: LocalDocumentStatus
    indexed_pages: int
    embeddings_ready: bool
    detail: str
    updated_at: datetime

    def __init__(
        self,
        document: StandardDocument,
        status: LocalDocumentStatus,
        indexed_pages: int,
        embeddings_ready: bool,
        detail: str | None = None,
        updated_at: datetime | None = None,
    ) -> None:
        """Java: Compact-Constructor (None → Default; ``indexedPages`` ≥ 0)."""
        if indexed_pages < 0:
            raise ValueError("indexedPages darf nicht negativ sein")
        object.__setattr__(self, "document", document)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "indexed_pages", indexed_pages)
        object.__setattr__(self, "embeddings_ready", embeddings_ready)
        object.__setattr__(self, "detail", "" if detail is None else detail)
        object.__setattr__(
            self, "updated_at", datetime.now(UTC) if updated_at is None else updated_at
        )

    @classmethod
    def cached(cls, document: StandardDocument) -> LocalDocumentState:
        """Java: ``cached`` — frischer Status nach erfolgreichem Download."""
        return cls(
            document,
            LocalDocumentStatus.CACHED,
            0,
            False,
            "PDF im verschlüsselten Sitzungscache",
            datetime.now(UTC),
        )


#: Java: ``Consumer<List<LocalDocumentState>>`` — Listener erhält Snapshot.
SnapshotListener = Callable[[list[LocalDocumentState]], None]


class LocalDocumentRegistry:
    """Threadsicheres Statusregister für alle lokal gehaltenen Normen.

    Java: ``LocalDocumentRegistry`` (LinkedHashMap → Einfügeordnung).
    """

    def __init__(self) -> None:
        self._states: dict[str, LocalDocumentState] = {}
        self._listeners: list[SnapshotListener] = []
        self._lock = threading.RLock()  # Java: synchronized-Methoden

    def cached(self, document: StandardDocument) -> None:
        """Java: ``cached``."""
        with self._lock:
            self._put(LocalDocumentState.cached(document))

    def indexing(self, document: StandardDocument) -> None:
        """Java: ``indexing``."""
        with self._lock:
            self._put(
                LocalDocumentState(
                    document,
                    LocalDocumentStatus.INDEXING,
                    0,
                    False,
                    "Lokale Verarbeitung läuft",
                    datetime.now(UTC),
                )
            )

    def indexed(
        self, document: StandardDocument, pages: int, embeddings: bool, detail: str
    ) -> None:
        """Java: ``indexed`` — ``FULLTEXT_READY`` bzw. ``HYBRID_READY`` je nach Embeddings."""
        with self._lock:
            status = (
                LocalDocumentStatus.HYBRID_READY
                if embeddings
                else LocalDocumentStatus.FULLTEXT_READY
            )
            self._put(
                LocalDocumentState(document, status, pages, embeddings, detail, datetime.now(UTC))
            )

    def error(self, document: StandardDocument, detail: str) -> None:
        """Java: ``error``."""
        with self._lock:
            self._put(
                LocalDocumentState(
                    document, LocalDocumentStatus.ERROR, 0, False, detail, datetime.now(UTC)
                )
            )

    def remove(self, document_id: str) -> None:
        """Java: ``remove`` — Eintrag löschen und Listener informieren (fehlend = no-op)."""
        with self._lock:
            self._states.pop(document_id, None)
            self._notify()

    def get(self, document_id: str) -> LocalDocumentState | None:
        """Java: ``get`` — None, wenn nicht vorhanden (``Optional.empty``)."""
        with self._lock:
            return self._states.get(document_id)

    def all(self) -> list[LocalDocumentState]:
        """Java: ``all`` — Ablichtung in Einfügeordnung (``List.copyOf``)."""
        with self._lock:
            return list(self._states.values())

    def listen(self, listener: SnapshotListener) -> None:
        """Java: ``listen`` — registriert den Listener und ruft ihn sofort mit dem Snapshot auf."""
        with self._lock:
            self._listeners.append(listener)
            listener(self.all())

    # ------------------------------------------------------------------ intern

    def _put(self, state: LocalDocumentState) -> None:
        self._states[state.document.product_id] = state
        self._notify()

    def _notify(self) -> None:
        snapshot = self.all()
        for listener in self._listeners:
            listener(snapshot)
