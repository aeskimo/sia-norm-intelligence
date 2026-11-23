# 03 – Architektur

## Schichten (Abhängigkeiten nur von oben nach unten)
```
api/          FastAPI-Endpunkte, OpenAPI
service/      Answering, Klassifikation, Compliance-Check
export/       Export: SKOS/Turtle, IDS, BCF (M7)
rules/        Regel-Engine (sichere Ausdrucksauswertung, kein eval())
knowledge/    NormStatement, SourceReference, Editions
catalog/      Concept, Property, Relation, Import CatalogSnapshot
ingest/       Normdokument → Kandidaten-Objekte (inkl. Human Review Queue, PDF-Extraktion M8)
projectdata/  IFC-/CSV-Adapter → normalisierte Projektwerte
core/         Basistypen, IDs, Schemas, Fehler
```
`core` hängt von nichts ab. `catalog` kennt `knowledge` nicht. `api` enthält keine Fachlogik.
`export` hängt nur nach unten ab (`service`, `rules`, `catalog`), niemals umgekehrt.

## Verzeichnisstruktur
```
src/sni/<modul>/        Code
schemas/                JSON-Schemas (Verträge, Quelle der Wahrheit)
data/catalog/           CatalogSnapshots (read-only)
data/norms/             NICHT im Repo – lizenzierter Normtext, lokal gemountet
data/extracted/         reviewte semantische Objekte (YAML, versioniert)
tests/unit|integration/ Tests
tests/benchmark/        Benchmark-Fälle
reports/                Eval-Ergebnisse
```

## Antwort-Pipeline (deterministisch vor generativ)
1. Frage → relevante `Concept`s identifizieren
2. Passende `NormStatement`s und `Rule`s per Strukturabfrage holen (nicht nur Vektor-Suche)
3. Falls Regel ausführbar und Inputs vorhanden → Regel berechnen → `abgeleitet`
4. Falls direkte Aussage mit verifizierter Fundstelle → `normativ_belegt`
5. LLM darf nur formulieren, nicht Fakten liefern; jede Behauptung muss auf eine Objekt-ID zeigen
6. **Verifier**: prüft jede Behauptung gegen referenzierte Objekte; scheitert die Prüfung → Klasse herabstufen
7. Kein Treffer oder Widerspruch → `nicht_eindeutig`

## API (v1)
| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/v1/concepts/{id}` | Konzept inkl. Relationen |
| GET | `/v1/statements?concept=&norm=&edition=` | Normaussagen |
| POST | `/v1/answer` | Frage → `Answer` (Schema `answer.schema.json`) |
| POST | `/v1/check` | Projektdaten + Regel-IDs → Prüfergebnisse |
| GET | `/v1/gaps` | GapReports als JSON |
| GET | `/v1/export/catalog?format=json|ttl[&snapshot=<id>]` | Katalog-Export als JSON oder Turtle/SKOS (M7) |
| POST | `/v1/export/bcf` | Prüfergebnisse `fail` → BCF-Topic-Datei (M7) |
| POST | `/v1/export/ids` | Regeln → IDS-Spezifikation, sonst GapReport (M7) |
