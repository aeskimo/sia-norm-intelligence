# 06 – Tests und Evaluation

## Teststufen
- `tests/unit` – reine Funktionen, keine I/O
- `tests/integration` – API, Import, Adapter mit Fixture-Daten
- `tests/benchmark` – fachliche Fälle, ausgewertet durch `make eval`

## Benchmark-Fall (Format: `tests/benchmark/*.yaml`)
Siehe `tests/benchmark/cases_example.yaml`. Benchmark-Fälle werden von **Fachpersonen**
erstellt. Der Agent darf das Format, den Runner und synthetische Struktur-Testfälle bauen,
aber keine fachlichen Sollantworten erfinden.

### Fallfelder
| Feld | Pflicht | Bedeutung |
|---|---|---|
| `id` | ja | eindeutige Fall-ID |
| `category` | ja | Kategorie (siehe Fallkategorien) |
| `question` | ja | Normfrage |
| `expected_class` | ja | erwartete Aussageklasse |
| `project_data` | nein | Concept-ID → `{value, unit}` (Calculation-Fälle) |
| `expected_rule` | nein | Regel-ID, auf der die Rechnung beruhen soll |
| `expected_sources` | nein | erwartete Fundstellen `{norm, edition, clause}` (Fundstellen-Trefferquote) |
| `expected_value` | nein | `{value, unit}` – erwartetes Ergebnis der Regelrechnung |
| `note`, `author` | nein | Metadaten |

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

## Kennzahlen (REQ-600)
`make eval` berechnet alle Kennzahlen aus `00_VISION.md` (Report:
`reports/eval_<datum>.json`); Ausgezählt werden die ausgeführten Fälle
(Platzhalter-Fälle werden gezippt, nicht gezählt):

| Kennzahl | Report-Feld | Definition | v1-Ziel |
|---|---|---|---|
| Critical Failure Rate | `critical_failure_rate` | Anteil der kritischen Fälle (oben) | 0 % |
| Aussageklassen-Genauigkeit | `class_accuracy` | Antwortklasse = erwartete Klasse | ≥ 90 % |
| Fundstellen-Trefferquote | `source_citation_accuracy` | Fälle mit `expected_class: normativ_belegt` + `expected_sources`: Antwort ist `normativ_belegt` **und** jede erwartete Fundstelle (Norm + Ausgabe + Ziffer, exakt) steht in `sources` der Antwort | ≥ 95 % |
| Korrekte Enthaltung | `correct_abstention_rate` | Fälle mit `expected_class: nicht_eindeutig`: Antwort ebenfalls `nicht_eindeutig` (begründete Enthaltung) | ≥ 90 % |
| Regelrechnung-Korrektheit | `rule_calculation_accuracy` | Deterministische Fälle (`expected_class: abgeleitet`): Antwort ist `abgeleitet`, beruht auf der erwarteten Regel (`supported_by`) und — falls `expected_value` angegeben — die M3-Engine berechnet mit den Projektdaten des Falls unabhängig vom Antwortpfad exakt diesen Wert inkl. Einheit (Toleranzen ADR-0004) | 100 % |

Anwendbarkeits-Zähler je Kennzahl: `source_citation_cases`, `abstention_cases`,
`deterministic_cases`. Nenner = 0 → Kennzahl ist `null` (nicht messbar); die
Critical Failure Rate bleibt `0.0` bei 0 ausgeführten Fällen.

## Failures (REQ-601)
Das Report-Feld `failures` listet jeden Fehlschlag (ausgeführte Fälle, bei denen
die erwartete Klasse nicht getroffen wurde) mit Fall-ID, Kategorie, erwarteter
Klasse, tatsächlicher Klasse, Critical-Flag und `details` (Begründungen,
inklusive der fehlgeschlagenen REQ-600-Prüfungen).
