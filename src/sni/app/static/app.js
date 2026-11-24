/* App-Logik (M8): Hash-Router, Session-Token, Statuszeile.
   Kein Framework — Vanilla-JS (ADR-0007). Läuft komplett offline
   (CSP default-src 'self'). */
"use strict";

(function () {
  /* --- Session-Token (REQ-816): nur aus der Start-URL, nur JS-Memory ---- */
  const params = new URLSearchParams(window.location.search);
  const siaToken = params.get("sia_token");
  if (siaToken) {
    // Token aus der Adressleiste entfernen (bleibt nur im Speicher)
    window.history.replaceState({}, "", window.location.pathname);
  }

  function apiFetch(path, options) {
    const opts = options || {};
    if (siaToken) {
      opts.headers = Object.assign({}, opts.headers, { "x-sia-token": siaToken });
    }
    return fetch(path, opts);
  }

  /* --- Hash-Router (6 Views, wie die Java-Tabs) -------------------------- */
  const VIEWS = ["catalog", "norms", "assistant", "intelligence", "models", "settings"];
  const DEFAULT_VIEW = "catalog";

  function currentView() {
    const hash = window.location.hash.replace(/^#\/?/, "");
    return VIEWS.includes(hash) ? hash : DEFAULT_VIEW;
  }

  function render() {
    const view = currentView();
    for (const name of VIEWS) {
      const section = document.getElementById("view-" + name);
      if (section) {
        section.hidden = name !== view;
      }
      const link = document.querySelector('.nav-item[href="#/' + name + '"]');
      if (link) {
        link.classList.toggle("active", name === view);
      }
    }
  }

  window.addEventListener("hashchange", render);
  render();

  /* --- Statuszeile: /v1/status, semantische Klassifikation ---------------
     Wie SiaDesign.Status (Java): Fehler-Keywords zuerst, dann Erfolg,
     Text endend auf "…" = läuft (neutral). */
  function classify(text) {
    const t = String(text).toLowerCase();
    if (/(fehlgeschlagen|ungültig|nicht gefunden|keine verbindung|fehler|error)/.test(t)) {
      return "error";
    }
    if (/(abgeschlossen|erhalten|verbunden|freigegeben|erfolgreich|bereit)/.test(t)) {
      return "success";
    }
    return "neutral";
  }

  function setStatus(section, className, text) {
    const dot = section.querySelector(".status-dot");
    const label = section.querySelector(".status-text");
    if (dot) {
      dot.className = "status-dot " + className;
    }
    if (label) {
      label.textContent = text;
    }
  }

  async function pollStatus() {
    const section = document.getElementById("view-" + currentView());
    if (!section) {
      return;
    }
    try {
      const res = await apiFetch("/v1/status");
      if (!res.ok) {
        throw new Error("HTTP " + res.status);
      }
      const data = await res.json();
      const text = data.summary || "Verbunden.";
      setStatus(section, classify(text), text);
    } catch (err) {
      setStatus(section, "error", "Keine Verbindung zur App-API (" + err.message + ").");
    }
  }

  pollStatus();
  setInterval(pollStatus, 2000);
})();
