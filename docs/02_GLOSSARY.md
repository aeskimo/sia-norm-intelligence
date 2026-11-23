# 02 – Glossar (verbindliche Bezeichner)

Im Code werden die englischen Bezeichner verwendet, in Doku und UI die deutschen.

| Deutsch | Code | Bedeutung | Gehört in |
|---|---|---|---|
| Konzept | `Concept` | Fachlicher Begriff mit stabiler Bedeutung unabhängig von einer konkreten Anforderung (z. B. Geschossfläche) | Datenkatalog |
| Merkmal | `Property` | Messbare/benennbare Eigenschaft eines Konzepts, mit Datentyp und Einheit | Datenkatalog |
| Beziehung | `Relation` | Typisierte Verbindung zwischen Konzepten (`part_of`, `specialization_of`, `derived_from`, …) | Datenkatalog |
| Werteliste | `ValueList` | Zulässige Werte eines Merkmals | Datenkatalog |
| Normaussage | `NormStatement` | Was eine bestimmte Norm in einer bestimmten Ausgabe an einer Fundstelle über Konzepte aussagt | Normwissen |
| Regel | `Rule` | Maschinenausführbare Form einer Normaussage (Formel, Bedingung, Grenzwert) | Regelmodell |
| Fundstelle | `SourceReference` | Norm-ID, Ausgabe, Ziffer, ggf. Tabelle/Formel-Nr. | Provenienz |
| Ausgabe | `Edition` | Konkrete Version einer Norm (z. B. 2003) | Provenienz |
| Aussageklasse | `AnswerClass` | `normativ_belegt`, `abgeleitet`, `fachliche_interpretation`, `projektfestlegung`, `nicht_eindeutig` | Service |
| Projektfestlegung | `ProjectDecision` | Wert/Entscheid, der im Projekt getroffen wird, nicht in der Norm | Projektdaten |
| Gap-Meldung | `GapReport` | Strukturierte Rückmeldung an das Datenkatalog-Projekt | Schnittstelle |
| Katalog-Snapshot | `CatalogSnapshot` | Eingefrorener, versionierter Ausschnitt des Datenkatalogs | Datenkatalog |
| Namespace | `namespace` | Präfix zur eindeutigen Identifikation, z. B. `sia:` | alle |

## Entscheidungsregel für die Klassifikation extrahierter Information
1. „Was ist das?" → `Concept` / `Property` / `Relation`
2. „Was sagt Norm X Ausgabe Y dazu?" → `NormStatement`
3. „Wie wird es berechnet oder geprüft?" → `Rule`
4. „Wird es im Projekt entschieden?" → `ProjectDecision`
Nicht eindeutig → `OPEN_QUESTIONS.md`, nicht raten.
