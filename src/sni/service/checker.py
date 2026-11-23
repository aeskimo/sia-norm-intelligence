"""Check-Service: Projektdaten gegen approved Regeln prüfen (M5, REQ-501/502).

Konsistenzprüfung laut ADR-0004 (OQ-005, Option A): das Projekt liefert
die Pflicht-Inputs einer Regel und einen Wert für deren Output-Konzept;
die M3-Regel-Engine leitet den Wert ab:
- abgeleitet ≈ geliefert (``math.isclose``, rel_tol 1e-6, abs_tol 1e-9)
  -> ``pass``
- abgeleitet ≠ geliefert -> ``fail``
- Pflicht-Input fehlt, referenzierter optionaler Input fehlt oder der
  Output-Wert fehlt -> ``insufficient_data``
- Engine-Fehler (Einheitenkonflikt, Regeldefekt) -> ``fail`` mit dem
  Engine-Bericht als Begründung

``pass`` bedeutet: die Projektdaten sind mit der Regel konsistent – keine
Aussage über Normkonformität (Grenzwertprüfung ist ein Follow-up-ADR,
OQ-005). Nur approved Regeln werden geprüft (G3). Fehlende Projektdaten
erzeugen zusätzlich GapReports ``missing_project_data`` (REQ-502; die API
ist stateless, GAP-IDs laufen pro Antwort). Das Ergebnis wird gegen
``check_result.schema.json`` validiert (AGENTS.md §6).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import cast

from jsonschema.exceptions import ValidationError

from sni.core.schemas import make_validator
from sni.projectdata.gaps import missing_project_data_gaps
from sni.rules.engine import STATUS_INSUFFICIENT_DATA, STATUS_OK, InputValue, evaluate
from sni.rules.expression import ExpressionError, identifiers_in

REL_TOL = 1e-6
ABS_TOL = 1e-9
CHECK_PASS = "pass"
CHECK_FAIL = "fail"
CHECK_INSUFFICIENT_DATA = "insufficient_data"
DISCLAIMER = (
    "Keine Rechtsauskunft. Basis: freigegebene Regeln und gelieferte "
    "Projektdaten; v1 prüft Konsistenz, keine Grenzwerte (ADR-0004)."
)


class CheckError(RuntimeError):
    """Check-Ergebnis konnte nicht gebaut oder nicht schemakonform validiert werden."""


class CheckInputError(ValueError):
    """Ungültige Projektdaten im Check-Request (REQ-501)."""


def check(
    rules: Sequence[Mapping[str, object]],
    project_data: Mapping[str, Mapping[str, object]] | None,
    existing_gap_ids: Iterable[str] = (),
) -> dict[str, object]:
    """Prüft Projektdaten gegen approved Regeln (REQ-501, ADR-0004).

    ``rules``: Regel-Objekte (wie von ``sni.rules.engine.load_rules``
    geladen, validiert gegen ``rule.schema.json``). Nur
    ``review_status == "approved"`` wird geprüft (G3); die
    Check-Reihenfolge ist deterministisch (Rule-ID). ``project_data``:
    Concept-ID -> ``{"value": Zahl, "unit": "..."}`` (gleiche Form wie
    ``AnswerRequest.project_data``). ``existing_gap_ids``: bereits
    vergebene GAP-IDs, auf deren höchster Nummer weitergezählt wird.

    Wirft ``CheckInputError`` bei ungültiger ``project_data`` und
    ``CheckError``, wenn das Ergebnis nicht schemakonform ist.
    """
    inputs = _to_input_values(project_data)
    approved = sorted(
        (rule for rule in rules if _is_approved(rule)),
        key=lambda rule: _rule_id(rule),
    )
    result: dict[str, object] = {
        "checks": [_check_rule(rule, inputs) for rule in approved],
        "gaps": missing_project_data_gaps(approved, inputs.keys(), existing_gap_ids),
        "disclaimer": DISCLAIMER,
    }
    _validate(result)
    return result


def _check_rule(rule: Mapping[str, object], inputs: Mapping[str, InputValue]) -> dict[str, object]:
    """Einzelner Check-Eintrag; Statuslogik laut ADR-0004."""
    rule_id = _rule_id(rule)
    output_concept, output_unit = _declared_output(rule)
    claimed, claimed_unit = _claimed_value(inputs, output_concept)
    referenced_missing = _referenced_not_delivered(rule, inputs)
    # Engine erwartet dict[str, object] (load_rules liefert das); die
    # Service-API ist bewusst weiter (Mapping) wie die REQ-502-Gap-Funktion.
    result = evaluate(cast("dict[str, object]", rule), inputs)

    if result.status == STATUS_OK:
        if result.value is None:
            return _entry(
                rule,
                rule_id,
                CHECK_FAIL,
                "Regeldefekt: Engine-Status ok ohne Wert (intern)",
                None,
                claimed,
                result.unit,
                [],
            )
        return _check_consistent(
            rule,
            rule_id,
            result.value,
            result.unit,
            claimed,
            claimed_unit,
            output_concept,
            output_unit,
        )
    if result.status == STATUS_INSUFFICIENT_DATA:
        missing = sorted(set(result.missing_inputs) | set(referenced_missing))
        return _entry(
            rule,
            rule_id,
            CHECK_INSUFFICIENT_DATA,
            _missing_reason(missing),
            None,
            claimed,
            None,
            missing,
        )
    if _is_pure_missing_data_error(result.report, referenced_missing):
        missing = sorted(set(result.missing_inputs) | set(referenced_missing))
        return _entry(
            rule,
            rule_id,
            CHECK_INSUFFICIENT_DATA,
            _missing_reason(missing),
            None,
            claimed,
            None,
            missing,
        )
    return _entry(rule, rule_id, CHECK_FAIL, "; ".join(result.report), None, claimed, None, [])


def _check_consistent(
    rule: Mapping[str, object],
    rule_id: str,
    value: float,
    unit: str | None,
    claimed: float | None,
    claimed_unit: str | None,
    output_concept: str | None,
    output_unit: str | None,
) -> dict[str, object]:
    """Vergleich abgeleiteter vs. gelieferter Output-Wert (ADR-0004)."""
    if output_concept is None:
        return _entry(
            rule,
            rule_id,
            CHECK_FAIL,
            "Regeldefekt: Output-Concept nicht deklariert",
            value,
            claimed,
            unit,
            [],
        )
    if claimed is None:
        return _entry(
            rule,
            rule_id,
            CHECK_INSUFFICIENT_DATA,
            f"Kein Projektwert für Output-Concept '{output_concept}' geliefert "
            f"(Konsistenzprüfung benötigt ihn)",
            value,
            None,
            unit,
            [output_concept],
        )
    if output_unit is None:
        return _entry(
            rule,
            rule_id,
            CHECK_FAIL,
            "Regeldefekt: Output-Einheit nicht deklariert",
            value,
            claimed,
            unit,
            [],
        )
    if claimed_unit != output_unit:
        return _entry(
            rule,
            rule_id,
            CHECK_FAIL,
            f"Einheitenkonflikt: Output deklariert {output_unit!r}, "
            f"Projekt liefert {claimed_unit!r}",
            value,
            claimed,
            unit,
            [],
        )
    if math.isclose(value, claimed, rel_tol=REL_TOL, abs_tol=ABS_TOL):
        reason = (
            f"Konsistent: Regel leitet {_fmt(value, unit)} ab, "
            f"Projekt liefert {_fmt(claimed, claimed_unit)}"
        )
        return _entry(rule, rule_id, CHECK_PASS, reason, value, claimed, unit, [])
    reason = (
        f"Inkonsistent: Regel leitet {_fmt(value, unit)} ab, "
        f"Projekt liefert {_fmt(claimed, claimed_unit)}"
    )
    return _entry(rule, rule_id, CHECK_FAIL, reason, value, claimed, unit, [])


def _entry(
    rule: Mapping[str, object],
    rule_id: str,
    status: str,
    reason: str,
    value: float | None,
    claimed: float | None,
    unit: str | None,
    missing_inputs: list[str],
) -> dict[str, object]:
    """Schemakonformer Check-Eintrag (check_result.schema.json)."""
    return {
        "rule_id": rule_id,
        "status": status,
        "reason": reason,
        "value": value,
        "claimed": claimed,
        "unit": unit,
        "missing_inputs": missing_inputs,
        "derived_from": _derived_from(rule),
    }


def _to_input_values(
    project_data: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, InputValue]:
    """Project-Request -> Engine-Inputs (gleiche Validierung wie M4)."""
    if project_data is None:
        return {}
    inputs: dict[str, InputValue] = {}
    for concept_id, raw in project_data.items():
        value: object = raw.get("value")
        unit: object = raw.get("unit")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CheckInputError(f"Projektwert {concept_id}: 'value' muss eine Zahl sein")
        if not isinstance(unit, str) or not unit.strip():
            raise CheckInputError(
                f"Projektwert {concept_id}: 'unit' muss eine nicht leere Zeichenkette sein"
            )
        inputs[concept_id] = InputValue(float(value), unit)
    return inputs


def _is_pure_missing_data_error(report: tuple[str, ...], concepts: list[str]) -> bool:
    """True, wenn der Engine-Bericht nur aus fehlenden, referenzierten
    Inputs besteht (ADR-0004: Datenmangel, kein Regeldefekt). Das
    Zeilenformat stammt aus ``sni.rules.engine``.
    """
    if not concepts:
        return False
    expected = {
        f"Ausdruck: Input {concept!r} referenziert, aber nicht geliefert" for concept in concepts
    }
    return set(report) == expected


def _referenced_not_delivered(
    rule: Mapping[str, object], inputs: Mapping[str, InputValue]
) -> list[str]:
    """Referenzierte, aber nicht gelieferte Input-Concepts (ADR-0004)."""
    return sorted(concept for concept in _referenced_concepts(rule) if concept not in inputs)


def _referenced_concepts(rule: Mapping[str, object]) -> list[str]:
    """Concept-IDs, die der Regel-Ausdruck referenziert ([] bei Defekt)."""
    expression: object = rule.get("expression")
    if not isinstance(expression, str) or not expression:
        return []
    declared = _declared_inputs(rule)
    if declared is None:
        return []
    try:
        used = identifiers_in(expression)
    except ExpressionError:
        return []
    mapping: dict[str, str] = {}
    for concept, _unit, _required in declared:
        ident = _identifier_for(concept)
        if ident in mapping and mapping[ident] != concept:
            return []  # Slug mehrdeutig -> Engine-Fehler, kein Datenmangel
        mapping[ident] = concept
    return [mapping[ident] for ident in used if ident in mapping]


def _declared_inputs(rule: Mapping[str, object]) -> list[tuple[str, str, bool]] | None:
    """Deklarierte Inputs (concept, unit, required); None bei Defekt.

    Eigener Helfer im House-Style (vgl. ``sni.rules.engine``).
    """
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


def _declared_output(rule: Mapping[str, object]) -> tuple[str | None, str | None]:
    """Output (concept, unit) der Regel; None-Felder bei Defekt."""
    output: object = rule.get("output")
    if not isinstance(output, dict):
        return None, None
    concept: object = output.get("concept")
    unit: object = output.get("unit")
    return (
        concept if isinstance(concept, str) else None,
        unit if isinstance(unit, str) else None,
    )


def _claimed_value(
    inputs: Mapping[str, InputValue], output_concept: str | None
) -> tuple[float | None, str | None]:
    """Gelieferter Output-Wert (value, unit); (None, None) wenn nicht geliefert."""
    if output_concept is None:
        return None, None
    provided = inputs.get(output_concept)
    if provided is None:
        return None, None
    return provided.value, provided.unit


def _derived_from(rule: Mapping[str, object]) -> list[str]:
    """NormStatement-IDs (Fundstelle der Regel) aus ``derived_from``."""
    raw: object = rule.get("derived_from")
    if not isinstance(raw, list):
        return []
    return [ref for ref in raw if isinstance(ref, str)]


def _missing_reason(missing: list[str]) -> str:
    return f"Fehlende Projektdaten für: {', '.join(missing)}"


def _fmt(value: float, unit: str | None) -> str:
    return f"{value:g} {unit or ''}".strip()


def _rule_id(rule: Mapping[str, object]) -> str:
    rule_id: object = rule.get("id")
    return rule_id if isinstance(rule_id, str) else "<unbekannt>"


def _is_approved(rule: Mapping[str, object]) -> bool:
    """G3: nur freigegebene Regeln werden geprüft oder zitiert."""
    return rule.get("review_status") == "approved"


def _identifier_for(concept_id: str) -> str:
    """Slug der Concept-ID (gleiche Regel wie ``sni.rules.engine``)."""
    return concept_id.rsplit("/", 1)[-1].replace("-", "_")


def _validate(result: dict[str, object]) -> None:
    """DoD (AGENTS.md §6): Ergebnis muss gegen das Schema validieren."""
    try:
        make_validator("check_result.schema.json").validate(result)
    except ValidationError as exc:
        raise CheckError(f"Check-Ergebnis nicht schemakonform: {exc.message}") from exc
