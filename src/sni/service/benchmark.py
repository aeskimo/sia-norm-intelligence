"""Benchmark-Runner: Critical Failure Rate und Kennzahlen (REQ-402/600/601).

Faelle: ``tests/benchmark/*.yaml``, erstellt von Fachpersonen. Faelle mit
``<...>``-Platzhaltern sind noch nicht fachlich ausgefuehrt und werden
gezippt (nicht gezaehlt).

Critical Failure: Antwort fachlich falsch UND als ``normativ_belegt``
klassifiziert. Bei >0 kritischen Faelen liefert der Runner Exit-Code 1
(REQ-402: sonst waere ``make eval`` ein falsches Guenzeichen).

M6 (REQ-600): der Report enthaelt alle Kennzahlen aus 00_VISION.md
(Definitionen: docs/06_TESTING.md): Critical Failure Rate, class_accuracy,
source_citation_accuracy, correct_abstention_rate, rule_calculation_accuracy.
Nenner 0 -> null (nicht messbar). REQ-601: Feld ``failures`` listet jeden
Fehlschlag mit Fall-ID, erwarteter und tatsächlicher Aussageklasse.
"""

from __future__ import annotations

import argparse
import json
import math
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
from sni.rules.engine import STATUS_OK, InputValue, evaluate
from sni.service.answerer import (
    CLASS_ABGELEITET,
    CLASS_NICHT_EINDEUTIG,
    CLASS_NORMATIV_BELEGT,
    AnswerRequest,
    answer,
)

PLACEHOLDER = re.compile(r"<[^<>]+>")
# Toleranzen für den Wertvergleich, gemäss ADR-0004 (Konsistenzprüfung).
REL_TOL = 1e-6
ABS_TOL = 1e-9


@dataclass(frozen=True)
class BenchmarkCase:
    """Ein Benchmark-Fall (Format: docs/06_TESTING.md)."""

    id: str
    category: str
    question: str
    expected_class: str
    project_data: dict[str, dict[str, object]] | None = None
    expected_rule: str | None = None
    expected_sources: tuple[dict[str, str], ...] = ()
    expected_value: tuple[float, str] | None = None
    note: str | None = None
    author: str | None = None


@dataclass(frozen=True)
class CaseResult:
    """Auswertung eines Falls.

    ``correct`` = Aussageklasse stimmt (REQ-402). ``citation_ok``,
    ``abstention_ok``, ``calculation_ok`` sind die REQ-600-Kennzahlen je
    Fall; ``None`` = Kennzahl auf diesen Fall nicht anwendbar.
    """

    case_id: str
    category: str
    question: str
    expected_class: str
    actual_class: str | None
    executed: bool
    correct: bool
    critical: bool
    details: list[str] = field(default_factory=list)
    citation_ok: bool | None = None
    abstention_ok: bool | None = None
    calculation_ok: bool | None = None


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

    raw_sources: object = entry.get("expected_sources")
    expected_sources: list[dict[str, str]] = []
    if raw_sources is not None:
        if not isinstance(raw_sources, list) or not raw_sources:
            raise ValueError(
                f"{file_name}: Fall {entry.get('id')!r}: 'expected_sources' muss "
                "eine nicht leere Liste sein"
            )
        for item in raw_sources:
            if not isinstance(item, dict):
                raise ValueError(
                    f"{file_name}: Fall {entry.get('id')!r}: 'expected_sources'-Eintrag "
                    "muss ein Objekt sein"
                )
            source: dict[str, str] = {}
            for key in ("norm", "edition", "clause"):
                value: object = item.get(key)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"{file_name}: Fall {entry.get('id')!r}: "
                        f"'expected_sources[].[{key}]' fehlt oder ist leer"
                    )
                source[key] = value
            expected_sources.append(source)

    raw_expected_value: object = entry.get("expected_value")
    expected_value: tuple[float, str] | None = None
    if raw_expected_value is not None:
        if not isinstance(raw_expected_value, Mapping):
            raise ValueError(
                f"{file_name}: Fall {entry.get('id')!r}: 'expected_value' muss ein "
                "Objekt {value, unit} sein"
            )
        expected_number: object = raw_expected_value.get("value")
        expected_unit: object = raw_expected_value.get("unit")
        if isinstance(expected_number, bool) or not isinstance(expected_number, (int, float)):
            raise ValueError(
                f"{file_name}: Fall {entry.get('id')!r}: 'expected_value.value' muss eine Zahl sein"
            )
        if not isinstance(expected_unit, str) or not expected_unit.strip():
            raise ValueError(
                f"{file_name}: Fall {entry.get('id')!r}: 'expected_value.unit' muss "
                "eine nicht leere Zeichenkette sein"
            )
        expected_value = (float(expected_number), expected_unit)

    return BenchmarkCase(
        id=required("id"),
        category=required("category"),
        question=required("question"),
        expected_class=required("expected_class"),
        project_data=project_data,
        expected_rule=optional("expected_rule"),
        expected_sources=tuple(expected_sources),
        expected_value=expected_value,
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
        answer_obj: dict[str, object] | None = None
        details: list[str] = []
        try:
            answer_obj = answer(AnswerRequest(case.question, case.project_data), kb, catalog)
            raw_actual: object = answer_obj.get("answer_class")
            actual_class: str | None = raw_actual if isinstance(raw_actual, str) else None
        except Exception as exc:  # ein einzelner Fall darf den Lauf nicht brechen
            actual_class = None
            details.append(f"Auswertung fehlgeschlagen: {exc}")
        correct = actual_class == case.expected_class
        critical = (not correct) and actual_class == CLASS_NORMATIV_BELEGT
        if not correct:
            details.append(f"erwartet: {case.expected_class}, erhalten: {actual_class}")
        citation_ok, citation_details = _check_citation(case, actual_class, _sources_of(answer_obj))
        abstention_ok, abstention_details = _check_abstention(case, actual_class)
        calculation_ok, calculation_details = _check_calculation(
            case, kb, actual_class, _supported_by(answer_obj)
        )
        details.extend(citation_details)
        details.extend(abstention_details)
        details.extend(calculation_details)
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
                citation_ok,
                abstention_ok,
                calculation_ok,
            )
        )
    return results, sum(1 for r in results if r.critical)


