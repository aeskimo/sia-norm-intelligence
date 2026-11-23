# ADR-0005: Export-Design für M7 (SKOS/Turtle, IDS, BCF)
- Status: akzeptiert
- Datum: 2026-11-23
- Kontext: M7 (REQ-700/701/702) macht die Systemobjekte an
  branchenübliche Zielformate angebbar: Katalog-Concepts als
  JSON/Turtle (SKOS), Regeln als IDS-Spezifikationen,
  Prüfergebnisse `fail` als BCF-Topics. Offene Fragen: OQ-006
  (Modulstruktur, Abhängigkeiten, Endpunkte), OQ-007 (SKOS-
  Mapping, Namespaces), OQ-008 (Abbildkriterium für IDS).
  Zielformate wurden vor dieser Entscheidung verifiziert: BCF
  2.1 (buildingSMART/BCF-XML, Branch `release_2_1`, markup.xsd),
  IDS 1.0 (buildingSMART/IDS, Tag `v1.0.0`, ids.xsd), KBOB
  natdd-core.ttl (CC0) als Turtle-Stil-Vorbild.
- Entscheidung:
  1. **Modulstruktur und Abhängigkeiten** (OQ-006, Option A):
     Keine neuen Laufzeit-Abhängigkeiten (ADR-0002 bleibt
     unverändert). Neues Modul `src/sni/export/` mit
     handgeschriebenen Serialisierern `skos.py` (REQ-700),
     `ids.py` (REQ-701), `bcf.py` (REQ-702); stdlib-only
     (`json`, `zipfile`, `xml.etree.ElementTree`). Die neue
     Schicht `export` liegt zwischen `service` und `rules`
     (03_ARCHITECTURE.md entsprechend aktualisiert). `api/`
     enthält keine Fachlogik und verdrahtet nur die drei
     Endpunkte.
  2. **Endpunkte** (OQ-006, Option A):
     - `GET /v1/export/catalog?format=json|ttl[&snapshot=<id>]`
       (REQ-700): `json` → Objekt `{"concepts": [...],
       "disclaimer"}` mit schemakonformen Concepts, optional
       auf einen Snapshot beschränkt; `ttl` → Turtle-Dokument
       (Mapping nach Punkt 3) mit G6-Disclaimer als
       Kommentarzeile. Unbekannte `format`- oder `snapshot`-
       Werte → 400.
     - `POST /v1/export/bcf` (REQ-702): Body wie `POST
       /v1/check` (CheckPayload). Der Endpoint ruft den
       Check-Service intern auf (approved Regeln, G3) und
       exportiert nur `fail`-Ergebnisse als BCF-Topics.
       Response: binäre `.bcf`-Datei (ZIP,
       `application/octet-stream`,
       `Content-Disposition: attachment`), bestehend aus
       `bcf.version` (`VersionId 2.1`) und je Topic
       `<guid>/markup.bcf`. Ohne `fail`-Ergebnisse enthält die
       Datei nur `bcf.version` (keine Topics).
     - `POST /v1/export/ids` (REQ-701): Body
       `{"rule_ids": [...]}`; leer = alle approved Regeln.
       Response JSON: `{"ids_xml": <string|null>, "gaps":
       [GapReport], "disclaimer"}`. `ids_xml` ist der komplette
       XML-Inhalt einer `.ids`-Datei (eine Datei für alle
       abbildbaren Regeln); `null`, wenn keine Regel abbildbar
       ist (IDS verlangt mindestens eine Specification).
       Unbekannte `rule_ids` oder nicht-approved Regeln → 400
       (G3).
  3. **SKOS/Turtle-Mapping** (OQ-007, Option A):
     Standardvokabular, wo 1:1-Semantik besteht, sonst `sni:`:
     - name → `skos:prefLabel` (sprachgetaggt @de/@fr/@it)
     - definition → `skos:definition` (sprachgetaggt)
     - abbreviation → `skos:altLabel`
     - specialization_of → `skos:broader`
     - part_of → `dcterms:isPartOf`; has_part → `dcterms:hasPart`
     - derived_from → `prov:wasDerivedFrom`
     - related_to → `skos:related`
     - unit → `sni:unit`; quantity_type → `sni:quantityType`
     - mappings → `sni:mappings` auf einen Blank-Node mit je
       einer Property pro Key (z. B. `sni:ifc`)
     - catalog_snapshot → `sni:catalogSnapshot`

     Namespaces (provisorisch; Migrations-Policy gemäss
     KBOB-Vorbild: IRIs dürfen sich ändern, Versionierung
     läuft über neue Snapshots): `sia:` →
     `https://sia-norm-intelligence.dev/sia/` (Concept-IDs wie
     `sia:concept/x` sind dadurch IRIs), `sni:` →
     `https://sia-norm-intelligence.dev/ns/`. Je Snapshot ein
     `skos:ConceptScheme` (IRI = Snapshot-ID unter dem `sia:`-
     Präfix) mit `dcterms:title`; Concepts tragen
     `skos:inScheme`. Relation-Ziele, die nicht im Export
     enthalten sind, werden als IRI geschrieben (hängende
     Referenzen sind in RDF zulässig).
  4. **BCF-Topic-Inhalt** (REQ-702, BCF 2.1): Je `fail`-
     Ergebnis ein Topic mit deterministischem
     `Guid = uuid5(NAMESPACE_URL, rule_id)`. Pflichtfelder:
     `Title` = Rule-ID, `CreationDate` (UTC, Exportzeitpunkt),
     `CreationAuthor` = `sni@localhost`. `Description` enthält
     `reason`, Fundstelle (`derived_from`), `value`/`claimed`/
     `unit` und den G6-Disclaimer. Keine Viewpoints, keine
     `project.bcfp` (beide optional in 2.1; kein
     Geodaten-/Projektbezug vorhanden). `pass` und
     `insufficient_data` werden nicht exportiert.
  5. **IDS-Abbildkriterium** (OQ-008, Option A): Eine Regel
     ist "abbildbar", wenn jedes Input-Concept UND das
     Output-Concept im Katalog einen Eintrag `mappings.ifc` in
     der Form `{"entity": "…", "property_set": "…",
     "base_name": "…"}` (Dreier-Tupel, IFC4) trägt. Je
     abbildbarer Regel ein `<specification ifcVersion="IFC4"
     name=<Rule-ID> identifier=<Rule-ID> description=…
     instructions=…>`:
     - applicability: entity-Facet (`<entity><name>`) des
       Output-Concepts
     - requirements: je Input- und Output-Concept ein
       property-Facet (`propertySet` + `baseName`,
       cardinality `required`)
     - expression, applicability-Text, Fundstelle
       (`derived_from`) und G6-Disclaimer in `description` /
       `instructions` (menschenlesbar; in IDS 1.0 nicht
       maschinenprüfbar)

     Alle übrigen approved Regeln (fehlendes oder unvollständiges
     ifc-Mapping, Concept nicht im Katalog) → GapReport
     `not_ids_expressible` (target_layer `mapping`,
     evidence `[Rule-ID]`, description benennt die betroffenen
     Concepts). Keine Teilabbildung: eine nicht vollständig
     abbildbare Regel wird nicht teilweise exportiert (G5).
     `<info>` trägt Titel, Version und Beschreibung mit
     Disclaimer; `author` wird nicht gesetzt (das XSD-
     E-Mail-Muster wäre eine Erfindung).
