"""REQ-101: Ungültige Objekte werden mit Fehlerbericht abgelehnt, Import ist atomar."""

import pytest

from sni.catalog.snapshot import SnapshotValidationError, load_snapshot
from sni.catalog.store import ConceptStore, ImportConflictError
from tests.conftest import (
    CONCEPT_A,
    CONCEPT_B,
    concept_at,
    concepts_of,
    make_snapshot,
)


def test_req101_invalid_concept_rejected_with_report() -> None:
    snap = make_snapshot()
    del concept_at(snap, 0)["definition"]  # required laut concept.schema.json
    with pytest.raises(SnapshotValidationError) as exc:
        load_snapshot(snap)
    assert exc.value.report
    assert any("definition" in e for e in exc.value.report)


def test_req101_missing_snapshot_id_rejected() -> None:
    snap = make_snapshot()
    del snap["snapshot_id"]
    with pytest.raises(SnapshotValidationError) as exc:
        load_snapshot(snap)
    assert any("snapshot_id" in e for e in exc.value.report)


def test_req101_concepts_not_a_list_rejected() -> None:
    snap = make_snapshot()
    snap["concepts"] = {"id": CONCEPT_A}
    with pytest.raises(SnapshotValidationError) as exc:
        load_snapshot(snap)
    assert any("concepts" in e for e in exc.value.report)


def test_req101_snapshot_id_mismatch_rejected() -> None:
    snap = make_snapshot()
    concept_at(snap, 0)["catalog_snapshot"] = "sia:catalog/anderes@1.0.0"
    with pytest.raises(SnapshotValidationError) as exc:
        load_snapshot(snap)
    assert any("catalog_snapshot" in e for e in exc.value.report)


def test_req101_duplicate_concept_id_rejected() -> None:
    snap = make_snapshot(concept_ids=(CONCEPT_A,))
    concepts_of(snap).append(
        {
            "id": CONCEPT_A,
            "name": {"de": "X"},
            "definition": {"de": "Y"},
            "catalog_snapshot": snap["snapshot_id"],
        }
    )
    with pytest.raises(SnapshotValidationError) as exc:
        load_snapshot(snap)
    assert any("doppelte" in e for e in exc.value.report)


def test_req101_report_lists_all_errors() -> None:
    snap = make_snapshot()
    del concept_at(snap, 0)["definition"]
    concept_at(snap, 1)["id"] = "Ungültige-ID!"  # verletzt das ID-Pattern
    with pytest.raises(SnapshotValidationError) as exc:
        load_snapshot(snap)
    assert len(exc.value.report) >= 2


def test_req101_conflicting_import_is_atomic() -> None:
    from pathlib import Path
    from tempfile import TemporaryDirectory

    first_data = make_snapshot(concept_ids=(CONCEPT_A,))
    second_data = make_snapshot(concept_ids=(CONCEPT_A, CONCEPT_B))
    concept_at(second_data, 0)["definition"] = {"de": "Aenderter Inhalt (synthetisch)."}

    with TemporaryDirectory() as tmp:
        store = ConceptStore(Path(tmp) / "catalog.db")
        try:
            first = load_snapshot(first_data)
            store.import_snapshot(first)

            second = load_snapshot(second_data)
            with pytest.raises(ImportConflictError) as exc:
                store.import_snapshot(second)
            assert any(CONCEPT_A in e for e in exc.value.report)

            # Atomar: B (neue ID) wurde NICHT importiert, A unverändert.
            assert store.get_concept(CONCEPT_B) is None
            assert store.get_concept(CONCEPT_A) == first.concepts[0]
        finally:
            store.close()
