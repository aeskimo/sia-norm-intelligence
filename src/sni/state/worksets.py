"""Arbeitssets (REQ-808): benannte Gruppen lokaler Dokument-IDs.

1:1-Port von ``ch.sia.integration.WorksetStore`` (Java-Referenz):
``LinkedHashMap<String, LinkedHashSet<String>>`` mit synchronisierten
Methoden; in Python ein Lock-geschütztes, die Einfüge-Reihenfolge
beibehaltendes Mapping (LinkedHashSet-Semantik: eindeutig +
Einfüge-Reihenfolge).

- Name: gestrippt, nicht leer und ≤ 100 Zeichen, sonst
  ``ValueError("Ungültiger Arbeitssetname")`` (Java:
  ``IllegalArgumentException``).
- Dokument-ID: ``[A-Za-z0-9._-]{1,160}`` (Vollmatch), sonst
  ``ValueError("Ungültige Dokument-ID")``.
- ``create`` ist idempotent (Java: ``computeIfAbsent``); ``add``
  erzeugt das Arbeitsset bei Bedarf.

Persistenz (Python, 09 §9.1): die Arbeitssets liegen in
``workspace.json`` (non-secret) unter dem Key ``worksets``
(``{name: [doc_id, ...]}``) — Java hält dieselben Daten in
``PersistedWorkspace``. :func:`load_store`/ :func:`save_store` sind
das Bindeglied; Laden ist best-effort und non-destruktiv (ungültige
Einträge werden übersprungen, wie die REQ-815-Migration).
"""

from __future__ import annotations

import contextlib
import re
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path

from sni.state.workspace import load_workspace_json, save_workspace_json

_DOC_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,160}")
_NAME_MAX_LENGTH = 100


def valid_name(name: str) -> str:
    """Name validieren (Java: ``validName``); liefert den gestrippten Namen."""
    stripped = name.strip()
    if not stripped or len(stripped) > _NAME_MAX_LENGTH:
        raise ValueError("Ungültiger Arbeitssetname")
    return stripped


def valid_document_id(document_id: str) -> str:
    """Dokument-ID validieren (Java: ``validId``, Vollmatch)."""
    if not _DOC_ID_RE.fullmatch(document_id):
        raise ValueError("Ungültige Dokument-ID")
    return document_id


class WorksetStore:
    """In-Memory-Arbeitssets (Java 1:1; Persistenz über :func:`save_store`)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._worksets: dict[str, list[str]] = {}

    def create(self, name: str) -> None:
        """Arbeitsset anlegen (idempotent, Java: ``computeIfAbsent``)."""
        with self._lock:
            self._worksets.setdefault(valid_name(name), [])

    def delete(self, name: str) -> None:
        """Arbeitsset löschen (Java: ``remove``; Abwesenheit ist ein No-op)."""
        with self._lock:
            self._worksets.pop(name, None)

    def add(self, name: str, document_id: str) -> None:
        """Dokument-Id zum Arbeitsset hinzufügen (erzeugt es bei Bedarf)."""
        with self._lock:
            workset = self._worksets.setdefault(valid_name(name), [])
            document = valid_document_id(document_id)
            if document not in workset:  # LinkedHashSet: eindeutig
                workset.append(document)

    def remove(self, name: str, document_id: str) -> None:
        """Dokument-Id entfernen (Abwesenheit ist ein No-op)."""
        with self._lock:
            workset = self._worksets.get(name)
            if workset is not None and document_id in workset:
                workset.remove(document_id)

    def documents(self, name: str) -> tuple[str, ...]:
        """Dokument-Ids (Java: ``Set.copyOf`` — unveränderliche Ablichtung)."""
        with self._lock:
            workset = self._worksets.get(name)
            return () if workset is None else tuple(workset)

    def names(self) -> list[str]:
        """Arbeitsset-Namen in Einfüge-Reihenfolge (Java: ``List.copyOf``)."""
        with self._lock:
            return list(self._worksets)

    def snapshot(self) -> dict[str, tuple[str, ...]]:
        """Vollständige Ablichtung (Java: ``Map.copyOf``)."""
        with self._lock:
            return {name: tuple(workset) for name, workset in self._worksets.items()}

    def restore(self, values: Mapping[str, Iterable[str]]) -> None:
        """Zustand setzen (Java: ``restore`` — ersetzt den alten, validiert)."""
        with self._lock:
            self._worksets.clear()
            for name, document_ids in values.items():
                self.create(name)
                for document_id in document_ids:
                    self.add(name, document_id)

    def remove_document_everywhere(self, document_id: str) -> None:
        """Dokument-Id aus allen Arbeitssets entfernen (Java 1:1)."""
        with self._lock:
            for workset in self._worksets.values():
                if document_id in workset:
                    workset.remove(document_id)


# ---------------------------------------------------------------------------
# Persistenz glue (workspace.json, 09 §9.1)
# ---------------------------------------------------------------------------


def load_store(data_dir: Path | None = None) -> WorksetStore:
    """Lädt die Arbeitssets aus ``workspace.json`` (best-effort, non-destruktiv)."""
    store = WorksetStore()
    state = load_workspace_json(data_dir)
    if state is None:
        return store
    values = state.get("worksets")
    if not isinstance(values, dict):
        return store
    for name, document_ids in values.items():
        if not isinstance(document_ids, list):
            continue
        for document_id in document_ids:
            if not isinstance(document_id, str):
                continue
            with contextlib.suppress(ValueError):
                store.add(name, document_id)
    return store


def save_store(store: WorksetStore, data_dir: Path | None = None) -> None:
    """Schreibt die Arbeitssets in ``workspace.json`` (atomar, übrige Keys bleiben)."""
    state = load_workspace_json(data_dir) or {}
    state["worksets"] = {name: list(store.documents(name)) for name in store.names()}
    save_workspace_json(state, data_dir)
