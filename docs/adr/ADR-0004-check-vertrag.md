# ADR-0004: Check-Antwort-Vertrag und pass/fail-Semantik (M5)
- Status: akzeptiert
- Datum: 2026-11-23
- Kontext: REQ-501 (`POST /v1/check`) braucht (1) einen stabilen
  Antwort-Vertrag – die Definition of Done (AGENTS.md §6) verlangt, dass
  jedes neue Datenobjekt gegen ein JSON-Schema validiert wird, und (2)
  eine definierte pass/fail-Semantik – `rule.schema.json` kennt kein
  Vergleichs- oder Grenzwertfeld, und die M3-Ausdrucks-Sprache keine
  Bedingungen. Offene Fragen: OQ-004 (Vertrag), OQ-005 (Semantik).
- Entscheidung:
  1. **Vertrag** (OQ-004, Option A): Neues Schema
     `schemas/check_result.schema.json` (`$id: sni:check_result`,
     Draft 2020-12). `POST /v1/check` liefert ein Objekt mit
     `checks`, `gaps`, `disclaimer`:
     - `checks`: pro `approved` Regel (G3) ein Eintrag mit `rule_id`,
       `status` (`pass` | `fail` | `insufficient_data`), `reason`
       (Begründung, REQ-501), `value` (abgeleiteter Wert, `null` wenn
       nicht berechenbar), `claimed` (gelieferter Output-Wert, `null`
       wenn nicht geliefert), `unit` (Einheit des abgeleiteten Werts),
       `missing_inputs` (nur bei `insufficient_data` befüllt) und
       `derived_from` (NormStatement-IDs = Fundstelle der Regel).
     - `gaps`: GapReports `missing_project_data` (REQ-502, referenziert
       via `$ref` auf `gap_report.schema.json`).
     - `disclaimer`: Pflichtfeld (G6).
     Die API ist stateless: GAP-IDs werden pro Antwort fortlaufend ab
     `GAP-0001` vergeben. Persistenz mit stabilen IDs (z. B. Review
     Queue) gehört zu M7 (REQ-702, BCF-Export).
  2. **Semantik** (OQ-005, Option A): Konsistenzprüfung. Das Projekt
     liefert die Pflicht-Inputs der Regel und einen Wert für das
     Output-Konzept; die M3-Engine (REQ-300/301/302) leitet den Wert ab:
     - abgeleitet = geliefert (Vergleich via `math.isclose`,
       `rel_tol=1e-6`, `abs_tol=1e-9`) → `pass`
     - abgeleitet ≠ geliefert → `fail`
     - Pflicht-Input fehlt, oder optionaler Input ist im Ausdruck
       referenziert aber nicht geliefert, oder kein Output-Wert
       geliefert → `insufficient_data` (mit Liste der fehlenden
       Concept-IDs)
     - Engine-Fehler (Einheitenkonflikt, Ausdrucksdefekt) → `fail` mit
       dem Engine-Bericht als Begründung: die Daten sind geliefert,
       aber nicht mit der Regel vereinbar.
     - Einheitenkonflikt des gelieferten Output-Werts (geliefert ≠
       deklariert) → `fail`.
  3. **Keine Grenzwertprüfung in v1**: `pass` besagt, dass die
     Projektdaten konsistent mit der Regel sind – nicht, dass sie
     normkonform sind. Constraint-/Grenzwertfelder in `rule.schema.json`
     (OQ-005 Option B, z. B. `gesamtflaeche <= 5000`) sind ein
     Follow-up-ADR und greifen, sobald Grenzwert-Regeln fachlich
     konkret werden.
- Konsequenzen:
  + stabiler, versionierbarer Vertrag, den REQ-702 (BCF-Export von
    `fail`) direkt verwenden kann
  + DoD erfüllt: Check-Resultat wird im Service gegen
    `check_result.schema.json` validiert
  + nur bestehende Module werden wiederverwendet (M3-Engine,
    REQ-502-Gap-Funktion); keine Schema-Änderung an `rule.schema.json`
  − `pass` darf nicht als "normkonform" missverstanden werden
    (Disclaimer + Dokumentation der Limitation)
  − die Vergleichstoleranz (1e-6/1e-9) ist ein ADR-Wert für
    Gleitkomma-Arithmetik, keine Normzahl
  − `applicability`-Felder von Regeln werden weiterhin nicht
    ausgewertet (Limitation aus M3, unverändert)
- Verworfene Alternativen:
  - OQ-004 B: Laufzeit-Objekt ohne Schema – verstösst gegen die DoD
    und gibt REQ-702 keinen stabilen Export-Vertrag.
  - OQ-005 B: Constraint-Feld in `rule.schema.json` – fachlich die
    stärkere Prüfung, aber ohne konkrete Grenzwert-Regeln nur
    Spekulation; als Follow-up-ADR vorbereitet.
  - OQ-005 C: `pass` = Engine lief fehlerfrei – zu schwach, keine
    fachliche Prüfung, würde mehr Sicherheit behaupten, als die Daten
    hergeben (Mission).
