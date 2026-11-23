"""REQ-402: Benchmark-Runner – Critical Failure Rate = 0, sonst Exit-Code != 0."""

import json
import shutil
from datetime import date
from pathlib import Path
from typing import cast

from sni.catalog.snapshot import load_snapshot
from sni.catalog.store import ConceptStore
from sni.knowledge.store import load_knowledge
from sni.service.benchmark import load_cases, main_eval, run_benchmark

ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_DIR = ROOT / "tests" / "benchmark"


def _catalog_store(tmp_path: Path) -> ConceptStore:
    store = ConceptStore(tmp_path / "catalog.db")
    raw: object = json.loads((BENCHMARK_DIR / "catalog_snapshot.json").read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    store.import_snapshot(load_snapshot(raw))
    return store


def _report(reports_dir: Path) -> dict[str, object]:
    path = reports_dir / f"eval_{date.today().isoformat()}.json"
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)
    return raw


def test_req402_placeholder_cases_are_skipped() -> None:
    cases, skipped = load_cases(BENCHMARK_DIR)
    ids = [case.id for case in cases]
    assert "BM-SYN-001" in ids  # synthetische Strukturfaelle werden gelesen
    assert all(not case_id.startswith("BM-000") for case_id in ids)  # Beispiel-Faelle gezippt
    assert any("Platzhalter" in line for line in skipped)


def test_req402_repo_benchmark_no_critical_failures(tmp_path: Path) -> None:
    cases, _ = load_cases(BENCHMARK_DIR)
    kb = load_knowledge(BENCHMARK_DIR / "knowledge")
    store = _catalog_store(tmp_path)
    try:
        results, critical = run_benchmark(cases, kb, store)
    finally:
        store.close()
    executed = [r for r in results if r.executed]
    assert executed
    assert all(r.correct for r in executed)  # M4: Klassenvergleich auf Repo-Benchmark
    assert critical == 0


def test_req402_main_eval_exit_zero_and_report(tmp_path: Path) -> None:
    rc = main_eval(
        BENCHMARK_DIR,
        BENCHMARK_DIR / "knowledge",
        BENCHMARK_DIR / "catalog_snapshot.json",
        tmp_path / "reports",
    )
    assert rc == 0
    report = _report(tmp_path / "reports")
    assert report["critical_failures"] == 0
    assert report["status"] == "ok"
    assert cast(int, report["executed"]) >= 5
    assert report["cases"]


def test_req402_tampered_knowledge_is_critical(tmp_path: Path) -> None:
    """Unerlaubte 'Freigabe' eines candidate Statements -> Antwort behauptet
    normativ_belegt bei erwarteter Enthaltung -> Critical Failure (REQ-402)."""
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
    rc = main_eval(
        BENCHMARK_DIR,
        tampered,
        BENCHMARK_DIR / "catalog_snapshot.json",
        tmp_path / "reports_bad",
    )
    assert rc == 1  # REQ-402: Critical Failure Rate != 0 -> make eval exit != 0
    report = _report(tmp_path / "reports_bad")
    assert cast(int, report["critical_failures"]) >= 1
    assert report["status"] == "critical"
    raw_cases = report["cases"]
    assert isinstance(raw_cases, list)
    critical_ids = [c["id"] for c in raw_cases if isinstance(c, dict) and c.get("critical")]
    assert "BM-SYN-004" in critical_ids
