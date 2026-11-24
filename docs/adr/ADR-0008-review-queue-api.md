# ADR-0008: Review-Queue-API (G3 als UI-Akt)
- Status: akzeptiert (User-Entscheid 2026-11-24)
- Datum: 2026-11-24
- Kontext: Die Review-Queue (REQ-200/201/202) hat heute **keine
  Endpunkte** — Freigabe ist manuelle Dateibewegung (`candidate` in
  `data/review_queue/` → `data/extracted/` mit `approved_by`/`approved_at`,
  `source.verified=true`). Das ist für M8 (Consumer-App) nicht
  bedienbar und fehleranfällig. G3 verlangt einen **menschlichen Akt**.
- Entscheidung:
  - Neue Endpunkte (nur `app_mode=True`, `sni/app/api.py` +
    Service `sni/review/`):
    - `GET /v1/review/queue` → Kandidaten (`sni:norm_statement`,
      `review_status=candidate`) + offene `sni:gap_report`;
    - `POST /v1/review/{id}/approve` mit `{approved_by?}` → setzt
      `review_status=approved`, `approved_by` = konfigurierte
      Freigabeperson aus `sni:settings`; **wenn keine gesetzt ist,
      fragt die UI beim ersten Freigeben einmalig nach** und speichert
      die Antwort (ein OS-Username allein gilt als schwacher
      Audit-Eintrag — User-Entscheid 24.11.2026); optionaler
      Override im Freigabe-Dialog. `approved_at` (UTC),
      `source.verified=true` (nur, wenn die Fundstelle geprüft wurde —
      Bestätigung im UI-Dialog), Move nach `extracted/` (atomar,
      Validierung vor Move, wie Ingest);
    - `POST /v1/review/{id}/reject` → Kandidat wird verworfen
      (Datei entfernt, Audit-Zeile im Log mit ID + Zeit).
  - **Nie automatisch:** kein Ingest-/API-Pfad darf `approved` setzen;
    die Verifier-Logik (REQ-401) bleibt die zweite Schranke.
  - Kein neues Schema (Wiederverwendung `sni:norm_statement` /
    `sni:gap_report`); jede Antwort trägt `disclaimer` (G6).
- Konsequenzen:
  - Echter: G3-Flow ist in der App ein Klick (menschlich!), Freigabe
    wirkt ohne Neustart (Wissensbasis wird pro Request geladen —
    bleibt).
  - `sni/review/` wird neues Modul (Schichten: über `knowledge/`);
    Reject ist nicht rückholbar (Doku im UI).
- Verworfene Alternativen:
  - Keine Endpunkte, UI zeigt Dateipfade (Consumer-tauglich = nein).
  - SQLite-Queue statt Dateiformat (bricht REQ-202-Vertrag +
    Re-Ingest-Semantik auf).
  - Approve ohne `source.verified`-Bestätigung (G6: `normativ_belegt`
    würde ohne Prüfung möglich werden — abgelehnt).
  - Immer OS-User als `approved_by` (schwacher Audit-Eintrag,
    User-Entscheid 24.11.2026).
