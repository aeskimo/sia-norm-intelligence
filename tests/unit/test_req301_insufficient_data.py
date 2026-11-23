"""REQ-301: Fehlende Inputs ergeben Status `insufficient_data`, nie einen
erfundenen Wert."""

from sni.rules.engine import InputValue, evaluate
from tests.conftest import load_synthetic_rule, rule_full_inputs


def test_req301_missing_required_input_is_insufficient_data() -> None:
    rule = load_synthetic_rule()
    inputs = {"sia:concept/teilsflaeche-a": InputValue(100.0, "m2")}
    result = evaluate(rule, inputs)
    assert result.status == "insufficient_data"
    assert result.missing_inputs == ("sia:concept/teilsflaeche-b",)
    assert result.value is None


def test_req301_multiple_missing_inputs_all_listed() -> None:
    rule = load_synthetic_rule()
    result = evaluate(rule, {})
    assert result.status == "insufficient_data"
    assert result.missing_inputs == (
        "sia:concept/teilsflaeche-a",
        "sia:concept/teilsflaeche-b",
    )
    assert result.value is None


def test_req301_optional_input_may_be_missing() -> None:
    """'korrektur' hat required: false und wird im Ausdruck nicht referenziert."""
    rule = load_synthetic_rule()
    result = evaluate(rule, rule_full_inputs())
    assert result.status == "ok"
    assert result.value == 150.0
    assert result.missing_inputs == ()


def test_req301_referenced_optional_input_missing_is_error() -> None:
    rule = load_synthetic_rule()
    rule["expression"] = "teilsflaeche_a + teilsflaeche_b + korrektur"
    result = evaluate(rule, rule_full_inputs())
    assert result.status == "error"
    assert any("sia:concept/korrektur" in line for line in result.report)


def test_req301_never_invents_a_value() -> None:
    """Ohne alle Inputs gibt es kein Ergebnis – kein Platzhalterwert."""
    rule = load_synthetic_rule()
    result = evaluate(rule, {})
    assert result.value is None
    assert result.unit is None
    assert result.status == "insufficient_data"
