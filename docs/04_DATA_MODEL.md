# 04 – Datenmodell

Quelle der Wahrheit sind die JSON-Schemas in `/schemas`. Dieses Dokument erklärt sie.

## Identifikatoren (Namespace-Prinzip)
Format: `<namespace>:<typ>/<slug>[@<version>]`
- `sia:concept/geschossflaeche`
- `sia:statement/sia416-2003/<ziffer>/<laufnr>`
- `sia:rule/sia416-2003/gf-summe`
IDs sind unveränderlich. Änderungen erzeugen neue Versionen, nie Überschreibungen.

## Kernobjekte und Verantwortung
| Objekt | Schema | Erstellt durch | Freigabe durch |
|---|---|---|---|
| Concept, Property, Relation | `concept.schema.json` | Import CatalogSnapshot | Datenkatalog-Projekt |
| NormStatement | `norm_statement.schema.json` | Ingest (Agent) als `candidate` | Fachreview (Mensch) |
| Rule | `rule.schema.json` | Agent als `candidate` | Fachreview (Mensch) |
| Answer | `answer.schema.json` | Service zur Laufzeit | – |
| GapReport | `gap_report.schema.json` | Agent/Teams | Interface Board |
| DocumentDraft (Arbeitsdatei) | `document_draft.schema.json` | `extract` (Maschine) als Entwurf | Fachperson (Stufe 2, manuell) |

`DocumentDraft` ist eine lokale Arbeitsdatei (`data/norms/<norm-id>/document.draft.json`,
M8/ADR-0006): enthält extrahierten Normtext und kommt deshalb **nie ins Repo** (G4).
Die Maschine belegt nur Ziffern-Skelett und Text (G1); die Fachfelder bleiben bis zur
manuellen Vervollständigung leer.

## Lebenszyklus `review_status`
`candidate` → `reviewed` → `approved` | `rejected`
Nur `approved`-Objekte dürfen zur Klasse `normativ_belegt` führen.
Der Agent darf `candidate` erzeugen, aber **nie** selbst `approved` setzen.

## Aussageklassen – Vergaberegeln
| Klasse | Bedingung (alle müssen erfüllt sein) |
|---|---|
| `normativ_belegt` | ≥1 `approved` NormStatement, Fundstelle verifiziert, Antwort sagt nicht mehr als die Aussage |
| `abgeleitet` | Ergebnis aus `approved` Rule berechnet, alle Inputs nachgewiesen |
| `fachliche_interpretation` | Kein direkter Beleg; Antwort stützt sich auf Kontext; explizit als Interpretation markiert |
| `projektfestlegung` | Antwort hängt von einer ProjectDecision ab, die nicht in der Norm steht |
| `nicht_eindeutig` | Kein Beleg, Widerspruch, fehlende Inputs oder Verifier gescheitert |

Bei Zweifel immer die schwächere Klasse wählen.

## Mehrsprachigkeit
Alle Benennungen als Objekt `{ "de": "...", "fr": "...", "it": "...", "en": "..." }`, `de` Pflicht.
