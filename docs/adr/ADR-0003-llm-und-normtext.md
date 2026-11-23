# ADR-0003: Nutzung von LLMs mit lizenziertem Normtext
- Status: vorgeschlagen – Freigabe durch SIA erforderlich
- Kontext: Ingest und Formulierung können LLMs nutzen; Normtexte sind urheberrechtlich geschützt.
- Entscheidung (Vorschlag): Nur freigegebene Modelle/Endpunkte ohne Trainingsnutzung der Daten; Konfiguration über `SNI_LLM_ENDPOINT`. Bis zur Freigabe arbeitet die Pipeline mit synthetischen Testnormen.
