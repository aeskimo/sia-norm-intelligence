"""REQ-500: CSV-Adapter liefert normalisierte Werte mit Herkunft (Datei, Zeile)."""

from pathlib import Path

import pytest

from sni.projectdata.csv_adapter import read_csv
from sni.projectdata.models import ProjectDataError

VALID = (
    "concept,value,unit\nsia:concept/teilsflaeche-a,100,m2\nsia:concept/teilsflaeche-b,50.5,m2\n"
)


def _write(tmp_path: Path, content: str, name: str = "flaechen.csv") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_req500_csv_values_with_provenance(tmp_path: Path) -> None:
    values = read_csv(_write(tmp_path, VALID))
    assert len(values) == 2
    first = values[0]
    assert first.concept == "sia:concept/teilsflaeche-a"
    assert first.value == 100.0
    assert first.unit == "m2"
    assert first.provenance.file == "flaechen.csv"
    assert first.provenance.locator == "Zeile 2"  # Kopfzeile = Zeile 1
    assert values[1].value == 50.5
    assert values[1].provenance.locator == "Zeile 3"


def test_req500_csv_header_only_is_empty(tmp_path: Path) -> None:
    values = read_csv(_write(tmp_path, "concept,value,unit\n"))
    assert values == []


def test_req500_csv_blank_lines_ignored(tmp_path: Path) -> None:
    values = read_csv(_write(tmp_path, "concept,value,unit\n\nsia:concept/a,1,m2\n\n"))
    assert len(values) == 1
    assert values[0].provenance.locator == "Zeile 3"


def test_req500_csv_bom_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "bom.csv"
    path.write_text("concept,value,unit\nsia:concept/a,1,m2\n", encoding="utf-8-sig")
    values = read_csv(path)
    assert len(values) == 1


def test_req500_csv_bad_header_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProjectDataError, match="Kopfzeile"):
        read_csv(_write(tmp_path, "concept,amount,unit\nsia:concept/a,1,m2\n"))


def test_req500_csv_non_numeric_value_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProjectDataError, match=r"flaechen\.csv:2:.*ist keine Zahl"):
        read_csv(_write(tmp_path, "concept,value,unit\nsia:concept/a,viele,m2\n"))


def test_req500_csv_missing_unit_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProjectDataError, match="Einheit fehlt"):
        read_csv(_write(tmp_path, "concept,value,unit\nsia:concept/a,1,\n"))


def test_req500_csv_missing_concept_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProjectDataError, match="Concept fehlt"):
        read_csv(_write(tmp_path, "concept,value,unit\n,1,m2\n"))


def test_req500_csv_non_finite_value_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProjectDataError, match="endlich"):
        read_csv(_write(tmp_path, "concept,value,unit\nsia:concept/a,nan,m2\n"))


def test_req500_csv_wrong_column_count_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProjectDataError, match="3 Spalten"):
        read_csv(_write(tmp_path, "concept,value,unit\nsia:concept/a,1\n"))


def test_req500_csv_collects_all_errors_atomically(tmp_path: Path) -> None:
    broken = (
        "concept,value,unit\n"
        "sia:concept/a,viele,m2\n"  # Zeile 2: keine Zahl
        ",1,m2\n"  # Zeile 3: Concept fehlt
        "sia:concept/b,2,\n"  # Zeile 4: Einheit fehlt
    )
    with pytest.raises(ProjectDataError) as excinfo:
        read_csv(_write(tmp_path, broken))
    # alle Fehler gesammelt, nicht nur der erste (KBOB)
    assert len(excinfo.value.report) == 3


def test_req500_csv_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(ProjectDataError, match="nicht lesbar"):
        read_csv(tmp_path / "existiert-nicht.csv")
