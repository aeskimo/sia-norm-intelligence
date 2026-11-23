"""REQ-300: Ausdrucks-Sprache wird ohne eval() ausgewertet (Parser/Evaluator)."""

import pathlib

import pytest

from sni.rules.expression import (
    ExpressionError,
    ExpressionValue,
    evaluate_expression,
    identifiers_in,
)


def _v(value: float, unit: str | None = None) -> ExpressionValue:
    return ExpressionValue(value, unit)


def test_req300_arithmetic_precedence() -> None:
    assert evaluate_expression("2 + 3 * 4", {}) == _v(14.0)
    assert evaluate_expression("(2 + 3) * 4", {}) == _v(20.0)


def test_req300_unary_minus() -> None:
    assert evaluate_expression("-2 + 5", {}) == _v(3.0)
    assert evaluate_expression("-(2 + 3)", {}) == _v(-5.0)


def test_req300_division_and_floats() -> None:
    assert evaluate_expression("10 / 4", {}) == _v(2.5)
    assert evaluate_expression("3.5 * 2", {}) == _v(7.0)


def test_req300_identifier_bindings() -> None:
    bindings = {"a": _v(3.0, "m2"), "b": _v(4.0, "m2")}
    assert evaluate_expression("a + b", bindings) == _v(7.0, "m2")


def test_req300_division_by_zero_raises() -> None:
    with pytest.raises(ExpressionError, match="Division durch Null"):
        evaluate_expression("1 / 0", {})


def test_req300_unknown_identifier_raises() -> None:
    with pytest.raises(ExpressionError, match="unbekannter Identifier"):
        evaluate_expression("a + b", {"a": _v(1.0)})


def test_req300_syntax_errors_raise() -> None:
    for text in ("", "2 +", "(2 + 3", "2 3", "a @ b"):
        with pytest.raises(ExpressionError):
            evaluate_expression(text, {})


def test_req300_unit_conflict_on_plus_raises() -> None:
    with pytest.raises(ExpressionError, match="Einheitenkonflikt"):
        evaluate_expression("a + b", {"a": _v(1.0, "m2"), "b": _v(1.0, "m")})


def test_req300_scalar_plus_quantity_keeps_unit() -> None:
    assert evaluate_expression("a + 2", {"a": _v(3.0, "m2")}) == _v(5.0, "m2")


def test_req300_multiplication_with_scalar_propagates_unit() -> None:
    assert evaluate_expression("a * 2", {"a": _v(3.0, "m2")}) == _v(6.0, "m2")


def test_req300_multiplication_two_quantities_raises() -> None:
    with pytest.raises(ExpressionError, match="abgeleitete Einheiten"):
        evaluate_expression("a * b", {"a": _v(3.0, "m2"), "b": _v(2.0, "m")})


def test_req300_identifiers_in_expression() -> None:
    assert identifiers_in("a + b * a") == ["a", "b"]
    assert identifiers_in("(2 + 3) * 4") == []


def test_req300_no_eval_in_rules_sources() -> None:
    """REQ-300: Auswertung ohne eval()/exec() – AST-Prüfung als Guardrail.

    Das AST erfasst echte Aufrufe von ``eval``/``exec``, unabhängig von
    Erwähnungen in Dokstrings oder Kommentaren.
    """
    import ast

    src_dir = pathlib.Path(__file__).resolve().parents[2] / "src" / "sni" / "rules"
    for path in sorted(src_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("eval", "exec")
        ]
        assert not offenders, f"{path.name} ruft eval/exec auf (Zeilen {offenders})"