- Konsequenzen:
  + keine neuen Laufzeit-Abhängigkeiten (ADR-0002)
  + stabile Export-Verträge aus bestehenden Schemas (concept,
    rule, gap_report, check_result) – keine Schema-Änderungen
  + REQ-701 läuft ohne Schemaänderung (gap_report.schema.json
    kennt `not_ids_expressible` + target_layer `mapping`)
  + BCF-Export baut direkt auf dem ADR-0004-Vertrag
    (`fail` + `reason` + `derived_from`)
  + deterministische BCF-Guids (uuid5) → vergleichbare Dateien
  − Namespaces sind provisorisch (Migration bei Domain-Wechsel;
    Policy dokumentiert)
  − expression/applicability/derived_from sind in IDS nur
    menschenlesbar, nicht maschinenprüfbar (Limitation von IDS
    1.0)
  − BCF ohne Viewpoints: Topics sind im 3D-Kontext nicht
    verortbar (bekannte Limitation v1)
- Verworfene Alternativen:
  - OQ-006 B: RDF-Bibliothek (z. B. rdflib) – neue
    Laufzeit-Abhängigkeit unzulässig ohne ADR-Änderung
    (AGENTS.md §5); die Konstruktmenge ist klein genug für
    handgeschriebenen Output.
  - OQ-007 B: Minimales SKOS-Subset ohne PROV-O/Dublin Core –
    würde die 1:1-Semantiken (has_part, derived_from) verwerfen
    und widerspricht 08_REFERENCES.md Punkt 4
    (Standardvokabular wiederverwenden).
  - OQ-008 B: Teilabbildung einzelner Facets pro Regel –
    behauptet mehr Maschinenprüfbarkeit, als die Daten hergeben
    (Mission, G5); C: v1 komplett ohne IDS-Abbild – REQ-701
    hätte dann keinen positiven Pfad.
