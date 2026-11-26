# ADR-0003: Nutzung von LLMs mit lizenziertem Normtext
- Status: akzeptiert (SIA-Freigabe 2026-11-26)
- Datum: 2026-11-23, akzeptiert 2026-11-26
- Kontext: Ingest und Formulierung können LLMs nutzen; Normtexte sind urheberrechtlich geschützt.
- Entscheidung: Nur freigegebene Modelle/Endpunkte ohne Trainingsnutzung der Daten; Konfiguration über `SNI_LLM_ENDPOINT`.
- Freigabenumfang (2026-11-26): Freigegebener Endpunkt ist die hauseigene Plattform **gibb** (`https://chat.gibb.ch`, OpenAI-kompatible API; lokale Modelle: Daten bleiben im Haus, keine Trainingsnutzung). Konfiguration: `SNI_LLM_ENDPOINT` (Basis-URL), `SNI_LLM_MODEL` (Modell-ID), `SNI_LLM_API_KEY` (Bearer-Schlüssel; Fallback: Keyring-Account `gibb-api-key` aus den Einstellungen). Umsetzung: M13 (Stufe 3 von ADR-0010), `make llm NORM=<norm-id>` — Vorschläge für die Fachfelder (Aussageklasse, Obligation, Summary, Concepts) aus dem lokal extrahierten Ziffern-Text; Output bleibt Vorschlag (`document.llm.json`), Freigabe bleibt menschlicher Akt (G3).
- Grenzen: Normtext verlässt die lokale Umgebung nur Richtung des konfigurierten Endpunkts (REQ-1301); HTTPS-Zwang (HTTP ausschliesslich Loopback); keine lizenzierten Texte an nicht-freigegebene Endpunkte (öffentliche Modelle).
