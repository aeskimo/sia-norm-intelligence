"""CLI: ``python -m sni.ingest <norm-id>`` (Make-Target: ``make ingest NORM=<norm-id>``)."""

from __future__ import annotations

import sys
from pathlib import Path

from sni.catalog.store import ConceptStore
from sni.ingest.pipeline import (
    DEFAULT_NORMS_DIR,
    DEFAULT_QUEUE_DIR,
    IngestError,
    ingest_document,
    load_document,
)

ROOT = Path(__file__).resolve().parents[3]
# Gleicher Pfad wie sni.api.main (kein Import aus api: Schicht-Abhängigkeit).
DEFAULT_CATALOG_DB = ROOT / "data" / "catalog" / "catalog.db"


def main(
    argv: list[str] | None = None,
    *,
    norms_dir: Path | None = None,
    queue_dir: Path | None = None,
    catalog_db: Path | None = None,
) -> int:
    """Einstiegspunkt; liefert 0 (OK), 1 (Ingest-Fehler) oder 2 (Aufruferfehler)."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("Verwendung: python -m sni.ingest <norm-id>")
        return 2
    norm_id = args[0]
    store = ConceptStore(catalog_db if catalog_db is not None else DEFAULT_CATALOG_DB)
    try:
        document = load_document(norm_id, norms_dir if norms_dir is not None else DEFAULT_NORMS_DIR)
        result = ingest_document(
            document, store, queue_dir if queue_dir is not None else DEFAULT_QUEUE_DIR
        )
    except IngestError as exc:
        for line in exc.report:
            print(f"FEHLER: {line}", file=sys.stderr)
        return 1
    finally:
        store.close()
    # G4: nur IDs, Ziffern und Zahlen, nie Normtexte.
    print(
        f"[ingest] {result.norm_id}: {len(result.candidates)} Kandidaten, "
        f"{len(result.gap_reports)} GapReports"
    )
    for path in result.queue_files:
        print(f"  {path.name}")
    return 0
