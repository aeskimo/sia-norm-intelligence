"""REQ-501: Check-Service liefert pro Regel pass|fail|insufficient_data mit Begründung.

Semantik: ADR-0004 (Konsistenzprüfung; ``pass`` ≠ Normkonformität).
REQ-502: fehlende Projektdaten erzeugen GapReports im selben Ergebnis.
"""

from typing import Any, cast

import pytest

from sni.core.schemas import make_validator
from sni.service.checker import DISCLAIMER, CheckInputError, check

A = "sia:concept/teilsflaeche-a"
B = "sia:concept/teilsflaeche-b"
OUT = "sia:concept/gesamtflaeche"
RULE_ID = "sia:rule/syn1-2020/gf-summe"


def _rule(
    rule_id: str = RULE_ID,
    review_status: str = "approved",
    expression: str = "teilsflaeche_a + teilsflaeche_b",
    inputs: list[dict[str, object]] | None = None,
    output: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": rule_id,
        "derived_from": ["sia:statement/syn1-2020/4.1/1"],
        "inputs": (
            inputs
            if inputs is not None
            else [
                {"concept": A, "unit": "m2"},
                {"concept": B, "unit": "m2"},
            ]
        ),
        "output": output if output is not None else {"concept": OUT, "unit": "m2"},
        "expression": expression,
        "review_status": review_status,
    }


def _full_data(claimed: float = 150.0, claimed_unit: str = "m2") -> dict[str, dict[str, object]]:
    return {
        A: {"value": 100, "unit": "m2"},
        B: {"value": 50, "unit": "m2"},
        OUT: {"value": claimed, "unit": claimed_unit},
    }


