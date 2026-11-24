"""REQ-900: Given ein PDF unter data/norms/<norm-id>/document.pdf When `make extract`
Then entsteht document.draft.json mit Ziffern-Skelett (Ziffernnummern am
Zeilenanfang, deterministisch) und extrahiertem Ziffern-Text; Fachfelder bleiben
leer; der Entwurf ist validiert gegen document_draft.schema.json."""

from pathlib import Path

from sni.core.schemas import make_validator
from sni.ingest.pdf_extract import extract_pdf
from tests.conftest import PdfLine, clause_text, clauses_of, load_draft, write_norm_pdf


def test_req900_draft_created_with_clause_skeleton(tmp_path: Path) -> None:
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


def test_req900_clause_text_extracted(tmp_path: Path) -> None:
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


def test_req900_expert_fields_stay_empty(tmp_path: Path) -> None:
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


def test_req900_draft_validates_against_schema(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms)
    extract_pdf("syn1-2020", norms_dir=norms)
    draft = load_draft("syn1-2020", norms)
    assert list(make_validator("document_draft.schema.json").iter_errors(draft)) == []


def test_req900_toc_and_values_are_not_clauses(tmp_path: Path) -> None:
    norms = tmp_path / "norms"
    write_norm_pdf("syn1-2020", norms)  # enthält TOC-Punktguertel, "2003", "1.5", "0.8"
    extract_pdf("syn1-2020", norms_dir=norms)
    numbers = [c["number"] for c in clauses_of(load_draft("syn1-2020", norms))]
    assert numbers == ["1", "1.1", "2", "2.1", "3", "3.1"]
    assert "1.5" not in numbers
    assert "0.8" not in numbers


def test_req900_text_spans_pages(tmp_path: Path) -> None:
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


def test_req900_bold_headings_are_the_clauses(tmp_path: Path) -> None:
    """F1 (ADR-0010): nur Ueberschriften (boldes erstes Segment) werden Ziffern;
    regulaere TOC-/Werte-Zeilen bleiben draussen, karge Ueberschrift "2.4" kommt rein."""
    norms = tmp_path / "norms"
    pages: list[PdfLine] = [
        "SYN 1  Testnorm (synthetisch)",
        "Inhalt",
        "1 Ziel .......... 2",
        "2 Nachweise .......... 3",
        ("1 Ziel", True),
        "Diese synthetische Norm regelt Testfaelle.",
        ("1.1 Anwendungsbereich", True),
        "Sie gilt fuer alle Testgebaeude.",
        ("2 Nachweise", True),
        "Jeder Nachweis ist zu dokumentieren.",
        "1.5 m Abstand zwischen Kanten.",
        "2003 war eine alte Fassung.",
        ("2.1 Groessen", True),
        "0.8 kg pro Flaeche maximal.",
        ("2.4", True, 56.6),
        ("3 Grenzwerte", True),
        ("3.1 Flaeche", True),
        "Testgrenzwert fuer die Testflaeche.",
    ]
    write_norm_pdf("syn1-2020", norms, pages=pages)
    result = extract_pdf("syn1-2020", norms_dir=norms)
    assert result.clauses == 7
    draft = load_draft("syn1-2020", norms)
    numbers = [c["number"] for c in clauses_of(draft)]
    assert numbers == ["1", "1.1", "2", "2.1", "2.4", "3", "3.1"]
    by_number = {c["number"]: c for c in clauses_of(draft)}
    assert clause_text(by_number["2.4"]) == ""
    assert "Ziel" in clause_text(by_number["1"])


def test_req900_running_footer_rejected(tmp_path: Path) -> None:
    """F3: einstufige Ziffer == Seitenzahl im unteren Seitenband ist Laufzeile."""
    norms = tmp_path / "norms"
    pages: list[list[PdfLine]] = [
        [("1 Ziel", True), "Inhaltstext."],
        [
            "Fortsetzungstext.",
            "Fuellenzeile.",
            "Fuellenzeile.",
            "Fuellenzeile.",
            "Fuellenzeile.",
            ("2 Laufzeile", True),
        ],
    ]
    write_norm_pdf("syn1-2020", norms, pages=pages, line_height=160.0)
    extract_pdf("syn1-2020", norms_dir=norms)
    draft = load_draft("syn1-2020", norms)
    numbers = [c["number"] for c in clauses_of(draft)]
    assert numbers == ["1"]
    by_number = {c["number"]: c for c in clauses_of(draft)}
    assert "Fortsetzungstext." in clause_text(by_number["1"])


def test_req900_repeated_bold_row_rejected(tmp_path: Path) -> None:
    """F4: gleiche (Ziffer, Restlaenge) auf 2+ Seiten ist Tabellenkopf, keine Ziffer."""
    norms = tmp_path / "norms"
    pages: list[list[PdfLine]] = [
        [("1 Ziel", True), "Inhaltstext.", ("4.3.1 Wiederholung", True)],
        [("4.3.1 Wiederholung", True), "Weitere Inhalte."],
    ]
    write_norm_pdf("syn1-2020", norms, pages=pages)
    extract_pdf("syn1-2020", norms_dir=norms)
    numbers = [c["number"] for c in clauses_of(load_draft("syn1-2020", norms))]
    assert numbers == ["1"]


def test_req900_zero_component_rejected(tmp_path: Path) -> None:
    """F2: 0-Komponenten ("4.3.0", "0.8") sind Werte, keine Ziffernnummern."""
    norms = tmp_path / "norms"
    pages: list[PdfLine] = [
        ("1 Ziel", True),
        "Inhaltstext.",
        ("4.3.0 Tabellenwert", True),
        ("0.8 Sonderwert", True),
    ]
    write_norm_pdf("syn1-2020", norms, pages=pages)
    extract_pdf("syn1-2020", norms_dir=norms)
    numbers = [c["number"] for c in clauses_of(load_draft("syn1-2020", norms))]
    assert numbers == ["1"]


def test_req900_bare_number_right_of_margin_rejected(tmp_path: Path) -> None:
    """Kare bold-Ziffer rechts ausserhalb des linken Randbereichs (Tabelle) wird abgewiesen."""
    norms = tmp_path / "norms"
    pages: list[PdfLine] = [
        ("1 Ziel", True),
        "Inhaltstext.",
        ("22", True, 250.0),
    ]
    write_norm_pdf("syn1-2020", norms, pages=pages)
    extract_pdf("syn1-2020", norms_dir=norms)
    numbers = [c["number"] for c in clauses_of(load_draft("syn1-2020", norms))]
    assert numbers == ["1"]
