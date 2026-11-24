/* App-Logik (M8): Hash-Router, Session-Token, Statuszeile, Shop-UI (M8.2).
   Kein Framework — Vanilla-JS (ADR-0007). Läuft komplett offline
   (CSP default-src 'self', frame-src blob: für die PDF-Vorschau). */
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

  async function apiJson(path, options) {
    const res = await apiFetch(path, options);
    const data = await res.json().catch(function () {
      return {};
    });
    if (!res.ok) {
      const err = new Error(data.error || data.detail || "HTTP " + res.status);
      err.protocol = data.protocol || null;
      throw err;
    }
    return data;
  }

  function $(id) {
    return document.getElementById(id);
  }

  function esc(value) {
    const div = document.createElement("div");
    div.textContent = String(value);
    return div.innerHTML;
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
      const section = $("view-" + name);
      if (section) {
        section.hidden = name !== view;
      }
      const link = document.querySelector('.nav-item[href="#/' + name + '"]');
      if (link) {
        link.classList.toggle("active", name === view);
      }
    }
  }

  /* --- Shop-Zustand (M8.2) ------------------------------------------------ */
  const state = {
    loggedIn: false,
    catalog: []
  };

  /* --- Login --------------------------------------------------------------- */

  function setLoginMessage(text, isError) {
    const el = $("login-message");
    el.textContent = text || "";
    el.classList.toggle("error-text", !!isError);
  }

  function setLoginInputsEnabled(enabled) {
    for (const el of document.querySelectorAll("#login-card input, #login-card select")) {
      el.disabled = !enabled;
    }
    $("login-button").disabled = !enabled;
  }

  function setLoggedIn(loggedIn) {
    state.loggedIn = loggedIn;
    $("logout-button").hidden = !loggedIn;
    setLoginInputsEnabled(!loggedIn);
    if (!loggedIn) {
      state.catalog = [];
      $("catalog-hint").textContent = "Bitte zuerst einloggen.";
      $("catalog-hint").classList.remove("error-text");
      $("catalog-search").hidden = true;
      $("catalog-results").innerHTML = "";
      $("pdf-card").hidden = true;
      $("norms-hint").textContent =
        "Keine lokalen Dokumente. Nach dem Download erscheint die Norm hier.";
      $("norms-hint").hidden = false;
      $("norms-results").innerHTML = "";
      $("jobs-line").textContent = "";
      setLoginMessage("");
    }
  }

  $("login-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    const body = {
      provider: $("login-provider").value,
      customer: $("login-customer").value,
      password: $("login-password").value,
      device_id: $("login-device").value,
      remember: $("login-remember").checked
    };
    setLoginInputsEnabled(false);
    $("login-button").disabled = false;
    $("login-button").textContent = "Einloggen …";
    setLoginMessage("Einloggen …");
    try {
      const data = await apiJson("/v1/session/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body)
      });
      state.loggedIn = true;
      state.catalog = data.catalog || [];
      $("logout-button").hidden = false;
      $("catalog-hint").textContent = state.catalog.length + " Normen im Lizenz-Katalog.";
      $("catalog-hint").classList.remove("error-text");
      $("catalog-search").hidden = false;
      renderCatalog();
      if (data.keyring && data.keyring !== "ok") {
        setLoginMessage("Eingeloggt. " + data.keyring, true);
      } else {
        const warn =
          data.message && data.message !== "OK" ? " (" + data.message + ")" : "";
        setLoginMessage("Eingeloggt" + warn + ".", false);
      }
      $("login-password").value = "";
    } catch (err) {
      state.loggedIn = false;
      state.catalog = [];
      setLoginInputsEnabled(true);
      setLoginMessage(
        err.message + (err.protocol ? " [" + err.protocol + "]" : ""),
        true
      );
    } finally {
      $("login-button").textContent = "Einloggen";
    }
  });

  $("logout-button").addEventListener("click", async function () {
    $("logout-button").disabled = true;
    try {
      await apiJson("/v1/session/logout", { method: "POST" });
    } catch (err) {
      /* auch lokal abmelden (Zeroing erfolgt serverseitig) */
    }
    setLoggedIn(false);
    $("logout-button").disabled = false;
  });

  /* --- Katalog --------------------------------------------------------------- */

  function renderCatalog() {
    const q = $("catalog-search").value.trim().toLowerCase();
    const rows = state.catalog
      .filter(function (d) {
        if (!q) {
          return true;
        }
        return (
          d.number + " " + d.title + " " + d.description + " " + d.keywords
        )
          .toLowerCase()
          .includes(q);
      })
      .map(function (d) {
        return (
          "<tr>" +
          "<td>" + esc(d.number) + "</td>" +
          "<td>" + esc(d.title) + "</td>" +
          "<td>" + esc(d.year) + "</td>" +
          "<td>" + esc(d.language) + "</td>" +
          "<td>" + (d.view_allowed ? "Ja" : "Nein") + "</td>" +
          '<td><button class="btn btn-sm" data-download="' +
          esc(d.product_id) + '" ' +
          (d.view_allowed ? "" : "disabled") + ">Download</button></td>" +
          "</tr>"
        );
      })
      .join("");
    $("catalog-results").innerHTML =
      "<table><thead><tr><th>Nummer</th><th>Titel</th><th>Jahr</th>" +
      "<th>Sprache</th><th>Anzeige</th><th></th></tr></thead>" +
      "<tbody>" +
      rows +
      "</tbody></table>";
  }

  let searchTimer = 0;
  $("catalog-search").addEventListener("input", function () {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(renderCatalog, 250);
  });

  $("catalog-results").addEventListener("click", async function (event) {
    const button = event.target.closest("button[data-download]");
    if (!button) {
      return;
    }
    const productId = button.getAttribute("data-download");
    button.disabled = true;
    try {
      await apiJson("/v1/documents/download", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ product_id: productId })
      });
      window.location.hash = "#/norms";
    } catch (err) {
      button.disabled = false;
      $("catalog-hint").textContent = err.message;
      $("catalog-hint").classList.add("error-text");
    }
  });

  /* --- Meine Normen ---------------------------------------------------------- */

  function statusChip(doc) {
    const cls =
      {
        CACHED: "chip-accent",
        INDEXING: "chip-warning",
        FULLTEXT_READY: "chip-success",
        HYBRID_READY: "chip-success",
        ERROR: "chip-error"
      }[doc.status] || "";
    return '<span class="chip ' + cls + '">' + esc(doc.status_label) + "</span>";
  }

  function renderNorms(docs, jobs) {
    if (!docs.length) {
      $("norms-hint").hidden = false;
      $("norms-results").innerHTML = "";
    } else {
      $("norms-hint").hidden = true;
      $("norms-results").innerHTML =
        "<table><thead><tr><th>Nummer</th><th>Titel</th><th>Status</th>" +
        "<th>Detail</th><th>Aktionen</th></tr></thead>" +
        "<tbody>" +
        docs
          .map(function (d) {
            return (
              "<tr>" +
              "<td>" + esc(d.number) + "</td>" +
              "<td>" + esc(d.title) + "</td>" +
              "<td>" + statusChip(d) + "</td>" +
              "<td>" + esc(d.detail) + "</td>" +
              '<td class="row-actions">' +
              '<button class="btn btn-sm" data-open="' + esc(d.product_id) +
              '">PDF öffnen</button> ' +
              '<button class="btn btn-sm" data-remove="' + esc(d.product_id) +
              '">Entfernen</button>' +
              "</td></tr>"
            );
          })
          .join("") +
        "</tbody></table>";
    }
    const active = jobs.filter(
      function (j) {
        return j.kind === "download" && (j.status === "queued" || j.status === "running");
      }
    );
    const last = jobs.length ? jobs[jobs.length - 1] : null;
    let text = "";
    let isError = false;
    if (active.length) {
      const j = active[0];
      text = "Job: " + (j.progress || "arbeitet …");
    } else if (last && last.kind === "download" && last.status === "error") {
      text = "Fehler: " + (last.error || "unbekannt");
      isError = true;
    } else if (last && last.kind === "download" && last.status === "done") {
      text = "Fertig: " + (last.progress || "abgeschlossen");
    }
    $("jobs-line").textContent = text;
    $("jobs-line").classList.toggle("error-text", isError);
  }

  async function refreshNorms() {
    if (!state.loggedIn) {
      return;
    }
    try {
      const docs = await apiJson("/v1/documents");
      const jobs = await apiJson("/v1/jobs");
      renderNorms(docs, jobs);
    } catch (err) {
      $("jobs-line").textContent = "Keine Verbindung: " + err.message;
    }
  }

  $("norms-results").addEventListener("click", async function (event) {
    const removeButton = event.target.closest("button[data-remove]");
    if (removeButton) {
      const productId = removeButton.getAttribute("data-remove");
      try {
        await apiJson("/v1/documents/" + encodeURIComponent(productId), {
          method: "DELETE"
        });
        $("pdf-card").hidden = true;
        await refreshNorms();
      } catch (err) {
        $("jobs-line").textContent = err.message;
      }
      return;
    }
    const openButton = event.target.closest("button[data-open]");
    if (!openButton) {
      return;
    }
    const productId = openButton.getAttribute("data-open");
    try {
      const res = await apiFetch(
        "/v1/documents/" + encodeURIComponent(productId) + "/pdf"
      );
      if (!res.ok) {
        throw new Error("HTTP " + res.status);
      }
      const blob = await res.blob();
      const frame = $("pdf-frame");
      if (frame.src.startsWith("blob:")) {
        URL.revokeObjectURL(frame.src);
      }
      frame.src = URL.createObjectURL(blob);
      $("pdf-title").textContent = "PDF-Vorschau: " + productId;
      $("pdf-card").hidden = false;
    } catch (err) {
      $("jobs-line").textContent = "PDF konnte nicht geladen werden: " + err.message;
    }
  });

  /* --- Statuszeile + Polling --------------------------------------------------- */

  /* --- Statuszeile: semantische Klassifikation ----------------------------
      Wie SiaDesign.Status (Java): Fehler-Keywords zuerst, dann Erfolg. */
  function classify(text) {
    const t = String(text).toLowerCase();
    if (/(fehlgeschlagen|ungültig|nicht gefunden|keine verbindung|fehler|error)/.test(t)) {
      return "error";
    }
    if (/(abgeschlossen|erhalten|verbunden|freigegeben|erfolgreich|eingeloggt|bereit)/.test(t)) {
      return "success";
    }
    return "neutral";
  }

  function setStatus(section, kind, text) {
    const dot = section.querySelector(".status-dot");
    const label = section.querySelector(".status-text");
    dot.className = "status-dot " + kind;
    label.textContent = text;
  }

  async function poll() {
    render();
    const section = document.getElementById("view-" + currentView());
    if (section) {
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
    if (state.loggedIn && currentView() === "norms") {
      refreshNorms();
    }
  }

  window.addEventListener("hashchange", render);
  poll();
  setInterval(poll, 2000);
})();
