# PROGRESS

| Datum | Milestone | REQ-IDs | Status | Messwerte / Notizen |
|---|---|---|---|---|
| 2026-11-23 | M0 | REQ-000, REQ-001, REQ-002 | fertig | `make check` grün: ruff (check + format), mypy --strict (16 Dateien), 15/15 Tests, 6 Schemas validiert (Draft 2020-12). Coverage `src/sni/core`: 97.5 % (≥ 90 %). `make eval` schreibt `reports/eval_2026-11-23.json`. `make run`: Smoke-Test `/healthz`, `/docs`, `/openapi.json` OK. Hinweis: Windows ohne natives `make` → Wrapper `make.cmd` (PowerShell: `.\make.cmd <target>`, cmd: `make <target>`); CI nutzt `make` (Python 3.12, ADR-0002). |