def _check_citation(
    case: BenchmarkCase,
    actual_class: str | None,
    sources: list[Mapping[str, object]],
) -> tuple[bool | None, list[str]]:
    """REQ-600: Fundstellen (Norm + Ausgabe + Ziffer) der Antwort korrekt?

    Anwendbar nur für Faelle mit ``expected_class: normativ_belegt`` und
    ``expected_sources``; jede erwartete Fundstelle muss in den
    Antwort-Fundstellen vorkommen (exakte Übereinstimmung aller drei
    Felder). ``None`` = nicht anwendbar.
    """
    if case.expected_class != CLASS_NORMATIV_BELEGT or not case.expected_sources:
        return None, []
    if actual_class != CLASS_NORMATIV_BELEGT:
        return False, [
            f"Fundstellenprüfung: Antwort ist {actual_class!r}, erwartet normativ_belegt"
        ]
    details: list[str] = []
    for expected in case.expected_sources:
        if not any(_same_source(source, expected) for source in sources):
            details.append(
                f"Fundstelle fehlt in Antwort: {expected['norm']} {expected['edition']} "
                f"Ziffer {expected['clause']}"
            )
    return (not details), details


def _same_source(source: Mapping[str, object], expected: Mapping[str, str]) -> bool:
    return all(source.get(key) == expected[key] for key in ("norm", "edition", "clause"))


def _check_abstention(
    case: BenchmarkCase, actual_class: str | None
) -> tuple[bool | None, list[str]]:
    """REQ-600: unbeantwortbare Frage (erwartet ``nicht_eindeutig``) korrekt abgelehnt?"""
    if case.expected_class != CLASS_NICHT_EINDEUTIG:
        return None, []
    if actual_class == CLASS_NICHT_EINDEUTIG:
        return True, []
    return False, [f"Enthaltung erwartet, erhalten {actual_class!r}"]


def _check_calculation(
    case: BenchmarkCase,
    kb: KnowledgeBase,
    actual_class: str | None,
    supported_by: list[str],
) -> tuple[bool | None, list[str]]:
    """REQ-600: deterministischer Fall (erwartet ``abgeleitet``) korrekt?

    Klasse ``abgeleitet`` UND — falls ``expected_value`` angegeben — der
    Wert durch direkte Regelauswertung (M3-Engine, unabhängig vom
    Antwortpfad) bestätigt, inkl. Einheit und ADR-0004-Toleranzen.
    """
    if case.expected_class != CLASS_ABGELEITET:
        return None, []
    if actual_class != CLASS_ABGELEITET:
        return False, [f"Regelrechnung erwartet, Antwort ist {actual_class!r}"]
    details: list[str] = []
    rule_id = case.expected_rule
    if rule_id is not None and rule_id not in supported_by:
        details.append(f"Antwort beruht nicht auf der erwarteten Regel {rule_id}")
    if rule_id is None:
        rule_ids = sorted(ref for ref in supported_by if ":rule/" in ref)
        rule_id = rule_ids[0] if len(rule_ids) == 1 else None
    if case.expected_value is None:
        return (not details), details
    rule: dict[str, object] | None = kb.rules.get(rule_id) if rule_id is not None else None
    if rule is None:
        return False, details + [
            f"Regel {rule_id!r} nicht verfügbar; expected_value nicht überprüfbar"
        ]
    inputs = _to_inputs(case.project_data)
    if inputs is None:
        return False, details + ["Projektdaten ungültig; expected_value nicht überprüfbar"]
    result = evaluate(rule, inputs)
    expected_value, expected_unit = case.expected_value
    if result.status != STATUS_OK or result.value is None:
        return False, details + [
            f"Regelauswertung fehlgeschlagen: {'; '.join(result.report) or 'kein Wert'}"
        ]
    if result.unit != expected_unit:
        return False, details + [f"Einheit erwartet {expected_unit}, Regel liefert {result.unit!r}"]
    if not math.isclose(result.value, expected_value, rel_tol=REL_TOL, abs_tol=ABS_TOL):
        return False, details + [
            f"expected_value {expected_value:g} {expected_unit}, "
            f"Regel berechnet {result.value:g} {result.unit}"
        ]
    return (not details), details


