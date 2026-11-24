"""REQ-903: End-to-End – PDF → Entwurf (Stufe 1, Maschine) → document.json
(Stufe 2, Facharbeit, hier simuliert) → Kandidaten mit Fundstelle
(bestehende Ingest-Pipeline M2 unverändert, ADR-0010)."""

import json
from pathlib import Path

from sni.catalog.store import ConceptStore
from sni.ingest.pdf_extract import extract_pdf
from sni.ingest.pipeline import ingest_document
from tests.conftest import CONCEPT_A, CONCEPT_B, clauses_of, load_draft, source_of, write_norm_pdf


def test_req903_extract_then_ingest_candidates(catalog_store: ConceptStore, tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf(
        "syn1-2020",
        norms,
        pages=[
            ["1 Ziel", "Diese synthetische Norm regelt Testfaelle."],
            ["2 Nachweise", "2.1 Flaeche", "Testgrenzwert fuer die Testflaeche."],
        ],
    )
    # Stufe 1: Maschine (deterministisch).
    result = extract_pdf("syn1-2020", norms_dir=norms)
    assert result.clauses == 3
    draft = load_draft("syn1-2020", norms)
    assert {c["number"] for c in clauses_of(draft)} == {"1", "2", "2.1"}

    # Stufe 2: Facharbeit (simuliert): Entwurf → gültige document.json im Mount.
    document: dict[str, object] = {
        "norm": "SYN 1",
        "norm_id": "syn1-2020",
        "edition": "2020",
        "clauses": [
            {
                "number": "1",
                "statement_type": "requirement",
                "obligation": "muss",
                "summary": "Synthetische Zielangabe (eigene Zusammenfassung, kein Normzitat).",
                "concepts": [CONCEPT_A],
            },
            {
                "number": "2.1",
                "statement_type": "requirement",
                "obligation": "soll",
                "summary": "Synthetischer Grenzwerthinweis (eigene Zusammenfassung, kein Zitat).",
                "concepts": [CONCEPT_B],
            },
        ],
    }
    (norms / "syn1-2020" / "document.json").write_text(
        json.dumps(document, ensure_ascii=False), encoding="utf-8"
    )
    # M2-Pipeline unverändert:
    ingest_result = ingest_document(document, catalog_store, tmp_path / "queue")
    assert len(ingest_result.candidates) == 2
    for candidate in ingest_result.candidates:
        assert candidate["review_status"] == "candidate"  # G3
        source = source_of(candidate)
        assert source["norm"] == "SYN 1"
        assert source["edition"] == "2020"
        assert source["verified"] is False  # G6
