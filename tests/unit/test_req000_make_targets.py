"""REQ-000: `make setup|check|eval|run` existieren und laufen."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAKE_SCRIPT = ROOT / "scripts" / "make.py"


def test_req000_makefile_contains_all_targets() -> None:
    text = (ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("setup", "check", "eval", "run", "ingest", "extract"):
        assert f"{target}:" in text, f"Target {target} fehlt in der Makefile"


def test_req000_windows_make_wrapper_exists() -> None:
    # Windows hat kein natives `make`; make.cmd ist der Wrapper (REQ-000).
    assert (ROOT / "make.cmd").is_file()


def test_req000_make_script_unknown_target_fails() -> None:
    res = subprocess.run(
        [sys.executable, str(MAKE_SCRIPT), "falsch"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert res.returncode != 0
    assert "setup" in res.stdout and "check" in res.stdout
