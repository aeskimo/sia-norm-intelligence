/* App-Logik (M8): Hash-Router, Session-Token, Statuszeile, Shop-UI (M8.2).
   Kein Framework — Vanilla-JS (ADR-0007). Läuft komplett offline
   (CSP default-src 'self', frame-src blob: für die PDF-Vorschau). */
"use strict";

(function () {
  /* --- Session-Token (REQ-816): nur aus der Start-URL, nur JS-Memory ---- */
  const params = new URLSearchParams(window.location.search);
  const siaToken = params.get("sia_token");
  if (siaToken) {
    // Token aus der Adressleiste entfernen (bleibt nur im Speicher);
    // den Hash (Deep Link, z. B. #/norms) erhalten.
    window.history.replaceState({}, "", window.location.pathname + window.location.hash);
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

  /* --- Hash-Router (6 Views wie die Java-Tabs + Onboarding, M8.6) -------- */
  const VIEWS = ["catalog", "norms", "assistant", "intelligence", "models", "settings", "onboarding"];
  const DEFAULT_VIEW = "catalog";

  function currentView() {
    const hash = window.location.hash.replace(/^#\/?/, "");
    return VIEWS.includes(hash) ? hash : DEFAULT_VIEW;
  }

  function render() {
    const view = currentView();
    if (view !== "settings") {
      settingsLoaded = false; // beim erneuten Betreten neu laden
    }
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
      assistantState.checkedDocs.clear();
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

  async function openPdf(productId) {
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
    openPdf(openButton.getAttribute("data-open"));
  });

  /* --- Lokale Modelle (M8.4) -------------------------------------------------- */

  function formatBytes(n) {
    if (!n) {
      return "–";
    }
    const gb = n / (1024 * 1024 * 1024);
    if (gb >= 1) {
      return gb.toFixed(1) + " GB";
    }
    return Math.max(1, Math.round(n / (1024 * 1024))) + " MB";
  }

  function formatModified(value) {
    if (!value) {
      return "–";
    }
    const d = new Date(value);
    return isNaN(d.getTime()) ? esc(value) : d.toLocaleDateString("de-CH");
  }

  function renderOllama(data) {
    const chip = $("ollama-chip");
    chip.hidden = false;
    $("ollama-missing").hidden = data.available !== false;
    if (data.available) {
      chip.textContent = "verfügbar";
      chip.className = "chip chip-success";
      $("ollama-hint").textContent =
        (data.models || []).length + " Modelle installiert.";
      const rows = (data.models || [])
        .map(function (m) {
          return (
            "<tr>" +
            "<td>" + esc(m.name) + "</td>" +
            "<td>" + formatBytes(m.size_bytes) + "</td>" +
            "<td>" + formatModified(m.modified_at) + "</td>" +
            '<td class="row-actions">' +
            '<button class="btn btn-sm" data-use-model="' +
            esc(m.name) + '">Für Fragen verwenden</button> ' +
            '<button class="btn btn-sm" data-delete-model="' +
            esc(m.name) + '">Löschen</button>' +
            "</td></tr>"
          );
        })
        .join("");
      $("ollama-results").innerHTML = (data.models || []).length
        ? "<table><thead><tr><th>Modell</th><th>Größe</th><th>Geändert</th>" +
          "<th>Aktionen</th></tr></thead><tbody>" +
          rows +
          "</tbody></table>"
        : "";
    } else {
      chip.textContent = "nicht erreichbar";
      chip.className = "chip chip-error";
      $("ollama-hint").textContent = "";
      $("ollama-results").innerHTML = "";
    }
  }

  function renderGibbModels(data) {
    const hint = $("gibb-models-hint");
    const row = $("gibb-models");
    if (data.available) {
      hint.textContent = "Verfügbare gibb-Modelle:";
      row.innerHTML = (data.models || [])
        .map(function (m) {
          return '<span class="chip chip-accent">' + esc(m) + "</span>";
        })
        .join("");
    } else {
      hint.textContent =
        "Nicht verfügbar (kein API-Key oder kein Modell konfiguriert, nicht erreichbar).";
      row.innerHTML = "";
    }
  }

  function renderModelJobs(jobs) {
    const line = $("models-jobs-line");
    const pulls = jobs.filter(function (j) {
      return j.kind === "pull";
    });
    const pull = pulls.length ? pulls[pulls.length - 1] : null;
    if (!pull) {
      line.textContent = "";
      line.classList.remove("error-text");
      return;
    }
    if (pull.status === "queued" || pull.status === "running") {
      line.textContent = "Pull: " + (pull.progress || "arbeitet …");
      line.classList.remove("error-text");
    } else if (pull.status === "error") {
      line.textContent = "Fehler: " + (pull.error || "unbekannt");
      line.classList.add("error-text");
    } else {
      line.textContent = "Fertig: " + (pull.progress || "abgeschlossen");
      line.classList.remove("error-text");
    }
  }

  async function refreshModels() {
    try {
      renderOllama(await apiJson("/v1/models/ollama"));
    } catch (err) {
      $("ollama-hint").textContent = "Keine Verbindung: " + err.message;
    }
    try {
      renderGibbModels(await apiJson("/v1/models/gibb"));
    } catch (err) {
      /* ignoriert (gibb optional) */
    }
    try {
      renderModelJobs(await apiJson("/v1/jobs"));
    } catch (err) {
      /* ignoriert */
    }
  }

  $("models-refresh").addEventListener("click", refreshModels);

  $("models-pull").addEventListener("click", async function () {
    const name = $("pull-name").value.trim();
    if (!name) {
      setStatus($("view-models"), "error", "Modellname fehlt.");
      return;
    }
    try {
      await apiJson("/v1/models/ollama/" + encodeURIComponent(name) + "/pull", {
        method: "POST"
      });
      $("pull-name").value = "";
      setStatus($("view-models"), "neutral", "Pull eingereiht: " + name);
      await refreshModels();
    } catch (err) {
      setStatus($("view-models"), "error", err.message);
    }
  });

  $("ollama-results").addEventListener("click", async function (event) {
    const useButton = event.target.closest("button[data-use-model]");
    if (useButton) {
      const name = useButton.getAttribute("data-use-model");
      try {
        await apiJson("/v1/settings", {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ generation_model: name })
        });
        setStatus($("view-models"), "success", "Frage-Modell gesetzt: " + name);
      } catch (err) {
        setStatus($("view-models"), "error", err.message);
      }
      return;
    }
    const deleteButton = event.target.closest("button[data-delete-model]");
    if (!deleteButton) {
      return;
    }
    const name = deleteButton.getAttribute("data-delete-model");
    if (!window.confirm("Modell \"" + name + "\" löschen?")) {
      return;
    }
    try {
      await apiJson("/v1/models/ollama/" + encodeURIComponent(name), {
        method: "DELETE"
      });
      setStatus($("view-models"), "success", "Modell gelöscht: " + name);
      await refreshModels();
    } catch (err) {
      setStatus($("view-models"), "error", err.message);
    }
  });

  /* --- Einstellungen (M8.4) ---------------------------------------------------- */

  let settingsLoaded = false;

  async function loadSettings() {
    try {
      const data = await apiJson("/v1/settings");
      $("set-generation-model").value = data.generation_model;
      $("set-embedding-model").value = data.embedding_model;
      $("set-provider").value = data.provider;
      $("set-approval-name").value = data.approval_name;
      $("set-gibb-base-url").value = data.gibb_base_url;
      $("set-gibb-model").value = data.gibb_model;
      $("set-gibb-key").value = "";
      $("set-data-dir").textContent = data.data_dir;
      $("set-state-key").textContent = data.state_key_set
        ? "vorhanden (Umgebungsvariable oder Keyring)"
        : "nicht vorhanden";
      $("set-gibb-key-state").textContent = data.gibb_key_set
        ? "im OS-Keyring gespeichert"
        : "nicht gespeichert";
      settingsLoaded = true;
    } catch (err) {
      $("settings-message").textContent = "Keine Verbindung: " + err.message;
      $("settings-message").classList.add("error-text");
    }
  }

  $("settings-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    const key = $("set-gibb-key").value;
    const body = {
      generation_model: $("set-generation-model").value,
      embedding_model: $("set-embedding-model").value,
      provider: $("set-provider").value,
      approval_name: $("set-approval-name").value,
      gibb_base_url: $("set-gibb-base-url").value,
      gibb_model: $("set-gibb-model").value
    };
    if (key.trim()) {
      body.gibb_key = key;
    }
    $("settings-save").disabled = true;
    $("settings-message").textContent = "Speichern …";
    $("settings-message").classList.remove("error-text");
    try {
      await apiJson("/v1/settings", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body)
      });
      $("set-gibb-key").value = "";
      $("settings-message").textContent = "Gespeichert.";
      $("settings-message").classList.remove("error-text");
    } catch (err) {
      $("settings-message").textContent = err.message;
      $("settings-message").classList.add("error-text");
    } finally {
      $("settings-save").disabled = false;
    }
  });

  /* --- Assistent (M8.4) ---------------------------------------------------------- */

  const assistantState = {
    checkedDocs: new Set(),
    asking: false
  };

  function isRagReady(doc) {
    return doc.status === "FULLTEXT_READY" || doc.status === "HYBRID_READY";
  }

  function renderAssistantDocs(docs) {
    if (!docs.length) {
      $("assistant-docs-hint").hidden = false;
      $("assistant-docs").innerHTML = "";
      return;
    }
    $("assistant-docs-hint").hidden = true;
    $("assistant-docs").innerHTML = docs
      .map(function (d) {
        const ready = isRagReady(d);
        const checked = ready && assistantState.checkedDocs.has(d.product_id);
        return (
          '<label class="doc-check">' +
          '<input type="checkbox" data-assistant-doc="' +
          esc(d.product_id) + '"' +
          (checked ? " checked" : "") +
          (ready ? "" : " disabled") +
          '><span class="doc-label">' +
          esc(d.number) + " " + esc(d.title) + "</span> " +
          (ready ? "" : '<span class="muted">(' + esc(d.status_label) + ")</span>") +
          "</label>"
        );
      })
      .join("");
  }

  function renderWorksets(worksets) {
    const select = $("workset-scope");
    const current = select.value;
    select.innerHTML =
      '<option value="">(kein Arbeitsset)</option>' +
      worksets
        .map(function (w) {
          return (
            '<option value="' +
            esc(w.name) +
            '">' +
            esc(w.name) +
            " (" +
            w.document_ids.length +
            ")</option>"
          );
        })
        .join("");
    if (worksets.some(function (w) {
      return w.name === current;
    })) {
      select.value = current;
    }
    $("workset-list").innerHTML = worksets
      .map(function (w) {
        return (
          '<div class="doc-check">' +
          '<span class="doc-label">' +
          esc(w.name) +
          ' <span class="muted">' +
          w.document_ids.length +
          " Dokumente</span></span> " +
          '<button class="btn btn-sm" data-delete-workset="' +
          esc(w.name) + '">Löschen</button>' +
          "</div>"
        );
      })
      .join("");
  }

  async function refreshAssistant() {
    if (!state.loggedIn) {
      $("assistant-docs-hint").hidden = false;
      $("assistant-docs-hint").textContent =
        "Bitte zuerst im Normenkatalog einloggen.";
      $("assistant-docs").innerHTML = "";
      $("workset-scope").innerHTML =
        '<option value="">(kein Arbeitsset)</option>';
      $("workset-list").innerHTML = "";
      return;
    }
    try {
      const [docs, worksets] = await Promise.all([
        apiJson("/v1/documents"),
        apiJson("/v1/worksets")
      ]);
      renderAssistantDocs(docs);
      renderWorksets(worksets);
    } catch (err) {
      $("workset-message").textContent = "Keine Verbindung: " + err.message;
    }
  }

  $("assistant-docs").addEventListener("change", function (event) {
    const box = event.target.closest("input[data-assistant-doc]");
    if (!box) {
      return;
    }
    const id = box.getAttribute("data-assistant-doc");
    if (box.checked) {
      assistantState.checkedDocs.add(id);
    } else {
      assistantState.checkedDocs.delete(id);
    }
  });

  $("workset-create").addEventListener("click", async function () {
    const name = $("workset-name").value.trim();
    if (!name) {
      return;
    }
    try {
      await apiJson("/v1/worksets", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: name })
      });
      $("workset-name").value = "";
      $("workset-message").textContent = "Arbeitsset angelegt.";
      await refreshAssistant();
    } catch (err) {
      $("workset-message").textContent = err.message;
    }
  });

  $("workset-list").addEventListener("click", async function (event) {
    const button = event.target.closest("button[data-delete-workset]");
    if (!button) {
      return;
    }
    const name = button.getAttribute("data-delete-workset");
    try {
      await apiJson("/v1/worksets/" + encodeURIComponent(name), {
        method: "DELETE"
      });
      $("workset-message").textContent = "Arbeitsset gelöscht: " + name;
      await refreshAssistant();
    } catch (err) {
      $("workset-message").textContent = err.message;
    }
  });

  function setAnswerBusy(busy) {
    assistantState.asking = busy;
    $("ask-button").disabled = busy;
    $("ask-button").textContent = busy ? "Wird generiert …" : "Fragen";
  }

  function renderSources(sources) {
    $("sources-title").hidden = !sources.length;
    $("answer-sources").innerHTML = sources
      .map(function (s) {
        const docId = String(s.source_id || "").split(":")[0];
        const where =
          "Seite " + s.page + (s.section ? ", Abschnitt " + s.section : "");
        return (
          '<li class="source-item">' +
          '<div class="source-cite"><span>' +
          esc(s.standard) +
          (s.edition ? " " + esc(s.edition) : "") +
          " · " +
          where +
          '</span><button class="btn btn-sm" data-open-source="' +
          esc(docId) + '">Öffnen</button></div>' +
          (s.text ? '<p class="source-quote">„' + esc(s.text) + "“</p>" : "") +
          "</li>"
        );
      })
      .join("");
  }

  /* SSE-Block auswerten (Stream-Adapter, 09 §6.2). */
  function handleSseBlock(block) {
    let event = null;
    let data = null;
    for (const line of block.split("\n")) {
      if (line.startsWith("event: ")) {
        event = line.slice(7);
      } else if (line.startsWith("data: ")) {
        try {
          data = JSON.parse(line.slice(6));
        } catch (err) {
          data = null;
        }
      }
    }
    if (!event) {
      return null;
    }
    if (event === "token" && data && data.text) {
      $("answer-text").textContent += data.text;
    } else if (event === "sources" && data && data.sources) {
      renderSources(data.sources);
    } else if (event === "answer" && data) {
      $("answer-model").textContent = data.model_id ? "· " + data.model_id : "";
      $("answer-disclaimer").textContent = data.disclaimer || "";
      setStatus($("view-assistant"), "success", "Antwort fertig.");
    } else if (event === "error" && data) {
      $("answer-text").textContent = "Fehler: " + data.error;
      setStatus($("view-assistant"), "error", "Fehler bei der Frage.");
    }
    return event;
  }

  $("answer-sources").addEventListener("click", function (event) {
    const button = event.target.closest("button[data-open-source]");
    if (!button) {
      return;
    }
    const docId = button.getAttribute("data-open-source");
    window.location.hash = "#/norms";
    openPdf(docId);
  });

  $("ask-button").addEventListener("click", async function () {
    const question = $("ask-question").value.trim();
    if (!question || assistantState.asking) {
      return;
    }
    if (!state.loggedIn) {
      setStatus($("view-assistant"), "error", "Bitte zuerst einloggen.");
      return;
    }
    const scope = {};
    if (assistantState.checkedDocs.size) {
      scope.document_ids = Array.from(assistantState.checkedDocs);
    }
    if ($("workset-scope").value) {
      scope.workset_id = $("workset-scope").value;
    }
    setAnswerBusy(true);
    $("answer-card").hidden = false;
    $("answer-text").textContent = "";
    $("answer-model").textContent = "";
    $("answer-disclaimer").textContent = "";
    $("sources-title").hidden = true;
    $("answer-sources").innerHTML = "";
    try {
      const res = await apiFetch("/v1/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          question: question,
          scope: Object.keys(scope).length ? scope : null
        })
      });
      if (!res.ok || !res.body) {
        let detail = "HTTP " + res.status;
        try {
          const d = await res.json();
          if (d.error) {
            detail = d.error;
          }
        } catch (err) {
          /* Standardmeldung behalten */
        }
        throw new Error(detail);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const chunk = await reader.read();
        if (chunk.done) {
          break;
        }
        buffer += decoder.decode(chunk.value, { stream: true });
        let sep;
        while ((sep = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          handleSseBlock(block);
        }
      }
    } catch (err) {
      $("answer-text").textContent = "Fehler: " + err.message;
      setStatus($("view-assistant"), "error", "Fehler bei der Frage.");
    } finally {
      setAnswerBusy(false);
    }
  });

  /* --- Norm Intelligence (M8.5, REQ-811/812) ----------------------------------
      1:1 Java IntelligencePanel: Normfrage → deterministische Antwort
      (Aussageklasse-Chip, Claims, Fundstellen, Disclaimer), Semantik-Export,
      Review-Queue (Freigeben/Ablehnen, G3) und Projektdaten-Prüfung
      (pass/fail/insufficient_data, BCF/IDS-Export). */

  const intelState = {
    queue: { candidates: [], gaps: [] },
    queueSelection: null,
    queueSelectionIsGap: true,
    projectRows: [{ concept: "", value: "", unit: "" }]
  };

  function intelStatus(kind, text) {
    setStatus($("view-intelligence"), kind, text);
  }

  function showIntelReport(id, text) {
    const el = $(id);
    el.textContent = text;
    el.hidden = false;
    el.scrollTop = 0;
  }

  /* --- 1) Normfrage → Antwort (REQ-811) -------------------------------------- */

  function intelClassChip(cls) {
    // 1:1 Java SiaDesign.classColor
    const map = {
      normativ_belegt: "chip-success",
      abgeleitet: "chip-accent",
      fachliche_interpretation: "chip-warning",
      projektfestlegung: "chip-warning",
      nicht_eindeutig: "chip-error"
    };
    return (
      '<span class="chip ' + (map[cls] || "") + '">Aussageklasse: ' +
      esc(cls || "unbekannt") + "</span>"
    );
  }

  function intelFormatSource(s) {
    // 1:1 Java formatSource
    let out = String(s.norm || "");
    if (s.edition != null && String(s.edition).trim()) out += ":" + s.edition;
    if (s.clause != null && String(s.clause).trim()) out += "  Ziffer " + s.clause;
    if (s.table != null && String(s.table).trim()) out += "  Tabelle " + s.table;
    if (s.formula != null && String(s.formula).trim()) out += "  Formel " + s.formula;
    if (s.page != null) out += "  Seite " + s.page;
    if (s.verified === true) out += "  [verifiziert]";
    return out;
  }

  $("intel-ask").addEventListener("click", async function () {
    const question = $("intel-question").value.trim();
    if (!question) {
      intelStatus("error", "Frage eingeben.");
      return;
    }
    $("intel-ask").disabled = true;
    $("intel-ask").textContent = "Wird beantwortet …";
    $("intel-answer-card").hidden = false;
    $("intel-answer-class").innerHTML = "";
    $("intel-answer-text").textContent = "";
    $("intel-claims").hidden = true;
    $("intel-claims").innerHTML = "";
    $("intel-sources-title").hidden = true;
    $("intel-sources").innerHTML = "";
    $("intel-answer-disclaimer").textContent = "";
    try {
      const data = await apiJson("/v1/answer", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: question })
      });
      const cls = data.answer_class || "unbekannt";
      $("intel-answer-class").innerHTML = intelClassChip(cls);
      $("intel-answer-text").textContent = data.text || "";
      const claims = data.claims || [];
      if (claims.length) {
        $("intel-claims").innerHTML = claims
          .map(function (cl) {
            return (
              "<li>" + esc(cl.claim || "") +
              (cl.verified ? "  [verifiziert]" : "  [nicht verifiziert]") +
              "</li>"
            );
          })
          .join("");
        $("intel-claims").hidden = false;
      }
      const sources = data.sources || [];
      if (sources.length) {
        $("intel-sources-title").hidden = false;
        $("intel-sources").innerHTML = sources
          .map(function (s) {
            return (
              '<li class="source-item"><div class="source-cite"><span>' +
              esc(intelFormatSource(s)) + "</span></div></li>"
            );
          })
          .join("");
      }
      $("intel-answer-disclaimer").textContent = data.disclaimer || "";
      intelStatus("success", "Antwort erhalten. Aussageklasse: " + cls);
    } catch (err) {
      intelStatus("error", "Antwort fehlgeschlagen: " + err.message);
    } finally {
      $("intel-ask").disabled = false;
      $("intel-ask").textContent = "Fragen (deterministisch)";
    }
  });

  /* --- 2) Semantik-Export (REQ-812, 1:1 runExport) --------------------------- */

  async function refreshIntelNorms() {
    if (!state.loggedIn) {
      return;
    }
    const select = $("intel-export-norm");
    try {
      const docs = await apiJson("/v1/documents");
      const ready = docs.filter(function (d) {
        return d.status === "FULLTEXT_READY" || d.status === "HYBRID_READY";
      });
      const current = select.value;
      select.innerHTML =
        '<option value="">(keine indexierte Norm)</option>' +
        ready
          .map(function (d) {
            return (
              '<option value="' + esc(d.product_id) + '">' +
              esc(d.number) + " " + esc(d.title) + "</option>"
            );
          })
          .join("");
      if (
        ready.some(function (d) {
          return d.product_id === current;
        })
      ) {
        select.value = current;
      }
    } catch (err) {
      /* Auswahl behalten */
    }
  }

  $("intel-export").addEventListener("click", async function () {
    const productId = $("intel-export-norm").value;
    if (!productId) {
      intelStatus("error", "Norm für den Export auswählen (indexierte Normen).");
      return;
    }
    $("intel-export").disabled = true;
    $("intel-export").textContent = "Export läuft …";
    try {
      const data = await apiJson("/v1/ingest/semantic-export", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ norm_id: productId })
      });
      const lines = [
        "[Export] " + (data.candidates || []).length + " Kandidat(en), " +
          (data.skipped || []).length + " übersprungen, " +
          (data.gaps || []).length + " Gaps – Norm: " + data.norm_id
      ];
      (data.candidates || []).forEach(function (id) {
        lines.push(" - Kandidat: " + id);
      });
      (data.skipped || []).forEach(function (reason) {
        lines.push(" - übersprungen: " + reason);
      });
      (data.gaps || []).forEach(function (id) {
        lines.push(" - Gap: " + id);
      });
      showIntelReport("intel-export-report", lines.join("\n"));
      intelStatus("success", "Export + Ingest fertig – Kandidaten stehen in der Review-Queue.");
      refreshIntelQueue();
    } catch (err) {
      intelStatus("error", "Export fehlgeschlagen: " + err.message);
    } finally {
      $("intel-export").disabled = false;
      $("intel-export").textContent = "document.json erzeugen + Ingest";
    }
  });

  /* --- 3) Review-Queue (REQ-812, 1:1 loadQueue/showQueueDetail) --------------- */

  async function refreshIntelQueue() {
    try {
      const data = await apiJson("/v1/review/queue");
      intelState.queue = {
        candidates: data.candidates || [],
        gaps: data.gaps || []
      };
      renderIntelQueue();
    } catch (err) {
      intelStatus("error", "Queue nicht lesbar: " + err.message);
    }
  }

  $("intel-queue-reload").addEventListener("click", refreshIntelQueue);

  function intelQueueItems() {
    return intelState.queue.candidates.concat(intelState.queue.gaps);
  }

  function intelIsGap(id) {
    return String(id || "").indexOf("GAP-") === 0;
  }

  function intelQueueSummary(o) {
    if (intelIsGap(o.id)) {
      return String(o.gap_type || "");
    }
    const source = o.source || {};
    let s = (source.norm || "") + ":" + (source.edition || "");
    if (source.clause) s += "  Ziffer " + source.clause;
    return s + " · " + (o.statement_type || "");
  }

  function renderIntelQueue() {
    const items = intelQueueItems();
    const list = $("intel-queue-list");
    if (!items.length) {
      list.innerHTML =
        '<li class="muted intel-queue-empty">Review-Queue ist leer.</li>';
    } else {
      list.innerHTML = items
        .map(function (o) {
          const id = String(o.id || "");
          const selected = intelState.queueSelection === id ? " selected" : "";
          return (
            '<li class="intel-queue-item' + selected + '" data-queue-id="' +
            esc(id) + '"><span>' + esc(id) + "</span>" +
            '<span class="muted">' + esc(intelQueueSummary(o)) + "</span></li>"
          );
        })
        .join("");
    }
    showIntelQueueDetail();
  }

  function showIntelQueueDetail() {
    const detail = $("intel-queue-detail");
    const id = intelState.queueSelection;
    const obj = id
      ? intelQueueItems().filter(function (o) {
          return String(o.id) === id;
        })[0]
      : undefined;
    if (!obj) {
      detail.hidden = true;
      detail.textContent = "";
      updateIntelQueueButtons();
      return;
    }
    let lines;
    if (intelIsGap(obj.id)) {
      intelState.queueSelectionIsGap = true;
      lines = [
        "ID: " + obj.id,
        "Typ: " + (obj.gap_type || ""),
        "Ziel: " + (obj.target_layer || ""),
        "",
        String(obj.description || "")
      ];
      if (obj.proposal) lines.push("", "Vorschlag: " + obj.proposal);
      const evidence = (obj.evidence || []).map(String);
      if (evidence.length) lines.push("", "Beleg: " + evidence.join(", "));
      lines.push(
        "",
        "(GapReports werden nicht freigegeben – sie dokumentieren fehlende Konzepte/Daten.)"
      );
    } else {
      intelState.queueSelectionIsGap = false;
      const source = obj.source || {};
      lines = [
        "ID: " + obj.id,
        "Norm: " + (source.norm || "") + ":" + (source.edition || "") +
          (source.clause ? ", Ziffer " + source.clause : "") +
          (source.table ? " (Tabelle " + source.table + ")" : ""),
        "Klasse: " + (obj.statement_type || "") +
          "  |  Obligation: " + (obj.obligation || ""),
        "Review-Status: " + (obj.review_status || ""),
        "Konzepte: " + (obj.concepts || []).join(", "),
        "Fundstelle verifiziert: " + (source.verified === true ? "ja" : "nein (G6)"),
        "",
        "Zusammenfassung: " + (obj.summary || "")
      ];
    }
    detail.hidden = false;
    detail.textContent = lines.join("\n");
    updateIntelQueueButtons();
  }

  function updateIntelQueueButtons() {
    const hasSelection = intelState.queueSelection !== null;
    $("intel-approve").disabled = !(hasSelection && !intelState.queueSelectionIsGap);
    $("intel-reject").disabled = !hasSelection;
  }

  $("intel-queue-list").addEventListener("click", function (event) {
    const item = event.target.closest("li[data-queue-id]");
    if (!item) {
      return;
    }
    intelState.queueSelection = item.getAttribute("data-queue-id");
    renderIntelQueue();
  });

  function intelReviewPath(action, id) {
    return (
      "/v1/review/" + id.split("/").map(encodeURIComponent).join("/") + "/" + action
    );
  }

  $("intel-approve").addEventListener("click", async function () {
    const id = intelState.queueSelection;
    if (!id || intelState.queueSelectionIsGap) {
      return;
    }
    const approver = $("intel-reviewer").value.trim();
    const body = JSON.stringify(approver ? { approved_by: approver } : {});
    try {
      const data = await apiJson(intelReviewPath("approve", id), {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: body
      });
      intelStatus("success", "Freigegeben: " + data.id +
        " (" + data.approved_by + ", " + data.approved_at + ")");
      refreshIntelQueue();
    } catch (err) {
      if (!approver && err.message.indexOf("Keine Freigabeperson") === 0) {
        // G3: Freigabeperson einmalig nachfragen und in den Settings speichern.
        const name = window.prompt(
          "Keine Freigabeperson konfiguriert (G3). Name der Freigabeperson:"
        );
        if (name && name.trim()) {
          try {
            await apiJson("/v1/settings", {
              method: "PUT",
              headers: { "content-type": "application/json" },
              body: JSON.stringify({ approval_name: name.trim() })
            });
            $("intel-reviewer").value = name.trim();
            const data = await apiJson(intelReviewPath("approve", id), {
              method: "POST",
              headers: { "content-type": "application/json" },
              body: body
            });
            intelStatus("success", "Freigegeben: " + data.id +
              " (" + data.approved_by + ", " + data.approved_at + ")");
            refreshIntelQueue();
            return;
          } catch (err2) {
            err = err2;
          }
        }
      }
      intelStatus("error", "Freigabe fehlgeschlagen: " + err.message);
    }
  });

  $("intel-reject").addEventListener("click", async function () {
    const id = intelState.queueSelection;
    if (!id) {
      return;
    }
    try {
      await apiJson(intelReviewPath("reject", id), { method: "POST" });
      intelStatus("success", "Ablehnen: " + id + " aus der Queue entfernt.");
      intelState.queueSelection = null;
      refreshIntelQueue();
    } catch (err) {
      intelStatus("error", "Ablehnen fehlgeschlagen: " + err.message);
    }
  });

  /* --- 4) Projektdaten-Prüfung (REQ-812, 1:1 projectData/runCheck/BCF/IDS) ----- */

  function renderIntelProject() {
    $("intel-project").innerHTML =
      '<table class="intel-project-table"><thead><tr>' +
      "<th>Konzept</th><th>Wert</th><th>Einheit</th></tr></thead><tbody>" +
      intelState.projectRows
        .map(function (r, i) {
          return (
            "<tr>" +
            '<td><input data-pi="' + i + '" data-pk="concept" value="' +
            esc(r.concept) + '" placeholder="sia:concept/…" aria-label="Konzept">' +
            '</td><td><input data-pi="' + i + '" data-pk="value" value="' +
            esc(r.value) + '" inputmode="decimal" aria-label="Wert">' +
            '</td><td><input data-pi="' + i + '" data-pk="unit" value="' +
            esc(r.unit) + '" placeholder="m2" aria-label="Einheit"></td></tr>'
          );
        })
        .join("") +
      "</tbody></table>";
  }

  $("intel-project").addEventListener("input", function (event) {
    const input = event.target.closest("input[data-pi]");
    if (!input) {
      return;
    }
    const row = intelState.projectRows[Number(input.getAttribute("data-pi"))];
    if (row) {
      row[input.getAttribute("data-pk")] = input.value;
    }
  });

  $("intel-preset").addEventListener("click", function () {
    // 1:1 Java fillPresetData
    intelState.projectRows = [
      { concept: "sia:concept/teilsflaeche-a", value: "100", unit: "m2" },
      { concept: "sia:concept/teilsflaeche-b", value: "50", unit: "m2" },
      { concept: "sia:concept/gesamtflaeche", value: "150", unit: "m2" }
    ];
    renderIntelProject();
    intelStatus("success", "Beispielwerte (Synthetik) geladen.");
  });

  $("intel-row-add").addEventListener("click", function () {
    intelState.projectRows.push({ concept: "", value: "", unit: "" });
    renderIntelProject();
  });

  $("intel-row-del").addEventListener("click", function () {
    if (intelState.projectRows.length > 1) {
      intelState.projectRows.pop();
    } else {
      intelState.projectRows = [{ concept: "", value: "", unit: "" }];
    }
    renderIntelProject();
  });

  $("intel-file").addEventListener("change", async function () {
    const file = this.files && this.files[0];
    if (!file) {
      return;
    }
    const form = new FormData();
    form.append("file", file);
    try {
      const data = await apiJson("/v1/projectdata", { method: "POST", body: form });
      const values = data.values || [];
      intelState.projectRows = values.map(function (v) {
        return {
          concept: String(v.concept),
          value: String(v.value),
          unit: String(v.unit || "")
        };
      });
      renderIntelProject();
      intelStatus("success", "Projektdaten geladen: " + values.length +
        " Wert(e) aus " + (data.file || file.name));
    } catch (err) {
      intelStatus("error", "Upload fehlgeschlagen: " + err.message);
    } finally {
      this.value = "";
    }
  });

  function intelProjectData() {
    // 1:1 Java projectData (Validierung)
    const data = {};
    intelState.projectRows.forEach(function (r, i) {
      const concept = String(r.concept || "").trim();
      const value = String(r.value || "").trim();
      const unit = String(r.unit || "").trim();
      if (!concept && !value && !unit) return;
      if (!concept || !value || !unit) {
        throw new Error(
          "Zeile " + (i + 1) +
          ": Konzept, Wert und Einheit füllen (oder Zeile leer lassen)."
        );
      }
      const v = Number(value.replace(",", "."));
      if (Number.isNaN(v)) {
        throw new Error("Zeile " + (i + 1) + ": Wert ist keine Zahl: " + value);
      }
      if (data[concept] !== undefined) {
        throw new Error("Konzept mehrfach vorhanden: " + concept);
      }
      data[concept] = { value: v, unit: unit };
    });
    return data;
  }

  function intelRenderCheck(r) {
    // 1:1 Java renderCheck
    let pass = 0;
    let fail = 0;
    let missing = 0;
    const lines = [];
    (r.checks || []).forEach(function (c) {
      let tag;
      if (c.status === "pass") {
        pass++;
        tag = "[pass] ";
      } else if (c.status === "fail") {
        fail++;
        tag = "[fail] ";
      } else {
        missing++;
        tag = "[insufficient_data] ";
      }
      lines.push(tag + c.rule_id);
      lines.push("   " + (c.reason || ""));
      if (c.value !== null && c.value !== undefined) {
        lines.push("   Regelwert: " + c.value + (c.unit ? " " + c.unit : ""));
      }
      if (c.claimed !== null && c.claimed !== undefined) {
        lines.push("   Projektwert: " + c.claimed);
      }
      if ((c.missing_inputs || []).length) {
        lines.push("   Fehlend: " + c.missing_inputs.join(", "));
      }
      if ((c.derived_from || []).length) {
        lines.push("   Fundstelle: " + c.derived_from.join(", "));
      }
    });
    if (!(r.checks || []).length) {
      lines.push("Keine approved Regeln vorhanden (Regeln: data/rules/).");
    }
    if ((r.gaps || []).length) {
      lines.push("Gaps:");
      (r.gaps || []).forEach(function (g) {
        lines.push(" - " + g.id + " (" + g.gap_type + "): " + g.description);
      });
    }
    if (r.disclaimer) lines.push("", r.disclaimer);
    return { text: lines.join("\n"), pass: pass, fail: fail, missing: missing };
  }

  $("intel-check").addEventListener("click", async function () {
    let data;
    try {
      data = intelProjectData();
    } catch (err) {
      intelStatus("error", "Projektdaten: " + err.message);
      return;
    }
    $("intel-check").disabled = true;
    $("intel-check").textContent = "Prüfe …";
    try {
      const r = await apiJson("/v1/check", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ project_data: data })
      });
      const report = intelRenderCheck(r);
      showIntelReport("intel-check-report", report.text);
      intelStatus("success", "Prüfung abgeschlossen: " + (r.checks || []).length +
        " Regel(n) – " + report.pass + " pass, " + report.fail + " fail, " +
        report.missing + " insufficient_data");
    } catch (err) {
      intelStatus("error", "Prüfung fehlgeschlagen: " + err.message);
    } finally {
      $("intel-check").disabled = false;
      $("intel-check").textContent = "Prüfen";
    }
  });

  async function intelDownload(url, body, filename) {
    const res = await apiFetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      let detail = "HTTP " + res.status;
      try {
        const d = await res.json();
        if (d.error) detail = d.error;
      } catch (err) {
        /* Standardmeldung behalten */
      }
      throw new Error(detail);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    const href = URL.createObjectURL(blob);
    a.href = href;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(function () {
      URL.revokeObjectURL(href);
    }, 10000);
    return blob.size;
  }

  $("intel-bcf").addEventListener("click", async function () {
    let data;
    try {
      data = intelProjectData();
    } catch (err) {
      intelStatus("error", "Projektdaten: " + err.message);
      return;
    }
    try {
      const size = await intelDownload(
        "/v1/export/bcf",
        { project_data: data },
        "sni-checks.bcf"
      );
      intelStatus("success", "BCF gespeichert: sni-checks.bcf (" + size + " Bytes)");
    } catch (err) {
      intelStatus("error", "BCF-Export fehlgeschlagen: " + err.message);
    }
  });

  $("intel-ids").addEventListener("click", async function () {
    try {
      await intelDownload("/v1/export/ids", {}, "sni-ids.json");
      intelStatus("success", "IDS gespeichert: sni-ids.json");
    } catch (err) {
      intelStatus("error", "IDS-Export fehlgeschlagen: " + err.message);
    }
  });

  renderIntelProject();

  /* --- Onboarding (M8.6, 09 §2): „Erste Schritte“-View ----------------------- */

  function setOnboardChip(id, ok, okText, notOkText) {
    const chip = $(id);
    if (!chip) {
      return;
    }
    chip.textContent = ok ? okText : notOkText;
    chip.classList.toggle("chip-success", ok);
  }

  async function refreshOnboarding() {
    try {
      const data = await apiJson("/v1/onboarding");
      setOnboardChip("onboard-shop-chip", !!data.shop_logged_in, "Eingeloggt", "Nicht eingeloggt");
      setOnboardChip(
        "onboard-ollama-chip",
        !!data.ollama_available,
        "Ollama erreichbar",
        "Ollama nicht erreichbar"
      );
      setOnboardChip(
        "onboard-gibb-chip",
        !!data.gibb_key_set,
        "API-Key hinterlegt",
        "Kein API-Key"
      );
    } catch (err) {
      /* Fehleranzeige über die Statuszeile (poll) */
    }
  }

  $("onboard-finish").addEventListener("click", async function () {
    const button = $("onboard-finish");
    button.disabled = true;
    try {
      await apiJson("/v1/onboarding/complete", { method: "POST" });
      window.location.hash = "#/catalog";
    } catch (err) {
      button.disabled = false; // Statuszeile zeigt den API-Fehler
    }
  });

  let firstRunChecked = false;
  async function checkFirstRun() {
    if (firstRunChecked) {
      return;
    }
    firstRunChecked = true;
    if (window.location.hash) {
      return; // Deep Link wird respektiert
    }
    try {
      const data = await apiJson("/v1/onboarding");
      if (!data.done) {
        window.location.hash = "#/onboarding";
      }
    } catch (err) {
      /* API noch nicht bereit: Default-View bleibt */
    }
  }

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
    const view = currentView();
    if (state.loggedIn && view === "norms") {
      refreshNorms();
    }
    if (view === "assistant") {
      refreshAssistant();
    }
    if (view === "intelligence") {
      refreshIntelNorms();
      refreshIntelQueue();
    }
    if (view === "models") {
      refreshModels();
    }
    if (view === "settings" && !settingsLoaded) {
      loadSettings();
    }
    if (view === "onboarding") {
      refreshOnboarding();
    }
  }

  /* Geräte-ID (1:1 Java NormenAssistentApp): beim Start mit neuer
     zufälliger UUID präfillen — die alte App generierte sie, der
     Nutzer braucht sie nicht zu kennen. */
  const deviceField = $("login-device");
  if (deviceField && window.crypto && typeof crypto.randomUUID === "function") {
    deviceField.value = "SIA-APP-" + crypto.randomUUID();
  }

  window.addEventListener("hashchange", render);
  checkFirstRun();
  poll();
  setInterval(poll, 2000);
})();
