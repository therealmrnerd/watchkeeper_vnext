(function () {
  const state = {
    lastAssist: null,
    lastPolicyPreview: null,
    eventBuffer: [],
    currentLogFile: null,
    eventFilterCorrelationId: null,
    latestSitrep: null,
    demoEnabled: false,
    demoScenario: "none",
    demoPreviewItems: null,
  };

  const el = {
    watchTier: document.getElementById("watchTier"),
    watchCondition: document.getElementById("watchCondition"),
    watchMode: document.getElementById("watchMode"),
    advisoryStatus: document.getElementById("advisoryStatus"),
    advisoryLatency: document.getElementById("advisoryLatency"),
    vectorStatus: document.getElementById("vectorStatus"),
    vectorLatency: document.getElementById("vectorLatency"),
    lastAlarmTs: document.getElementById("lastAlarmTs"),
    lastAlarmMeta: document.getElementById("lastAlarmMeta"),
    modeSelect: document.getElementById("modeSelect"),
    promptInput: document.getElementById("promptInput"),
    sendAssistBtn: document.getElementById("sendAssistBtn"),
    clearPromptBtn: document.getElementById("clearPromptBtn"),
    saveMacroBtn: document.getElementById("saveMacroBtn"),
    assistMeta: document.getElementById("assistMeta"),
    assistResponse: document.getElementById("assistResponse"),
    copyResponseBtn: document.getElementById("copyResponseBtn"),
    incidentId: document.getElementById("incidentId"),
    copyIncidentBtn: document.getElementById("copyIncidentBtn"),
    openIncidentLogsBtn: document.getElementById("openIncidentLogsBtn"),
    policyDemoRow: document.getElementById("policyDemoRow"),
    policyDemoSelect: document.getElementById("policyDemoSelect"),
    policyPreview: document.getElementById("policyPreview"),
    quickSitrep: document.getElementById("quickSitrep"),
    servicesTable: document.getElementById("servicesTable"),
    runtimeInfo: document.getElementById("runtimeInfo"),
    handoverInfo: document.getElementById("handoverInfo"),
    refreshLogsBtn: document.getElementById("refreshLogsBtn"),
    diagBundleBtn: document.getElementById("diagBundleBtn"),
    diagBundleLink: document.getElementById("diagBundleLink"),
    logFiles: document.getElementById("logFiles"),
    logTail: document.getElementById("logTail"),
    logsFilter: document.getElementById("logsFilter"),
    eventTail: document.getElementById("eventTail"),
  };

  function nowIso() {
    return new Date().toISOString();
  }

  function requestId() {
    return "req-ui-" + Date.now().toString(36) + "-" + Math.floor(Math.random() * 100000).toString(36);
  }

  function toUpperOrDash(value) {
    const text = String(value || "").trim();
    return text ? text.toUpperCase() : "-";
  }

  function getQueryParams() {
    return new URLSearchParams(window.location.search || "");
  }

  function queryFlagEnabled(name) {
    const value = String(getQueryParams().get(name) || "").trim().toLowerCase();
    return value === "1" || value === "true" || value === "yes" || value === "on";
  }

  function isDemoModeEnabled() {
    return queryFlagEnabled("demo") || queryFlagEnabled("ui_demo") || queryFlagEnabled("dev");
  }

  function asBool(value) {
    if (typeof value === "boolean") {
      return value;
    }
    if (typeof value === "number") {
      return value !== 0;
    }
    if (typeof value === "string") {
      const text = value.trim().toLowerCase();
      return text === "1" || text === "true" || text === "yes" || text === "on";
    }
    return false;
  }

  async function copyText(text) {
    const value = String(text || "");
    if (!value) {
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
    const temp = document.createElement("textarea");
    temp.value = value;
    document.body.appendChild(temp);
    temp.select();
    document.execCommand("copy");
    document.body.removeChild(temp);
  }

  async function apiGet(path) {
    const res = await fetch(path, { method: "GET" });
    const text = await res.text();
    const data = text ? JSON.parse(text) : {};
    if (!res.ok) {
      const msg = data && data.error ? data.error : `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return data;
  }

  async function apiPost(path, payload) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : {};
    if (!res.ok) {
      const msg = data && data.error ? data.error : `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return data;
  }

  function activateTab(tabId) {
    for (const btn of document.querySelectorAll(".tab-btn")) {
      btn.classList.toggle("active", btn.dataset.tab === tabId);
    }
    for (const panel of document.querySelectorAll(".tab-panel")) {
      panel.classList.toggle("active", panel.id === `tab-${tabId}`);
    }
  }

  function setAssistMeta(text) {
    el.assistMeta.textContent = text || "";
  }

  function setIncidentId(incidentId) {
    const value = String(incidentId || "").trim();
    el.incidentId.textContent = value || "-";
  }

  const DEMO_SCENARIOS = {
    no_actions: {
      incident_id: "inc-demo-no-actions",
      policy_preview: [],
    },
    needs_confirmation: {
      incident_id: "inc-demo-confirm",
      policy_preview: [
        {
          tool: "input.keypress",
          allowed: false,
          requires_confirmation: true,
          confirm_token: "demo-token-123",
          reason_code: "DENY_NEEDS_CONFIRMATION",
          reason_text: "Confirmation required for high-risk tool.",
        },
      ],
    },
    denied: {
      incident_id: "inc-demo-denied",
      policy_preview: [
        {
          tool: "input.keypress",
          allowed: false,
          requires_confirmation: false,
          reason_code: "DENY_NOT_ALLOWED_IN_CONDITION",
          reason_text: "Tool is denied in current watch condition.",
        },
      ],
    },
    mixed: {
      incident_id: "inc-demo-mixed",
      policy_preview: [
        {
          tool: "jinx.set_scene",
          allowed: true,
          requires_confirmation: false,
          reason_code: "ALLOW",
          reason_text: "",
        },
        {
          tool: "input.keypress",
          allowed: false,
          requires_confirmation: true,
          confirm_token: "demo-token-mixed-01",
          reason_code: "DENY_NEEDS_CONFIRMATION",
          reason_text: "Confirmation required before keypress action.",
        },
        {
          tool: "twitch.redeem",
          allowed: false,
          requires_confirmation: false,
          reason_code: "DENY_EXPLICITLY_DENIED",
          reason_text: "Tool denied by current standing orders.",
        },
      ],
    },
  };

  function policyStatus(item) {
    if (item.demo_confirmed) {
      return { label: "Confirmed (demo)", className: "policy-status allowed" };
    }
    if (item.allowed) {
      return { label: "Allowed", className: "policy-status allowed" };
    }
    if (item.requires_confirmation) {
      return { label: "Needs confirm", className: "policy-status confirm" };
    }
    return { label: "Denied", className: "policy-status denied" };
  }

  function buildPolicyLine(label, value, cssClass) {
    const row = document.createElement("div");
    if (cssClass) {
      row.className = cssClass;
    }
    row.textContent = `${label}: ${value}`;
    return row;
  }

  function setPolicyPreviewEmptyState(message) {
    el.policyPreview.innerHTML = "";
    const text = document.createElement("div");
    text.className = "policy-empty";
    text.textContent = String(message || "No proposal received.");
    el.policyPreview.appendChild(text);
    state.lastPolicyPreview = null;
    window.__lastPolicyPreview = null;
  }

  function setPolicyPreviewInvalid(message, detail) {
    el.policyPreview.innerHTML = "";
    const card = document.createElement("div");
    card.className = "policy-item policy-error";
    const title = document.createElement("div");
    title.className = "policy-title";
    title.textContent = String(message || "Invalid proposal");
    card.appendChild(title);
    if (detail) {
      card.appendChild(buildPolicyLine("Detail", String(detail), "policy-reason"));
    }
    el.policyPreview.appendChild(card);
    state.lastPolicyPreview = { error: true, message: message || "Invalid proposal", detail: detail || "" };
    window.__lastPolicyPreview = state.lastPolicyPreview;
  }

  function normalizePolicyPreviewItems(preview) {
    if (!Array.isArray(preview)) {
      throw new Error("policy_preview is not an array");
    }
    const normalized = [];
    for (let idx = 0; idx < preview.length; idx++) {
      const raw = preview[idx];
      if (!raw || typeof raw !== "object") {
        throw new Error(`policy_preview item ${idx} is not an object`);
      }
      const decision = raw.decision && typeof raw.decision === "object" ? raw.decision : {};
      const tool = String(raw.tool || raw.tool_name || "").trim() || "-";
      const allowed = asBool(
        decision.allowed !== undefined && decision.allowed !== null ? decision.allowed : raw.allowed
      );
      const requiresConfirmation = asBool(
        decision.requires_confirmation !== undefined && decision.requires_confirmation !== null
          ? decision.requires_confirmation
          : raw.requires_confirmation
      );
      const confirmToken = String(raw.confirm_token || decision.confirm_token || "").trim();
      const reasonCode = String(
        decision.deny_reason_code || raw.reason_code || (allowed ? "ALLOW" : "")
      ).trim();
      const reasonText = String(decision.deny_reason_text || raw.reason_text || "").trim();
      normalized.push({
        tool,
        allowed,
        requires_confirmation: requiresConfirmation,
        confirm_token: confirmToken,
        reason_code: reasonCode || (requiresConfirmation ? "DENY_NEEDS_CONFIRMATION" : "ALLOW"),
        reason_text: reasonText,
        demo_confirmed: asBool(raw.demo_confirmed),
      });
    }
    return normalized;
  }

  async function handlePolicyConfirm(item, incidentId, source, confirmBtn) {
    if (source === "demo") {
      item.demo_confirmed = true;
      confirmBtn.disabled = true;
      confirmBtn.textContent = "Confirmed (demo)";
      renderPolicyPreview(state.demoPreviewItems || [], incidentId, { source: "demo" });
      return;
    }
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Confirming...";
    try {
      const result = await apiPost("/confirm", {
        incident_id: incidentId,
        tool_name: item.tool,
        user_confirm_token: item.confirm_token,
        request_id: state.lastAssist ? state.lastAssist.request_id : null,
        mode: el.modeSelect.value,
      });
      confirmBtn.textContent = "Confirmed";
      setAssistMeta(`confirmation recorded for ${result.tool_name}`);
      await loadEvents();
    } catch (err) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = "Confirm";
      setAssistMeta(String(err.message || err));
    }
  }

  function renderPolicyPreview(previewInput, incidentId, options = {}) {
    const source = String(options.source || "backend");
    if (options.validationError) {
      setPolicyPreviewInvalid("Invalid proposal", options.validationError);
      return;
    }
    if (previewInput === undefined || previewInput === null) {
      setPolicyPreviewEmptyState("No proposal received.");
      return;
    }

    let items;
    try {
      items = normalizePolicyPreviewItems(previewInput);
    } catch (err) {
      setPolicyPreviewInvalid("Invalid proposal", String(err.message || err));
      return;
    }

    state.lastPolicyPreview = items;
    window.__lastPolicyPreview = items;
    el.policyPreview.innerHTML = "";

    if (!items.length) {
      setPolicyPreviewEmptyState("No actions proposed.");
      return;
    }

    for (const item of items) {
      const status = policyStatus(item);
      const card = document.createElement("div");
      card.className = "policy-item";

      const title = document.createElement("div");
      title.className = "policy-title";
      title.textContent = `Tool: ${item.tool}`;
      card.appendChild(title);

      card.appendChild(buildPolicyLine("Status", status.label, status.className));
      card.appendChild(buildPolicyLine("Reason Code", item.reason_code || "ALLOW", "policy-code"));
      if (item.reason_text) {
        card.appendChild(buildPolicyLine("Reason", item.reason_text, "policy-reason"));
      }
      if (item.confirm_token) {
        card.appendChild(buildPolicyLine("Confirm Token", item.confirm_token, "policy-code"));
      }

      if (item.requires_confirmation && item.confirm_token && !item.demo_confirmed) {
        const row = document.createElement("div");
        row.className = "row policy-item-actions";

        const confirmBtn = document.createElement("button");
        confirmBtn.className = "secondary";
        confirmBtn.textContent = source === "demo" ? "Confirm (demo)" : "Confirm";
        confirmBtn.addEventListener("click", async () => {
          await handlePolicyConfirm(item, incidentId, source, confirmBtn);
        });
        row.appendChild(confirmBtn);

        const copyTokenBtn = document.createElement("button");
        copyTokenBtn.className = "secondary";
        copyTokenBtn.textContent = "Copy Token";
        copyTokenBtn.addEventListener("click", async () => {
          await copyText(item.confirm_token);
          setAssistMeta("confirm token copied");
        });
        row.appendChild(copyTokenBtn);
        card.appendChild(row);
      }

      el.policyPreview.appendChild(card);
    }
  }

  function applyDemoScenario(name) {
    if (!state.demoEnabled) {
      return;
    }
    const selected = String(name || "none").trim().toLowerCase();
    state.demoScenario = selected;
    if (selected === "none") {
      state.demoPreviewItems = null;
      setPolicyPreviewEmptyState("No proposal received.");
      setAssistMeta("demo disabled");
      return;
    }
    const scenario = DEMO_SCENARIOS[selected];
    if (!scenario) {
      setPolicyPreviewInvalid("Invalid proposal", `Unknown demo scenario: ${selected}`);
      return;
    }
    const clonedItems = JSON.parse(JSON.stringify(scenario.policy_preview || []));
    state.demoPreviewItems = clonedItems;
    renderPolicyPreview(clonedItems, scenario.incident_id || "inc-demo", { source: "demo" });
    setAssistMeta(`demo scenario: ${selected}`);
  }

  async function sendAssist() {
    const userText = (el.promptInput.value || "").trim();
    if (!userText) {
      setAssistMeta("prompt is empty");
      return;
    }
    el.sendAssistBtn.disabled = true;
    setAssistMeta("sending /assist...");
    try {
      const payload = {
        schema_version: "1.0",
        request_id: requestId(),
        timestamp_utc: nowIso(),
        mode: el.modeSelect.value,
        domain: "general",
        urgency: "normal",
        user_text: userText,
      };
      const data = await apiPost("/assist", payload);
      state.lastAssist = data;
      const proposal = data.proposal || {};
      el.assistResponse.textContent = proposal.response_text || JSON.stringify(proposal, null, 2);
      setIncidentId(data.incident_id || "");
      const hasPolicyPreview = Object.prototype.hasOwnProperty.call(data, "policy_preview");
      const previewInput = hasPolicyPreview ? data.policy_preview : null;
      const validationError = data.validation_error || data.proposal_error || "";
      renderPolicyPreview(previewInput, data.incident_id || "", {
        source: "backend",
        validationError: validationError || null,
      });
      setAssistMeta(`request ${data.request_id} | actions ${data.queued_actions || 0}`);
      await loadEvents();
      await loadSitrep();
    } catch (err) {
      el.assistResponse.textContent = "";
      setAssistMeta(String(err.message || err));
    } finally {
      el.sendAssistBtn.disabled = false;
    }
  }

  function renderServices(services) {
    const names = Object.keys(services || {});
    if (!names.length) {
      el.servicesTable.textContent = "No service data.";
      return;
    }
    const lines = [];
    for (const name of names) {
      const row = services[name] || {};
      lines.push(`${name}: ${row.status || "unknown"} ${row.ok ? "" : "(down)"}`.trim());
      if (row.error) {
        lines.push(`  error: ${row.error}`);
      }
      if (row.latency_ms !== undefined) {
        lines.push(`  latency_ms: ${row.latency_ms}`);
      }
    }
    el.servicesTable.textContent = lines.join("\n");
  }

  function deriveWatchTier(condition) {
    const value = String(condition || "").toUpperCase();
    if (value === "RESTRICTED") {
      return "RESTRICTED";
    }
    if (value === "DEGRADED") {
      return "DEGRADED";
    }
    return "NORMAL";
  }

  function setTierClass(tier) {
    el.watchTier.classList.remove("tier-normal", "tier-restricted", "tier-degraded");
    if (tier === "RESTRICTED") {
      el.watchTier.classList.add("tier-restricted");
      return;
    }
    if (tier === "DEGRADED") {
      el.watchTier.classList.add("tier-degraded");
      return;
    }
    el.watchTier.classList.add("tier-normal");
  }

  function setOnlineStatus(node, online) {
    node.classList.remove("status-online", "status-offline");
    if (online) {
      node.classList.add("status-online");
      node.textContent = "[+] online";
      return;
    }
    node.classList.add("status-offline");
    node.textContent = "[-] offline";
  }

  function setLatency(node, ms) {
    if (typeof ms === "number" && Number.isFinite(ms)) {
      node.textContent = `~${ms}ms`;
    } else {
      node.textContent = "-";
    }
  }

  function renderQuickSitrep(data) {
    const handover = data.handover || {};
    const ed = handover.ed_state || {};
    const music = handover.music_state || {};
    const alarms = Array.isArray(handover.active_alarms) ? handover.active_alarms.slice(0, 3) : [];

    const lines = [];
    lines.push(`ED running: ${handover.ed_running ? "yes" : "no"}`);
    const fmt = (value) => (value === undefined || value === null || value === "" ? "-" : value);
    lines.push(`ED landed: ${fmt(ed.landed)}`);
    lines.push(`ED shields: ${fmt(ed.shields_up)}`);
    lines.push(`ED lights: ${fmt(ed.lights_on)}`);
    lines.push(`Music playing: ${fmt(music.playing)}`);
    lines.push(`Track: ${music.title || "-"} ${music.artist ? " / " + music.artist : ""}`);
    lines.push("");
    lines.push("Recent alarms:");
    if (!alarms.length) {
      lines.push("- none");
    } else {
      for (const alarm of alarms) {
        lines.push(`- ${alarm.timestamp_utc || "-"} ${alarm.event_type || "-"}`);
      }
    }
    el.quickSitrep.textContent = lines.join("\n");
  }

  function updateBridgePanel(data) {
    const watchCondition = toUpperOrDash(data.watch_condition || "STANDBY");
    const watchTier = deriveWatchTier(watchCondition);
    const handover = data.handover || {};
    const aiState = handover.ai_state || {};
    const services = data.services || {};
    const alarms = Array.isArray(handover.active_alarms) ? handover.active_alarms : [];

    el.watchCondition.textContent = watchCondition;
    el.watchTier.textContent = watchTier;
    setTierClass(watchTier);
    el.watchMode.textContent = toUpperOrDash(aiState.mode || data.runtime?.mode || "standby");

    const advisory = services.advisory || {};
    setOnlineStatus(el.advisoryStatus, Boolean(advisory.ok));
    setLatency(el.advisoryLatency, advisory.latency_ms);

    const knowledge = services.knowledge || {};
    const qdrant = services.qdrant || {};
    const knowledgeDetail = knowledge.detail || {};
    const vectorBackend = String(knowledgeDetail.vector_backend || "").toLowerCase();
    const vectorOnline = vectorBackend === "qdrant" ? Boolean(qdrant.ok) : Boolean(knowledge.ok);
    setOnlineStatus(el.vectorStatus, vectorOnline);
    setLatency(el.vectorLatency, vectorBackend === "qdrant" ? qdrant.latency_ms : knowledge.latency_ms);

    if (alarms.length > 0) {
      const top = alarms[0];
      el.lastAlarmTs.textContent = top.timestamp_utc || "unknown";
      el.lastAlarmMeta.textContent = `${String(top.severity || "").toUpperCase()} ${top.event_type || ""}`.trim();
    } else {
      el.lastAlarmTs.textContent = "none";
      el.lastAlarmMeta.textContent = "-";
    }
  }

  async function loadSitrep() {
    try {
      const data = await apiGet("/sitrep");
      state.latestSitrep = data;
      updateBridgePanel(data);
      renderQuickSitrep(data);
      renderServices(data.services || {});
      el.runtimeInfo.textContent = JSON.stringify(data.runtime || {}, null, 2);
      el.handoverInfo.textContent = JSON.stringify(data.handover || {}, null, 2);
    } catch (err) {
      el.runtimeInfo.textContent = `sitrep error: ${String(err.message || err)}`;
    }
  }

  async function loadLogFiles() {
    try {
      const data = await apiGet("/logs/files");
      const files = data.files || [];
      el.logFiles.innerHTML = "";
      if (!files.length) {
        el.logFiles.textContent = "No logs found.";
        return;
      }
      for (const file of files) {
        const row = document.createElement("div");
        row.className = "row";
        const link = document.createElement("a");
        link.href = file.href;
        link.target = "_blank";
        link.rel = "noopener";
        link.textContent = `${file.name} (${file.size_bytes} bytes)`;
        row.appendChild(link);

        const tailBtn = document.createElement("button");
        tailBtn.className = "secondary";
        tailBtn.textContent = "Tail";
        tailBtn.addEventListener("click", () => {
          state.currentLogFile = file.name;
          loadLogTail();
        });
        row.appendChild(tailBtn);
        el.logFiles.appendChild(row);
      }
      if (!state.currentLogFile && files[0]) {
        state.currentLogFile = files[0].name;
      }
    } catch (err) {
      el.logFiles.textContent = String(err.message || err);
    }
  }

  async function loadLogTail() {
    if (!state.currentLogFile) {
      el.logTail.textContent = "No file selected.";
      return;
    }
    try {
      const data = await apiGet(`/logs/tail?file=${encodeURIComponent(state.currentLogFile)}&lines=120`);
      el.logTail.textContent = (data.lines || []).join("\n");
    } catch (err) {
      el.logTail.textContent = String(err.message || err);
    }
  }

  function renderEventLines(items) {
    const lines = [];
    for (const item of items.slice().reverse()) {
      lines.push(`${item.timestamp_utc} [${item.severity}] ${item.event_type} :: ${item.source}`);
    }
    el.eventTail.textContent = lines.join("\n");
  }

  async function loadEvents(correlationId) {
    try {
      let path = "/events?limit=200";
      if (correlationId) {
        path += `&correlation_id=${encodeURIComponent(correlationId)}`;
        state.eventFilterCorrelationId = correlationId;
        el.logsFilter.textContent = `Filtered by incident/correlation: ${correlationId}`;
      } else if (state.eventFilterCorrelationId) {
        path += `&correlation_id=${encodeURIComponent(state.eventFilterCorrelationId)}`;
        el.logsFilter.textContent = `Filtered by incident/correlation: ${state.eventFilterCorrelationId}`;
      } else {
        el.logsFilter.textContent = "Showing latest global events";
      }
      const data = await apiGet(path);
      const items = Array.isArray(data.items) ? data.items : [];
      renderEventLines(items);
    } catch (err) {
      el.eventTail.textContent = String(err.message || err);
    }
  }

  async function downloadDiagBundle() {
    try {
      const data = await apiPost("/diag/bundle", {});
      if (data.bundle_href) {
        el.diagBundleLink.href = data.bundle_href;
        el.diagBundleLink.textContent = `Download ${data.bundle_name}`;
        window.open(data.bundle_href, "_blank", "noopener");
      }
    } catch (err) {
      el.diagBundleLink.textContent = String(err.message || err);
    }
  }

  function startEventStream() {
    try {
      const es = new EventSource("/events/stream");
      es.addEventListener("event", (evt) => {
        try {
          const item = JSON.parse(evt.data);
          if (
            state.eventFilterCorrelationId &&
            String(item.correlation_id || "") !== String(state.eventFilterCorrelationId)
          ) {
            return;
          }
          state.eventBuffer.push(item);
          if (state.eventBuffer.length > 200) {
            state.eventBuffer = state.eventBuffer.slice(-200);
          }
          const lines = [];
          for (const row of state.eventBuffer) {
            lines.push(`${row.timestamp_utc} [${row.severity}] ${row.event_type} :: ${row.source}`);
          }
          el.eventTail.textContent = lines.join("\n");
        } catch (err) {
          return;
        }
      });
    } catch (err) {
      return;
    }
  }

  function bindPromptShortcuts() {
    el.promptInput.addEventListener("keydown", async (evt) => {
      if (evt.key === "Enter" && evt.ctrlKey) {
        evt.preventDefault();
        await sendAssist();
      }
    });
  }

  function bind() {
    for (const btn of document.querySelectorAll(".tab-btn")) {
      btn.addEventListener("click", () => activateTab(btn.dataset.tab));
    }
    el.sendAssistBtn.addEventListener("click", sendAssist);
    el.clearPromptBtn.addEventListener("click", () => {
      el.promptInput.value = "";
      el.promptInput.focus();
    });
    bindPromptShortcuts();
    el.copyResponseBtn.addEventListener("click", async () => {
      await copyText(el.assistResponse.textContent || "");
      setAssistMeta("response copied");
    });
    el.copyIncidentBtn.addEventListener("click", async () => {
      await copyText(el.incidentId.textContent || "");
      setAssistMeta("incident id copied");
    });
    el.openIncidentLogsBtn.addEventListener("click", async () => {
      const incidentId = String(el.incidentId.textContent || "").trim();
      if (!incidentId || incidentId === "-") {
        return;
      }
      activateTab("logs");
      await loadEvents(incidentId);
    });
    el.refreshLogsBtn.addEventListener("click", async () => {
      await loadLogFiles();
      await loadLogTail();
      await loadEvents();
    });
    el.diagBundleBtn.addEventListener("click", downloadDiagBundle);
    if (el.policyDemoSelect) {
      el.policyDemoSelect.addEventListener("change", () => {
        applyDemoScenario(el.policyDemoSelect.value);
      });
    }
  }

  async function init() {
    state.demoEnabled = isDemoModeEnabled();
    bind();
    setIncidentId("");
    setPolicyPreviewEmptyState("No proposal received.");

    if (el.policyDemoRow) {
      el.policyDemoRow.classList.toggle("is-hidden", !state.demoEnabled);
    }
    if (state.demoEnabled && el.policyDemoSelect) {
      const queryScenario = String(getQueryParams().get("scenario") || "").trim().toLowerCase();
      if (queryScenario && DEMO_SCENARIOS[queryScenario]) {
        el.policyDemoSelect.value = queryScenario;
      }
      applyDemoScenario(el.policyDemoSelect.value);
    }

    await loadSitrep();
    await loadLogFiles();
    await loadLogTail();
    await loadEvents();
    startEventStream();
    setInterval(loadSitrep, 10000);
  }

  init();
})();
