"""Plattformuebergreifendes Make-Aequivalent: setup | check | eval | run | ingest (REQ-000/REQ-200).

Wird aufgerufen von:
- Makefile (Linux/macOS/CI)
- make.cmd (Windows ohne `make`)

Alle Targets laufen auch auf einem frisch geklonten Projekt: der virtuelle
Interpret wird bei Bedarf automatisch angelegt (ADR-0002: Python >= 3.12).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
MIN_VERSION = (3, 12)
PREFERRED_VERSIONS = ("3.12", "3.13", "3.14")
TARGETS = ("setup", "check", "eval", "run", "ingest")
PROBE_VERSION = "import sys; raise SystemExit(0 if sys.version_info >= {min_version} else 1)"
PROBE_EXECUTABLE = "import sys; print(sys.executable)"


class MakeError(RuntimeError):
    """Fehler mit nutzerfreundlicher Meldung."""


def _venv_python() -> Path:
    suffix = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return VENV_DIR / suffix


def _find_interpreter() -> str:
    """Findet ein Python >= 3.12 (ADR-0002); bevorzugt 3.12."""
    candidates: list[list[str]] = []
    if os.name == "nt" and shutil.which("py") is not None:
        candidates.extend([["py", f"-{v}"] for v in PREFERRED_VERSIONS])
    candidates.extend([[f"python{v}"] for v in PREFERRED_VERSIONS])
    candidates.extend([["python3"], ["python"]])
    for cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        probe = subprocess.run(
            [*cmd, "-c", PROBE_VERSION.format(min_version=MIN_VERSION)],
            capture_output=True,
        )
        if probe.returncode == 0:
            out = subprocess.run(
                [*cmd, "-c", PROBE_EXECUTABLE],
                capture_output=True,
                text=True,
            )
            return out.stdout.strip()
    raise MakeError("Kein Python >= 3.12 gefunden (ADR-0002). Bitte installieren.")


def ensure_venv() -> Path:
    """Liefert den venv-Interpreter; legt venv und Abhaengigkeiten bei Bedarf an."""
    py = _venv_python()
    if not py.exists():
        interpreter = _find_interpreter()
        print(f"[setup] erstelle {VENV_DIR.name} mit {interpreter}")
        subprocess.run([interpreter, "-m", "venv", str(VENV_DIR)], check=True)
        subprocess.run([str(py), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    if subprocess.run([str(py), "-c", "import sni"], capture_output=True).returncode != 0:
        print("[setup] installiere Abhaengigkeiten: pip install -e .[dev]")
        subprocess.run([str(py), "-m", "pip", "install", "-e", ".[dev]"], check=True)
    return py


def _run(args: list[str]) -> None:
    print(f"+ {' '.join(str(a) for a in args)}")
    try:
        subprocess.run(args, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        raise MakeError(f"Schritt fehlgeschlagen: {' '.join(str(a) for a in args)}") from exc


def cmd_setup() -> int:
    py = ensure_venv()
    out = subprocess.run([str(py), "--version"], capture_output=True, text=True)
    print(f"[setup] fertig: {out.stdout.strip()} in {VENV_DIR.name}/")
    return 0


def cmd_check() -> int:
    py = str(ensure_venv())
    _run([py, "-m", "ruff", "check", "."])
    _run([py, "-m", "ruff", "format", "--check", "."])
    _run([py, "-m", "mypy", "--strict", "src", "tests", "scripts"])
    _run([py, "-m", "pytest"])
    _run([py, "-m", "sni.core.schemas"])
    print("[check] alle Pruefungen bestanden")
    return 0


def cmd_eval() -> int:
    ensure_venv()
    case_files = sorted(p.name for p in (ROOT / "tests" / "benchmark").glob("*.yaml"))
    report = {
        "date": date.today().isoformat(),
        "case_files": case_files,
        "cases": 0,
        "executed": 0,
        "critical_failures": 0,
        "status": "ok",
        "note": "M0: Runner-Geruest; Auswertung echter Benchmark-Faelle ab M2 (docs/06_TESTING.md)",
    }
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    out = reports / f"eval_{date.today().isoformat()}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[eval] Report geschrieben: {out.relative_to(ROOT)}")
    return 0


def cmd_ingest(norm_id: str | None) -> int:
    py = str(ensure_venv())
    if not norm_id:
        print("make: ingest braucht eine Norm-ID: make ingest NORM=<norm-id>")
        return 2
    _run([py, "-m", "sni.ingest", norm_id])
    return 0


def cmd_run() -> int:
    py = str(ensure_venv())
    port = os.environ.get("PORT", "8000")
    print(f"+ uvicorn sni.api.main:app --port {port}")
    return subprocess.run(
        [py, "-m", "uvicorn", "sni.api.main:app", "--port", port],
        cwd=ROOT,
    ).returncode


HANDLERS: dict[str, Callable[[], int]] = {
    "setup": cmd_setup,
    "check": cmd_check,
    "eval": cmd_eval,
    "run": cmd_run,
}


def _parse_norm_arg(arg: str) -> str | None:
    """Akzeptiert '<norm-id>' oder 'NORM=<norm-id>' (make.cmd reicht %* durch)."""
    if arg.startswith("NORM="):
        return arg.removeprefix("NORM=") or None
    return arg


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] not in TARGETS:
        print(f"Verwendung: make <{' | '.join(TARGETS)}> [ingest: NORM=<norm-id>]")
        return 2
    target = args[0]
    norm_id: str | None = None
    if target == "ingest":
        if len(args) > 2:
            print("Verwendung: make ingest NORM=<norm-id>")
            return 2
        if len(args) == 2:
            norm_id = _parse_norm_arg(args[1])
    elif len(args) != 1:
        print(f"Verwendung: make {target}")
        return 2
    try:
        if target == "ingest":
            return cmd_ingest(norm_id)
        return HANDLERS[target]()
    except MakeError as exc:
        print(f"make: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"make: Schritt fehlgeschlagen (exit {exc.returncode})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
