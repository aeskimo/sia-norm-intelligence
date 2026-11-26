"""SQLite-Speicher für importierte Concepts (M1, REQ-100/REQ-101).

Prinzipien:
- Import ist atomar: widersprüchliche Objekte werden vollständig abgelehnt.
- IDs sind unveränderlich (docs/04_DATA_MODEL.md): gleiches JSON unter derselben
  ID ist idempotent, anderes JSON unter derselben ID ist ein Konflikt.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from sni.catalog.snapshot import CatalogSnapshot

_CREATE_TABLE = (
    "CREATE TABLE IF NOT EXISTS concepts ("
    "id TEXT PRIMARY KEY, "
    "snapshot_id TEXT NOT NULL, "
    "concept_json TEXT NOT NULL"
    ")"
)


class ImportConflictError(RuntimeError):
    """Import abgelehnt; ``report`` enthält alle Konflikte."""

    def __init__(self, report: list[str]) -> None:
        super().__init__("; ".join(report))
        self.report = report


class ConceptStore:
    """SQLite-Zugriff auf die importierten Concepts."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI ruft sync-Endpoints im Threadpool auf.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(_CREATE_TABLE)
            self._conn.commit()

    @property
    def db_path(self) -> Path:
        """Pfad der SQLite-Datei (für Tools, die den Katalog direkt öffnen)."""
        return self._db_path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def import_snapshot(self, snapshot: CatalogSnapshot) -> int:
        """Importiert neue Concepts; idempotent für unveränderte Objekte.

        Liefert die Anzahl neu importierter Concepts. Widersprüchliche
        Objekte (gleiche ID, anderer Inhalt) lehnt der Import ab –
        atomar: es wird dann nichts importiert (REQ-101).
        """
        with self._lock:
            stored: dict[str, str] = {
                str(row[0]): str(row[1])
                for row in self._conn.execute("SELECT id, concept_json FROM concepts")
            }
            conflicts: list[str] = []
            new_rows: list[tuple[str, str, str]] = []
            for concept in snapshot.concepts:
                concept_id = str(concept["id"])
                payload = json.dumps(concept, ensure_ascii=False, sort_keys=True)
                if concept_id in stored:
                    if stored[concept_id] != payload:
                        conflicts.append(
                            f"Concept {concept_id}: widersprüchlicher Inhalt "
                            "(ID existiert bereits mit anderem Inhalt)"
                        )
                else:
                    new_rows.append((concept_id, snapshot.snapshot_id, payload))
            if conflicts:
                raise ImportConflictError(conflicts)
            with self._conn:
                self._conn.executemany(
                    "INSERT INTO concepts (id, snapshot_id, concept_json) VALUES (?, ?, ?)",
                    new_rows,
                )
            return len(new_rows)

    def get_concept(self, concept_id: str) -> dict[str, object] | None:
        """Liefert das Concept per ID oder ``None`` (unbekannt)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT concept_json FROM concepts WHERE id = ?", (concept_id,)
            ).fetchone()
        if row is None:
            return None
        raw: object = json.loads(str(row[0]))
        if isinstance(raw, dict):
            return raw
        return None

    def concept_ids(self) -> list[str]:
        """Alle importierten Concept-IDs, sortiert."""
        with self._lock:
            rows = self._conn.execute("SELECT id FROM concepts ORDER BY id").fetchall()
        return [str(row[0]) for row in rows]
