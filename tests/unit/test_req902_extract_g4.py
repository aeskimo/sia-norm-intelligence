"""REQ-902: G4 – Fehlerbericht und CLI-Ausgabe enthalten nur Norm-ID, Ziffern,
Feldnamen und Zählungen – nie Normtexte."""

from pathlib import Path

import pytest

from sni.ingest.cli import main
from sni.ingest.pdf_extract import PdfExtractError, extract_pdf
from tests.conftest import write_norm_pdf

MARKER = "ZZG4MARKER987"


def test_req902_error_report_contains_no_norm_text(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms, pages=[f"Keine Ziffern, {MARKER} in diesem Text."])
    with pytest.raises(PdfExtractError) as excinfo:
        extract_pdf("syn1-2020", norms_dir=norms)
    assert MARKER not in " ".join(excinfo.value.report)
    assert any("keine Ziffern erkannt" in line for line in excinfo.value.report)


def test_req902_corrupt_pdf_report_references_only_filename(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    norm_dir = norms / "syn1-2020"
    norm_dir.mkdir(parents=True)
    (norm_dir / "document.pdf").write_bytes(b"kaputt")
    with pytest.raises(PdfExtractError) as excinfo:
        extract_pdf("syn1-2020", norms_dir=norms)
    joined = " ".join(excinfo.value.report)
    assert "document.pdf" in joined  # Referenz auf Dateiname/ID, nicht auf Inhalt
    assert "kaputt" not in joined


def test_req902_cli_success_output_contains_no_norm_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms, pages=[["1 Ziel", f"Testtext mit {MARKER}."]])
    rc = main(["extract", "syn1-2020"], norms_dir=norms)
    assert rc == 0
    out = capsys.readouterr().out
    assert "syn1-2020" in out
    assert "Ziffern" in out
    assert MARKER not in out


def test_req902_cli_error_output_contains_no_norm_text(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms, pages=[f"Keine Ziffern, {MARKER} hier."])
    rc = main(["extract", "syn1-2020"], norms_dir=norms)
    assert rc == 1
    err = capsys.readouterr().err
    assert "FEHLER" in err
    assert MARKER not in err
