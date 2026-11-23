"""Benchmark-Runner: Critical Failure Rate (M4, REQ-402; docs/06_TESTING.md).

Faelle: ``tests/benchmark/*.yaml``, erstellt von Fachpersonen. Faelle mit
``<...>``-Platzhaltern sind noch nicht fachlich ausgefuehrt und werden
gezippt (nicht gezaehlt).

Critical Failure: Antwort fachlich falsch UND als ``normativ_belegt``
klassifiziert. M4 vergleicht die Aussageklassen; der Vergleich von Werten
und Fundstellen folgt in M6. Bei >0 kritischen Faelen liefert der Runner
Exit-Code 1 (REQ-402: sonst waere ``make eval`` ein falsches Guenzeichen).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

from sni.catalog.snapshot import load_snapshot
from sni.catalog.store import ConceptStore
from sni.knowledge.store import KnowledgeBase, load_knowledge
from sni.service.answerer import CLASS_NORMATIV_BELEGT, AnswerRequest, answer

PLACEHOLDER = re.compile(r"<[^<>]+>")


@dataclass(frozen=True)
class BenchmarkCase:
    """Ein Benchmark-Fall (Format: docs/06_TESTING.md)."""

    id: str
    category: str
    question: str
    expected_class: str
    project_data: dict[str, dict[str, object]] | None = None
    expected_rule: str | None = None
    note: str | None = None
    author: str | None = None


@dataclass(frozen=True)
class CaseResult:
    """Auswertung eines Falls (M4: Klassenvergleich)."""

    case_id: str
    category: str
    question: str
    expected_class: str
    actual_class: str | None
    executed: bool
    correct: bool
    critical: bool
    details: list[str] = field(default_factory=list)


def load_cases(benchmark_dir: Path) -> tuple[list[BenchmarkCase], list[str]]:
    """Liest alle ``*.yaml``; liefert (Faelle, Skip-Meldungen).

    Platzhalter-Faelle (<...>) werden gezippt; formatfehlerhafte Faelle
    brechen die Auswertung ab (keine stille Wegzipperei).
    """
    cases: list[BenchmarkCase] = []
    skipped: list[str] = []
    for path in sorted(benchmark_dir.glob("*.yaml")):
        doc: object
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            skipped.append(f"{path.name}: nicht lesbar: {exc}")
            continue
        if not isinstance(doc, list):
            skipped.append(f"{path.name}: erwartet eine Fall-Liste")
            continue
        for entry in doc:
            if not isinstance(entry, dict):
                skipped.append(f"{path.name}: Eintrag ist kein Objekt")
                continue
            case_id: object = entry.get("id")
            label = case_id if isinstance(case_id, str) else "<ohne-ID>"
            if PLACEHOLDER.search(json.dumps(entry, ensure_ascii=False, default=str)):
                skipped.append(
                    f"{path.name}: {label}: <...>-Platzhalter (fachliche Auswertung offen)"
                )
                continue
            try:
                cases.append(_parse_case(path.name, entry))
            except ValueError as exc:
                raise ValueError(f"{exc} (formatfehlerhafter Benchmark-Fall)") from exc
    return cases, skipped


def _parse_case(file_name: str, entry: Mapping[str, object]) -> BenchmarkCase:
    def required(key: str) -> str:
        value: object = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{file_name}: Fall {entry.get('id')!r}: Feld '{key}' fehlt oder ist leer"
            )
        return value

    def optional(key: str) -> str | None:
        value: object = entry.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(
                f"{file_name}: Fall {entry.get('id')!r}: Feld '{key}' muss eine Zeichenkette sein"
            )
        return value

    raw_pd: object = entry.get("project_data")
    project_data: dict[str, dict[str, object]] | None = None
    if raw_pd is not None:
        if not isinstance(raw_pd, Mapping):
            raise ValueError(
                f"{file_name}: Fall {entry.get('id')!r}: 'project_data' muss ein Objekt sein"
            )
        project_data = {}
        for concept, raw_value in raw_pd.items():
            if not isinstance(concept, str):
                raise ValueError(
                    f"{file_name}: Fall {entry.get('id')!r}: Projektwert ohne Concept-ID"
                )
            if not isinstance(raw_value, Mapping):
                raise ValueError(
                    f"{file_name}: Fall {entry.get('id')!r}: Projektwert {concept!r} "
                    "muss ein Objekt sein"
                )
            value_dict: dict[str, object] = {str(k): v for k, v in raw_value.items()}
            project_data[concept] = value_dict
    return BenchmarkCase(
        id=required("id"),
        category=required("category"),
        question=required("question"),
        expected_class=required("expected_class"),
        project_data=project_data,
        expected_rule=optional("expected_rule"),
        note=optional("note"),
        author=optional("author"),
    )


def run_benchmark(
    cases: list[BenchmarkCase],
    kb: KnowledgeBase,
    catalog: ConceptStore,
) -> tuple[list[CaseResult], int]:
    """Führt alle Faelle aus; liefert (Resultate, Anzahl kritischer Faelle)."""
    results: list[CaseResult] = []
    for case in cases:
        try:
            result = answer(AnswerRequest(case.question, case.project_data), kb, catalog)
            actual: object = result.get("answer_class")
            actual_class = actual if isinstance(actual, str) else None
        except Exception as exc:  # ein einzelner Fall darf den Lauf nicht brechen
            results.append(
                CaseResult(
                    case.id,
                    case.category,
                    case.question,
                    case.expected_class,
                    None,
                    True,
                    False,
                    False,
                    [f"Auswertung fehlgeschlagen: {exc}"],
                )
            )
            continue
        correct = actual_class == case.expected_class
        critical = (not correct) and actual_class == CLASS_NORMATIV_BELEGT
        details = [] if correct else [f"erwartet: {case.expected_class}, erhalten: {actual_class}"]
        results.append(
            CaseResult(
                case.id,
                case.category,
                case.question,
                case.expected_class,
                actual_class,
                True,
                correct,
                critical,
                details,
            )
        )
    return results, sum(1 for r in results if r.critical)


def main_eval(
    benchmark_dir: Path,
    knowledge_dir: Path,
    catalog_snapshot: Path,
    reports_dir: Path,
) -> int:
    """Führt die Benchmark aus und schreibt ``eval_<datum>.json``.

    Liefert 0 ohne kritische Faelle, sonst 1 (REQ-402).
    """
    cases, skipped = load_cases(benchmark_dir)
    kb = load_knowledge(knowledge_dir)
    raw: object = json.loads(catalog_snapshot.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{catalog_snapshot.name}: Katalog-Snapshot ist kein JSON-Objekt")
    with tempfile.TemporaryDirectory(prefix="sni-eval-") as tmp:
        store = ConceptStore(Path(tmp) / "catalog.db")
        try:
            store.import_snapshot(load_snapshot(raw))
            results, critical = run_benchmark(cases, kb, store)
        finally:
            store.close()
    executed = sum(1 for r in results if r.executed)
    passed = sum(1 for r in results if r.executed and r.correct)
    report: dict[str, object] = {
        "date": date.today().isoformat(),
        "benchmark_dir": str(benchmark_dir),
        "knowledge_dir": str(knowledge_dir),
        "catalog_snapshot": str(catalog_snapshot),
        "cases_loaded": len(cases),
        "executed": executed,
        "skipped": skipped,
        "passed": passed,
        "failed": executed - passed,
        "critical_failures": critical,
        "critical_failure_rate": round(critical / executed, 4) if executed else 0.0,
        "status": "ok" if critical == 0 else "critical",
        "note": "M4: Vergleich der Aussageklassen; Wert-/Fundstellen-Vergleich folgt in M6.",
        "cases": [
            {
                "id": r.case_id,
                "category": r.category,
                "question": r.question,
                "expected_class": r.expected_class,
                "actual_class": r.actual_class,
                "correct": r.correct,
                "critical": r.critical,
                "details": r.details,
            }
            for r in results
        ],
    }
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / f"eval_{date.today().isoformat()}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[eval] Report: {out}")
    print(f"[eval] ausgefuehrt: {executed}, bestanden: {passed}, kritisch: {critical}")
    return 1 if critical else 0


def main(argv: list[str] | None = None) -> int:
    """CLI: ``python -m sni.service.benchmark`` (wird von ``make eval`` aufgerufen)."""
    repo = Path(__file__).resolve().parents[3]
    benchmark = repo / "tests" / "benchmark"
    parser = argparse.ArgumentParser(description="SNI Benchmark-Runner (REQ-402)")
    parser.add_argument("--cases-dir", type=Path, default=benchmark)
    parser.add_argument("--knowledge-dir", type=Path, default=benchmark / "knowledge")
    parser.add_argument(
        "--catalog-snapshot", type=Path, default=benchmark / "catalog_snapshot.json"
    )
    parser.add_argument("--reports-dir", type=Path, default=repo / "reports")
    args = parser.parse_args(argv)
    try:
        return main_eval(
            args.cases_dir, args.knowledge_dir, args.catalog_snapshot, args.reports_dir
        )
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"[eval] Fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
