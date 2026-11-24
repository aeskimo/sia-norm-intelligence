"""CLI: ``python -m sni.catalog import <snapshot.json>`` (Katalog-Snapshot importieren).

Basis für die Anbindung an den SIA-Normenassistenten (M3.2): der Assistent
erzeugt aus extrahierten Normtexten Kandidaten per Ingest; davor müssen die
Konzepte des Datenkatalogs als versionierter Snapshot im lokalen Katalog
liegen (Consumer-Seiten-Kontrakt, OQ-002). Der Import ist idempotent für
unveränderte Objekte und atomar bei Konflikten (REQ-100/REQ-101).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sni.catalog.snapshot import SnapshotValidationError, load_snapshot
from sni.catalog.store import ConceptStore, ImportConflictError

ROOT = Path(__file__).resolve().parents[3]
# Gleicher Pfad wie sni.api.main (kein Import aus api: Schicht-Abhängigkeit).
DEFAULT_CATALOG_DB = ROOT / "data" / "catalog" / "catalog.db"


def main(argv: list[str] | None = None, *, catalog_db: Path | None = None) -> int:
    """Einstiegspunkt; liefert 0 (OK), 1 (Import-Fehler) oder 2 (Aufruferfehler)."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "import":
        print("Verwendung: python -m sni.catalog import <snapshot.json>")
        return 2
    path = Path(args[1])
    if not path.is_file():
        print(f"FEHLER: Snapshot-Datei nicht gefunden: {path}", file=sys.stderr)
        return 1
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FEHLER: {path.name} ist kein gültiges JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(raw, dict):
        print(f"FEHLER: {path.name} muss ein JSON-Objekt sein", file=sys.stderr)
        return 1
    try:
        snapshot = load_snapshot(raw)
    except SnapshotValidationError as exc:
        for line in exc.report:
            print(f"FEHLER: {line}", file=sys.stderr)
        return 1
    store = ConceptStore(catalog_db if catalog_db is not None else DEFAULT_CATALOG_DB)
    try:
        try:
            new_count = store.import_snapshot(snapshot)
        except ImportConflictError as exc:
            for line in exc.report:
                print(f"FEHLER: {line}", file=sys.stderr)
            return 1
        print(
            f"[catalog] snapshot {snapshot.snapshot_id}: {new_count} neue Concept(s), "
            f"insgesamt {len(store.concept_ids())} im Katalog"
        )
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