def _check(
    rules: list[dict[str, object]],
    data: dict[str, dict[str, object]] | None,
    existing_gap_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    return cast("dict[str, Any]", check(rules, data, existing_gap_ids))


def test_req501_consistent_project_data_passes() -> None:
    result = _check([_rule()], _full_data())
    entry = result["checks"][0]
    assert entry["status"] == "pass"
    assert entry["value"] == 150.0
    assert entry["claimed"] == 150.0
    assert entry["unit"] == "m2"
    assert entry["missing_inputs"] == []
    assert entry["derived_from"] == ["sia:statement/syn1-2020/4.1/1"]
    assert entry["reason"] == "Konsistent: Regel leitet 150 m2 ab, Projekt liefert 150 m2"
    assert result["gaps"] == []
    assert result["disclaimer"] == DISCLAIMER


def test_req501_inconsistent_project_data_fails() -> None:
    result = _check([_rule()], _full_data(claimed=160.0))
    entry = result["checks"][0]
    assert entry["status"] == "fail"
    assert entry["value"] == 150.0
    assert entry["claimed"] == 160.0
    assert entry["reason"] == "Inkonsistent: Regel leitet 150 m2 ab, Projekt liefert 160 m2"


def test_req501_difference_within_tolerance_passes() -> None:
    # relative Abweichung 0.0001/150 ≈ 6.7e-9 < rel_tol 1e-6 (ADR-0004)
    entry = _check([_rule()], _full_data(claimed=150.0001))["checks"][0]
    assert entry["status"] == "pass"


def test_req501_difference_beyond_tolerance_fails() -> None:
    # relative Abweichung 0.001/150 ≈ 6.7e-7 > rel_tol 1e-6 (ADR-0004)
    entry = _check([_rule()], _full_data(claimed=150.001))["checks"][0]
    assert entry["status"] == "fail"
    assert entry["reason"].startswith("Inkonsistent")


def test_req501_missing_required_input_is_insufficient() -> None:
    data = {A: {"value": 100, "unit": "m2"}, OUT: {"value": 150, "unit": "m2"}}
    entry = _check([_rule()], data)["checks"][0]
    assert entry["status"] == "insufficient_data"
    assert entry["missing_inputs"] == [B]
    assert entry["value"] is None
    assert entry["claimed"] == 150.0
    assert entry["reason"] == f"Fehlende Projektdaten für: {B}"


def test_req501_missing_output_value_is_insufficient_but_value_derived() -> None:
    data = {A: {"value": 100, "unit": "m2"}, B: {"value": 50, "unit": "m2"}}
    entry = _check([_rule()], data)["checks"][0]
    assert entry["status"] == "insufficient_data"
    assert entry["missing_inputs"] == [OUT]
    assert entry["value"] == 150.0  # abgeleitet, nicht erfunden
    assert entry["claimed"] is None
    assert "Output-Concept" in entry["reason"]


def test_req501_referenced_optional_input_missing_is_insufficient() -> None:
    rule = _rule(
        expression="teilsflaeche_a + teilsflaeche_b + korrektur",
        inputs=[
            {"concept": A, "unit": "m2"},
            {"concept": B, "unit": "m2"},
            {"concept": "sia:concept/korrektur", "unit": "m2", "required": False},
        ],
    )
    entry = _check([rule], _full_data())["checks"][0]
    assert entry["status"] == "insufficient_data"
    assert entry["missing_inputs"] == ["sia:concept/korrektur"]
    assert entry["value"] is None
    assert entry["reason"] == "Fehlende Projektdaten für: sia:concept/korrektur"


def test_req501_unreferenced_optional_input_not_required() -> None:
    rule = _rule(
        inputs=[
            {"concept": A, "unit": "m2"},
            {"concept": B, "unit": "m2"},
            {"concept": "sia:concept/korrektur", "unit": "m2", "required": False},
        ],
    )
    entry = _check([rule], _full_data())["checks"][0]
    assert entry["status"] == "pass"


def test_req501_output_unit_conflict_fails() -> None:
    entry = _check([_rule()], _full_data(claimed_unit="m3"))["checks"][0]
    assert entry["status"] == "fail"
    assert entry["reason"] == "Einheitenkonflikt: Output deklariert 'm2', Projekt liefert 'm3'"


def test_req501_input_unit_conflict_fails_with_engine_report() -> None:
    data = _full_data()
    data[B] = {"value": 50, "unit": "m3"}
    entry = _check([_rule()], data)["checks"][0]
    assert entry["status"] == "fail"
    assert entry["reason"] == f"Einheitenkonflikt: {B} erwartet m2, geliefert m3"
    assert entry["value"] is None


def test_req501_only_approved_rules_are_checked() -> None:
    rules = [_rule(), _rule(rule_id="sia:rule/syn1-2020/kandidat", review_status="candidate")]
    result = _check(rules, _full_data())
    assert [c["rule_id"] for c in result["checks"]] == [RULE_ID]


def test_req501_missing_project_data_creates_gap_reports() -> None:
    data = {A: {"value": 100, "unit": "m2"}, OUT: {"value": 150, "unit": "m2"}}
    result = _check([_rule()], data)
    gaps = result["gaps"]
    assert len(gaps) == 1
    gap = gaps[0]
    assert gap["gap_type"] == "missing_project_data"
    assert gap["id"] == "GAP-0001"
    assert gap["evidence"] == [RULE_ID]


def test_req501_gap_ids_continue_from_existing_ids() -> None:
    data = {A: {"value": 100, "unit": "m2"}}
    result = _check([_rule()], data, ("GAP-0007", "GAP-0002"))
    assert [g["id"] for g in result["gaps"]] == ["GAP-0008"]


def test_req501_result_is_valid_against_check_result_schema() -> None:
    validator = make_validator("check_result.schema.json")
    incomplete = {A: {"value": 100, "unit": "m2"}}  # insufficient + Gaps
    validator.validate(check([_rule()], incomplete))
    validator.validate(check([_rule()], _full_data()))  # pass, keine Gaps


def test_req501_invalid_project_value_raises_check_input_error() -> None:
    bad = {A: {"value": "viel", "unit": "m2"}}
    with pytest.raises(CheckInputError, match="'value' muss eine Zahl sein"):
        check([_rule()], bad)


def test_req501_invalid_project_unit_raises_check_input_error() -> None:
    bad = {A: {"value": 100, "unit": "  "}}
    with pytest.raises(CheckInputError, match="'unit' muss eine nicht leere Zeichenkette sein"):
        check([_rule()], bad)


def test_req501_unused_project_concepts_are_ignored() -> None:
    data = _full_data()
    data["sia:concept/sonstiges"] = {"value": 7, "unit": "kg"}
    entry = _check([_rule()], data)["checks"][0]
    assert entry["status"] == "pass"
    assert entry["claimed"] == 150.0


def test_req501_checks_are_ordered_by_rule_id() -> None:
    rules = [
        _rule(rule_id="sia:rule/syn1-2020/b-regel"),
        _rule(rule_id="sia:rule/syn1-2020/a-regel"),
    ]
    result = _check(rules, _full_data())
    assert [c["rule_id"] for c in result["checks"]] == [
        "sia:rule/syn1-2020/a-regel",
        "sia:rule/syn1-2020/b-regel",
    ]


def test_req501_no_rules_yields_empty_schema_valid_result() -> None:
    result = _check([], _full_data())
    assert result["checks"] == []
    assert result["gaps"] == []
    assert result["disclaimer"] == DISCLAIMER
    make_validator("check_result.schema.json").validate(result)


def test_req501_no_project_data_all_insufficient_with_gaps() -> None:
    result = _check([_rule()], None)
    entry = result["checks"][0]
    assert entry["status"] == "insufficient_data"
    assert entry["missing_inputs"] == [A, B]
    assert len(result["gaps"]) == 2


def test_req501_expression_defect_fails_with_engine_report() -> None:
    rule = _rule(expression="teilsflaeche_a +")
    entry = _check([rule], _full_data())["checks"][0]
    assert entry["status"] == "fail"
    assert entry["reason"].startswith("Ausdruck:")
    assert entry["value"] is None


def test_req501_missing_declared_output_unit_fails() -> None:
    rule = _rule(output={"concept": OUT})  # ohne "unit"
    entry = _check([rule], _full_data())["checks"][0]
    assert entry["status"] == "fail"
    assert entry["reason"] == "Regeldefekt: Output-Einheit nicht deklariert"
