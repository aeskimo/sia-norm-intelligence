"""REQ-601: Der Report listet jeden Fehlschlag mit Fall-ID, erwarteter und
tatsächlicher Aussageklasse (Feld ``failures``)."""

import json
import shutil
from pathlib import Path
from typing import cast

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


def _failures(report: dict[str, object]) -> list[dict[str, object]]:
    raw: object = report["failures"]
    assert isinstance(raw, list)
    return [entry for entry in raw if isinstance(entry, dict)]


def _by_id(failures: list[dict[str, object]], case_id: str) -> dict[str, object]:
    for entry in failures:
        if entry.get("id") == case_id:
            return entry
    raise AssertionError(f"Fall {case_id} nicht in Failures: {failures}")


def _tampered_knowledge(tmp_path: Path) -> Path:
    tampered = tmp_path / "knowledge_tampered"
    shutil.copytree(BENCHMARK_DIR / "knowledge", tampered)
    path = tampered / "sia_statement_syn1-2020_5.5_1.json"
    obj: dict[str, object] = json.loads(path.read_text(encoding="utf-8"))
    obj["review_status"] = "approved"
    obj["approved_by"] = "Fachperson Test (synthetisch)"
    obj["approved_at"] = "2026-11-23"
    source = obj.get("source")
    assert isinstance(source, dict)
    source["verified"] = True
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return tampered


def test_req601_repo_benchmark_reports_no_failures(tmp_path: Path) -> None:
    rc = main_eval(
        BENCHMARK_DIR,
        BENCHMARK_DIR / "knowledge",
        BENCHMARK_DIR / "catalog_snapshot.json",
        tmp_path / "reports",
    )
    assert rc == 0
    assert _failures(_report(tmp_path / "reports")) == []


def test_req601_failures_carry_id_expected_and_actual_class(tmp_path: Path) -> None:
    tampered = _tampered_knowledge(tmp_path)
    rc = main_eval(
        BENCHMARK_DIR,
        tampered,
        BENCHMARK_DIR / "catalog_snapshot.json",
        tmp_path / "reports",
    )
    assert rc == 1
    failures = _failures(_report(tmp_path / "reports"))
    entry = _by_id(failures, "BM-SYN-004")
    assert entry["expected_class"] == "nicht_eindeutig"
    assert entry["actual_class"] == "normativ_belegt"
    assert entry["critical"] is True
    for failure in failures:
        assert {"id", "expected_class", "actual_class"} <= set(failure)
        details: object = failure["details"]
        assert (
            isinstance(details, list) and details and all(isinstance(line, str) for line in details)
        )


def test_req601_non_critical_class_mismatch_is_a_failure(tmp_path: Path) -> None:
    benchmark = _copy_benchmark(tmp_path)
    doc = _load_cases_doc(benchmark)
    for entry in doc:
        if entry.get("id") == "BM-SYN-001":
            entry["question"] = "Was schreibt die Norm zur Photovoltaik?"
    _save_cases_doc(benchmark, doc)
    rc = main_eval(
        benchmark,
        benchmark / "knowledge",
        benchmark / "catalog_snapshot.json",
        tmp_path / "reports",
    )
    assert rc == 0  # kein Critical Failure
    report = _report(tmp_path / "reports")
    failures = _failures(report)
    entry = _by_id(failures, "BM-SYN-001")
    assert entry["expected_class"] == "normativ_belegt"
    assert entry["actual_class"] == "nicht_eindeutig"
    assert entry["critical"] is False
    assert cast(int, report["critical_failures"]) == 0
