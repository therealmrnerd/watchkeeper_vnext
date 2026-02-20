(function () {
  const state = {
    lastAssist: null,
    lastPolicyPreview: null,
    lastPolicyContext: { incidentId: "", source: "backend" },
    eventBuffer: [],
    currentLogFile: null,
    eventFilterCorrelationId: null,
    latestSitrep: null,
    demoEnabled: false,
    demoScenario: "none",
    demoPreviewItems: null,
    twitchRecent: [],
    policyView: "pending",
    autoAssistMode: "standby",
    manualAssistMode: null,
  };
  const DEFAULT_CONFIRM_WINDOW_SEC = 12;

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
    modeAutoBtn: document.getElementById("modeAutoBtn"),
    modeNormalBtn: document.getElementById("modeNormalBtn"),
    modeGameBtn: document.getElementById("modeGameBtn"),
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
    policyViewSelect: document.getElementById("policyViewSelect"),
    policyApproveAllBtn: document.getElementById("policyApproveAllBtn"),
    policyDenyAllBtn: document.getElementById("policyDenyAllBtn"),
    policyPreview: document.getElementById("policyPreview"),
    quickSitrep: document.getElementById("quickSitrep"),
    quickNowPlaying: document.getElementById("quickNowPlaying"),
    quickNowPlayingValue: document.getElementById("quickNowPlayingValue"),
    quickAppElite: document.getElementById("quickAppElite"),
    quickAppJinx: document.getElementById("quickAppJinx"),
    quickAppSammi: document.getElementById("quickAppSammi"),
    quickAppYtmd: document.getElementById("quickAppYtmd"),
    quickAppEliteState: document.getElementById("quickAppEliteState"),
    quickAppJinxState: document.getElementById("quickAppJinxState"),
    quickAppSammiState: document.getElementById("quickAppSammiState"),
    quickAppYtmdState: document.getElementById("quickAppYtmdState"),
    servicesTable: document.getElementById("servicesTable"),
    runtimeInfo: document.getElementById("runtimeInfo"),
    handoverInfo: document.getElementById("handoverInfo"),
    quickTwitchChats: document.getElementById("quickTwitchChats"),
    quickTwitchEvents: document.getElementById("quickTwitchEvents"),
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

  function parseIsoToMs(value) {
    if (!value) {
      return null;
    }
    const ms = Date.parse(String(value));
    if (!Number.isFinite(ms)) {
      return null;
    }
    return ms;
  }

  function remainingSecondsLabel(expiresAtMs) {
    if (!Number.isFinite(expiresAtMs) || expiresAtMs <= 0) {
      return "Expires in -";
    }
    const remainMs = expiresAtMs - Date.now();
    if (remainMs <= 0) {
      return "Expired";
    }
    const remainSec = Math.max(1, Math.ceil(remainMs / 1000));
    return `Expires in ${remainSec}s`;
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

  function normalizeAssistMode(value) {
    const mode = String(value || "").trim().toLowerCase();
    if (mode === "game") {
      return "game";
    }
    return "standby";
  }

  function getEffectiveAssistMode() {
    if (state.manualAssistMode) {
      return state.manualAssistMode;
    }
    return normalizeAssistMode(state.autoAssistMode);
  }

  function updateModeButtons() {
    const effective = getEffectiveAssistMode();
    const isAuto = !state.manualAssistMode;
    if (el.modeAutoBtn) {
      el.modeAutoBtn.classList.toggle("active", isAuto);
    }
    if (el.modeNormalBtn) {
      el.modeNormalBtn.classList.toggle("active", effective === "standby" && !isAuto);
    }
    if (el.modeGameBtn) {
      el.modeGameBtn.classList.toggle("active", effective === "game" && !isAuto);
    }
  }

  function setQuickAppState(stateNode, appButton, running) {
    if (!stateNode || !appButton) {
      return;
    }
    const up = Boolean(running);
    stateNode.textContent = up ? "✓" : "✗";
    stateNode.classList.toggle("is-up", up);
    stateNode.classList.toggle("is-down", !up);
    appButton.classList.toggle("is-running", up);
    appButton.classList.toggle("is-stopped", !up);
  }

  async function openQuickApp(appId, buttonNode) {
    const app = String(appId || "").trim().toLowerCase();
    if (!app) {
      return;
    }
    if (buttonNode) {
      buttonNode.disabled = true;
    }
    try {
      const result = await apiPost("/app/open", { app_id: app });
      setAssistMeta(`opened ${result.app_id}`);
    } catch (err) {
      setAssistMeta(`open ${app} failed: ${String(err.message || err)}`);
    } finally {
      if (buttonNode) {
        buttonNode.disabled = false;
      }
    }
  }

  function setIncidentId(incidentId) {
    const value = String(incidentId || "").trim();
    el.incidentId.textContent = value || "-";
  }

  const DEMO_SCENARIOS = {
    all: {
      incident_id: "inc-demo-all",
      policy_preview: [
        {
          tool: "jinx.set_scene",
          allowed: true,
          requires_confirmation: false,
          reason_code: "ALLOW",
          reason_text: "Allowed in GAME mode.",
        },
        {
          tool: "docs.read",
          allowed: true,
          requires_confirmation: false,
          reason_code: "ALLOW",
          reason_text: "Read-only tool available.",
        },
        {
          tool: "input.keypress",
          allowed: false,
          requires_confirmation: true,
          confirm_token: "demo-token-all-01",
          reason_code: "DENY_NEEDS_CONFIRMATION",
          reason_text: "High-risk input action requires confirmation.",
        },
        {
          tool: "files.write",
          allowed: false,
          requires_confirmation: true,
          confirm_token: "demo-token-all-02",
          reason_code: "DENY_NEEDS_CONFIRMATION",
          reason_text: "Write operation requires user confirmation.",
        },
        {
          tool: "twitch.redeem",
          allowed: false,
          requires_confirmation: false,
          reason_code: "DENY_EXPLICITLY_DENIED",
          reason_text: "Denied by standing orders for current watch condition.",
        },
        {
          tool: "input.keypress",
          allowed: false,
          requires_confirmation: false,
          reason_code: "DENY_FOREGROUND_MISMATCH",
          reason_text: "Foreground mismatch detected for input target.",
        },
        {
          tool: "web.search",
          allowed: false,
          requires_confirmation: false,
          reason_code: "DENY_RATE_LIMIT",
          reason_text: "Rate limit exceeded for this minute.",
        },
      ],
    },
    no_actions: {
      incident_id: "inc-demo-no-actions",
      policy_preview: [],
    },
    allowed: {
      incident_id: "inc-demo-allowed",
      policy_preview: [
        {
          tool: "jinx.set_scene",
          allowed: true,
          requires_confirmation: false,
          reason_code: "ALLOW",
          reason_text: "Allowed in GAME mode.",
        },
        {
          tool: "state.write",
          allowed: true,
          requires_confirmation: false,
          reason_code: "ALLOW",
          reason_text: "Low-risk state update allowed.",
        },
        {
          tool: "docs.read",
          allowed: true,
          requires_confirmation: false,
          reason_code: "ALLOW",
          reason_text: "Read-only tool available.",
        },
        {
          tool: "vector.search",
          allowed: true,
          requires_confirmation: false,
          reason_code: "ALLOW",
          reason_text: "Retrieval allowed under current mode.",
        },
      ],
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
        {
          tool: "sammi.trigger_button",
          allowed: false,
          requires_confirmation: true,
          confirm_token: "demo-token-124",
          reason_code: "DENY_NEEDS_CONFIRMATION",
          reason_text: "Confirmation required before SAMMI action.",
        },
        {
          tool: "twitch.redeem",
          allowed: false,
          requires_confirmation: true,
          confirm_token: "demo-token-125",
          reason_code: "DENY_NEEDS_CONFIRMATION",
          reason_text: "External integration requires explicit confirmation.",
        },
        {
          tool: "files.write",
          allowed: false,
          requires_confirmation: true,
          confirm_token: "demo-token-126",
          reason_code: "DENY_NEEDS_CONFIRMATION",
          reason_text: "Write operations require user confirmation.",
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
        {
          tool: "twitch.ban_user",
          allowed: false,
          requires_confirmation: false,
          reason_code: "DENY_EXPLICITLY_DENIED",
          reason_text: "Twitch tools denied by standing orders.",
        },
        {
          tool: "files.write",
          allowed: false,
          requires_confirmation: false,
          reason_code: "DENY_EXPLICITLY_DENIED",
          reason_text: "File writes denied in current mode.",
        },
        {
          tool: "input.keypress",
          allowed: false,
          requires_confirmation: false,
          reason_code: "DENY_FOREGROUND_MISMATCH",
          reason_text: "Foreground process mismatch for input action.",
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
        {
          tool: "docs.read",
          allowed: true,
          requires_confirmation: false,
          reason_code: "ALLOW",
          reason_text: "Read operation allowed.",
        },
        {
          tool: "files.write",
          allowed: false,
          requires_confirmation: true,
          confirm_token: "demo-token-mixed-02",
          reason_code: "DENY_NEEDS_CONFIRMATION",
          reason_text: "Confirm required for write path.",
        },
        {
          tool: "input.keypress",
          allowed: false,
          requires_confirmation: false,
          reason_code: "DENY_RATE_LIMIT",
          reason_text: "Rate limit exceeded for this tool.",
        },
      ],
    },
  };

  function policyStatus(item) {
    if (item.demo_confirmed) {
      return {
        label: "Confirmed (demo)",
        className: "policy-status allowed",
        badgeClass: "policy-badge policy-badge-allowed",
        toneClass: "policy-item--allowed",
      };
    }
    if (item.allowed) {
      return {
        label: "Allowed",
        className: "policy-status allowed",
        badgeClass: "policy-badge policy-badge-allowed",
        toneClass: "policy-item--allowed",
      };
    }
    if (item.requires_confirmation) {
      return {
        label: "Needs confirm",
        className: "policy-status confirm",
        badgeClass: "policy-badge policy-badge-confirm",
        toneClass: "policy-item--confirm",
      };
    }
    return {
      label: "Denied",
      className: "policy-status denied",
      badgeClass: "policy-badge policy-badge-denied",
      toneClass: "policy-item--denied",
    };
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

  function getPolicyViewMode() {
    const raw = String((el.policyViewSelect && el.policyViewSelect.value) || state.policyView || "pending").trim().toLowerCase();
    return raw === "all" ? "all" : "pending";
  }

  function isPolicyPending(item) {
    if (!item || typeof item !== "object") {
      return false;
    }
    if (item.demo_confirmed || item.operator_denied) {
      return false;
    }
    if (!item.requires_confirmation || !item.confirm_token) {
      return false;
    }
    if (item.runtime_state === "executed" || item.runtime_state === "failed") {
      return false;
    }
    if (item.expires_at_ms && Number.isFinite(item.expires_at_ms) && Date.now() >= item.expires_at_ms) {
      return false;
    }
    return true;
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
      const decisionConstraints =
        decision.constraints && typeof decision.constraints === "object" ? decision.constraints : {};
      const confirmByRaw =
        raw.confirm_by_ts || decision.confirm_by_ts || decisionConstraints.confirm_by_ts || "";
      const rawExpiresAtMs = Number(raw.expires_at_ms || 0);
      let expiresAtMs = Number.isFinite(rawExpiresAtMs) && rawExpiresAtMs > 0 ? rawExpiresAtMs : 0;
      if (!expiresAtMs) {
        const parsedMs = parseIsoToMs(confirmByRaw);
        if (parsedMs) {
          expiresAtMs = parsedMs;
        }
      }
      if (!expiresAtMs && requiresConfirmation && confirmToken) {
        expiresAtMs = Date.now() + DEFAULT_CONFIRM_WINDOW_SEC * 1000;
      }
      const reasonCode = String(
        decision.deny_reason_code || raw.reason_code || (allowed ? "ALLOW" : "")
      ).trim();
      const reasonText = String(decision.deny_reason_text || raw.reason_text || "").trim();
      normalized.push({
        tool,
        allowed,
        requires_confirmation: requiresConfirmation,
        confirm_token: confirmToken,
        confirm_by_ts: String(confirmByRaw || "").trim() || null,
        expires_at_ms: expiresAtMs || 0,
        reason_code: reasonCode || (requiresConfirmation ? "DENY_NEEDS_CONFIRMATION" : "ALLOW"),
        reason_text: reasonText,
        demo_confirmed: asBool(raw.demo_confirmed),
        runtime_state: String(raw.runtime_state || "").trim().toLowerCase(),
        runtime_message: String(raw.runtime_message || "").trim(),
      });
    }
    return normalized;
  }

  async function handlePolicyConfirm(item, incidentId, source, options = {}) {
    const suppressRefresh = Boolean(options.suppressRefresh);
    if (source === "demo") {
      item.demo_confirmed = true;
      item.runtime_state = "executed";
      item.runtime_message = "Demo confirmation accepted.";
      renderPolicyPreview(state.demoPreviewItems || [], incidentId, { source: "demo", normalized: true });
      return;
    }
    const incident = String(incidentId || state.lastPolicyContext.incidentId || "").trim();
    if (!incident) {
      item.runtime_state = "failed";
      item.runtime_message = "Missing incident_id";
      renderPolicyPreview(state.lastPolicyPreview || [], incidentId, { source, normalized: true });
      setAssistMeta("missing incident id for confirm");
      return;
    }
    item.runtime_state = "executing";
    item.runtime_message = "";
    renderPolicyPreview(state.lastPolicyPreview || [], incident, { source, normalized: true });
    try {
      const result = await apiPost("/confirm", {
        incident_id: incident,
        confirm_token: item.confirm_token,
      });
      item.runtime_state = "executed";
      item.runtime_message = "Executed successfully.";
      setAssistMeta(`confirmation recorded for ${result.tool_name}`);
      renderPolicyPreview(state.lastPolicyPreview || [], incident, { source, normalized: true });
      if (!suppressRefresh) {
        await Promise.allSettled([loadEvents(incident), loadSitrep()]);
      }
    } catch (err) {
      item.runtime_state = "failed";
      item.runtime_message = String(err.message || err).slice(0, 120);
      renderPolicyPreview(state.lastPolicyPreview || [], incident, { source, normalized: true });
      setAssistMeta(String(err.message || err));
    }
  }

  async function approvePendingPolicies() {
    const source = String(state.lastPolicyContext.source || "backend");
    const incident = String(state.lastPolicyContext.incidentId || "").trim();
    const items = Array.isArray(state.lastPolicyPreview) ? state.lastPolicyPreview : [];
    const pending = items.filter(isPolicyPending);
    if (!pending.length) {
      setAssistMeta("no pending requests");
      return;
    }
    if (el.policyApproveAllBtn) {
      el.policyApproveAllBtn.disabled = true;
    }
    let approved = 0;
    try {
      for (const item of pending) {
        await handlePolicyConfirm(item, incident, source, { suppressRefresh: true });
        if (item.runtime_state === "executed") {
          approved += 1;
        }
      }
      setAssistMeta(`approved ${approved}/${pending.length} pending`);
      await Promise.allSettled([loadEvents(incident), loadSitrep()]);
    } finally {
      if (el.policyApproveAllBtn) {
        el.policyApproveAllBtn.disabled = false;
      }
    }
  }

  function denyPendingPolicies() {
    const incident = String(state.lastPolicyContext.incidentId || "").trim();
    const source = String(state.lastPolicyContext.source || "backend");
    const items = Array.isArray(state.lastPolicyPreview) ? state.lastPolicyPreview : [];
    const pending = items.filter(isPolicyPending);
    if (!pending.length) {
      setAssistMeta("no pending requests");
      return;
    }
    for (const item of pending) {
      item.operator_denied = true;
      item.allowed = false;
      item.requires_confirmation = false;
      item.reason_code = "DENY_EXPLICITLY_DENIED";
      item.reason_text = "Denied by operator.";
      item.runtime_state = "failed";
      item.runtime_message = "Denied by operator.";
    }
    renderPolicyPreview(items, incident, { source, normalized: true });
    setAssistMeta(`denied ${pending.length} pending`);
  }

  function renderPolicyPreview(previewInput, incidentId, options = {}) {
    const source = String(options.source || "backend");
    const normalizedInput = Boolean(options.normalized);
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
      items = normalizedInput ? previewInput : normalizePolicyPreviewItems(previewInput);
    } catch (err) {
      setPolicyPreviewInvalid("Invalid proposal", String(err.message || err));
      return;
    }

    state.lastPolicyPreview = items;
    state.lastPolicyContext = { incidentId: String(incidentId || ""), source };
    window.__lastPolicyPreview = items;
    el.policyPreview.innerHTML = "";

    if (!items.length) {
      setPolicyPreviewEmptyState("No actions proposed.");
      return;
    }

    const viewMode = getPolicyViewMode();
    state.policyView = viewMode;
    const displayItems = viewMode === "pending" ? items.filter(isPolicyPending) : items;
    if (!displayItems.length) {
      el.policyPreview.innerHTML = "";
      const text = document.createElement("div");
      text.className = "policy-empty";
      text.textContent = viewMode === "pending" ? "No pending requests." : "No actions proposed.";
      el.policyPreview.appendChild(text);
      return;
    }

    for (const item of displayItems) {
      const status = policyStatus(item);
      const card = document.createElement("div");
      card.className = `policy-item ${status.toneClass}`;

      const title = document.createElement("div");
      title.className = "policy-title";
      title.textContent = `Tool: ${item.tool}`;
      card.appendChild(title);

      const statusRow = document.createElement("div");
      statusRow.className = "policy-status-row";
      const statusLabel = document.createElement("span");
      statusLabel.className = "policy-status-label";
      statusLabel.textContent = "Status:";
      const statusBadge = document.createElement("span");
      statusBadge.className = status.badgeClass;
      statusBadge.textContent = status.label;
      statusRow.appendChild(statusLabel);
      statusRow.appendChild(statusBadge);
      card.appendChild(statusRow);

      if (item.runtime_state) {
        const runtime = document.createElement("div");
        runtime.className = `policy-runtime policy-runtime--${item.runtime_state}`;
        if (item.runtime_state === "executing") {
          runtime.textContent = "Executing...";
        } else if (item.runtime_state === "executed") {
          runtime.textContent = `Executed \u2713${item.runtime_message ? ` ${item.runtime_message}` : ""}`;
        } else if (item.runtime_state === "failed") {
          runtime.textContent = `Failed \u2717${item.runtime_message ? ` ${item.runtime_message}` : ""}`;
        } else {
          runtime.textContent = item.runtime_message || item.runtime_state;
        }
        card.appendChild(runtime);
      }

      if (item.reason_text) {
        card.appendChild(buildPolicyLine("Reason", item.reason_text, "policy-reason"));
      }

      if (item.reason_code) {
        const details = document.createElement("details");
        details.className = "policy-tech-details";
        const summary = document.createElement("summary");
        summary.textContent = "Details";
        details.appendChild(summary);
        details.appendChild(buildPolicyLine("Reason Code", item.reason_code || "ALLOW", "policy-code"));
        card.appendChild(details);
      }

      if (item.confirm_token) {
        const tokenLine = document.createElement("div");
        tokenLine.className = "policy-code policy-token-line";
        tokenLine.textContent = `Confirm Token: ${item.confirm_token}`;
        tokenLine.title = "Click to copy token";
        tokenLine.addEventListener("click", async () => {
          await copyText(item.confirm_token);
          setAssistMeta("confirm token copied");
        });
        card.appendChild(tokenLine);
      }

      if (item.requires_confirmation && item.confirm_token && !item.demo_confirmed) {
        const expiry = document.createElement("div");
        expiry.className = "policy-expiry";
        expiry.dataset.expiryMs = String(item.expires_at_ms || 0);
        expiry.textContent = remainingSecondsLabel(item.expires_at_ms || 0);
        card.appendChild(expiry);
      }

      const row = document.createElement("div");
      row.className = "row policy-item-actions";

      const notExpired = !item.expires_at_ms || Date.now() < item.expires_at_ms;
      const canConfirm =
        item.requires_confirmation &&
        Boolean(item.confirm_token) &&
        !item.demo_confirmed &&
        notExpired &&
        item.runtime_state !== "executing";
      const confirmBtn = document.createElement("button");
      confirmBtn.className = "secondary policy-action-btn policy-confirm-btn";
      if (item.demo_confirmed) {
        confirmBtn.textContent = "Confirmed";
        confirmBtn.disabled = true;
      } else if (!notExpired && item.requires_confirmation && item.confirm_token) {
        confirmBtn.textContent = "Expired";
        confirmBtn.disabled = true;
      } else if (item.runtime_state === "executing") {
        confirmBtn.textContent = "Executing...";
        confirmBtn.disabled = true;
      } else if (canConfirm) {
        confirmBtn.textContent = source === "demo" ? "Confirm (demo)" : "Confirm";
      } else {
        confirmBtn.textContent = "No Confirm";
        confirmBtn.disabled = true;
      }
      if (canConfirm) {
        confirmBtn.addEventListener("click", async () => {
          await handlePolicyConfirm(item, incidentId, source);
        });
      }
      row.appendChild(confirmBtn);

      const copyTokenBtn = document.createElement("button");
      copyTokenBtn.className = "secondary policy-action-btn";
      if (item.confirm_token) {
        copyTokenBtn.textContent = "Copy Token";
        copyTokenBtn.addEventListener("click", async () => {
          await copyText(item.confirm_token);
          setAssistMeta("confirm token copied");
        });
      } else {
        copyTokenBtn.textContent = "No Token";
        copyTokenBtn.disabled = true;
      }
      row.appendChild(copyTokenBtn);
      card.appendChild(row);

      el.policyPreview.appendChild(card);
    }
    updateConfirmExpiryLabels();
  }

  function updateConfirmExpiryLabels() {
    const nodes = document.querySelectorAll(".policy-expiry[data-expiry-ms]");
    for (const node of nodes) {
      const expiryMs = Number(node.getAttribute("data-expiry-ms") || "0");
      node.textContent = remainingSecondsLabel(expiryMs);
      const card = node.closest(".policy-item");
      const confirmBtn = card ? card.querySelector(".policy-confirm-btn") : null;
      if (!confirmBtn) {
        continue;
      }
      if (expiryMs > 0 && Date.now() >= expiryMs) {
        if (!confirmBtn.disabled || confirmBtn.textContent !== "Expired") {
          confirmBtn.disabled = true;
          confirmBtn.textContent = "Expired";
        }
      }
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
        mode: getEffectiveAssistMode(),
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
    if (!el.servicesTable) {
      return;
    }
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
    if (!node) {
      return;
    }
    let nextText = "-";
    if (typeof ms === "number" && Number.isFinite(ms)) {
      nextText = `~${ms}ms`;
    }
    if (node.textContent === nextText) {
      return;
    }
    node.textContent = nextText;
    node.classList.remove("latency-tick");
    void node.offsetWidth;
    node.classList.add("latency-tick");
  }

  function formatClock(tsValue) {
    if (!tsValue) {
      return "-";
    }
    const asNum = Number(tsValue);
    if (Number.isFinite(asNum) && String(tsValue).indexOf("T") === -1) {
      const dt = new Date(asNum * 1000);
      if (Number.isFinite(dt.getTime())) {
        return dt.toLocaleTimeString();
      }
    }
    const dt = new Date(String(tsValue));
    if (!Number.isFinite(dt.getTime())) {
      return String(tsValue);
    }
    return dt.toLocaleTimeString();
  }

  function normalizeTwitchItem(raw) {
    const item = raw && typeof raw === "object" ? raw : {};
    const wrapped = item.payload && typeof item.payload === "object" ? item.payload : {};
    const nested = wrapped.payload && typeof wrapped.payload === "object" ? wrapped.payload : {};
    const eventType = String(item.event_type || wrapped.event_type || "").trim().toUpperCase();
    const commitTs = String(item.commit_ts || nested.commit_ts || "").trim();
    const displayName =
      String(wrapped.display_name || nested.display_name || wrapped.login_name || nested.login_name || item.user_id || "")
        .trim() || "unknown";
    return {
      eventType,
      commitTs,
      userId: String(item.user_id || wrapped.user_id || nested.user_id || "").trim(),
      displayName,
      wrapped,
      nested,
    };
  }

  function eventIconMeta(eventType) {
    const key = String(eventType || "").toUpperCase();
    const table = {
      CHAT: { glyph: "C", css: "evt-chat", label: "Chat" },
      BITS: { glyph: "B", css: "evt-bits", label: "Bits" },
      FOLLOW: { glyph: "F", css: "evt-follow", label: "Follow" },
      REDEEM: { glyph: "R", css: "evt-redeem", label: "Redeem" },
      SUB: { glyph: "S", css: "evt-sub", label: "Sub" },
      RAID: { glyph: "D", css: "evt-raid", label: "Raid" },
      SHOUTOUT: { glyph: "O", css: "evt-shoutout", label: "Shoutout" },
      POLL: { glyph: "P", css: "evt-poll", label: "Poll" },
      PREDICTION: { glyph: "P", css: "evt-prediction", label: "Prediction" },
      HYPE_TRAIN: { glyph: "H", css: "evt-hype", label: "Hype Train" },
      POWER_UPS: { glyph: "U", css: "evt-powerups", label: "Power Ups" },
    };
    return table[key] || { glyph: "?", css: "evt-unknown", label: key || "Event" };
  }

  function summarizeTwitchItem(item) {
    const normalized = normalizeTwitchItem(item);
    const eventType = normalized.eventType;
    const nested = normalized.nested;
    const display = normalized.displayName;
    if (eventType === "CHAT") {
      const msg = String(nested.message_text || nested.message || "").trim() || "(empty)";
      return `${display}: ${msg}`;
    }
    if (eventType === "BITS") {
      const amount = nested.amount !== undefined && nested.amount !== null ? nested.amount : "?";
      return `${display} cheered ${amount}`;
    }
    if (eventType === "FOLLOW") {
      return `${display} followed`;
    }
    if (eventType === "REDEEM") {
      const reward = String(nested.reward_title || nested.reward_id || "reward").trim();
      return `${display} redeemed ${reward}`;
    }
    if (eventType === "SUB") {
      const tier = String(nested.tier || "").trim();
      return tier ? `${display} subscribed (${tier})` : `${display} subscribed`;
    }
    if (eventType === "RAID") {
      const viewers = nested.viewer_count !== undefined && nested.viewer_count !== null ? nested.viewer_count : "?";
      return `${display} raided (${viewers})`;
    }
    if (eventType === "SHOUTOUT") {
      const target = String(nested.target_display_name || nested.target_login_name || "").trim();
      return target ? `${display} shouted out ${target}` : `${display} shoutout`;
    }
    return `${display} ${eventType.toLowerCase()}`;
  }

  function twitchSortMs(item) {
    const normalized = normalizeTwitchItem(item);
    const rawTs = String(normalized.commitTs || "").trim();
    if (!rawTs) {
      return 0;
    }
    const asNum = Number(rawTs);
    if (Number.isFinite(asNum)) {
      return rawTs.indexOf("T") === -1 ? asNum * 1000 : asNum;
    }
    const parsed = Date.parse(rawTs);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
    return 0;
  }

  function renderQuickTwitchEventCards(items) {
    if (!el.quickTwitchEvents) {
      return;
    }
    el.quickTwitchEvents.innerHTML = "";
    const recent = Array.isArray(items) ? items.slice(0, 3) : [];
    if (!recent.length) {
      const empty = document.createElement("div");
      empty.className = "quick-twitch-empty";
      empty.textContent = "- none";
      el.quickTwitchEvents.appendChild(empty);
      return;
    }

    for (const item of recent) {
      const normalized = normalizeTwitchItem(item);
      const meta = eventIconMeta(normalized.eventType);
      const card = document.createElement("div");
      card.className = "quick-twitch-event-card";

      const icon = document.createElement("span");
      icon.className = `quick-twitch-event-icon ${meta.css}`;
      icon.textContent = meta.glyph;
      icon.title = meta.label;

      const body = document.createElement("div");
      body.className = "quick-twitch-event-body";

      const title = document.createElement("div");
      title.className = "quick-twitch-event-title";
      title.textContent = `${meta.label}  ${formatClock(normalized.commitTs)}`;

      const desc = document.createElement("div");
      desc.className = "quick-twitch-event-desc";
      desc.textContent = summarizeTwitchItem(item);

      body.appendChild(title);
      body.appendChild(desc);
      card.appendChild(icon);
      card.appendChild(body);
      el.quickTwitchEvents.appendChild(card);
    }
  }

  function renderQuickTwitchSummary(items) {
    if (!el.quickTwitchEvents && !el.quickTwitchChats) {
      return;
    }
    const recent = Array.isArray(items) ? items : [];
    const sortedRecent = recent.slice().sort((left, right) => twitchSortMs(right) - twitchSortMs(left));
    const chats = sortedRecent.filter((item) => normalizeTwitchItem(item).eventType === "CHAT").slice(0, 5);
    const latestEvents = sortedRecent
      .filter((item) => normalizeTwitchItem(item).eventType !== "CHAT")
      .slice(0, 3);

    if (el.quickTwitchChats) {
      if (!chats.length) {
        el.quickTwitchChats.textContent = "- none";
      } else {
        const lines = chats.map((item) => {
          const normalized = normalizeTwitchItem(item);
          const text = summarizeTwitchItem(item);
          return `${formatClock(normalized.commitTs)}  ${text}`;
        });
        el.quickTwitchChats.textContent = lines.join("\n");
      }
    }

    renderQuickTwitchEventCards(latestEvents);
  }

  async function loadTwitchRecent() {
    try {
      const data = await apiGet("/twitch/recent?limit=120");
      const items = Array.isArray(data.items) ? data.items : [];
      state.twitchRecent = items;
      renderQuickTwitchSummary(items);
      if (state.latestSitrep) {
        renderQuickSitrep(state.latestSitrep);
      }
    } catch (err) {
      if (el.quickTwitchChats) {
        el.quickTwitchChats.textContent = `error: ${String(err.message || err)}`;
      }
      if (el.quickTwitchEvents) {
        el.quickTwitchEvents.innerHTML = "";
        const errorNode = document.createElement("div");
        errorNode.className = "quick-twitch-empty";
        errorNode.textContent = `error: ${String(err.message || err)}`;
        el.quickTwitchEvents.appendChild(errorNode);
      }
    }
  }

  function renderQuickSitrep(data) {
    const handover = data.handover || {};
    const music = handover.music_state || {};
    const apps = handover.apps || {};
    setQuickAppState(el.quickAppEliteState, el.quickAppElite, Boolean(apps.ed_running ?? handover.ed_running));
    setQuickAppState(el.quickAppJinxState, el.quickAppJinx, Boolean(apps.jinx_running));
    setQuickAppState(el.quickAppSammiState, el.quickAppSammi, Boolean(apps.sammi_running));
    setQuickAppState(el.quickAppYtmdState, el.quickAppYtmd, Boolean(apps.ytmd_running));
    if (el.quickNowPlayingValue) {
      el.quickNowPlayingValue.textContent = `${music.title || "-"}${music.artist ? ` / ${music.artist}` : ""}`;
    }
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
    const detectedMode = normalizeAssistMode(aiState.mode || data.runtime?.mode || "standby");
    state.autoAssistMode = detectedMode;
    el.watchMode.textContent = toUpperOrDash(detectedMode);
    updateModeButtons();

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
      if (el.runtimeInfo) {
        el.runtimeInfo.textContent = JSON.stringify(data.runtime || {}, null, 2);
      }
      if (el.handoverInfo) {
        el.handoverInfo.textContent = JSON.stringify(data.handover || {}, null, 2);
      }
    } catch (err) {
      if (el.runtimeInfo) {
        el.runtimeInfo.textContent = `sitrep error: ${String(err.message || err)}`;
      }
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
    if (el.policyViewSelect) {
      el.policyViewSelect.addEventListener("change", () => {
        state.policyView = getPolicyViewMode();
        if (Array.isArray(state.lastPolicyPreview)) {
          renderPolicyPreview(
            state.lastPolicyPreview,
            state.lastPolicyContext.incidentId || "",
            { source: state.lastPolicyContext.source || "backend", normalized: true }
          );
        }
      });
    }
    if (el.policyApproveAllBtn) {
      el.policyApproveAllBtn.addEventListener("click", approvePendingPolicies);
    }
    if (el.policyDenyAllBtn) {
      el.policyDenyAllBtn.addEventListener("click", denyPendingPolicies);
    }
    if (el.quickAppElite) {
      el.quickAppElite.addEventListener("click", () => openQuickApp("elite", el.quickAppElite));
    }
    if (el.quickAppJinx) {
      el.quickAppJinx.addEventListener("click", () => openQuickApp("jinx", el.quickAppJinx));
    }
    if (el.quickAppSammi) {
      el.quickAppSammi.addEventListener("click", () => openQuickApp("sammi", el.quickAppSammi));
    }
    if (el.quickAppYtmd) {
      el.quickAppYtmd.addEventListener("click", () => openQuickApp("ytmd", el.quickAppYtmd));
    }
    if (el.modeAutoBtn) {
      el.modeAutoBtn.addEventListener("click", () => {
        state.manualAssistMode = null;
        updateModeButtons();
        setAssistMeta(`assist mode: auto (${getEffectiveAssistMode()})`);
      });
    }
    if (el.modeNormalBtn) {
      el.modeNormalBtn.addEventListener("click", () => {
        state.manualAssistMode = "standby";
        updateModeButtons();
        setAssistMeta("assist mode: normal");
      });
    }
    if (el.modeGameBtn) {
      el.modeGameBtn.addEventListener("click", () => {
        state.manualAssistMode = "game";
        updateModeButtons();
        setAssistMeta("assist mode: game");
      });
    }
  }

  async function init() {
    state.demoEnabled = isDemoModeEnabled();
    bind();
    updateModeButtons();
    setIncidentId("");
    setPolicyPreviewEmptyState("No proposal received.");
    if (el.policyViewSelect) {
      el.policyViewSelect.value = "pending";
    }

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
    await loadTwitchRecent();
    await loadLogFiles();
    await loadLogTail();
    await loadEvents();
    startEventStream();
    setInterval(loadSitrep, 10000);
    setInterval(loadTwitchRecent, 6000);
    setInterval(updateConfirmExpiryLabels, 500);
  }

  init();
})();
