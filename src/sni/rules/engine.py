"""Regel-Engine: Regeln laden und auswerten (M3, REQ-300/301/302).

Regeln liegen als JSON-Dateien in ``data/rules/`` (lokaler Mount) und
werden gegen ``rule.schema.json`` validiert. Die Auswertung nutzt die
sichere Ausdrucks-Sprache aus ``sni.rules.expression`` (kein eval()).

Statuses von ``RuleResult``:
- ``ok``: Regel berechnet, Ergebnis und Einheit bekannt.
- ``insufficient_data``: ein oder mehrere Pflicht-Inputs fehlen (REQ-301);
  es wird nie ein Wert erfunden.
- ``error``: Einheitenkonflikt (REQ-302), Ausdrucksfehler oder Regeldefekt.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from jsonschema.exceptions import ValidationError

from sni.core.schemas import make_validator
from sni.rules.expression import (
    ExpressionError,
    ExpressionValue,
    evaluate_expression,
    identifiers_in,
)

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RULES_DIR = ROOT / "data" / "rules"

STATUS_OK = "ok"
STATUS_INSUFFICIENT_DATA = "insufficient_data"
STATUS_ERROR = "error"


class RuleLoadError(RuntimeError):
    """Regel-Ladung fehlgeschlagen; ``report`` enthält alle gesammelten Fehler."""

    def __init__(self, report: list[str]) -> None:
        super().__init__("; ".join(report))
        self.report = report


@dataclass(frozen=True)
class InputValue:
    """Gelieferter Wert für ein Concept: Zahl plus Einheit."""

    value: float
    unit: str


@dataclass(frozen=True)
class RuleResult:
    """Ergebnis einer Regelauswertung."""

    rule_id: str
    status: str  # STATUS_OK | STATUS_INSUFFICIENT_DATA | STATUS_ERROR
    value: float | None = None
    unit: str | None = None
    missing_inputs: tuple[str, ...] = ()
    report: tuple[str, ...] = ()


def load_rules(rules_dir: Path = DEFAULT_RULES_DIR) -> list[dict[str, object]]:
    """Lädt alle ``*.json`` aus ``rules_dir`` und validiert sie (atomar).

    Fehlendes Verzeichnis = keine Regeln (leere Liste). Alle Fehler werden
    gesammelt (KBOB-Muster); bei Fehlern wird nichts geliefert. Die
    Regel-ID muss zum Dateinamen passen (sanitisierte ID = Dateiname).
    """
    if not rules_dir.is_dir():
        return []
    validator = make_validator("rule.schema.json")
    errors: list[str] = []
    rules: list[dict[str, object]] = []
    for path in sorted(rules_dir.glob("*.json")):
        file_errors: list[str] = []
        try:
            raw: object = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            file_errors.append(f"{path.name}: kein gültiges JSON: {exc}")
            errors.extend(file_errors)
            continue
        if not isinstance(raw, dict):
            file_errors.append(f"{path.name}: Regel muss ein JSON-Objekt sein")
            errors.extend(file_errors)
            continue
        for error in validator.iter_errors(raw):
            file_errors.append(f"{path.name}: {_error_detail(error)}")
        rule_id: object = raw.get("id")
        if isinstance(rule_id, str) and _sanitize_id(rule_id) != path.stem:
            file_errors.append(f"{path.name}: Regel-ID {rule_id!r} passt nicht zum Dateinamen")
        errors.extend(file_errors)
        if not file_errors:
            rules.append(raw)
    if errors:
        raise RuleLoadError(errors)
    return rules


def evaluate(rule: dict[str, object], inputs: Mapping[str, InputValue]) -> RuleResult:
    """Wertet eine Regel mit gelieferten Werten aus.

    ``inputs`` ist ein Mapping Concept-ID -> ``InputValue``. Fehlende
    Pflicht-Inputs ergeben ``insufficient_data`` (REQ-301); Einheitenkonflikte
    (geliefert vs. deklariert, im Ausdruck, Output) sind Fehler (REQ-302).
    """
    rule_id: object = rule.get("id")
    rule_id_str = rule_id if isinstance(rule_id, str) else "<unbekannt>"

    declared = _declared_inputs(rule)
    if declared is None:
        return _error(rule_id_str, ["Regel: Feld 'inputs' fehlt oder ist ungültig"])

    # REQ-301: fehlende Pflicht-Inputs -> insufficient_data (nie Werte erfinden).
    missing = sorted(
        concept for concept, _, required in declared if required and concept not in inputs
    )
    if missing:
        return RuleResult(
            rule_id=rule_id_str, status=STATUS_INSUFFICIENT_DATA, missing_inputs=tuple(missing)
        )

    # Identifier-Mapping: Concept-Slug -> Concept-ID (mehrdeutigkeit ist ein Fehler).
    identifiers: dict[str, str] = {}
    problems: list[str] = []
    for concept, _, _ in declared:
        ident = _identifier_for(concept)
        if ident in identifiers and identifiers[ident] != concept:
            problems.append(f"Regel: Concept-Slug {ident!r} ist mehrdeutig")
        identifiers[ident] = concept

    # REQ-302: gelieferte Einheit muss zur deklarierten Einheit passen.
    for concept, unit, _ in declared:
        provided = inputs.get(concept)
        if provided is not None and provided.unit != unit:
            problems.append(
                f"Einheitenkonflikt: {concept} erwartet {unit}, geliefert {provided.unit}"
            )
    if problems:
        return _error(rule_id_str, problems)

    expression: object = rule.get("expression")
    if not isinstance(expression, str) or not expression:
        return _error(rule_id_str, ["Regel: Feld 'expression' fehlt oder ist leer"])
    try:
        used = identifiers_in(expression)
    except ExpressionError as exc:
        return _error(rule_id_str, [f"Ausdruck: {exc}"])

    for ident in used:
        if ident not in identifiers:
            problems.append(f"Ausdruck: Identifier {ident!r} ist kein deklarierter Input")
        elif identifiers[ident] not in inputs:
            problems.append(
                f"Ausdruck: Input {identifiers[ident]!r} referenziert, aber nicht geliefert"
            )
    if problems:
        return _error(rule_id_str, problems)

    bindings = {
        ident: ExpressionValue(inputs[concept].value, inputs[concept].unit)
        for ident, concept in identifiers.items()
        if concept in inputs
    }
    try:
        result = evaluate_expression(expression, bindings)
    except ExpressionError as exc:
        return _error(rule_id_str, [f"Ausdruck: {exc}"])

    # REQ-302: Ergebnis-Einheit muss zur deklarierten Output-Einheit passen.
    output: object = rule.get("output")
    out_unit: object = output.get("unit") if isinstance(output, dict) else None
    if isinstance(out_unit, str) and out_unit != result.unit:
        return _error(
            rule_id_str,
            [
                f"Einheitenkonflikt: Ausdruck liefert {result.unit!r}, "
                f"Output deklariert {out_unit!r}"
            ],
        )

    return RuleResult(rule_id=rule_id_str, status=STATUS_OK, value=result.value, unit=result.unit)


def _declared_inputs(rule: dict[str, object]) -> list[tuple[str, str, bool]] | None:
    """Liest die deklarierten Inputs (concept, unit, required); None bei Defekt."""
    raw: object = rule.get("inputs")
    if not isinstance(raw, list):
        return None
    declared: list[tuple[str, str, bool]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None
        concept: object = item.get("concept")
        unit: object = item.get("unit")
        required: object = item.get("required", True)
        if (
            not isinstance(concept, str)
            or not isinstance(unit, str)
            or not isinstance(required, bool)
        ):
            return None
        declared.append((concept, unit, required))
    return declared


def _identifier_for(concept_id: str) -> str:
    """Slug der Concept-ID (Teil nach dem letzten "/"), mit "-" durch "_" ersetzt."""
    return concept_id.rsplit("/", 1)[-1].replace("-", "_")


def _error(rule_id: str, problems: list[str]) -> RuleResult:
    return RuleResult(rule_id=rule_id, status=STATUS_ERROR, report=tuple(problems))


def _sanitize_id(obj_id: str) -> str:
    """Macht eine Objekt-ID dateisystem-sicher (gleiche Regel wie M2-Queue)."""
    return re.sub(r"[:/@]", "_", obj_id)


def _error_detail(error: ValidationError) -> str:
    path = "/".join(str(part) for part in error.absolute_path)
    return f"{path}: {error.message}" if path else error.message
