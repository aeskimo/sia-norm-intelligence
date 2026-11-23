# SIA Norm Intelligence – Referenzimplementierung

Technische Referenzimplementierung, die SIA-Normen in ein semantisches Modell überführt
(Datenkatalog-Konzepte, normative Aussagen, Regeln), Normfragen mit Fundstelle und
Antwortklasse beantwortet und Projektdaten prüft.

**Für Menschen:** Start mit `docs/00_VISION.md`.
**Für LLM-Agenten:** Start zwingend mit `AGENTS.md`.

Pilotnormen: SIA 416:2003, SIA 2024:2015 (Abstimmung mit Projekt SIA-Datenkatalog).

## Befehle

| Zweck | Befehl |
|---|---|
| Setup | `make setup` |
| Alle Prüfungen | `make check` (lint + typecheck + test + schema-validate) |
| Benchmark | `make eval` → `reports/eval_<datum>.json` |
| API lokal | `make run` → http://localhost:8000/docs |

**Windows ohne natives `make`:** der Wrapper `make.cmd` übernimmt dieselben Targets.
In PowerShell: `.\make.cmd <target>` (in `cmd.exe` funktioniert einfach `make <target>`).
Die Implementierung liegt in `scripts/make.py` und ist plattformübergreifend.
