"""REQ-800: Given ein PDF unter data/norms/<norm-id>/document.pdf When `make extract`
Then entsteht document.draft.json mit Ziffern-Skelett (Ziffernnummern am
Zeilenanfang, deterministisch) und extrahiertem Ziffern-Text; Fachfelder bleiben
leer; der Entwurf ist validiert gegen document_draft.schema.json."""

from pathlib import Path

from sni.core.schemas import make_validator
from sni.ingest.pdf_extract import extract_pdf
from tests.conftest import clause_text, clauses_of, load_draft, write_norm_pdf


def test_req800_draft_created_with_clause_skeleton(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms)
    result = extract_pdf("syn1-2020", norms_dir=norms)
    assert result.norm_id == "syn1-2020"
    assert result.pages == 1
    assert result.clauses == 6
    draft = load_draft("syn1-2020", norms)
    assert draft["norm_id"] == "syn1-2020"
    assert draft["source_file"] == "document.pdf"
    assert draft["page_count"] == 1
    assert [c["number"] for c in clauses_of(draft)] == ["1", "1.1", "2", "2.1", "3", "3.1"]


def test_req800_clause_text_extracted(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms)
    extract_pdf("syn1-2020", norms_dir=norms)
    by_number = {c["number"]: c for c in clauses_of(load_draft("syn1-2020", norms))}
    assert "Ziel" in clause_text(by_number["1"])
    assert "regelt Testfaelle" in clause_text(by_number["1"])
    assert "Jeder Nachweis ist zu dokumentieren" in clause_text(by_number["2"])
    # Fehlpunkte bleiben (korrekt) im Text der Ziffer 2:
    assert "1.5 m Abstand" in clause_text(by_number["2"])
    assert "2003 war eine alte Fassung" in clause_text(by_number["2"])


def test_req800_expert_fields_stay_empty(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms)
    extract_pdf("syn1-2020", norms_dir=norms)
    draft = load_draft("syn1-2020", norms)
    # G1: die Maschine belegt keine fachlichen Felder.
    for clause in clauses_of(draft):
        assert clause["statement_type"] == ""
        assert clause["obligation"] == ""
        assert clause["summary"] == ""
        assert clause["concepts"] == []
    assert draft["norm"] == ""
    assert draft["edition"] == ""


def test_req800_draft_validates_against_schema(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms)
    extract_pdf("syn1-2020", norms_dir=norms)
    draft = load_draft("syn1-2020", norms)
    assert list(make_validator("document_draft.schema.json").iter_errors(draft)) == []


def test_req800_toc_and_values_are_not_clauses(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms)  # enthält TOC-Punktguertel, "2003", "1.5", "0.8"
    extract_pdf("syn1-2020", norms_dir=norms)
    numbers = [c["number"] for c in clauses_of(load_draft("syn1-2020", norms))]
    assert numbers == ["1", "1.1", "2", "2.1", "3", "3.1"]
    assert "1.5" not in numbers
    assert "0.8" not in numbers


def test_req800_text_spans_pages(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    pages = [
        ["3 Grenzwerte", "Testgrenzwert fuer die Testflaeche."],
        ["Fortsetzung der Ziffer 3 auf Seite 2.", "4 Schluss"],
    ]
    write_norm_pdf("syn1-2020", norms, pages=pages)
    result = extract_pdf("syn1-2020", norms_dir=norms)
    assert result.pages == 2
    by_number = {c["number"]: c for c in clauses_of(load_draft("syn1-2020", norms))}
    assert set(by_number) == {"3", "4"}
    assert "Testgrenzwert" in clause_text(by_number["3"])
    assert "Fortsetzung der Ziffer 3" in clause_text(by_number["3"])
    assert clause_text(by_number["4"]) == "Schluss"
