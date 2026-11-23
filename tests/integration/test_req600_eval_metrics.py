"""REQ-600: ``make eval`` berechnet alle Kennzahlen aus docs/00_VISION.md.

Kennzahlen (Definitionen: docs/06_TESTING.md):
- Critical Failure Rate (vorhanden seit REQ-402)
- class_accuracy: Anteil ausgefuehrter Faelle mit richtiger Aussageklasse
- source_citation_accuracy: Fundstellen (Norm + Ausgabe + Ziffer) korrekt,
  nur Faelle mit expected_class normativ_belegt + expected_sources
- correct_abstention_rate: Faelle mit erwarteter Enthaltung (nicht_eindeutig)
  korrekt abgelehnt
- rule_calculation_accuracy: deterministische Faelle (expected_class
  abgeleitet): Klasse korrekt UND expected_value durch direkte
  Regelauswertung (M3-Engine) bestaetigt

Nenner 0 -> Kennzahl null (nicht messbar).
"""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
import yaml

from sni.service.benchmark import main_eval

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = ROOT / "tests" / "benchmark"


def _report(reports_dir: Path) -> dict[str, object]:
    from datetime import date

    path = reports_dir / f"eval_{date.today().isoformat()}.json"
    raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def _copy_benchmark(tmp_path: Path) -> Path:
    target = tmp_path / "benchmark"
    shutil.copytree(BENCHMARK_DIR, target)
    return target


def _load_cases_doc(benchmark_dir: Path) -> list[dict[str, object]]:
    path = benchmark_dir / "cases_synthetic.yaml"
    doc: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(doc, list)
    return [entry for entry in doc if isinstance(entry, dict)]


def _save_cases_doc(benchmark_dir: Path, doc: list[dict[str, object]]) -> None:
    path = benchmark_dir / "cases_synthetic.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _mutate_case(
    benchmark_dir: Path, case_id: str, mutate: Callable[[dict[str, object]], None]
) -> None:
    doc = _load_cases_doc(benchmark_dir)
    for entry in doc:
        if entry.get("id") == case_id:
            mutate(entry)
    _save_cases_doc(benchmark_dir, doc)


def _add_case(benchmark_dir: Path, case: dict[str, object]) -> None:
    doc = _load_cases_doc(benchmark_dir)
    doc.append(case)
    _save_cases_doc(benchmark_dir, doc)


def _tampered_knowledge(tmp_path: Path) -> Path:
    """Kandidaten-Statement 'freigeben' (wie REQ-402-Test): BM-SYN-004
    beantwortet dann normativ_belegt statt nicht_eindeutig."""
    tampered = tmp_path / "knowledge_tampered"
    shutil.copytree(BENCHMARK_DIR / "knowledge", tampered)
    path = tampered / "sia_statement_syn1-2020_5.5_1.json"
    import json

    obj: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    obj["review_status"] = "approved"
    obj["approved_by"] = "Fachperson Test (synthetisch)"
    obj["approved_at"] = "2026-11-23"
    source = obj.get("source")
    assert isinstance(source, dict)
    source["verified"] = True
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return tampered


def test_req600_repo_benchmark_reports_all_vision_metrics(tmp_path: Path) -> None:
    rc = main_eval(
        BENCHMARK_DIR,
        BENCHMARK_DIR / "knowledge",
        BENCHMARK_DIR / "catalog_snapshot.json",
        tmp_path / "reports",
    )
    assert rc == 0
    report = _report(tmp_path / "reports")
    assert report["critical_failure_rate"] == 0.0
    assert report["class_accuracy"] == 1.0
    assert report["source_citation_accuracy"] == 1.0
    assert cast(int, report["source_citation_cases"]) == 1
    assert report["correct_abstention_rate"] == 1.0
    assert cast(int, report["abstention_cases"]) == 3
    assert report["rule_calculation_accuracy"] == 1.0
    assert cast(int, report["deterministic_cases"]) == 1


def test_req600_class_accuracy_counts_class_mismatches(tmp_path: Path) -> None:
    benchmark = _copy_benchmark(tmp_path)
    _mutate_case(
        benchmark,
        "BM-SYN-001",
        lambda entry: entry.__setitem__("question", "Was schreibt die Norm zur Photovoltaik?"),
    )
    rc = main_eval(
        benchmark,
        benchmark / "knowledge",
        benchmark / "catalog_snapshot.json",
        tmp_path / "reports",
    )
    assert rc == 0  # kein Critical Failure (Antwort ist nicht normativ_belegt)
    report = _report(tmp_path / "reports")
    assert report["class_accuracy"] == 0.8  # 4/5
    assert report["critical_failures"] == 0
    assert report["source_citation_accuracy"] == 0.0  # BM-SYN-001 liefert keine Fundstelle