def _to_inputs(
    project_data: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, InputValue] | None:
    """Projektdaten -> Engine-Inputs; None bei ungültigen Werten (wie Answerer)."""
    if project_data is None:
        return {}
    inputs: dict[str, InputValue] = {}
    for concept, raw in project_data.items():
        value: object = raw.get("value")
        unit: object = raw.get("unit")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not isinstance(unit, str) or not unit.strip():
            return None
        inputs[concept] = InputValue(float(value), unit)
    return inputs


def _sources_of(answer_obj: dict[str, object] | None) -> list[Mapping[str, object]]:
    if answer_obj is None:
        return []
    raw: object = answer_obj.get("sources", [])
    if not isinstance(raw, list):
        return []
    return [source for source in raw if isinstance(source, Mapping)]


def _supported_by(answer_obj: dict[str, object] | None) -> list[str]:
    if answer_obj is None:
        return []
    raw: object = answer_obj.get("claims", [])
    if not isinstance(raw, list):
        return []
    refs: list[str] = []
    for claim in raw:
        if not isinstance(claim, Mapping):
            continue
        supported: object = claim.get("supported_by")
        if isinstance(supported, list):
            refs.extend(ref for ref in supported if isinstance(ref, str))
    return refs


def compute_metrics(results: list[CaseResult]) -> dict[str, object]:
    """REQ-600: alle Kennzahlen aus 00_VISION.md (Definitionen: docs/06_TESTING.md).

    Nenner 0 -> null (nicht messbar); die Critical Failure Rate bleibt
    0.0 bei 0 ausgeführten Faelen (REQ-402-Verhalten).
    """
    executed = [r for r in results if r.executed]
    n = len(executed)
    passed = sum(1 for r in executed if r.correct)
    critical = sum(1 for r in executed if r.critical)
    citation = [r for r in executed if r.citation_ok is not None]
    abstention = [r for r in executed if r.abstention_ok is not None]
    deterministic = [r for r in executed if r.calculation_ok is not None]
    return {
        "critical_failures": critical,
        "critical_failure_rate": round(critical / n, 4) if n else 0.0,
        "class_accuracy": round(passed / n, 4) if n else None,
        "source_citation_accuracy": _rate(
            sum(1 for r in citation if r.citation_ok is True), len(citation)
        ),
        "source_citation_cases": len(citation),
        "correct_abstention_rate": _rate(
            sum(1 for r in abstention if r.abstention_ok is True), len(abstention)
        ),
        "abstention_cases": len(abstention),
        "rule_calculation_accuracy": _rate(
            sum(1 for r in deterministic if r.calculation_ok is True), len(deterministic)
        ),
        "deterministic_cases": len(deterministic),
    }


def _rate(numerator: int, denominator: int) -> float | None:
    """Anteil (gerundet auf 4 Stellen); Nenner 0 -> null (nicht messbar)."""
    return round(numerator / denominator, 4) if denominator else None


def build_failures(results: list[CaseResult]) -> list[dict[str, object]]:
    """REQ-601: jeder Fehlschlag mit Fall-ID, erwarteter und tatsächlicher Klasse."""
    return [
        {
            "id": r.case_id,
            "category": r.category,
            "expected_class": r.expected_class,
            "actual_class": r.actual_class,
            "critical": r.critical,
            "details": r.details,
        }
        for r in results
        if r.executed and not r.correct
    ]


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
    metrics = compute_metrics(results)
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
        **metrics,
        "status": "ok" if critical == 0 else "critical",
        "failures": build_failures(results),
        "note": (
            "REQ-600: alle Kennzahlen aus 00_VISION.md (Definitionen: "
            "docs/06_TESTING.md); Nenner 0 -> null. REQ-601: Failures mit "
            "Fall-ID, erwarteter und tatsächlicher Klasse."
        ),
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
