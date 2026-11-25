"""CLI: ``python -m sni.ingest <norm-id>`` und ``python -m sni.ingest extract <norm-id>``
(Make-Targets: ``make ingest NORM=<norm-id>``, ``make extract NORM=<norm-id>``)."""

from __future__ import annotations

import sys
from pathlib import Path

from sni.catalog.store import ConceptStore
from sni.ingest.pdf_extract import PdfExtractError, extract_pdf
from sni.ingest.pipeline import (
    IngestError,
    default_norms_dir,
    default_queue_dir,
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
    """Einstiegspunkt; liefert 0 (OK), 1 (Verarbeitungsfehler) oder 2 (Aufruferfehler)."""
    args = sys.argv[1:] if argv is None else argv
    if args and args[0] == "extract":
        if len(args) != 2:
            print("Verwendung: python -m sni.ingest extract <norm-id>")
            return 2
        return _run_extract(args[1], norms_dir if norms_dir is not None else default_norms_dir())
    if len(args) != 1:
        print("Verwendung: python -m sni.ingest <norm-id> | python -m sni.ingest extract <norm-id>")
        return 2
    norm_id = args[0]
    store = ConceptStore(catalog_db if catalog_db is not None else DEFAULT_CATALOG_DB)
    try:
        document = load_document(
            norm_id, norms_dir if norms_dir is not None else default_norms_dir()
        )
        result = ingest_document(
            document, store, queue_dir if queue_dir is not None else default_queue_dir()
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


def _run_extract(norm_id: str, norms_dir: Path) -> int:
    """Stufe 1 (ADR-0010): document.pdf → document.draft.json."""
    try:
        result = extract_pdf(norm_id, norms_dir)
    except PdfExtractError as exc:
        for line in exc.report:
            print(f"FEHLER: {line}", file=sys.stderr)
        return 1
    # G4: nur ID, Ziffern und Zählungen, nie Normtexte.
    seiten = f"{result.pages} Seite{'n' if result.pages != 1 else ''}"
    # ASCII-sicher (Windows-Konsole/PIPE kann cp1252 sein): kein Unicode-Pfeil.
    name = result.draft_path.name
    print(f"[extract] {result.norm_id}: {result.clauses} Ziffern, {seiten} -> {name}")
    return 0
