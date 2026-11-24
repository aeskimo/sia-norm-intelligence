"""REQ-002: Alle Dateien in /schemas sind gültige JSON-Schemas (Draft 2020-12)."""

import json
from pathlib import Path

from sni.core.schemas import main, schema_files, validate_all, validate_schema_file

DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"

EXPECTED = {
    "answer.schema.json",
    "catalog_item.schema.json",  # M8.2 (09 §6.2)
    "check_result.schema.json",
    "concept.schema.json",
    "document_draft.schema.json",  # M9, ADR-0010
    "gap_report.schema.json",
    "job.schema.json",  # M8.2 (09 §6.2)
    "local_document.schema.json",  # M8.2 (09 §6.2)
    "norm_statement.schema.json",
    "project_values.schema.json",
    "rule.schema.json",
    "source_reference.schema.json",
    "status.schema.json",
}


def test_req002_all_schema_files_valid_draft_2020_12() -> None:
    files = schema_files()
    assert len(files) == len(EXPECTED)
    assert validate_all() == []


def test_req002_all_expected_schemas_present() -> None:
    names = {p.name for p in schema_files()}
    assert names == EXPECTED


def test_req002_invalid_json_is_rejected(tmp_path: Path) -> None:
    p = tmp_path / "broken.schema.json"
    p.write_text("{", encoding="utf-8")
    errors = validate_schema_file(p)
    assert any("JSON" in e for e in errors)


def test_req002_non_object_schema_is_rejected(tmp_path: Path) -> None:
    p = tmp_path / "list.schema.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    errors = validate_schema_file(p)
    assert any("Objekt" in e for e in errors)


def test_req002_wrong_draft_is_rejected(tmp_path: Path) -> None:
    p = tmp_path / "draft07.schema.json"
    p.write_text(
        json.dumps({"$schema": "http://json-schema.org/draft-07/schema#", "type": "string"}),
        encoding="utf-8",
    )
    errors = validate_schema_file(p)
    assert any("Draft 2020-12" in e for e in errors)


def test_req002_invalid_meta_schema_is_rejected(tmp_path: Path) -> None:
    p = tmp_path / "badmeta.schema.json"
    p.write_text(
        json.dumps({"$schema": DRAFT_2020_12, "type": "nonsense"}),
        encoding="utf-8",
    )
    errors = validate_schema_file(p)
    assert any("2020-12" in e for e in errors)


def test_req002_main_reports_failure_for_bad_dir(tmp_path: Path) -> None:
    (tmp_path / "bad.schema.json").write_text(
        json.dumps({"$schema": DRAFT_2020_12, "type": "nonsense"}),
        encoding="utf-8",
    )
    assert main(schemas_dir=tmp_path) == 1


def test_req002_main_reports_success_for_real_dir() -> None:
    assert main() == 0
