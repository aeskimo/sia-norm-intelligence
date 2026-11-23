"""REQ-201: Jeder Kandidat verweist auf >=1 existierende Concept-ID, sonst entsteht
ein GapReport `missing_concept`."""

from pathlib import Path

from sni.catalog.store import ConceptStore
from sni.ingest.pipeline import ingest_document
from tests.conftest import CONCEPT_A, CONCEPT_B


def test_req201_all_candidate_concepts_exist_in_catalog(
    catalog_store: ConceptStore, synthetic_norm: dict[str, object], tmp_path: Path
) -> None:
    result = ingest_document(synthetic_norm, catalog_store, tmp_path / "queue")
    assert result.candidates
    for candidate in result.candidates:
        concepts = candidate["concepts"]
        assert isinstance(concepts, list) and concepts  # Schema: minItems 1
        for concept_id in concepts:
            assert isinstance(concept_id, str)
            assert catalog_store.get_concept(concept_id) is not None


def test_req201_missing_concept_creates_gap_report(
    catalog_store: ConceptStore, synthetic_norm: dict[str, object], tmp_path: Path
) -> None:
    result = ingest_document(synthetic_norm, catalog_store, tmp_path / "queue")
    assert [g["id"] for g in result.gap_reports] == ["GAP-0001", "GAP-0002"]

    # Ziffer 3.2: ein bekanntes + ein unbekanntes Concept -> Kandidat UND GapReport.
    gap_3_2 = result.gap_reports[0]
    assert gap_3_2["gap_type"] == "missing_concept"
    assert gap_3_2["target_layer"] == "datenkatalog"
    assert gap_3_2["priority"] == "medium"
    assert gap_3_2["status"] == "open"
    assert gap_3_2["evidence"] == ["sia:statement/syn1-2020/3.2/1"]
    assert "sia:concept/bauwerk" in str(gap_3_2["description"])
    assert "sia:concept/geschossflaeche" not in str(gap_3_2["description"])

    # Ziffer 5.5: alle Concepts unbekannt -> kein Kandidat, nur GapReport.
    gap_5_5 = result.gap_reports[1]
    assert "sia:concept/brandschutz" in str(gap_5_5["description"])
    assert "sia:concept/raeumliche-trennung" in str(gap_5_5["description"])
    assert gap_5_5["evidence"] == ["sia:statement/syn1-2020/5.5/1"]
    assert "sia:statement/syn1-2020/5.5/1" not in {c["id"] for c in result.candidates}


def test_req201_unknown_concept_ids_are_listed_not_invented(
    catalog_store: ConceptStore, synthetic_norm: dict[str, object], tmp_path: Path
) -> None:
    """Die Pipeline erfindet keine Concepts: nur IDs aus dem Dokument auftauchen."""
    result = ingest_document(synthetic_norm, catalog_store, tmp_path / "queue")
    doc_concepts = {
        CONCEPT_A,
        CONCEPT_B,
        "sia:concept/bauwerk",
        "sia:concept/brandschutz",
        "sia:concept/raeumliche-trennung",
    }
    for candidate in result.candidates:
        concepts = candidate["concepts"]
        assert isinstance(concepts, list)
        assert set(concepts) <= doc_concepts
    for gap in result.gap_reports:
        assert gap["target_layer"] == "datenkatalog"


def test_req201_gap_ids_continue_from_existing_queue_files(
    catalog_store: ConceptStore, synthetic_norm: dict[str, object], tmp_path: Path
) -> None:
    queue = tmp_path / "queue"
    queue.mkdir()
    (queue / "GAP-0042.json").write_text(
        '{"id": "GAP-0042", "gap_type": "missing_concept", "target_layer": '
        '"datenkatalog", "evidence": ["test"], "priority": "low", "status": "accepted"}\n',
        encoding="utf-8",
    )
    result = ingest_document(synthetic_norm, catalog_store, queue)
    assert [g["id"] for g in result.gap_reports] == ["GAP-0043", "GAP-0044"]


def test_req201_reingest_reuses_gap_ids(
    catalog_store: ConceptStore, synthetic_norm: dict[str, object], tmp_path: Path
) -> None:
    queue = tmp_path / "queue"
    first = ingest_document(synthetic_norm, catalog_store, queue)
    second = ingest_document(synthetic_norm, catalog_store, queue)
    assert [g["id"] for g in first.gap_reports] == ["GAP-0001", "GAP-0002"]
    assert [g["id"] for g in second.gap_reports] == ["GAP-0001", "GAP-0002"]
