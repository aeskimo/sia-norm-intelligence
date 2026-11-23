"""REQ-801: Extraktion ist atomar: alle Fehler werden gesammelt als Bericht
geliefert; bei Fehlern wird keine Datei geschrieben (KBOB-Muster)."""

from pathlib import Path

import pytest

from sni.ingest.pdf_extract import PdfExtractError, extract_pdf
from tests.conftest import write_norm_pdf


def test_req801_corrupt_pdf_reports_all_errors_and_writes_nothing(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    norm_dir = norms / "syn1-2020"
    norm_dir.mkdir(parents=True)
    (norm_dir / "document.pdf").write_bytes(b"kein PDF")
    with pytest.raises(PdfExtractError) as excinfo:
        extract_pdf("syn1-2020", norms_dir=norms)
    report = excinfo.value.report
    # Alle Fehler gesammelt: unlesbar UND kein extrahierbarer Text.
    assert len(report) >= 2
    assert not (norm_dir / "document.draft.json").exists()


def test_req801_no_clauses_reports_and_writes_nothing(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms, pages=["Keine Ziffern in diesem Text.", "Auch keine hier."])
    with pytest.raises(PdfExtractError) as excinfo:
        extract_pdf("syn1-2020", norms_dir=norms)
    assert any("keine Ziffern erkannt" in line for line in excinfo.value.report)
    assert not (norms / "syn1-2020" / "document.draft.json").exists()


def test_req801_empty_pdf_reports_and_writes_nothing(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms, pages=[[""]])
    with pytest.raises(PdfExtractError) as excinfo:
        extract_pdf("syn1-2020", norms_dir=norms)
    assert any("kein extrahierbarer Text" in line for line in excinfo.value.report)
    assert not (norms / "syn1-2020" / "document.draft.json").exists()


def test_req801_invalid_norm_id_reports(tmp_path: Path) -> None:
    with pytest.raises(PdfExtractError) as excinfo:
        extract_pdf("bad/../id", norms_dir=tmp_path / "norms")
    assert any("Ungültige Norm-ID" in line for line in excinfo.value.report)
    assert not (tmp_path / "norms" / "bad" / "id").exists()