def test_req600_source_citation_accuracy_detects_missing_citation(tmp_path: Path) -> None:
    benchmark = _copy_benchmark(tmp_path)
    _add_case(
        benchmark,
        {
            "id": "BM-T-600-01",
            "category": "definition",
            "question": "Was ist die Gesamtfläche?",
            "expected_class": "normativ_belegt",
            "expected_sources": [{"norm": "SYN 1", "edition": "2020", "clause": "9.9"}],
            "author": "SNI-Referenz (synthetischer Strukturfall)",
        },
    )
    rc = main_eval(
        benchmark,
        benchmark / "knowledge",
        benchmark / "catalog_snapshot.json",
        tmp_path / "reports",
    )
    assert rc == 0
    report = _report(tmp_path / "reports")
    assert cast(int, report["source_citation_cases"]) == 2
    assert report["source_citation_accuracy"] == 0.5  # BM-SYN-001 ok, BM-T-600-01 nicht


def test_req600_correct_abstention_rate_drops_on_tampered_knowledge(tmp_path: Path) -> None:
    tampered = _tampered_knowledge(tmp_path)
    rc = main_eval(
        BENCHMARK_DIR,
        tampered,
        BENCHMARK_DIR / "catalog_snapshot.json",
        tmp_path / "reports",
    )
    assert rc == 1  # REQ-402: Critical Failure -> exit != 0
    report = _report(tmp_path / "reports")
    assert cast(int, report["abstention_cases"]) == 3
    assert report["correct_abstention_rate"] == pytest.approx(2 / 3, abs=5e-5)


def test_req600_rule_calculation_accuracy_detects_wrong_expected_value(tmp_path: Path) -> None:
    benchmark = _copy_benchmark(tmp_path)
    _mutate_case(
        benchmark,
        "BM-SYN-002",
        lambda entry: entry.__setitem__("expected_value", {"value": 160, "unit": "m2"}),
    )
    rc = main_eval(
        benchmark,
        benchmark / "knowledge",
        benchmark / "catalog_snapshot.json",
        tmp_path / "reports",
    )
    assert rc == 0  # Klasse stimmt (abgeleitet), nur der Wert-Vergleich schlaegt fehl
    report = _report(tmp_path / "reports")
    assert report["class_accuracy"] == 1.0
    assert cast(int, report["deterministic_cases"]) == 1
    assert report["rule_calculation_accuracy"] == 0.0  # Engine rechnet 150, erwartet 160


def test_req600_rule_calculation_accuracy_detects_missing_rule(tmp_path: Path) -> None:
    benchmark = _copy_benchmark(tmp_path)
    (benchmark / "knowledge" / "sia_rule_syn1-2020_gf-summe.json").unlink()
    rc = main_eval(
        benchmark,
        benchmark / "knowledge",
        benchmark / "catalog_snapshot.json",
        tmp_path / "reports",
    )
    assert rc == 1  # Antwort rutscht auf normativ_belegt -> Critical Failure
    report = _report(tmp_path / "reports")
    assert report["rule_calculation_accuracy"] == 0.0
    assert cast(int, report["critical_failures"]) >= 1


def test_req600_metrics_null_when_no_applicable_cases(tmp_path: Path) -> None:
    benchmark = tmp_path / "benchmark_minimal"
    (benchmark / "knowledge").mkdir(parents=True)
    shutil.copytree(BENCHMARK_DIR / "knowledge", benchmark / "knowledge", dirs_exist_ok=True)
    shutil.copy(BENCHMARK_DIR / "catalog_snapshot.json", benchmark / "catalog_snapshot.json")
    cases = [
        {
            "id": "BM-T-600-02",
            "category": "calculation",
            "question": "Wie gross ist die Gesamtfläche für die gegebenen Projektwerte?",
            "project_data": {
                "sia:concept/teilsflaeche-a": {"value": 100, "unit": "m2"},
                "sia:concept/teilsflaeche-b": {"value": 50, "unit": "m2"},
            },
            "expected_class": "abgeleitet",
            "expected_rule": "sia:rule/syn1-2020/gf-summe",
            "expected_value": {"value": 150, "unit": "m2"},
            "author": "SNI-Referenz (synthetischer Strukturfall)",
        }
    ]
    (benchmark / "cases_minimal.yaml").write_text(
        yaml.safe_dump(cases, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    rc = main_eval(
        benchmark,
        benchmark / "knowledge",
        benchmark / "catalog_snapshot.json",
        tmp_path / "reports",
    )
    assert rc == 0
    report = _report(tmp_path / "reports")
    assert report["source_citation_accuracy"] is None
    assert cast(int, report["source_citation_cases"]) == 0
    assert report["correct_abstention_rate"] is None
    assert cast(int, report["abstention_cases"]) == 0
    assert report["class_accuracy"] == 1.0
    assert report["rule_calculation_accuracy"] == 1.0
