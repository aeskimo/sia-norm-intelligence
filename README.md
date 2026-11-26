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
| Normdokument ingestieren | `make ingest NORM=<norm-id>` → Kandidaten in die Review Queue |
| PDF-Extraktion (M9, ADR-0010) | `make extract NORM=<norm-id>` → `document.draft.json` im Mount |
| LLM-Vervollständigung (M13, ADR-0010) | `make llm NORM=<norm-id>` → `document.llm.json`-Vorschlag (Konfiguration: `SNI_LLM_ENDPOINT`/`SNI_LLM_MODEL`/`SNI_LLM_API_KEY`, ADR-0003) |

**Windows ohne natives `make`:** der Wrapper `make.cmd` übernimmt dieselben Targets.
In PowerShell: `.\make.cmd <target>` (in `cmd.exe` funktioniert einfach `make <target>`).
Die Implementierung liegt in `scripts/make.py` und ist plattformübergreifend.
