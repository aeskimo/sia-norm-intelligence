# ADR-0009: Datenlayout, Credentials und App-Daten (M8)
- Status: akzeptiert (User-Entscheid 2026-11-24)
- Datum: 2026-11-24
- Kontext: M8 verteilt die App ohne Repo-Checkout (Installer). Die
  Java-App bindet macOS-Komponenten ein (Keychain via `security`-Binary,
  `~/.sia-normenassistent/` mit `workspace.state` (SIASST1) und
  `*.siaidx` (SIAIDX01), beide AES-256-GCM). Cross-platform und
  migrationstauglich muss das Datenlayout sein.
- Entscheidung:
  - **User-Datenverzeichnis auf allen drei OS:**
    `~/.sia-normenassistent/` (Windows `%USERPROFILE%\.sia-normenassistent`,
    Linux `$HOME/.sia-normenassistent`), Override `SIA_DATA_DIR`.
    Inhalt: `catalog/catalog.db`, `extracted/`, `rules/`,
    `review_queue/`, `norms/<norm-id>/document.json`,
    `index/<product_id>.sniidx`, `workspace.json`.
    `create_app()` wird beim App-Start mit diesen Pfaden gefüttert
    (Parameter existieren; Queue/Norms-Daten analogous ergänzen).
  - **Credentials via `keyring`** (neue Laufzeit-Abhängigkeit,
    ADR-0007): Service `ch.sia.normenassistent`, Accounts `sia-login`
    (Payload `b64url(customer)|b64url(password)` — Java-kompatibel),
    `gibb-api-key`, `state-key`. Linux ohne Secret Service:
    `keyring`-File-Backend + sichtbare Warnung in `/settings`.
  - **Keyring-Migration (REQ-802, expliziter 3-OS-Test):** Die
    Java-App schrieb Credentials nur auf **macOS** (via
    `security`-Binary). macOS: Einträge unter gleichem
    Service/Account müssen lesbar sein (Test). Windows/Linux:
    keine Java-Einträge vorhanden — dokumentierte Abwesenheit,
    kein Migrationsfall. **Keine Annahme, sondern gesicherter
    Test.**
  - **`workspace.json`** (Klartext-JSON, atomar): Modelle, Provider,
    gibb-URL/Modell, Freigabename (G3), `device_id` (stabile UUID für
    SIA-Login), Arbeitssets. **Non-secret** (keine Norminhalte, keine
    Schlüssel) — die SIASST1-Verschlüsselung entfällt für Konfig.
  - **Index verschlüsselt bleiben** (AES-256-GCM, Nonce je Speicherung,
    AAD = product_id; Key: Env `SIA_STATE_KEY_B64` → Keyring
    `state-key`). Neue Dateien `.sniidx` mit **Byte-kompatiblen
    Importer** für `*.siaidx` (gleicher Zeilen-/float32-BE-Codec;
    Roundtrip- + Fixture-Test).
  - **PDF-Bytes: session-only** (In-Memory, AAD = product_id,
    Zeroing) — Status-Quo, endgültig (OQ-012/013).
  - **Lizenz-Policy (OQ-013, beantwortet 24.11.2026):** Status-Quo
    bleibt — lizenzierte PDFs nur in der Session, der verschlüsselte
    Index (enthält Seitentext) bleibt persistent. Entschieden durch
    den Produkt-Owner als Mitglied der Arbeitsgruppe
    SIA-Datenkatalog; **keine separate Nachfrage bei der SIA**.
  - **SIA-Protokoll-Krypto:** DES/CBC mit statischer Key wird als
    Protokoll-Kompatibilität übernommen (nicht einseitig änderbar);
    dokumentierte bekannte Schwäche, App-seitige Krypto = AES-256-GCM.
    `cryptography`-Version wird **gepinnt** ((3-)DES wird in neueren
    Versionen als decrepit markiert); Known-Answer-Test mit Werten
    aus der Java-Implementierung (bekannte statische Key/IV,
    synthetische `.mro`/`.srd`-Fixtures) sichert die
    Protokoll-Kompatibilität (REQ-801).
- Konsequenzen:
  - Echter: ein Datenverzeichnis, Migration vom Java-Stand mit
    Importer (REQ-815), keine neuen Credentials auf fremden Backends.
  - `sni/state/migrate.py` + `sni/secrets/` neue Module; Keyring-Fallback
    vermindert den Schutz (Doku, Warnung).
- Verworfene Alternativen:
  - **OS-native Datenordner** (`%APPDATA%`, `$XDG_DATA_HOME`,
    `~/Library/Application Support`): bricht die Java-Migration
    (Pfadwechsel) und die mentale Einfachheit für ein Local-Tool.
  - **Schlüssel in workspace.json**: Konfig-Verlust = Daten-Verlust;
    Keyring ist die Consumer-Standardantwort.
  - **Neues Index-Format ohne Importer**: erzwingt Re-Indexierung,
    die ohne persistierte PDFs einen Re-Download bräuchte (Lizenz-/
    Zeitkosten) — abgelehnt.
