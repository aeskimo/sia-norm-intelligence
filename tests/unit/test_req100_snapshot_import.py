"""REQ-100: Given ein CatalogSnapshot (JSON) When importiert Then alle Concepts per ID abrufbar."""

from pathlib import Path
from tempfile import TemporaryDirectory

from sni.catalog.snapshot import load_snapshot
from sni.catalog.store import ConceptStore
from tests.conftest import CONCEPT_A, CONCEPT_B, concepts_of


def test_req100_imported_concepts_retrievable_by_id(
    synthetic_snapshot: dict[str, object],
) -> None:
    with TemporaryDirectory() as tmp:
        store = ConceptStore(Path(tmp) / "catalog.db")
        try:
            snapshot = load_snapshot(synthetic_snapshot)
            assert store.import_snapshot(snapshot) == 2
            for concept_id in (CONCEPT_A, CONCEPT_B):
                stored = store.get_concept(concept_id)
                assert stored is not None
                expected = next(c for c in concepts_of(synthetic_snapshot) if c["id"] == concept_id)
                assert stored == expected
        finally:
            store.close()


def test_req100_relations_preserved(snapshot_with_relations: dict[str, object]) -> None:
    with TemporaryDirectory() as tmp:
        store = ConceptStore(Path(tmp) / "catalog.db")
        try:
            store.import_snapshot(load_snapshot(snapshot_with_relations))
            stored = store.get_concept(CONCEPT_A)
            assert stored is not None
            assert stored["relations"] == [{"type": "related_to", "target": CONCEPT_B}]
        finally:
            store.close()


def test_req100_reimport_is_idempotent(synthetic_snapshot: dict[str, object]) -> None:
    with TemporaryDirectory() as tmp:
        store = ConceptStore(Path(tmp) / "catalog.db")
        try:
            snapshot = load_snapshot(synthetic_snapshot)
            store.import_snapshot(snapshot)
            assert store.import_snapshot(snapshot) == 0
            assert store.concept_ids() == [CONCEPT_A, CONCEPT_B]
        finally:
            store.close()
