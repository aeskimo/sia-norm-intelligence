# AGENTS.md – Arbeitsanweisung für autonome Coding-Agenten

Diese Datei ist der verbindliche Einstiegspunkt. Lies sie vollständig, bevor du Code schreibst.
Bei Widersprüchen gilt: `docs/07_GUARDRAILS.md` > `AGENTS.md` > `docs/04_DATA_MODEL.md` > übrige Dokumente.

## 1. Mission (ein Satz)
Baue ein System, das Normtext in versionierte, quellengebundene semantische Objekte zerlegt
und daraus Normfragen so beantwortet, dass jede Antwort ihre Fundstelle und ihre Aussageklasse
nachweist – und niemals mehr Sicherheit behauptet, als die Quelle hergibt.

## 2. Lesereihenfolge
1. `docs/07_GUARDRAILS.md` – harte Grenzen (zuerst!)
2. `docs/00_VISION.md` – Zweck, Scope, Non-Goals
3. `docs/02_GLOSSARY.md` – Begriffe; verwende exakt diese Bezeichnungen im Code
4. `docs/04_DATA_MODEL.md` + `schemas/` – Verträge; Schemas sind die Wahrheit
5. `docs/03_ARCHITECTURE.md` – Module und Abhängigkeitsrichtung
6. `docs/05_MILESTONES.md` – was als Nächstes zu tun ist
7. `docs/06_TESTING.md` – wie „fertig" nachgewiesen wird
8. `docs/adr/` – bereits getroffene Entscheidungen; nicht erneut diskutieren
9. `docs/08_REFERENCES.md` – externe Referenzprojekte (KBOB, AEC-OSS-Directory);
   konsultieren bei M5 (IFC) und M7 (Export)

## 3. Arbeitsschleife (immer gleich)
1. Lies `PROGRESS.md` und bestimme den ersten offenen Milestone in `docs/05_MILESTONES.md`.
2. Zerlege ihn in Tasks ≤ ca. 200 geänderte Zeilen.
3. Schreibe zuerst Tests aus den Akzeptanzkriterien (Given/When/Then), dann den Code.
4. Führe `make check` aus. Erst bei grün weiter.
5. Aktualisiere `PROGRESS.md` (was erledigt, welche Akzeptanzkriterien erfüllt, Messwerte).
6. Commit mit Präfix `[M<nr>] <REQ-ID> kurze Beschreibung`.

## 4. Befehle
| Zweck | Befehl |
|---|---|
| Setup | `make setup` |
| Alle Prüfungen | `make check` (lint + typecheck + test + schema-validate) |
| Benchmark | `make eval` → schreibt `reports/eval_<datum>.json` |
| API lokal | `make run` → http://localhost:8000/docs |

Wenn ein Befehl noch nicht existiert: Erstelle ihn als Teil von M0.

## 5. Stack (fest, siehe ADR-0002)
Python 3.12, FastAPI, Pydantic v2, SQLite (später PostgreSQL), pytest, ruff, mypy --strict,
jsonschema, ifcopenshell (ab M5). Keine weiteren Laufzeit-Abhängigkeiten ohne neue ADR.

## 6. Definition of Done (für jeden Task)
- [ ] Alle Akzeptanzkriterien des Requirements haben einen Test mit der REQ-ID im Namen
- [ ] `make check` grün, Coverage für `src/core` ≥ 90 %
- [ ] Jedes neue Datenobjekt validiert gegen sein JSON-Schema
- [ ] Keine Norminhalte erfunden (siehe Guardrails G1–G3)
- [ ] `PROGRESS.md` aktualisiert

## 7. Wann du STOPPEN und fragen musst
Schreibe einen Eintrag in `OPEN_QUESTIONS.md` (Format dort) und arbeite an einem anderen,
nicht blockierten Task weiter, wenn:
- eine fachliche Bedeutung eines Normbegriffs unklar ist
- eine Klassifikation (Datenkatalog vs. Normaussage vs. Regel) nicht eindeutig ist
- ein Schema geändert werden müsste
- eine Entscheidung eine bestehende ADR verletzen würde
- Testdaten fehlen

Rate niemals fachliche Inhalte. Eine offene Frage ist ein gültiges Ergebnis.

## 8. Verboten
- Normtext, Zahlenwerte, Formeln oder Fundstellen aus dem eigenen Modellwissen ergänzen
- Tests abschwächen oder löschen, um sie grün zu bekommen
- Schemas in `schemas/` ohne ADR ändern
- Antwortklasse `normativ_belegt` vergeben ohne verifizierte `SourceReference`
- Lizenzierte Normtexte in Logs, Fixtures, Commits oder externe Dienste schreiben
