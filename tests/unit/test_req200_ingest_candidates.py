"""REQ-200: Given ein lokal gemountetes Normdokument When `make ingest` Then entstehen
NormStatement-Kandidaten mit Fundstelle."""

import json
from pathlib import Path

import pytest

from sni.catalog.store import ConceptStore
from sni.ingest.pipeline import IngestError, ingest_document, load_document
from tests.conftest import CONCEPT_A, load_synthetic_norm, source_of

EXPECTED_CANDIDATE_IDS = {
    "sia:statement/syn1-2020/3.1/1",
    "sia:statement/syn1-2020/3.2/1",
    "sia:statement/syn1-2020/4.1/1",
    "sia:statement/syn1-2020/4.1/2",
    "sia:statement/syn1-2020/4.1/3",
}


def test_req200_candidates_created_with_source(
    catalog_store: ConceptStore, synthetic_norm: dict[str, object], tmp_path: Path
) -> None:
    result = ingest_document(synthetic_norm, catalog_store, tmp_path / "queue")
    assert len(result.candidates) == 5
    for candidate in result.candidates:
        source = source_of(candidate)
        assert source["norm"] == "SYN 1"
        assert source["edition"] == "2020"
        clause: object = source["clause"]
        assert isinstance(clause, str) and clause
        assert source["verified"] is False  # Fundstelle nie automatisch "verifiziert" (G6)
        assert candidate["review_status"] == "candidate"
        summary: object = candidate["summary"]
        assert isinstance(summary, str) and summary


def test_req200_candidate_ids_are_stable(
    catalog_store: ConceptStore, synthetic_norm: dict[str, object], tmp_path: Path
) -> None:
    result = ingest_document(synthetic_norm, catalog_store, tmp_path / "queue")
    assert {c["id"] for c in result.candidates} == EXPECTED_CANDIDATE_IDS


def test_req200_missing_document_raises(tmp_path: Path) -> None:
    with pytest.raises(IngestError, match="nicht gefunden"):
        load_document("does-not-exist", norms_dir=tmp_path / "norms")


def test_req200_norm_id_mismatch_raises(tmp_path: Path) -> None:
    norm_dir = tmp_path / "norms" / "foo"
    norm_dir.mkdir(parents=True)
    doc = load_synthetic_norm()
    doc["norm_id"] = "bar"
    (norm_dir / "document.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(IngestError, match="passt nicht"):
        load_document("foo", norms_dir=tmp_path / "norms")


def test_req200_invalid_document_collects_all_errors(
    catalog_store: ConceptStore, tmp_path: Path
) -> None:
    doc = {
        "norm": "",  # Fehler 1: leer
        "norm_id": "syn1-2020",
        "edition": 2020,  # Fehler 2: falscher Typ
        "clauses": [
            {
                "number": "3.1",  # Fehler 3: ungültiges statement_type
                "statement_type": "falscher_typ",
                "obligation": "muss",
                "summary": "Synthetisch.",
                "concepts": [CONCEPT_A],
            }
        ],
    }
    queue = tmp_path / "queue"
    with pytest.raises(IngestError) as excinfo:
        ingest_document(doc, catalog_store, queue)
    assert len(excinfo.value.report) >= 3
    # atomar: nichts wurde geschrieben
    assert not queue.exists() or not list(queue.glob("*.json"))
