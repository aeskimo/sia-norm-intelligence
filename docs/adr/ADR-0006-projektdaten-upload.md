# ADR-0006: Projektdaten-Upload-Endpunkt (CSV/IFC) (Integration M3.5)
- Status: akzeptiert
- Datum: 2026-11-23
- Kontext: REQ-500 ist auf Adapter-Ebene umgesetzt und getestet
  (`sni/projectdata/csv_adapter.py`, `sni/projectdata/ifc_adapter.py`,
  normalisierte `ProjectValue`s mit Herkunft). Die Java-Client-App
  (SIA-Normenassistent) läuft ohne Laufzeit-Abhängigkeiten (reines `javac`)
  und kann IFC-Modelle nicht parsen (dafür bräuchte sie `ifcopenshell`);
  ein Dateizeugriff auf der API-Seite ist daher der einzige Weg, IFC
  (und CSV aus Fremdquellen) in die Prüfpipeline zu bringen.
  `ifcopenshell` ist bereits Laufzeit-Abhängigkeit (ADR-0002).
  Der Server ist loopback-only gebunden (G4); der Upload-Endpunkt öffnet
  keine neue Netzfläche. Offene Fragen: OQ-005 (pass/fail-Semantik) bleibt
  unberührt – dieser Endpunkt liefert nur normalisierte Werte, keine
  Prüfung.
- Entscheidung:
  1. **Endpunkt**: `POST /v1/projectdata` (multipart/form-data). Feld
     `file` (Datei: `.csv` oder `.ifc`); optional `quantity_mapping`
     (JSON-Objekt `{Mengen-Name: Concept-ID}`) für IFC-Modelle.
  2. **Format-Erkennung** ausschliesslich per Dateierweiterung
     (`.csv`, `.ifc`, case-insensitiv); jede andere Endung wird abgelehnt
     (G5: nie raten, z. B. keine Inhalts-Inspektion).
  3. **IFC-Mapping**: explizit im Request oder, bei fehlendem Feld, aus
     dem lokalen Katalog abgeleitet (Concepts mit
     `mappings.ifc.base_name` → `{base_name: concept_id}`). Kein Mapping
     möglich und keines übergeben → 400 (G5). CSV braucht kein Mapping
     (Concept-ID steht in der Datei).
  4. **Antwort-Vertrag**: neues Schema `schemas/project_values.schema.json`
     (`$id: sni:project_values`, Draft 2020-12): `format`
     (`csv`|`ifc`), `file` (Dateiname), `values[]` mit `concept`, `value`,
     `unit` und `provenance` (`file` + `locator`: CSV Zeile, IFC
     Bauelement-GUID), `quantity_mapping` (JSON-Objekt, `null` bei CSV),
     `disclaimer` (G6). Das Ergebnis wird wie bei `/v1/check` gegen das
     Schema validiert, bevor es geliefert wird (DoD, AGENTS.md §6).
  5. **Limitierung**: maximal 50 MB pro Datei (v1-Wert; grössere Modelle
     sind ein dokumentierter Follow-up). Der Dateiname wird auf den
     Basisnamen reduziert (keine Pfadkomponenten, kein Traversal); der
     Inhalt wird in ein temporäres Verzeichnis geschrieben (Adapter lesen
     von Pfad) und nach dem Request gelöscht.
  6. **Fehler** (400, KBOB-Bericht in `error`): unbekanntes Format,
     Dateigrösse überschritten, Adapter-Fehler (komplette
     Fehlerliste der Adapter), fehlendes IFC-Mapping, ungültiges
     Mapping-JSON. 500 = nicht schemakonformes internes Ergebnis.
     Fehlendes `file`-Feld = 422 (Pydantic, wie bei `/v1/answer`).
  7. **Abhängigkeit**: `python-multipart` (FastAPI-Voraussetzung für
     Form- und UploadFile-Parameter; AGENTS.md §5 erlaubt neue
     Laufzeit-Abhängigkeiten nur mit ADR – diese ist sie).
- Konsequenzen:
  + Java-Client kann CSV/IFC ohne neue Abhängigkeit uploaden; die
    getesteten REQ-500-Adapter bleiben die einzige Parse-Stelle
  + Herkunft (Datei + GUID/Zeile) bleibt über die ganze Kette
    nachvollziehbar (Basis für REQ-501-Fundstellen)
  + IFC-Mapping aus dem Katalog macht den Pilot-Fall ohne
    zusätzliche Eingabe abbildbar
  − neues Schema (DoD) und neuer Endpunkt (OpenAPI-Oberfläche wächst)
  − 50-MB-Limit muss für grosse Modelle revidiert werden (Follow-up)
  − Katalog-abgeleitetes Mapping ist nur so gut wie die
    IFC-Mappings des Katalogs (Pilot: synthetische Concepts)
- Verworfene Alternativen:
  - A: `/v1/check` um ein Datei-Feld erweitern – bricht den stabilen
    ADR-0004-Vertrag (JSON-Payload, check_result-Schema) und vermischt
    Parsen mit Prüfen; verworfen.
  - B: Dateipfad als Query-Parameter (Server liest lokale Datei) –
    Path-Traversal-Risiko und die Annahme, dass Server- und Client-Prozess
    dasselbe Dateisystem teilen; verworfen (G4, Defense in Depth).
  - C: Java parst IFC/CSV mit eigener Bibliothek – verletzt das
    No-Abhängigkeiten-Prinzip der Java-App und dupliziert die
    getesteten Adapter-Logik; verworfen. (CSV parst die Java-App
    zusätzlich lokal für den Offline-Fall – Format-Kontrakt bleibt der
    hier dokumentierte v1-Standard.)
