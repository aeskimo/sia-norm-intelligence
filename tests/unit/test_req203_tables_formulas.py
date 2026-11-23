"""REQ-203: Tabellen und Formeln werden als eigene Objekte mit Tabellen-/Formelnummer
erfasst (eigene Kandidaten mit eigener Fundstelle)."""

from pathlib import Path

from sni.catalog.store import ConceptStore
from sni.ingest.pipeline import IngestResult, ingest_document
from tests.conftest import CONCEPT_A, source_of


def _candidate(result: IngestResult, obj_id: str) -> dict[str, object]:
    for candidate in result.candidates:
        if candidate["id"] == obj_id:
            return candidate
    raise AssertionError(f"Kandidat {obj_id} fehlt: {[c['id'] for c in result.candidates]}")


def test_req203_table_is_own_object(
    catalog_store: ConceptStore, synthetic_norm: dict[str, object], tmp_path: Path
) -> None:
    result = ingest_document(synthetic_norm, catalog_store, tmp_path / "queue")
    table = _candidate(result, "sia:statement/syn1-2020/4.1/2")
    source = source_of(table)
    assert source["table"] == "T 3"
    assert "formula" not in source
    assert source["clause"] == "4.1"
    assert table["statement_type"] == "classification"


def test_req203_formula_is_own_object(
    catalog_store: ConceptStore, synthetic_norm: dict[str, object], tmp_path: Path
) -> None:
    result = ingest_document(synthetic_norm, catalog_store, tmp_path / "queue")
    formula = _candidate(result, "sia:statement/syn1-2020/4.1/3")
    source = source_of(formula)
    assert source["formula"] == "G 1"
    assert "table" not in source
    assert source["clause"] == "4.1"


def test_req203_table_without_valid_concepts_becomes_gap(
    catalog_store: ConceptStore, tmp_path: Path
) -> None:
    doc: dict[str, object] = {
        "norm": "SYN 1",
        "norm_id": "syn1-2020",
        "edition": "2020",
        "clauses": [
            {
                "number": "6.1",
                "statement_type": "requirement",
                "obligation": "muss",
                "summary": "Synthetische Ziffer mit unbekannter Tabelle.",
                "concepts": [CONCEPT_A],
                "tables": [
                    {
                        "number": "T 9",
                        "statement_type": "classification",
                        "obligation": "informativ",
                        "summary": "Synthetische Tabelle mit unbekanntem Begriff.",
                        "concepts": ["sia:concept/unbekannt"],
                    }
                ],
            }
        ],
    }
    result = ingest_document(doc, catalog_store, tmp_path / "queue")
    # Nur die Ziffer wird Kandidat, die Tabelle nicht (kein gültiges Concept).
    assert [c["id"] for c in result.candidates] == ["sia:statement/syn1-2020/6.1/1"]
    assert len(result.gap_reports) == 1
    gap = result.gap_reports[0]
    assert gap["gap_type"] == "missing_concept"
    assert "sia:concept/unbekannt" in str(gap["description"])
    assert gap["evidence"] == ["sia:statement/syn1-2020/6.1/2"]
