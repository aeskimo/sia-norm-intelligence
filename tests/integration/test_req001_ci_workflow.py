"""REQ-001: CI-Pipeline führt `make check` bei jedem Commit aus."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_req001_ci_workflow_exists_and_runs_make_check() -> None:
    assert WORKFLOW.is_file()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "make check" in text


def test_req001_ci_triggers_on_push_and_pull_request() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in text
    assert "pull_request:" in text


def test_req001_ci_uses_python_3_12() -> None:
    # ADR-0002: Python 3.12.
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "3.12" in text
