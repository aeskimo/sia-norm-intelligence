/* Bereichshilfe + Erstbesuchs-Onboarding (Hilfe in jedem Bereich).
 *
 * Statischer, versionierter Inhalt — keine externen Resources
 * (G4/CSP: UI ist voll offline-fähig, keine http(s)-URLs).
 *
 * Pro Arbeitsbereich:
 *   - «Hilfe»-Button im View-Header (jederzeit verfügbar)
 *   - beim ersten Besuch öffnet sich das Panel automatisch mit einem
 *     Kurz-Hinweis; «Verstanden» merkt sich das pro Bereich
 *     (localStorage), das Panel kann danach jederzeit über den Button
 *     wieder geöffnet werden.
 */
(function () {
  "use strict";

  const HELP = {
    catalog: {
      title: "Hilfe: Normenkatalog",
      tip: "Hier loggen Sie sich ein (Kundennummer + Passwort Ihres Normen-Abonnements). Danach lädt der Katalog automatisch. Norm wählen, «Downloaden» — sie erscheint in «Meine Normen».",
      sections: [
        ["Login", "Provider wählen (z. B. SIA), Kundennummer/Benutzername und Passwort eingeben. Die Device-ID wird automatisch präbefüllt und kann so bleiben. «Zugangsdaten merken» speichert Kundennummer und Passwort im OS-Keyring — nie im Klartext in der App. Nach dem Login lädt der Katalog als Sitzungs-Snapshot (bei SIA rund 6700 Normen)."],
        ["Katalog durchsuchen", "Suche nach Nummer, Titel oder Stichwort. Jede Zeile zeigt Nummer, Titel, Sprache, Ausgabe und Gültigkeit. Mit «Downloaden» wird die Norm als Hintergrund-Job in «Meine Normen» übernommen."],
        ["Typische Meldungen", "«Zeitüberschreitung» ist ein transienter Zustand des Portals — einfach erneut einloggen. Bei falschem Passwort zeigt die Meldung eine sichere Diagnose (nur Längen und Zeichengruppen, nie das Passwort). Abmelden oder App-Neustart beendet die Sitzung: PDFs sind nur während einer Sitzung verfügbar."],
      ],
    },
    norms: {
      title: "Hilfe: Meine Normen",
      tip: "Ihre heruntergeladenen Normen. Die Liste bleibt nach Neustarts erhalten — die PDFs selbst sind nur während dieser Sitzung verfügbar und werden nach einem Neustart bei Bedarf neu heruntergeladen.",
      sections: [
        ["Status der Dokumente", "«Heruntergeladen» = PDF im (verschlüsselten) Sitzungscache. «Volltext bereit» = Text extrahiert und durchsuchbar — Voraussetzung für Fragen im Normenassistenten. «Volltext + Vektoren» = zusätzlich für die semantische Suche indexiert (braucht ein installiertes Embedding-Modell, sonst bleibt die Suche auf Volltext)."],
        ["Jobs", "Download und Analyse laufen im Hintergrund; die Job-Zeile unten zeigt den Fortschritt. Fehler (z. B. Portal-Timeout) zeigt das jeweilige Job-Ergebnis."],
        ["PDF & Löschen", "Das PDF-Symbol öffnet die Vorschau. Löschen entfernt Cache und Index (Zeroing) und aktualisiert die Arbeitssets — die Norm bleibt im Katalog zum erneuten Download verfügbar."],
      ],
    },
    assistant: {
      title: "Hilfe: Normenassistent",
      tip: "Fragen an Ihre lokal analysierten Normen — die Antwort nennt die Fundstellen (Norm, Seite). Voraussetzungen: Normen herunterladen, analysieren lassen und hier als Scope markieren.",
      sections: [
        ["So läuft eine Frage", "1) Normen in «Meine Normen» herunterladen und analysieren. 2) Hier die Dokumente als Scope markieren — oder ein Arbeitsset als Scope wählen. 3) Frage stellen: Die Antwort wird gestreamt und verweist auf Fundstellen. Das Antwortmodell (lokal oder gibb) wählen Sie im Dropdown in der Frage-Karte; die Auswahl wird in den Einstellungen gespeichert."],
        ["Arbeitssets", "Gruppieren Sie Normen für wiederkehrende Projekte (z. B. «Bauvorhaben X»). Ein Arbeitsset lässt sich als Scope für Fragen festlegen — so bleibt die Dokument-Auswahl zwischen Sitzungen stabil."],
        ["Grenzen", "Die Antwort ist eine technische Unterstützung mit Quellenangabe — keine Rechtsauskunft. Thinking-Modelle (z. B. qwen3) «denken» zuerst: Die sichtbare Antwort erscheint deshalb erst nach einigen Sekunden bis Minuten."],
      ],
    },
    intelligence: {
      title: "Hilfe: Norm Intelligence",
      tip: "Deterministische Werkzeuge ohne Antwortmodell: Normfrage mit Fundstelle, Semantik-Export, Review-Freigabe. Ein Sprachmodell wird nur für den Semantik-Export genutzt. Die Projektdaten-Prüfung hat einen eigenen Bereich («Projektdaten» in der Navigation).",
      sections: [
        ["Normfrage (deterministisch)", "Stellt eine Frage an die indexierten Normtexte und liefert eine Antwort mit exakter Fundstelle (Norm, Ausgabe, Ziffer) — ohne Sprachmodell, deshalb reproduzierbar."],
        ["Semantik-Export → Review-Queue", "Der Export lässt das konfigurierte Modell aus einer indexierten Norm prüfbare Kandidaten (Aussagen, Begriffe) extrahieren. Diese landen in der Review-Queue und werden einzeln freigegeben oder abgelehnt (G3 — Freigabeperson pro Vorgang oder Standard aus den Einstellungen)."],
      ],
    },
    projectdata: {
      title: "Hilfe: Projektdaten",
      tip: "Prüft Projektdaten (Flächen, Werte) deterministisch gegen die freigegebenen Regeln — ohne Sprachmodell. Das Ergebnis lässt sich als BCF- oder IDS-Datei für Ihr Projekt speichern.",
      sections: [
        ["Daten erfassen", "Zeilen pflegen (Konzept-Id wie «sia:concept/…», Wert, Einheit), per «+ Zeile» erweitern oder mit «Beispielwerte (Synthetik)» befüllen. CSV/IFC-Dateien werden direkt geladen."],
        ["Prüfen & Exportieren", "«Prüfen» wendet alle approved Regeln an (REQ-501) und meldet pro Regel pass / fail / insufficient_data. «BCF speichern» bzw. «IDS speichern» erzeugt die Dateiformate für Ihr Projektdaten-Management."],
      ],
    },
    models: {
      title: "Hilfe: Lokale Modelle",
      tip: "Alle lokalen Ollama-Modelle auf einen Blick. Welches Modell für Fragen bzw. Embeddings genutzt wird, wählen Sie in den Einstellungen («Frage-Modell», «Embedding-Modell»).",
      sections: [
        ["Ollama (lokal)", "Ollama ist die lokale Laufzeit für KI-Modelle: Download unter ollama.com, danach im Terminal «ollama serve» starten (Standard-Port 11434, Loopback). Neue Modelle mit «Pull (laden)» beziehen (läuft als Job), per Zeile wieder entfernen. Grössere Modelle brauchen mehr RAM und Zeit — für Antworten genügt z. B. qwen3:4b."],
        ["Zwei Modellarten", "Frage-Modell: erzeugt die Antworten im Normenassistenten. Embedding-Modell: erzeugt die Vektoren für die semantische Suche — ist es nicht installiert, fällt die Suche automatisch auf Volltext zurück. Beide Modelle müssen in Ollama installiert sein."],
        ["gibb (Cloud-Alternative)", "Die gibb-Modellliste zeigt die verfügbaren Cloud-Modelle (API-Key in den Einstellungen nötig). Provider und Modell wechseln Sie in den Einstellungen."],
      ],
    },
    settings: {
      title: "Hilfe: Einstellungen",
      tip: "Antwortmodell, Provider (lokal oder gibb-Cloud) und Freigabename. Der gibb-API-Key wird nur im OS-Keyring gespeichert und von der App nie angezeigt oder zurückgeliefert.",
      sections: [
        ["Antwortmodell", "«Frage-Modell» = Modell für die Assistent-Antworten (z. B. qwen3:4b). «Embedding-Modell» = Modell für die semantische Suche (z. B. embeddinggemma). «Provider» = wo das Modell läuft: Lokal (Ollama) oder gibb (chat.gibb.ch)."],
        ["gibb einrichten", "Provider auf «gibb» stellen, gibb-URL prüfen (Standard: chat.gibb.ch/api), ein Modell aus der gibb-Modellliste wählen und den API-Key hinterlegen (leer lassen = unverändert). Der Key landet im OS-Keyring — G4: die App zeigt ihn nie an und liefert ihn nie zurück."],
        ["Freigabename & System", "«Freigabename» ist die Standard-Freigabeperson für die Review-Queue (G3). Unter «System» sehen Sie das Datenverzeichnis und ob Status- bzw. gibb-Key vorhanden sind."],
      ],
    },
  };

  const seenKey = (view) => "sia-help-seen-" + view;

  function isSeen(view) {
    try {
      return localStorage.getItem(seenKey(view)) === "1";
    } catch (e) {
      return true; // Speicher gesperrt: Hinweis nicht aufdringlich wiederholen
    }
  }

  function markSeen(view) {
    try {
      localStorage.setItem(seenKey(view), "1");
    } catch (e) {
      /* Speicher gesperrt — ignorieren */
    }
  }

  /* Baut Header-Button + Hilfe-Panel für einen View (idempotent). */
  function buildPanel(view, entry) {
    const section = document.getElementById("view-" + view);
    const h1 = section && section.querySelector("h1");
    if (!h1 || section.querySelector(".view-header")) {
      return;
    }

    const header = document.createElement("div");
    header.className = "view-header";
    h1.parentNode.insertBefore(header, h1);
    header.appendChild(h1);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-sm help-toggle";
    btn.textContent = "Hilfe";
    header.appendChild(btn);

    const panel = document.createElement("div");
    panel.className = "card help-card";
    panel.id = "help-panel-" + view;
    panel.hidden = true;

    const tipDiv = document.createElement("div");
    tipDiv.className = "help-tip";
    tipDiv.hidden = true;
    const tipP = document.createElement("p");
    tipP.textContent = entry.tip;
    const tipBtn = document.createElement("button");
    tipBtn.type = "button";
    tipBtn.className = "btn btn-sm btn-accent";
    tipBtn.textContent = "Verstanden";
    tipBtn.addEventListener("click", () => {
      markSeen(view);
      panel.hidden = true;
    });
    tipDiv.appendChild(tipP);
    tipDiv.appendChild(tipBtn);
    panel.appendChild(tipDiv);

    const title = document.createElement("h2");
    title.className = "card-title";
    title.textContent = entry.title;
    panel.appendChild(title);

    for (const pair of entry.sections) {
      const heading = document.createElement("h3");
      heading.className = "help-heading";
      heading.textContent = pair[0];
      const text = document.createElement("p");
      text.className = "muted";
      text.textContent = pair[1];
      panel.appendChild(heading);
      panel.appendChild(text);
    }

    const actions = document.createElement("div");
    actions.className = "help-actions";
    const closeBtn = document.createElement("button");
    closeBtn.type = "button";
    closeBtn.className = "btn btn-sm";
    closeBtn.textContent = "Schliessen";
    closeBtn.addEventListener("click", () => {
      panel.hidden = true;
    });
    actions.appendChild(closeBtn);
    panel.appendChild(actions);

    header.after(panel);

    btn.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      if (!panel.hidden) {
        tipDiv.hidden = isSeen(view); // Hinweis nur, solange nicht bestätigt
      }
    });

    // Erstbesuch: Panel automatisch öffnen (mit Kurz-Hinweis).
    if (!isSeen(view)) {
      panel.hidden = false;
      tipDiv.hidden = false;
    }
  }

  window.SiaHelp = {
    init(view) {
      const entry = HELP[view];
      if (entry) {
        buildPanel(view, entry);
      }
    },
    /* Nur für Tests: statische Einträge (Anzahl/Bereiche). */
    _entries: () => Object.keys(HELP).sort(),
  };
})();
