(() => {
  const slotSets = {
    four: ["top_left", "top_right", "bottom_left", "bottom_right"],
    single: ["primary"],
  };
  const defaultPanes = {
    top_left: "system",
    top_right: "ship",
    bottom_left: "conditional",
    bottom_right: "target",
    primary: "system",
  };
  const paneLabels = {
    blank: "Blank",
    conditional: "Messages",
    docking: "Docking Map",
    on_foot_planet: "On Foot Planet",
    on_foot_station: "On Foot Station",
    planet: "Planet",
    route: "Jump Route",
    ship: "Vessel",
    slf: "SLF",
    srv: "SRV",
    station: "Station",
    system: "System",
    target: "Target",
  };
  const contextLabels = {
    docked: "Docked",
    docking_granted: "Docking Granted",
    jump_route: "Jump Route Set",
    jumping: "Jumping",
    on_foot_planet: "On Foot Planet",
    on_foot_station: "On Foot Station",
    planetary_approach: "Planetary Approach",
    slf_deployed: "SLF Deployed",
    srv_deployed: "SRV Deployed",
  };
  const controlLabels = {
    auto_dock: "Dock",
    auto_launch: "Launch",
    cargo_scoop: "Scoop",
    comms_panel: "Comms",
    flight_assist: "FA",
    flight_control: "Flight",
    fss: "FSS",
    galaxy_map: "Galaxy",
    hardpoints: "Hardpoints",
    hyperspace: "Hyper",
    landing_gear: "Gear",
    light_sync: "Sync",
    lights: "Lights",
    management_panel: "Mgmt",
    nav_panel: "Nav",
    night_vision: "NV",
    role_panel: "Role",
    supercruise: "Super",
    system_map: "System",
  };
  const regionSlotCounts = {
    top: 8,
    left: 6,
    right: 6,
  };
  const el = {
    form: document.getElementById("layoutForm"),
    picker: document.getElementById("layoutPicker"),
    name: document.getElementById("layoutName"),
    id: document.getElementById("layoutId"),
    orientation: document.getElementById("orientation"),
    paneMode: document.getElementById("paneMode"),
    buttonsVisible: document.getElementById("buttonsVisible"),
    paneSlots: document.getElementById("paneSlots"),
    buttonRegions: document.getElementById("buttonRegions"),
    bank: document.getElementById("buttonBank"),
    customButtonForm: document.getElementById("customButtonForm"),
    customButtonName: document.getElementById("customButtonName"),
    customButtonIcon: document.getElementById("customButtonIcon"),
    customButtonKeypress: document.getElementById("customButtonKeypress"),
    customButtonMacro: document.getElementById("customButtonMacro"),
    customButtonStatus: document.getElementById("customButtonStatus"),
    newLayout: document.getElementById("newLayout"),
    layoutStatus: document.getElementById("layoutStatus"),
    outputs: document.getElementById("outputs"),
    saveOutputs: document.getElementById("saveOutputs"),
    outputStatus: document.getElementById("outputStatus"),
  };
  const state = {
    catalog: { panes: [], controls: [], contexts: [], button_regions: [] },
    layouts: [],
    outputs: [],
    layout: null,
    draggingButton: null,
    draggingSlot: "",
  };

  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const payload = await response.json();
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.error || `${response.status} ${response.statusText}`);
    }
    return payload;
  }

  function setStatus(node, message, isError = false) {
    node.textContent = message || "";
    node.dataset.error = isError ? "true" : "false";
  }

  function slug(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 64) || `layout-${Date.now()}`;
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function buttonIdFromName(value) {
    return `custom:${slug(value).replace(/-/g, "_")}`;
  }

  function controlCatalog() {
    const catalog = {};
    state.catalog.controls.forEach((id) => {
      catalog[id] = {
        control_id: id,
        label: controlLabels[id] || id,
        icon: "",
        custom: false,
      };
    });
    (state.layout?.custom_controls || []).forEach((control) => {
      catalog[control.control_id] = {
        ...control,
        label: control.label || control.control_id,
        custom: true,
      };
    });
    return catalog;
  }

  function normalizeButtonRegions(layout) {
    layout.custom_controls = Array.isArray(layout.custom_controls) ? layout.custom_controls : [];
    layout.button_regions = layout.button_regions || { top: [], left: [], right: [] };
    state.catalog.button_regions.forEach((region) => {
      const list = Array.isArray(layout.button_regions[region]) ? layout.button_regions[region] : [];
      layout.button_regions[region] = list.map((item, index) => {
        if (item === null) {
          return null;
        }
        if (typeof item === "string") {
          return {
            instance_id: `${region}-${String(index + 1).padStart(2, "0")}-${item.replaceAll("_", "-")}`,
            control_id: item,
          };
        }
        if (!item || typeof item !== "object") {
          return null;
        }
        return {
          instance_id: String(item.instance_id || `${region}-${String(index + 1).padStart(2, "0")}-${String(item.control_id || "button").replaceAll("_", "-")}`),
          control_id: String(item.control_id || item.id || ""),
        };
      });
      while (layout.button_regions[region].length && !layout.button_regions[region][layout.button_regions[region].length - 1]) {
        layout.button_regions[region].pop();
      }
    });
  }

  function newButtonInstance(controlId, region, slotIndex) {
    const suffix = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
    return {
      instance_id: `${region}-${String(slotIndex + 1).padStart(2, "0")}-${controlId.replace(/[^a-z0-9_-]+/gi, "-").toLowerCase()}-${suffix}`,
      control_id: controlId,
    };
  }

  function option(value, label, selectedValue) {
    const node = document.createElement("option");
    node.value = value;
    node.textContent = label;
    node.selected = value === selectedValue;
    return node;
  }

  function sortedLabels(ids, labels) {
    return [...ids].sort((a, b) => (labels[a] || a).localeCompare(labels[b] || b));
  }

  function createSelect(ids, labels, selected) {
    const select = document.createElement("select");
    sortedLabels(ids, labels).forEach((id) => select.appendChild(option(id, labels[id] || id, selected)));
    return select;
  }

  function defaultContextSwitching(enabled = false) {
    return { enabled, rules: [] };
  }

  function guidedLayout() {
    const name = el.name.value.trim() || "New Guided Layout";
    const paneMode = el.paneMode.value;
    return {
      schema_version: "1.0",
      layout_id: slug(el.id.value || name),
      name,
      orientation: el.orientation.value,
      pane_mode: paneMode,
      buttons_visible: el.buttonsVisible.checked,
      button_regions: { top: [], left: [], right: [] },
      custom_controls: clone(state.layout?.custom_controls || []),
      pane_slots: slotSets[paneMode].map((slot) => ({
        slot,
        default_pane: defaultPanes[slot],
        context_switching: defaultContextSwitching(slot === "top_left" || slot === "bottom_right"),
      })),
    };
  }

  function paneSlot(slot) {
    return state.layout.pane_slots.find((item) => item.slot === slot);
  }

  function normalizeVisibleSlotSet() {
    const wanted = slotSets[el.paneMode.value];
    const old = new Map((state.layout?.pane_slots || []).map((item) => [item.slot, item]));
    state.layout.pane_mode = el.paneMode.value;
    state.layout.pane_slots = wanted.map((slot) => old.get(slot) || {
      slot,
      default_pane: defaultPanes[slot],
      context_switching: defaultContextSwitching(),
    });
  }

  function renderContextRows(slotNode, slotState) {
    const list = slotNode.querySelector(".context-list");
    list.replaceChildren();
    const switching = slotState.context_switching || defaultContextSwitching();
    switching.rules.forEach((rule, index) => {
      const row = document.createElement("div");
      row.className = "context-row";
      const context = createSelect(state.catalog.contexts, contextLabels, rule.context);
      const pane = createSelect(state.catalog.panes, paneLabels, rule.pane);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "X";
      context.addEventListener("change", () => {
        switching.rules[index].context = context.value;
      });
      pane.addEventListener("change", () => {
        switching.rules[index].pane = pane.value;
      });
      remove.addEventListener("click", () => {
        switching.rules.splice(index, 1);
        renderContextRows(slotNode, slotState);
      });
      row.append(context, pane, remove);
      list.appendChild(row);
    });
  }

  function renderPaneSlots() {
    normalizeVisibleSlotSet();
    el.paneSlots.dataset.mode = state.layout.pane_mode;
    el.paneSlots.dataset.orientation = state.layout.orientation;
    el.paneSlots.replaceChildren();
    slotSets[state.layout.pane_mode].forEach((slot) => {
      const slotState = paneSlot(slot);
      const card = document.createElement("section");
      card.className = "pane-slot";
      card.dataset.slot = slot;
      card.draggable = true;
      card.addEventListener("dragstart", (event) => {
        state.draggingSlot = slot;
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("application/x-mfd-pane-slot", slot);
      });
      card.addEventListener("dragover", (event) => {
        if (state.draggingSlot) {
          event.preventDefault();
          event.dataTransfer.dropEffect = "move";
        }
      });
      card.addEventListener("drop", (event) => {
        const sourceSlot = event.dataTransfer.getData("application/x-mfd-pane-slot") || state.draggingSlot;
        if (!sourceSlot || sourceSlot === slot) {
          return;
        }
        event.preventDefault();
        const source = paneSlot(sourceSlot);
        const target = paneSlot(slot);
        if (!source || !target) {
          return;
        }
        [source.default_pane, target.default_pane] = [target.default_pane, source.default_pane];
        [source.context_switching, target.context_switching] = [target.context_switching, source.context_switching];
        renderPaneSlots();
      });
      card.addEventListener("dragend", () => {
        state.draggingSlot = "";
      });
      const heading = document.createElement("div");
      heading.className = "slot-heading";
      const title = document.createElement("strong");
      title.textContent = slot.replaceAll("_", " ");
      heading.appendChild(title);

      const pane = createSelect(state.catalog.panes, paneLabels, slotState.default_pane);
      pane.setAttribute("aria-label", `${slot} pane`);
      pane.addEventListener("change", () => {
        slotState.default_pane = pane.value;
      });

      const toggleLabel = document.createElement("label");
      toggleLabel.className = "toggle-row";
      const toggle = document.createElement("input");
      toggle.type = "checkbox";
      toggle.checked = Boolean(slotState.context_switching?.enabled);
      toggle.addEventListener("change", () => {
        slotState.context_switching.enabled = toggle.checked;
      });
      toggleLabel.append(toggle, "Context switching");

      const list = document.createElement("div");
      list.className = "context-list";
      const add = document.createElement("button");
      add.type = "button";
      add.textContent = "Add Context";
      add.addEventListener("click", () => {
        slotState.context_switching.rules.push({
          context: state.catalog.contexts[0] || "docked",
          pane: state.catalog.panes.includes("station") ? "station" : state.catalog.panes[0],
        });
        renderContextRows(card, slotState);
      });
      card.append(heading, pane, toggleLabel, list, add);
      renderContextRows(card, slotState);
      el.paneSlots.appendChild(card);
    });
  }

  function chip(controlId, options = {}) {
    const catalog = controlCatalog();
    const definition = catalog[controlId] || { label: controlLabels[controlId] || controlId };
    const node = document.createElement("span");
    node.className = `control-chip${options.placed ? " placed" : ""}${definition.custom ? " custom" : ""}`;
    node.draggable = true;
    node.dataset.control = controlId;
    if (options.slotNumber) {
      const badge = document.createElement("b");
      badge.textContent = String(options.slotNumber);
      node.appendChild(badge);
    }
    const label = document.createElement("span");
    label.textContent = definition.label || controlId;
    node.appendChild(label);
    if (definition.icon) {
      node.title = `${definition.label} | ${definition.icon}`;
    }
    node.addEventListener("dragstart", (event) => {
      const payload = {
        source: options.placed ? "slot" : "bank",
        control_id: controlId,
        instance_id: options.instanceId || "",
        region: options.region || "",
        index: Number.isInteger(options.index) ? options.index : -1,
      };
      state.draggingButton = payload;
      node.classList.add("dragging");
      event.dataTransfer.effectAllowed = options.placed ? "move" : "copy";
      event.dataTransfer.setData("application/x-mfd-button", JSON.stringify(payload));
      event.dataTransfer.setData("text/plain", controlId);
    });
    node.addEventListener("dragend", () => {
      state.draggingButton = null;
      node.classList.remove("dragging");
    });
    return node;
  }

  function removeButtonInstance(instanceId) {
    if (!instanceId) {
      return;
    }
    Object.values(state.layout.button_regions).forEach((buttons) => {
      const index = buttons.findIndex((item) => item?.instance_id === instanceId);
      if (index >= 0) {
        buttons[index] = null;
      }
      while (buttons.length && !buttons[buttons.length - 1]) {
        buttons.pop();
      }
    });
  }

  function readButtonDrag(event) {
    try {
      const raw = event.dataTransfer.getData("application/x-mfd-button");
      if (raw) {
        return JSON.parse(raw);
      }
    } catch {
      // Fall back below.
    }
    const controlId = event.dataTransfer.getData("text/plain") || state.draggingButton?.control_id;
    return controlId ? { source: "bank", control_id: controlId } : state.draggingButton;
  }

  function placeButton(payload, region, slotIndex) {
    if (!payload?.control_id || !controlCatalog()[payload.control_id]) {
      return;
    }
    const buttons = state.layout.button_regions[region];
    if (!Array.isArray(buttons)) {
      return;
    }
    let instance;
    if (payload.source === "slot" && payload.instance_id) {
      removeButtonInstance(payload.instance_id);
      instance = { instance_id: payload.instance_id, control_id: payload.control_id };
    } else {
      instance = newButtonInstance(payload.control_id, region, slotIndex);
    }
    buttons[slotIndex] = instance;
    while (buttons.length && !buttons[buttons.length - 1]) {
      buttons.pop();
    }
  }

  function makeDropZone(node, region, slotIndex = null) {
    node.ondragover = (event) => {
      event.preventDefault();
      event.dataTransfer.dropEffect = state.draggingButton?.source === "slot" ? "move" : "copy";
    };
    node.ondrop = (event) => {
      event.preventDefault();
      const payload = readButtonDrag(event);
      if (!payload?.control_id) {
        return;
      }
      const targetIndex = Number.isInteger(slotIndex) ? slotIndex : state.layout.button_regions[region].length;
      placeButton(payload, region, targetIndex);
      renderControls();
    };
  }

  function renderControls() {
    el.buttonRegions.replaceChildren();
    el.bank.replaceChildren();
    normalizeButtonRegions(state.layout);
    const catalog = controlCatalog();
    state.catalog.button_regions.forEach((region) => {
      const box = document.createElement("section");
      box.className = "button-region";
      box.dataset.region = region;
      const title = document.createElement("h3");
      title.textContent = `${region} slots`;
      box.appendChild(title);
      if (state.layout.buttons_visible) {
        const buttons = state.layout.button_regions[region];
        const slotCount = Math.max(regionSlotCounts[region] || 0, buttons.length + 1);
        for (let index = 0; index < slotCount; index += 1) {
          const slot = document.createElement("div");
          slot.className = "button-slot";
          slot.dataset.slotNumber = String(index + 1);
          slot.dataset.region = region;
          const number = document.createElement("span");
          number.className = "button-slot-number";
          number.textContent = String(index + 1);
          const button = buttons[index];
          slot.appendChild(number);
          if (button) {
            const placed = chip(button.control_id, {
              placed: true,
              slotNumber: index + 1,
              instanceId: button.instance_id,
              region,
              index,
            });
            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "slot-remove";
            remove.textContent = "X";
            remove.title = "Remove button from this slot";
            remove.addEventListener("click", () => {
              removeButtonInstance(button.instance_id);
              renderControls();
            });
            slot.append(placed, remove);
          } else {
            const empty = document.createElement("span");
            empty.className = "empty-slot";
            empty.textContent = "Drop button";
            slot.appendChild(empty);
          }
          makeDropZone(slot, region, index);
          box.appendChild(slot);
        }
      }
      makeDropZone(box, region);
      el.buttonRegions.appendChild(box);
    });
    Object.keys(catalog).sort((a, b) => String(catalog[a].label).localeCompare(String(catalog[b].label))).forEach((controlId) => {
      el.bank.appendChild(chip(controlId));
    });
    const hint = document.createElement("p");
    hint.className = "bank-hint";
    hint.textContent = "The bank is reusable: drag the same button into as many slots as the layout needs.";
    el.bank.appendChild(hint);
    el.buttonRegions.hidden = !state.layout.buttons_visible;
    el.bank.hidden = !state.layout.buttons_visible;
  }

  function syncFormFromLayout(layout) {
    state.layout = clone(layout);
    normalizeButtonRegions(state.layout);
    el.name.value = state.layout.name;
    el.id.value = state.layout.layout_id;
    el.orientation.value = state.layout.orientation;
    el.paneMode.value = state.layout.pane_mode;
    el.buttonsVisible.checked = Boolean(state.layout.buttons_visible);
    renderPaneSlots();
    renderControls();
  }

  function formLayout() {
    state.layout.name = el.name.value.trim();
    state.layout.layout_id = slug(el.id.value || state.layout.name);
    state.layout.orientation = el.orientation.value;
    state.layout.buttons_visible = el.buttonsVisible.checked;
    normalizeButtonRegions(state.layout);
    normalizeVisibleSlotSet();
    return clone(state.layout);
  }

  function renderLayoutPicker() {
    el.picker.replaceChildren();
    state.layouts.forEach((layout) => {
      const label = `${layout.name}${layout.is_template ? " (template)" : ""}`;
      el.picker.appendChild(option(layout.layout_id, label, state.layout?.layout_id));
    });
  }

  function renderOutputs() {
    el.outputs.replaceChildren();
    state.outputs.forEach((output) => {
      const row = document.createElement("div");
      row.className = "output-row";
      row.dataset.outputId = output.output_id;
      const enabledLabel = document.createElement("label");
      const enabled = document.createElement("input");
      enabled.type = "checkbox";
      enabled.checked = output.enabled;
      enabled.className = "output-enabled";
      enabledLabel.append(enabled, `Output ${output.output_id}`);
      const label = document.createElement("input");
      label.type = "text";
      label.className = "output-label";
      label.value = output.label;
      label.setAttribute("aria-label", `Output ${output.output_id} label`);
      const layout = document.createElement("select");
      layout.className = "output-layout";
      state.layouts.forEach((item) => layout.appendChild(option(item.layout_id, item.name, output.layout_id)));
      const link = document.createElement("a");
      link.href = output.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = output.url;
      row.append(enabledLabel, label, layout, link);
      el.outputs.appendChild(row);
    });
  }

  async function refreshLayouts(selectedLayoutId = "") {
    const payload = await api("/mfd/layouts");
    state.layouts = payload.layouts || [];
    state.catalog = payload.catalog || state.catalog;
    const selected = state.layouts.find((layout) => layout.layout_id === selectedLayoutId)
      || state.layouts.find((layout) => layout.layout_id === el.picker.value)
      || state.layouts[0];
    if (selected) {
      syncFormFromLayout(selected);
    }
    renderLayoutPicker();
  }

  async function refreshOutputs() {
    const payload = await api("/mfd/outputs");
    state.outputs = payload.outputs || [];
    renderOutputs();
  }

  el.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const payload = await api("/mfd/layouts", { method: "POST", body: JSON.stringify(formLayout()) });
      await refreshLayouts(payload.layout.layout_id);
      await refreshOutputs();
      setStatus(el.layoutStatus, `Saved ${payload.layout.name}.`);
    } catch (error) {
      setStatus(el.layoutStatus, error.message, true);
    }
  });

  el.newLayout.addEventListener("click", () => {
    el.name.value = "New Guided Layout";
    el.id.value = `guided-${Date.now()}`;
    syncFormFromLayout(guidedLayout());
    setStatus(el.layoutStatus, "New guided layout ready.");
  });

  el.picker.addEventListener("change", () => {
    const layout = state.layouts.find((item) => item.layout_id === el.picker.value);
    if (layout) {
      syncFormFromLayout(layout);
      setStatus(el.layoutStatus, "");
    }
  });

  el.name.addEventListener("change", () => {
    if (!el.id.value.trim() || el.id.value.startsWith("guided-")) {
      el.id.value = slug(el.name.value);
    }
  });
  el.orientation.addEventListener("change", () => {
    state.layout.orientation = el.orientation.value;
    renderPaneSlots();
  });
  el.paneMode.addEventListener("change", renderPaneSlots);
  el.buttonsVisible.addEventListener("change", () => {
    state.layout.buttons_visible = el.buttonsVisible.checked;
    renderControls();
  });

  el.customButtonForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const label = el.customButtonName.value.trim();
    const keypress = el.customButtonKeypress.value.trim();
    const macro = el.customButtonMacro.value.trim();
    if (!label) {
      setStatus(el.customButtonStatus, "Button name is required.", true);
      return;
    }
    if (!keypress && !macro) {
      setStatus(el.customButtonStatus, "Add a keypress or macro.", true);
      return;
    }
    const baseId = buttonIdFromName(label);
    const existing = new Set((state.layout.custom_controls || []).map((item) => item.control_id));
    let controlId = baseId;
    let suffix = 2;
    while (existing.has(controlId)) {
      controlId = `${baseId}_${suffix}`;
      suffix += 1;
    }
    state.layout.custom_controls.push({
      control_id: controlId,
      label,
      icon: el.customButtonIcon.value.trim(),
      keypress,
      macro,
    });
    el.customButtonForm.reset();
    renderControls();
    setStatus(el.customButtonStatus, `Added ${label} to the button bank.`);
  });

  el.saveOutputs.addEventListener("click", async () => {
    const outputs = Array.from(el.outputs.querySelectorAll(".output-row")).map((row) => ({
      output_id: Number(row.dataset.outputId),
      enabled: row.querySelector(".output-enabled").checked,
      label: row.querySelector(".output-label").value.trim(),
      layout_id: row.querySelector(".output-layout").value,
    }));
    try {
      const payload = await api("/mfd/outputs", { method: "POST", body: JSON.stringify({ outputs }) });
      state.outputs = payload.outputs || [];
      renderOutputs();
      setStatus(el.outputStatus, "Outputs saved.");
    } catch (error) {
      setStatus(el.outputStatus, error.message, true);
    }
  });

  refreshLayouts()
    .then(refreshOutputs)
    .catch((error) => {
      setStatus(el.layoutStatus, error.message, true);
    });
})();
