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

  /* --- Hash-Router (6 Views, wie die Java-Tabs) -------------------------- */
  const VIEWS = ["catalog", "norms", "assistant", "intelligence", "models", "settings"];
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
    if (view === "models") {
      refreshModels();
    }
    if (view === "settings" && !settingsLoaded) {
      loadSettings();
    }
  }

  window.addEventListener("hashchange", render);
  poll();
  setInterval(poll, 2000);
})();
