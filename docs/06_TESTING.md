# 06 – Tests und Evaluation

## Teststufen
- `tests/unit` – reine Funktionen, keine I/O
- `tests/integration` – API, Import, Adapter mit Fixture-Daten
- `tests/benchmark` – fachliche Fälle, ausgewertet durch `make eval`

## Benchmark-Fall (Format: `tests/benchmark/*.yaml`)
Siehe `tests/benchmark/cases_example.yaml`. Benchmark-Fälle werden von **Fachpersonen**
erstellt. Der Agent darf das Format, den Runner und synthetische Struktur-Testfälle bauen,
aber keine fachlichen Sollantworten erfinden.

## Fallkategorien (Zielverteilung)
| Kategorie | Anteil | Zweck |
|---|---|---|
| definition | 30 % | direkte Begriffsfragen |
| dependency | 20 % | bedingte Zuordnungen |
| calculation | 15 % | Regel + Projektdaten |
| ambiguous | 15 % | korrekte Antwort ist `nicht_eindeutig` |
| trap | 10 % | falsche Ausgabe, Verweis auf andere Norm |
| adversarial | 10 % | Frage unterstellt nicht existierende Normaussage |

## Critical Failure
Ein Fall ist critical, wenn die Antwort fachlich falsch ist **und** als `normativ_belegt`
klassifiziert wurde. Jeder Critical Failure bricht `make eval` mit Exit-Code ≠ 0 ab.
