"""REQ-300: Regeln werden aus rule.schema.json geladen (validiert, atomar)
und ohne eval() ausgewertet."""

import json
from pathlib import Path

import pytest

from sni.rules.engine import RuleLoadError, evaluate, load_rules
from tests.conftest import load_synthetic_rule, rule_full_inputs

RULE_ID = "sia:rule/syn1-2020/gf-summe"
RULE_FILE = "sia_rule_syn1-2020_gf-summe.json"


def _write_rule(rules_dir: Path, rule: dict[str, object], name: str = RULE_FILE) -> None:
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / name).write_text(
        json.dumps(rule, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_req300_loads_valid_rule(tmp_path: Path) -> None:
    _write_rule(tmp_path, load_synthetic_rule())
    rules = load_rules(tmp_path)
    assert len(rules) == 1
    assert rules[0]["id"] == RULE_ID


def test_req300_missing_directory_returns_empty(tmp_path: Path) -> None:
    assert load_rules(tmp_path / "keine-verzeichnisse") == []


def test_req300_invalid_rule_collects_all_errors(tmp_path: Path) -> None:
    rule = load_synthetic_rule()
    del rule["expression"]  # Pflichtfeld fehlt
    rule["inputs"] = "kein-array"  # falscher Typ
    _write_rule(tmp_path, rule)
    with pytest.raises(RuleLoadError) as excinfo:
        load_rules(tmp_path)
    assert len(excinfo.value.report) >= 2


def test_req300_id_filename_mismatch_rejected(tmp_path: Path) -> None:
    rule = load_synthetic_rule()
    rule["id"] = "sia:rule/syn1-2020/andere-regel"
    _write_rule(tmp_path, rule)
    with pytest.raises(RuleLoadError, match="passt nicht"):
        load_rules(tmp_path)


def test_req300_invalid_file_rejects_whole_load(tmp_path: Path) -> None:
    """Atomar: eine fehlerhafte Datei verdirbt die gesamte Ladung (KBOB)."""
    _write_rule(tmp_path, load_synthetic_rule())
    broken = load_synthetic_rule()
    del broken["derived_from"]
    broken["id"] = "sia:rule/syn1-2020/broken"
    _write_rule(tmp_path, broken, name="sia_rule_syn1-2020_broken.json")
    with pytest.raises(RuleLoadError):
        load_rules(tmp_path)


def test_req300_unknown_identifier_in_expression_is_error() -> None:
    rule = load_synthetic_rule()
    rule["expression"] = "teilsflaeche_a + unbekannt"
    result = evaluate(rule, rule_full_inputs())
    assert result.status == "error"
    assert any("unbekannt" in line for line in result.report)


def test_req300_load_and_evaluate_end_to_end(tmp_path: Path) -> None:
    _write_rule(tmp_path, load_synthetic_rule())
    rules = load_rules(tmp_path)
    result = evaluate(rules[0], rule_full_inputs())
    assert result.status == "ok"
    assert result.value == 150.0
    assert result.unit == "m2"
