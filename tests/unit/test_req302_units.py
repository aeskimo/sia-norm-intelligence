"""REQ-302: Einheiten werden validiert, Einheitenkonflikte sind Fehler."""

from sni.rules.engine import InputValue, evaluate
from tests.conftest import load_synthetic_rule, rule_full_inputs


def test_req302_provided_unit_mismatch_is_error() -> None:
    rule = load_synthetic_rule()
    inputs = {
        "sia:concept/teilsflaeche-a": InputValue(100.0, "m2"),
        "sia:concept/teilsflaeche-b": InputValue(50.0, "m"),  # deklariert: m2
    }
    result = evaluate(rule, inputs)
    assert result.status == "error"
    assert any("Einheitenkonflikt" in line for line in result.report)


def test_req302_same_unit_addition_ok() -> None:
    rule = load_synthetic_rule()
    result = evaluate(rule, rule_full_inputs())
    assert result.status == "ok"
    assert result.value == 150.0
    assert result.unit == "m2"


def test_req302_output_unit_mismatch_is_error() -> None:
    """Ergebnis-Einheit muss zur deklarierten Output-Einheit passen."""
    rule = load_synthetic_rule()
    output = rule["output"]
    assert isinstance(output, dict)
    output["unit"] = "m"
    result = evaluate(rule, rule_full_inputs())
    assert result.status == "error"
    assert any("Output" in line for line in result.report)


def test_req302_cross_unit_addition_in_expression_is_error() -> None:
    """Gelieferte Einheiten stimmen mit der Regel überein, widersprechen
    sich aber untereinander – der Ausdrucks-Evaluaton muss das abfangen."""
    rule = load_synthetic_rule()
    inputs_raw = rule["inputs"]
    assert isinstance(inputs_raw, list)
    second = inputs_raw[1]
    assert isinstance(second, dict)
    second["unit"] = "m"
    inputs = {
        "sia:concept/teilsflaeche-a": InputValue(100.0, "m2"),
        "sia:concept/teilsflaeche-b": InputValue(50.0, "m"),
    }
    result = evaluate(rule, inputs)
    assert result.status == "error"
    assert any("Einheitenkonflikt" in line for line in result.report)


def test_req302_scalar_multiplication_keeps_unit() -> None:
    rule = load_synthetic_rule()
    rule["expression"] = "teilsflaeche_a * 2"
    result = evaluate(rule, rule_full_inputs())
    assert result.status == "ok"
    assert result.value == 200.0
    assert result.unit == "m2"
