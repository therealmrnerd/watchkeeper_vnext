(function () {
  const el = {
    clock: document.getElementById("mfdClock"),
    updated: document.getElementById("mfdUpdated"),
    safety: document.getElementById("mfdSafety"),
    system: document.getElementById("mfdSystem"),
    systemPane: document.getElementById("mfdSystemPane"),
    systemAddress: document.getElementById("mfdSystemAddress"),
    systemAllegiance: document.getElementById("mfdSystemAllegiance"),
    systemFaction: document.getElementById("mfdSystemFaction"),
    systemPower: document.getElementById("mfdSystemPower"),
    systemPowerState: document.getElementById("mfdSystemPowerState"),
    systemGovernment: document.getElementById("mfdSystemGovernment"),
    systemEconomy: document.getElementById("mfdSystemEconomy"),
    systemSecurity: document.getElementById("mfdSystemSecurity"),
    systemPopulation: document.getElementById("mfdSystemPopulation"),
    currentRefuel: document.getElementById("mfdCurrentRefuel"),
    currentStarClass: document.getElementById("mfdCurrentStarClass"),
    station: document.getElementById("mfdStation"),
    body: document.getElementById("mfdBody"),
    mode: document.getElementById("mfdMode"),
    shipCanvas: document.getElementById("mfdShipCanvas"),
    shipViewTitle: document.getElementById("mfdShipViewTitle"),
    shipName: document.getElementById("mfdShipName"),
    shipReadouts: document.getElementById("mfdShipReadouts"),
    shipViewPrev: document.getElementById("mfdShipViewPrev"),
    shipViewNext: document.getElementById("mfdShipViewNext"),
    fuelSegments: document.getElementById("mfdFuelSegments"),
    statusIcons: document.getElementById("mfdStatusIcons"),
    shield: document.getElementById("mfdShield"),
    fuel: document.getElementById("mfdFuel"),
    cargo: document.getElementById("mfdCargo"),
    pips: document.getElementById("mfdPips"),
    legal: document.getElementById("mfdLegal"),
    lastEvent: document.getElementById("mfdLastEvent"),
    targetName: document.getElementById("mfdTargetName"),
    routePane: document.getElementById("mfdRoutePane"),
    routeTargetSystem: document.getElementById("mfdRouteTargetSystem"),
    routeTargetAddress: document.getElementById("mfdRouteTargetAddress"),
    routeDistance: document.getElementById("mfdRouteDistance"),
    routeJumps: document.getElementById("mfdRouteJumps"),
    routeNextJump: document.getElementById("mfdRouteNextJump"),
    routeStarClass: document.getElementById("mfdRouteStarClass"),
    routeUpcoming: document.getElementById("mfdRouteUpcoming"),
    targetStatus: document.getElementById("mfdTargetStatus"),
    fireGroup: document.getElementById("mfdFireGroup"),
    guiFocus: document.getElementById("mfdGuiFocus"),
    analysisMode: document.getElementById("mfdAnalysisMode"),
    targetPane: document.getElementById("mfdTargetPane"),
    slfPane: document.getElementById("mfdSlfPane"),
    slfName: document.getElementById("mfdSlfName"),
    slfStatus: document.getElementById("mfdSlfStatus"),
    slfSchematic: document.getElementById("mfdSlfSchematic"),
    slfMothership: document.getElementById("mfdSlfMothership"),
    slfSystem: document.getElementById("mfdSlfSystem"),
    slfLoadout: document.getElementById("mfdSlfLoadout"),
    slfControl: document.getElementById("mfdSlfControl"),
    slfShield: document.getElementById("mfdSlfShield"),
    slfHull: document.getElementById("mfdSlfHull"),
    slfMode: document.getElementById("mfdSlfMode"),
    slfFireGroup: document.getElementById("mfdSlfFireGroup"),
    slfPips: document.getElementById("mfdSlfPips"),
    slfHardpoints: document.getElementById("mfdSlfHardpoints"),
    planetPane: document.getElementById("mfdPlanetPane"),
    planetBody: document.getElementById("mfdPlanetBody"),
    planetStatus: document.getElementById("mfdPlanetStatus"),
    planetSystem: document.getElementById("mfdPlanetSystem"),
    planetFlightStatus: document.getElementById("mfdPlanetFlightStatus"),
    planetPosition: document.getElementById("mfdPlanetPosition"),
    planetAltitude: document.getElementById("mfdPlanetAltitude"),
    planetHeading: document.getElementById("mfdPlanetHeading"),
    planetTemp: document.getElementById("mfdPlanetTemp"),
    planetMode: document.getElementById("mfdPlanetMode"),
    planetLegal: document.getElementById("mfdPlanetLegal"),
    footPlanetPane: document.getElementById("mfdOnFootPlanetPane"),
    footPlanetSuit: document.getElementById("mfdFootPlanetSuit"),
    footPlanetStatus: document.getElementById("mfdFootPlanetStatus"),
    footPlanetBody: document.getElementById("mfdFootPlanetBody"),
    footPlanetPosition: document.getElementById("mfdFootPlanetPosition"),
    footPlanetHeading: document.getElementById("mfdFootPlanetHeading"),
    footPlanetWeapon: document.getElementById("mfdFootPlanetWeapon"),
    footPlanetLoadout: document.getElementById("mfdFootPlanetLoadout"),
    footPlanetOxygen: document.getElementById("mfdFootPlanetOxygen"),
    footPlanetHealth: document.getElementById("mfdFootPlanetHealth"),
    footPlanetEnvironment: document.getElementById("mfdFootPlanetEnvironment"),
    srvPane: document.getElementById("mfdSrvPane"),
    srvName: document.getElementById("mfdSrvName"),
    srvStatus: document.getElementById("mfdSrvStatus"),
    srvSchematic: document.getElementById("mfdSrvSchematic"),
    srvMothership: document.getElementById("mfdSrvMothership"),
    srvBody: document.getElementById("mfdSrvBody"),
    srvSystem: document.getElementById("mfdSrvSystem"),
    srvPosition: document.getElementById("mfdSrvPosition"),
    srvHeading: document.getElementById("mfdSrvHeading"),
    srvAltitude: document.getElementById("mfdSrvAltitude"),
    srvMode: document.getElementById("mfdSrvMode"),
    srvFireGroup: document.getElementById("mfdSrvFireGroup"),
    srvPips: document.getElementById("mfdSrvPips"),
    srvCargo: document.getElementById("mfdSrvCargo"),
    srvLegal: document.getElementById("mfdSrvLegal"),
    srvHull: document.getElementById("mfdSrvHull"),
    footStationPane: document.getElementById("mfdOnFootStationPane"),
    footStationSuit: document.getElementById("mfdFootStationSuit"),
    footStationStatus: document.getElementById("mfdFootStationStatus"),
    footStationName: document.getElementById("mfdFootStationName"),
    footStationServices: document.getElementById("mfdFootStationServices"),
    footStationLoadout: document.getElementById("mfdFootStationLoadout"),
    footStationWeapon: document.getElementById("mfdFootStationWeapon"),
    footStationArea: document.getElementById("mfdFootStationArea"),
    footStationSystem: document.getElementById("mfdFootStationSystem"),
    footStationAllegiance: document.getElementById("mfdFootStationAllegiance"),
    footStationGovernment: document.getElementById("mfdFootStationGovernment"),
    targetPilot: document.getElementById("mfdTargetPilot"),
    targetLegal: document.getElementById("mfdTargetLegal"),
    targetScan: document.getElementById("mfdTargetScan"),
    targetRank: document.getElementById("mfdTargetRank"),
    targetFaction: document.getElementById("mfdTargetFaction"),
    targetPower: document.getElementById("mfdTargetPower"),
    targetShield: document.getElementById("mfdTargetShield"),
    targetHull: document.getElementById("mfdTargetHull"),
    targetShieldBar: document.getElementById("mfdTargetShieldBar"),
    targetHullBar: document.getElementById("mfdTargetHullBar"),
    targetSchematic: document.getElementById("mfdTargetSchematic"),
    adviceList: document.getElementById("mfdAdviceList"),
    lampLights: document.getElementById("mfdLampLights"),
    lampGear: document.getElementById("mfdLampGear"),
    lampScoop: document.getElementById("mfdLampScoop"),
    lampHardpoints: document.getElementById("mfdLampHardpoints"),
    shipSchematic: document.getElementById("mfdShipSchematic"),
    shieldImage: document.getElementById("mfdShieldImage"),
    shieldEnvelope: document.getElementById("mfdShieldEnvelope"),
    shieldBands: [
      document.getElementById("mfdShieldBand1"),
      document.getElementById("mfdShieldBand2"),
      document.getElementById("mfdShieldBand3"),
    ],
    fullscreenGate: document.getElementById("mfdFullscreenGate"),
    fullscreenButton: document.getElementById("mfdFullscreenButton"),
    installHint: document.getElementById("mfdInstallHint"),
    core: document.querySelector(".mfd-core"),
    lightSyncToggle: document.getElementById("mfdLightSyncToggle"),
    autoDockButton: document.getElementById("mfdAutoDockButton"),
    autoLaunchButton: document.getElementById("mfdAutoLaunchButton"),
  };
  let latestSafety = { input_locked: true };
  let runtimeSettings = null;
  let lightSyncEnabled = false;
  let settingsBusy = false;
  let wakeLock = null;
  let latestTelemetry = {};
  let shipViewIndex = 0;
  let shipViewManual = false;
  let currentShieldEnvelope = "";
  let previousShieldPercent = null;
  let mfdStream = null;
  let lastStreamAt = 0;
  let fallbackPollTimer = null;
  let safetyPinnedUntil = 0;
  let hyperspaceGraceUntil = 0;
  let hyperspaceGraceTimer = null;
  let systemScrambleTimer = null;
  const HYPERSPACE_CANCEL_GRACE_MS = 5000;
  const SCRAMBLE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-";
  const LIGHT_SYNC_ID = "jinx_lighting";
  const dockAllowedActions = new Set([
    "lights",
    "nav_panel",
    "comms_panel",
    "role_panel",
    "management_panel",
    "galaxy_map",
    "system_map",
    "fss",
    "flight_control",
    "repair_refuel",
    "auto_launch",
    "lights",
    "night_vision",
  ]);
  const shipSlugAliases = {
    anaconda: "anaconda",
    anaconda_mk2: "anaconda",
    asp: "asp-explorer",
    asp_scout: "asp-scout",
    asp_scout_mk2: "asp-scout",
    beluga: "beluga",
    belugaliner: "beluga",
    caspian_explorer: "caspian-explorer",
    caspianexplorer: "caspian-explorer",
    explorer_nx: "caspian-explorer",
    cobra_mk3: "cobra-mk-3",
    cobra_mk4: "cobra-mk-4",
    diamondback: "diamondback-scout",
    diamondbackxl: "diamondback-explorer",
    dolphin: "dolphin",
    eagle: "eagle",
    empire_fighter: "gu97",
    empire_courier: "imperial-courier",
    empire_eagle: "imperial-eagle",
    empire_trader: "imperial-clipper",
    cutter: "imperial-cutter",
    federation_corvette: "federal-corvette",
    federation_dropship: "federal-dropship",
    federation_dropship_mkii: "federal-assault-ship",
    federation_fighter: "f63",
    federation_gunship: "federal-gunship",
    ferdelance: "fer-de-lance",
    fer_de_lance: "fer-de-lance",
    hauler: "hauler",
    independent_fighter: "taipan",
    keelback: "keelback",
    krait_light: "python",
    krait_mkii: "python",
    orca: "orca",
    python: "python",
    sidewinder: "sidewinder",
    taipan: "taipan",
    testbuggy_scorpion: "scarab-srv",
    testbuggy: "scarab-srv",
    combat_sr_vehicle: "scarab-srv",
    type6: "type6",
    type7: "type7",
    type9: "type9",
    type9_military: "type9",
    viper: "viper-mk-3",
    viper_mk4: "viper-mk-4",
    vulture: "vulture",
  };
  const edsaSchematicAliases = {
    beluga: "beluga-liner",
    "cobra-mk-3": "cobra-mk-iii",
    "cobra-mk-4": "cobra-mk-iv",
    f63: "slf-f63-condor",
    gu97: "slf-gu-97",
    taipan: "slf-taipan",
    type6: "type-6-transporter",
    type7: "type-7-transporter",
    type9: "type-9-heavy",
  };
  const edsaSchematicVersion = "3";
  const pairedSchematicVersion = "4";
  const shieldEnvelopeVersion = "7";
  const pairedSchematicShips = new Set(["anaconda"]);
  const shipsWithoutShieldEnvelope = new Set(["caspian-explorer"]);
  const edsaSchematics = new Set([
    "adder",
    "alliance-challenger",
    "alliance-chieftain",
    "alliance-crusader",
    "anaconda",
    "asp-explorer",
    "asp-scout",
    "beluga-liner",
    "cobra-mk-iii",
    "cobra-mk-iv",
    "cobra-mk-v",
    "corsair",
    "diamondback-explorer",
    "diamondback-scout",
    "dolphin",
    "eagle",
    "federal-assault-ship",
    "federal-corvette",
    "federal-dropship",
    "federal-gunship",
    "fer-de-lance",
    "hauler",
    "imperial-clipper",
    "imperial-courier",
    "imperial-cutter",
    "imperial-eagle",
    "keelback",
    "krait-mk-ii",
    "krait-phantom",
    "mamba",
    "mandalay",
    "orca",
    "python",
    "python-mk-ii",
    "sidewinder",
    "slf-f63-condor",
    "slf-gu-97",
    "slf-taipan",
    "slf-xg7-trident",
    "slf-xg8-javelin",
    "slf-xg9-lance",
    "type-10-defender",
    "type-6-transporter",
    "type-7-transporter",
    "type-8-transporter",
    "type-9-heavy",
    "viper-mk-iii",
    "viper-mk-iv",
    "vulture",
  ]);
  const edsaHardpointSizes = {
    "adder": ["M", "S", "S"],
    "anaconda": ["H", "L", "L", "L", "M", "M", "S", "S"],
    "caspian-explorer": ["M", "M", "", "", "M", "M"],
    "asp-explorer": ["M", "M", "S", "S", "S", "S"],
    "asp-scout": ["M", "M", "S", "S"],
    "cobra-mk-3": ["M", "M", "S", "S"],
    "cobra-mk-4": ["M", "M", "S", "S", "S"],
    "diamondback-explorer": ["L", "M", "M"],
    "diamondback-scout": ["M", "M", "S", "S"],
    "dolphin": ["S", "S"],
    "eagle": ["S", "S", "S"],
    "federal-assault-ship": ["L", "L", "M", "M"],
    "federal-corvette": ["H", "H", "L", "M", "M", "S", "S"],
    "federal-dropship": ["L", "M", "M", "M", "M"],
    "federal-gunship": ["L", "M", "M", "M", "M", "S", "S"],
    "fer-de-lance": ["H", "M", "M", "M", "M"],
    "hauler": ["S"],
    "imperial-clipper": ["L", "L", "M", "M"],
    "imperial-courier": ["M", "M", "M"],
    "imperial-cutter": ["H", "L", "L", "M", "M", "M", "M"],
    "imperial-eagle": ["M", "S", "S"],
    "keelback": ["M", "M", "S", "S"],
    "orca": ["L", "M", "M"],
    "python": ["L", "L", "L", "M", "M"],
    "sidewinder": ["S", "S"],
    "type6": ["S", "S"],
    "type7": ["S", "S", "S", "S"],
    "type9": ["M", "M", "M", "S", "S"],
    "vulture": ["L", "L"],
  };
  const edsaHardpointPoints = {
    "adder": [[49.29, 17.77], [52.26, 23.13], [46.31, 23.13]],
    "anaconda": [[49.99, 37.5], [49.99, 33.86], [46.41, 25.45], [53.48, 25.45], [45.05, 28.89], [54.83, 28.89], [49.15, 41.97], [50.79, 41.97]],
    "caspian-explorer": [[43.5, 31.5], [56.5, 31.5], [50, 50], [50, 50], [43.5, 21.5], [56.5, 21.5]],
    "asp-explorer": [[52.69, 20.45], [47.28, 20.45], [52.9, 23.77], [47.05, 23.77], [50.57, 25.48], [49.4, 25.48]],
    "asp-scout": [[52.7, 20.45], [47.28, 20.45], [50.6, 25.48], [49.4, 25.48]],
    "beluga": [[45.74, -10.24], [54.18, -10.24], [38.76, 39.3], [60.82, 39.3], [49.99, 38.84]],
    "cobra-mk-3": [[48.33, 22.69], [52.56, 22.69], [38.99, 24.39], [61.54, 24.39]],
    "cobra-mk-4": [[48.33, 22.69], [52.56, 22.69], [48.67, 19.34], [52.16, 19.34], [50.45, 19.5]],
    "diamondback-explorer": [[49.98, 25.86], [47.28, 23.03], [52.69, 23.03]],
    "diamondback-scout": [[47.28, 23.03], [52.69, 23.03], [48.97, 23.03], [51, 23.03]],
    "dolphin": [[49.03, 22.28], [51.07, 22.28]],
    "eagle": [[50, 19.23], [49.34, 24.06], [50.61, 24.06]],
    "f63": [[49.34, 22.03], [50.61, 22.03]],
    "federal-assault-ship": [[49.99, 24.41], [49.99, 11.42], [45.37, 25.56], [54.44, 25.56]],
    "federal-corvette": [[47.84, 19.97], [52.18, 19.97], [49.97, 37.16], [39.61, 31.38], [60.1, 31.38], [48.23, 27.06], [51.78, 27.06]],
    "federal-dropship": [[49.99, 24.41], [54.44, 25.56], [45.37, 25.56], [41.08, 22.7], [58.68, 22.7]],
    "federal-gunship": [[49.99, 24.58], [55.48, 23.19], [44.37, 23.27], [45.37, 25.92], [54.44, 25.92], [48.62, 10.69], [51.36, 10.69]],
    "fer-de-lance": [[49.66, 28.84], [51.86, 24.61], [47.44, 24.61], [44.44, 26.16], [54.86, 26.16]],
    "gu97": [[49.45, 21.33], [50.55, 21.31]],
    "hauler": [[51.9, 22.94]],
    "imperial-clipper": [[15.78, 20.67], [82.67, 20.67], [33.69, 30.95], [64.64, 30.95]],
    "imperial-courier": [[57.16, 23.55], [42.66, 23.55], [49.99, 23.69]],
    "imperial-cutter": [[48.95, 36], [45.77, 9.43], [51.92, 9.43], [42.22, 38.14], [55.44, 38.14], [0.72, 11.74], [94.77, 11.74]],
    "imperial-eagle": [[50, 19.23], [49.34, 24.06], [50.61, 24.06]],
    "keelback": [[45.72, 17.13], [54.1, 17.13], [45.34, 25.62], [54.54, 25.62]],
    "orca": [[51.06, 28.7], [57.09, 28.53], [44.94, 28.64]],
    "python": [[57.03, 19.59], [44.36, 19.59], [50.79, 26.72], [55.03, 21.02], [46.49, 21.02]],
    "sidewinder": [[48.7, 21.8], [51.26, 21.8]],
    "taipan": [[49.49, 21.13], [50.52, 21.13]],
    "type6": [[45.34, 25.62], [54.54, 25.62]],
    "type7": [[47.15, 21.78], [52.94, 21.78], [47.82, 24.78], [49.98, 1.14]],
    "type9": [[49.98, 34.41], [24.08, 6.99], [74.68, 6.99], [46.41, 25.19], [53.49, 25.19]],
    "viper-mk-3": [[47.21, 23.38], [52.76, 23.38], [48.57, 21.8], [51.48, 21.8]],
    "viper-mk-4": [[46.7, 23.73], [53.3, 23.7], [48.57, 21.8], [51.48, 21.8]],
    "vulture": [[46.08, 18.19], [53.79, 18.19]],
  };
  const physicalHardpointPoints = {
    "anaconda": [[50, 34], [50, 43], [43.8, 30.6], [56.2, 30.6], [43.0, 12.2], [57.0, 12.2], [53.1, 80.7], [46.9, 80.7]],
  };
  const shipViews = [
    {
      title: "Weapons",
      moduleGroup: "weapons",
      rows: [
        { label: "Mode", type: "mode", value: (t) => t.analysis_mode ? "Analysis" : "Combat" },
        { label: "Shield", type: "percent", value: (t) => t.shields_up === false ? 0 : 100 },
        { label: "Hull", type: "percent", value: (t) => t.hull_percent ?? t.hull ?? 100 },
        { label: "Pips", type: "pips", value: (t) => t.pips },
        { label: "Weapons", type: "modules", value: (t) => ({ modules: t.modules, hardpoints: t.hardpoints, group: "weapons" }) },
      ],
    },
    {
      title: "Modules",
      moduleGroup: "modules",
      rows: [
        { label: "Mode", type: "mode", value: (t) => t.analysis_mode ? "Analysis" : "Combat" },
        { label: "Shield", type: "percent", value: (t) => t.shields_up === false ? 0 : 100 },
        { label: "Hull", type: "percent", value: (t) => t.hull_percent ?? t.hull ?? 100 },
        { label: "Pips", type: "pips", value: (t) => t.pips },
        { label: "Modules", type: "modules", value: (t) => ({ modules: t.modules, group: "modules" }) },
      ],
    },
  ];

  function text(value) {
    if (value === null || value === undefined || value === "") {
      return "-";
    }
    if (Array.isArray(value)) {
      return value.join(" / ");
    }
    if (typeof value === "object") {
      return JSON.stringify(value);
    }
    return String(value);
  }

  function scrambleText(value) {
    const source = String(value || "");
    if (!source.trim()) {
      return "-";
    }
    return Array.from(source, (char) => {
      if (/\s/.test(char)) {
        return " ";
      }
      return SCRAMBLE_CHARS[Math.floor(Math.random() * SCRAMBLE_CHARS.length)];
    }).join("");
  }

  function setText(node, value) {
    if (node) {
      node.textContent = text(value);
    }
  }

  function setField(node, label, value) {
    if (!node) {
      return;
    }
    const labelNode = node.parentElement ? node.parentElement.querySelector(".mfd-label") : null;
    if (labelNode && label) {
      labelNode.textContent = label;
    }
    node.textContent = text(value);
  }

  function setSystemNameField(label, value, scramble) {
    if (!el.system) {
      return;
    }
    if (systemScrambleTimer) {
      clearInterval(systemScrambleTimer);
      systemScrambleTimer = null;
    }
    setField(el.system, label, scramble ? scrambleText(value) : value);
    if (scramble) {
      systemScrambleTimer = setInterval(() => {
        setField(el.system, label, scrambleText(value));
      }, 95);
    }
  }

  function setSafetyMessage(message, options = {}) {
    if (!el.safety) {
      return;
    }
    const now = Date.now();
    if (!options.force && safetyPinnedUntil > now) {
      return;
    }
    el.safety.textContent = text(message);
    el.safety.dataset.priority = options.priority || "normal";
    if (options.pinMs) {
      safetyPinnedUntil = now + Number(options.pinMs);
      window.setTimeout(() => {
        if (Date.now() >= safetyPinnedUntil && el.safety) {
          el.safety.dataset.priority = "normal";
        }
      }, Number(options.pinMs) + 20);
    } else if (options.force || safetyPinnedUntil <= now) {
      safetyPinnedUntil = 0;
    }
  }

  async function apiGet(path) {
    const res = await fetch(path, { method: "GET" });
    const raw = await res.text();
    const data = raw ? JSON.parse(raw) : {};
    if (!res.ok) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
  }

  async function apiPost(path, payload) {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const raw = await res.text();
    const data = raw ? JSON.parse(raw) : {};
    if (!res.ok) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
  }

  function runtimeSyncEnabled(syncId, fallback = true) {
    const syncs = runtimeSettings && runtimeSettings.syncs && typeof runtimeSettings.syncs === "object"
      ? runtimeSettings.syncs
      : {};
    const item = syncs[syncId];
    if (!item || typeof item !== "object" || typeof item.enabled !== "boolean") {
      return fallback;
    }
    return item.enabled;
  }

  function setLightSyncToggleState() {
    if (!el.lightSyncToggle) {
      return;
    }
    const enabled = lightSyncEnabled;
    el.lightSyncToggle.dataset.active = enabled ? "true" : "false";
    el.lightSyncToggle.dataset.unavailable = settingsBusy ? "true" : "false";
    el.lightSyncToggle.dataset.settingToggle = "true";
    el.lightSyncToggle.disabled = settingsBusy;
    el.lightSyncToggle.setAttribute("aria-pressed", enabled ? "true" : "false");
    el.lightSyncToggle.title = enabled ? "Light Sync On" : "Light Sync Off";
  }

  async function refreshRuntimeSettings() {
    const payload = await apiGet("/settings");
    runtimeSettings = payload && typeof payload === "object" ? payload.settings || null : null;
    setLightSyncToggleState();
  }

  async function forceLightSyncOffForSession() {
    lightSyncEnabled = false;
    settingsBusy = true;
    setLightSyncToggleState();
    try {
      const result = await apiPost("/mfd/light-sync", { enabled: false });
      runtimeSettings = result && typeof result === "object" ? result.settings || runtimeSettings : runtimeSettings;
    } catch (_err) {
      // Keep the MFD switch visually off even if the bridge is temporarily unavailable.
    } finally {
      lightSyncEnabled = false;
      settingsBusy = false;
      setLightSyncToggleState();
    }
  }

  function collectRuntimeSettingsWithSync(syncId, enabled) {
    const current = runtimeSettings && typeof runtimeSettings === "object" ? runtimeSettings : {};
    const providers = current.providers && typeof current.providers === "object" ? current.providers : {};
    const syncs = current.syncs && typeof current.syncs === "object" ? current.syncs : {};
    const nextProviders = {};
    const nextSyncs = {};
    Object.entries(providers).forEach(([key, item]) => {
      if (item && typeof item === "object" && typeof item.enabled === "boolean") {
        nextProviders[key] = { enabled: item.enabled };
      }
    });
    Object.entries(syncs).forEach(([key, item]) => {
      if (item && typeof item === "object" && typeof item.enabled === "boolean") {
        nextSyncs[key] = { enabled: key === syncId ? enabled : item.enabled };
      }
    });
    if (!nextSyncs[syncId]) {
      nextSyncs[syncId] = { enabled };
    }
    return {
      schema_version: "1.0",
      providers: nextProviders,
      syncs: nextSyncs,
    };
  }

  async function toggleLightSync() {
    if (settingsBusy) {
      return;
    }
    settingsBusy = true;
    setLightSyncToggleState();
    try {
      if (!runtimeSettings) {
        await refreshRuntimeSettings();
      }
      const nextEnabled = !lightSyncEnabled;
      const result = await apiPost("/mfd/light-sync", { enabled: nextEnabled });
      runtimeSettings = result && typeof result === "object" ? result.settings || runtimeSettings : runtimeSettings;
      lightSyncEnabled = Boolean(result && result.enabled);
      setLightSyncToggleState();
      if (el.safety) {
        const jinx = result && result.jinx && result.jinx.effect ? ` ${result.jinx.effect}` : "";
        el.safety.textContent = `Light Sync: ${nextEnabled ? "On" : "Off"}${jinx}`;
      }
    } catch (err) {
      if (el.safety) {
        el.safety.textContent = `Light Sync error: ${String(err.message || err)}`;
      }
    } finally {
      settingsBusy = false;
      setLightSyncToggleState();
    }
  }

  function setControlState(t, semantic = {}) {
    const now = Date.now();
    const guiFocus = Number(t.gui_focus);
    const inHyperspace = Boolean(t.in_hyperspace || t.fsd_jump || semantic.flight_status === "hyperspace");
    const jumpInitiated = Boolean(t.fsd_hyperdrive_charging || t.fsd_jump || inHyperspace);
    const hyperspaceCancelWindow = Boolean(now < hyperspaceGraceUntil);
    const massLocked = Boolean(t.fsd_mass_locked);
    const docked = Boolean(t.docked);
    const landed = Boolean(t.landed || t.touchdown || semantic.flight_status === "landed");
    const hardpointsOpen = Boolean(t.hardpoints_deployed);
    const cargoScoopOpen = Boolean(t.cargo_scoop_deployed);
    const landingGearDown = Boolean(t.landing_gear_down);
    const fsdBlocked = Boolean(massLocked || docked || landed || hardpointsOpen || cargoScoopOpen || landingGearDown);
    const hasHyperspaceTarget = hasHyperspaceDestination(t, semantic);
    const normalFlight = Boolean(!docked && !landed && !t.supercruise && !inHyperspace && !jumpInitiated);
    const dockingState = String(semantic.docking_state || "").toLowerCase();
    const dockingActive = ["requested", "granted", "approaching", "docking", "docked"].includes(dockingState);
    const canAutoDock = Boolean(!t.docked && !dockingActive && (semantic.can_request_docking || (semantic.no_fire_zone && normalFlight)));
    const canAutoLaunch = Boolean(t.docked);
    if (el.autoDockButton) {
      el.autoDockButton.hidden = !canAutoDock;
      el.autoDockButton.dataset.active = canAutoDock ? "true" : "false";
      el.autoDockButton.dataset.unavailable = canAutoDock ? "false" : "true";
      el.autoDockButton.disabled = false;
    }
    if (el.autoLaunchButton) {
      el.autoLaunchButton.hidden = !canAutoLaunch;
      el.autoLaunchButton.dataset.active = canAutoLaunch ? "true" : "false";
      el.autoLaunchButton.dataset.unavailable = canAutoLaunch ? "false" : "true";
      el.autoLaunchButton.disabled = false;
      const missingLimpets = Boolean(t.has_limpet_controller && t.has_cargo_rack && Number(t.limpet_count || 0) <= 0);
      el.autoLaunchButton.dataset.warning = missingLimpets ? "limpets" : "false";
      el.autoLaunchButton.title = missingLimpets ? "Auto launch: limpets missing" : "Auto launch";
    }
    const mapping = {
      landing_gear: landingGearDown,
      hardpoints: hardpointsOpen,
      lights: Boolean(t.lights_on),
      night_vision: Boolean(t.night_vision),
      cargo_scoop: cargoScoopOpen,
      flight_assist: Boolean(t.flight_assist_off),
      supercruise: Boolean(t.supercruise),
      hyperspace: inHyperspace || jumpInitiated,
      flight_control: guiFocus === 0,
      management_panel: guiFocus === 1,
      nav_panel: guiFocus === 2,
      comms_panel: guiFocus === 3,
      role_panel: guiFocus === 4,
      auto_dock: canAutoDock,
      auto_launch: canAutoLaunch,
      repair_refuel: Boolean(t.docked && semantic.station_services_available),
    };
    const unavailableByAction = {
      supercruise: fsdBlocked || inHyperspace || jumpInitiated,
      hyperspace: !hyperspaceCancelWindow && (fsdBlocked || inHyperspace || jumpInitiated || !hasHyperspaceTarget),
      fss: docked || !t.supercruise,
      hardpoints: Boolean(docked || t.supercruise || inHyperspace),
      flight_assist: Boolean(docked),
      cargo_scoop: !normalFlight,
      landing_gear: !normalFlight,
    };
    const inputLocked = Boolean(latestSafety.input_locked);
    for (const btn of document.querySelectorAll(".mfd-control")) {
      if (btn.classList.contains("mfd-control-blank")) {
        btn.dataset.active = "false";
        btn.dataset.unavailable = "false";
        btn.dataset.inputLocked = "false";
        btn.dataset.dockLocked = "false";
        btn.disabled = true;
        continue;
      }
      if (btn.dataset.settingToggle === "true") {
        continue;
      }
      const action = btn.dataset.action;
      const dockLocked = docked && !dockAllowedActions.has(action);
      const unavailable = dockLocked || Boolean(unavailableByAction[action]);
      btn.dataset.active = mapping[action] ? "true" : "false";
      btn.dataset.unavailable = unavailable ? "true" : "false";
      btn.dataset.inputLocked = inputLocked ? "true" : "false";
      btn.dataset.dockLocked = dockLocked ? "true" : "false";
      btn.disabled = false;
    }
    setLightSyncToggleState();
  }

  function slug(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }

  function shipAssetName(model) {
    const raw = String(model || "").trim().toLowerCase();
    const normalized = raw.replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    const dashed = slug(model);
    return shipSlugAliases[normalized] || shipSlugAliases[dashed.replaceAll("-", "_")] || dashed || "sidewinder";
  }

  function vehicleName(model, fallback) {
    const name = shipAssetName(model);
    if (name === "taipan") {
      return "Taipan";
    }
    if (name === "gu97") {
      return "GU-97";
    }
    if (name === "f63") {
      return "F63 Condor";
    }
    if (name === "scarab-srv") {
      return "Scarab SRV";
    }
    return text(model || fallback);
  }

  function schematicSrc(name) {
    if (pairedSchematicShips.has(name)) {
      return `Schematics/paired/${name}-schematic.png?v=${pairedSchematicVersion}`;
    }
    const edsaName = edsaSchematicAliases[name] || name;
    if (edsaSchematics.has(edsaName)) {
      return `Schematics/edsa/topdown/${edsaName}.svg?v=${edsaSchematicVersion}`;
    }
    return `Schematics/topdown/${name}.png`;
  }

  function setShipSchematic(model) {
    if (!el.shipSchematic) {
      return;
    }
    const name = shipAssetName(model);
    const next = schematicSrc(name);
    if (el.shipCanvas) {
      el.shipCanvas.dataset.ship = name;
    }
    if (name === "sidewinder" && el.shipCanvas) {
      el.shipCanvas.dataset.shieldImage = "true";
    }
    setShieldEnvelope(name);
    if (el.shipSchematic.getAttribute("src") === next) {
      return;
    }
    el.shipSchematic.onerror = () => {
      el.shipSchematic.onerror = null;
      currentShieldEnvelope = "";
      if (el.shipCanvas) {
        el.shipCanvas.dataset.ship = "sidewinder";
      }
      el.shipSchematic.src = schematicSrc("sidewinder");
      setShieldEnvelope("sidewinder");
    };
    el.shipSchematic.src = next;
  }

  function setTargetSchematic(model, locked) {
    if (!el.targetSchematic) {
      return;
    }
    if (!locked) {
      el.targetSchematic.onerror = null;
      el.targetSchematic.dataset.ship = "";
      el.targetSchematic.dataset.locked = "false";
      el.targetSchematic.removeAttribute("src");
      return;
    }
    const name = shipAssetName(model);
    const next = schematicSrc(name);
    el.targetSchematic.dataset.ship = name;
    el.targetSchematic.dataset.locked = "true";
    if (el.targetSchematic.getAttribute("src") === next) {
      return;
    }
    el.targetSchematic.onerror = () => {
      el.targetSchematic.onerror = null;
      el.targetSchematic.dataset.ship = "sidewinder";
      el.targetSchematic.src = schematicSrc("sidewinder");
    };
    el.targetSchematic.src = next;
  }

  function setVehicleSchematic(node, model, fallback) {
    if (!node) {
      return;
    }
    const name = shipAssetName(model || fallback);
    const next = schematicSrc(name);
    node.dataset.ship = name;
    if (node.getAttribute("src") === next) {
      return;
    }
    node.onerror = () => {
      node.onerror = null;
      node.src = schematicSrc(shipAssetName(fallback));
    };
    node.src = next;
  }

  function formatFixed(value, digits = 2) {
    const n = Number(value);
    if (!Number.isFinite(n)) {
      return "-";
    }
    return n.toFixed(digits);
  }

  function formatPosition(t) {
    const lat = Number(t.latitude);
    const lon = Number(t.longitude);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      return "-";
    }
    return `${lat.toFixed(4)} / ${lon.toFixed(4)}`;
  }

  function formatHeading(value) {
    return Number.isFinite(Number(value)) ? `${Math.round(Number(value))} deg` : "-";
  }

  function formatAltitude(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) {
      return "-";
    }
    if (Math.abs(n) >= 1000) {
      return `${(n / 1000).toFixed(1)} km`;
    }
    return `${Math.round(n)} m`;
  }

  function suitName(t) {
    const suit = t.suit || {};
    return suit.name_localised || suit.name || "Suit";
  }

  function suitLoadout(t) {
    const suit = t.suit || {};
    return suit.loadout_name || (Array.isArray(suit.modules) && suit.modules.length ? `${suit.modules.length} modules` : "-");
  }

  function suitWeapon(t) {
    const suit = t.suit || {};
    return suit.selected_weapon_localised || suit.selected_weapon || "-";
  }

  function suitEnvironment(t) {
    const suit = t.suit || {};
    if (suit.very_cold) {
      return "Very Cold";
    }
    if (suit.very_hot) {
      return "Very Hot";
    }
    if (suit.cold) {
      return "Cold";
    }
    if (suit.hot) {
      return "Hot";
    }
    if (suit.breathable_atmosphere) {
      return "Breathable";
    }
    return t.on_foot_on_planet ? "Surface" : "-";
  }

  function stationArea(t) {
    if (t.on_foot_in_hangar) {
      return "Hangar";
    }
    if (t.on_foot_social_space) {
      return "Social Space";
    }
    if (t.on_foot_exterior) {
      return "Exterior";
    }
    return "Station";
  }

  function stationServicesText(semantic = {}) {
    const items = [];
    if (semantic.station_services_available) {
      items.push("Station");
    }
    if (semantic.market_access_available) {
      items.push("Market");
    }
    return items.length ? items.join(" / ") : "Local";
  }

  function renderSlfPane(t) {
    const fighter = t.fighter || {};
    const model = fighter.model || "taipan";
    const name = fighter.model_localised || vehicleName(model, "Taipan");
    setText(el.slfName, name);
    setText(el.slfStatus, fighter.id ? `SLF ID ${fighter.id}` : (fighter.last_event || "SLF deployed"));
    setText(el.slfMothership, t.mothership_name || t.ship_name || "-");
    setText(el.slfSystem, t.system || "-");
    setText(el.slfLoadout, fighter.loadout || "-");
    setText(el.slfControl, fighter.player_controlled === false ? "Crew" : "Commander");
    setText(el.slfShield, formatPercent(fighter.shield_health_percent));
    setText(el.slfHull, formatPercent(fighter.hull_health_percent));
    setText(el.slfMode, t.analysis_mode ? "Analysis" : "Combat/Nav");
    setText(el.slfFireGroup, t.fire_group);
    setText(el.slfPips, formatPips(t.pips));
    setText(el.slfHardpoints, t.hardpoints_deployed ? "Hardpoints" : "Stowed");
    setVehicleSchematic(el.slfSchematic, model, "taipan");
  }

  function renderSrvPane(t) {
    const srv = t.srv || {};
    const model = srv.model || "scarab-srv";
    setText(el.srvName, srv.model_localised || vehicleName(model, "Scarab SRV"));
    setText(el.srvStatus, t.landed ? "Surface deployed" : (srv.last_event || "SRV active"));
    setText(el.srvMothership, t.mothership_name || t.ship_name || "-");
    setText(el.srvBody, t.body || "-");
    setText(el.srvSystem, t.system || "-");
    setText(el.srvPosition, formatPosition(t));
    setText(el.srvHeading, formatHeading(t.heading));
    setText(el.srvAltitude, formatAltitude(t.altitude));
    setText(el.srvMode, t.analysis_mode ? "Analysis" : "Combat/Nav");
    setText(el.srvFireGroup, t.fire_group);
    setText(el.srvPips, formatPips(t.pips));
    setText(el.srvCargo, t.cargo);
    setText(el.srvLegal, t.legal_state);
    setText(el.srvHull, formatPercent(t.hull_percent ?? t.hull ?? 100));
    setVehicleSchematic(el.srvSchematic, model, "scarab-srv");
  }

  function truthyPlanetFlag(value) {
    if (value === true || value === 1) {
      return true;
    }
    const text = String(value ?? "").trim().toLowerCase();
    return ["1", "true", "yes", "y", "landable", "landfall", "atmosphere", "atmospheric"].includes(text);
  }

  function planetIsLandable(t) {
    const explicit = [
      t.landable,
      t.body_landable,
      t.planet_landable,
      t.is_landable,
      t.has_lat_long,
      t.landed,
      t.glide_mode,
    ];
    if (explicit.some(truthyPlanetFlag)) {
      return true;
    }
    const status = String(t.planetary_status || "").toLowerCase();
    return /\b(land|landfall|glide|normal flight|oc)\b/.test(status);
  }

  function planetHasAtmosphere(t) {
    const explicit = [
      t.atmosphere,
      t.has_atmosphere,
      t.body_atmosphere,
      t.planet_atmosphere,
      t.atmosphere_type,
      t.atmosphere_composition,
      t.suit && t.suit.breathable_atmosphere,
    ];
    if (explicit.some(truthyPlanetFlag)) {
      return true;
    }
    const text = [
      t.body_type,
      t.body_subtype,
      t.planetary_status,
      t.destination_body_type,
    ].map((value) => String(value || "").toLowerCase()).join(" ");
    if (/\b(no|none|without)\s+atmos/.test(text)) {
      return false;
    }
    return /\batmos/.test(text);
  }

  function planetSurfaceSiteType(t) {
    const text = [
      t.station,
      t.station_type,
      t.destination_name,
      t.destination_body_type,
      t.on_foot_location,
      t.body_type,
    ].map((value) => String(value || "").toLowerCase()).join(" ");
    if (!text || text.includes("asteroid")) {
      return "";
    }
    if (text.includes("planetary port") || text.includes("surface port") || text.includes("horizons planetary port")) {
      return "outpost";
    }
    if (text.includes("settlement") || text.includes("planetary base") || /\bbase\b/.test(text)) {
      return "base";
    }
    return "";
  }

  function renderPlanetPane(t) {
    if (el.planetPane) {
      el.planetPane.dataset.landable = planetIsLandable(t) ? "true" : "false";
      el.planetPane.dataset.atmosphere = planetHasAtmosphere(t) ? "true" : "false";
      const surfaceSite = planetSurfaceSiteType(t);
      if (surfaceSite) {
        el.planetPane.dataset.surfaceSite = surfaceSite;
      } else {
        delete el.planetPane.dataset.surfaceSite;
      }
    }
    setText(el.planetBody, t.body || "Planetary body");
    setText(el.planetStatus, t.planetary_status || "-");
    setText(el.planetSystem, t.system || "-");
    setText(el.planetFlightStatus, t.planetary_status || "-");
    setText(el.planetPosition, formatPosition(t));
    setText(el.planetAltitude, formatAltitude(t.altitude));
    setText(el.planetHeading, formatHeading(t.heading));
    setText(el.planetTemp, Number.isFinite(Number(t.temperature)) ? `${Math.round(Number(t.temperature) * 100)}%` : "-");
    setText(el.planetMode, t.analysis_mode ? "Analysis" : "Combat/Nav");
    setText(el.planetLegal, t.legal_state);
  }

  function renderOnFootPlanetPane(t) {
    const suit = t.suit || {};
    setText(el.footPlanetSuit, suitName(t));
    setText(el.footPlanetStatus, suit.aim_down_sight ? "Aiming" : "Surface EVA");
    setText(el.footPlanetBody, t.body || "-");
    setText(el.footPlanetPosition, formatPosition(t));
    setText(el.footPlanetHeading, formatHeading(t.heading));
    setText(el.footPlanetWeapon, suitWeapon(t));
    setText(el.footPlanetLoadout, suitLoadout(t));
    setText(el.footPlanetOxygen, suit.low_oxygen ? "Low" : (suit.breathable_atmosphere ? "Breathable" : "Suit"));
    setText(el.footPlanetHealth, suit.low_health ? "Low" : "Nominal");
    setText(el.footPlanetEnvironment, suitEnvironment(t));
  }

  function renderOnFootStationPane(t, system, semantic) {
    const suit = t.suit || {};
    setText(el.footStationSuit, suitName(t));
    setText(el.footStationStatus, stationArea(t));
    setText(el.footStationName, t.station || "-");
    setText(el.footStationServices, stationServicesText(semantic));
    setText(el.footStationLoadout, suitLoadout(t));
    setText(el.footStationWeapon, suitWeapon(t));
    setText(el.footStationArea, stationArea(t));
    setText(el.footStationSystem, t.system || "-");
    setText(el.footStationAllegiance, system.allegiance);
    setText(el.footStationGovernment, system.station_government || system.government);
  }

  function stationContextName(t, semantic = {}) {
    const targetType = String(semantic.target_type || "").toLowerCase();
    const dockingState = String(semantic.docking_state || "").toLowerCase();
    const activeStationContext = Boolean(
      t.docked
      || t.on_foot_in_station
      || t.on_foot_in_hangar
      || t.on_foot_social_space
      || semantic.station_services_available
      || semantic.can_request_docking
      || semantic.no_fire_zone
      || ["requested", "granted", "approaching", "docking", "docked"].includes(dockingState)
    );
    if (activeStationContext && t.station) {
      return t.station;
    }
    if (["station", "outpost", "fleet_carrier"].includes(targetType) || semantic.can_request_docking || semantic.no_fire_zone) {
      return t.destination_name || t.target || "";
    }
    const destinationName = String(t.destination_name || "").trim();
    const destinationType = String(t.destination_body_type || semantic.destination_body_type || "").toLowerCase();
    const destinationBody = Number(t.destination_body);
    const localNames = [t.system, t.body].map((value) => String(value || "").trim().toLowerCase()).filter(Boolean);
    if (
      destinationName
      && !destinationType.includes("hyperspace")
      && Number.isFinite(destinationBody)
      && destinationBody >= 15
      && !localNames.includes(destinationName.toLowerCase())
    ) {
      return destinationName;
    }
    return "";
  }

  function isActivePlanetaryContext(t) {
    const status = String(t.planetary_status || "").toLowerCase();
    return Boolean(
      t.landed
      || (t.glide_mode && !t.supercruise)
      || t.planetary_approach
      || t.planetary_flight
      || status.includes("landed")
      || (status.includes("glide") && !t.supercruise)
      || status.includes("approach")
      || status.includes("orbital")
      || status.includes("surface")
    );
  }

  function renderSystemContext(t, system, semantic = {}) {
    const showSlf = Boolean(t.in_fighter || (t.fighter && t.fighter.active));
    const showFootPlanet = Boolean(t.on_foot_on_planet);
    const showRoute = hasHyperspaceDestination(t, semantic || {});
    const stationName = stationContextName(t, semantic);
    const stationContext = Boolean(
      t.docked
      || t.on_foot_in_station
      || t.on_foot_in_hangar
      || t.on_foot_social_space
      || semantic.station_services_available
      || semantic.can_request_docking
      || semantic.no_fire_zone
      || stationName
    );
    const activeVehicle = String(t.active_vehicle || "").toLowerCase();
    const activeShip = !showSlf && activeVehicle !== "fighter" && activeVehicle !== "srv" && activeVehicle !== "foot";
    const showPlanet = Boolean(!showRoute && !stationContext && !showSlf && !showFootPlanet && activeShip && isActivePlanetaryContext(t));
    if (el.systemPane) {
      el.systemPane.hidden = showSlf || showFootPlanet || showPlanet;
    }
    if (el.slfPane) {
      el.slfPane.hidden = !showSlf;
    }
    if (el.footPlanetPane) {
      el.footPlanetPane.hidden = !showFootPlanet;
    }
    if (el.planetPane) {
      el.planetPane.hidden = !showPlanet;
    }
    if (showSlf) {
      renderSlfPane(t);
      return;
    }
    if (showFootPlanet) {
      renderOnFootPlanetPane(t);
      return;
    }
    if (showPlanet) {
      renderPlanetPane(t);
      return;
    }
    const jumpTextActive = Boolean(t.in_hyperspace || t.fsd_hyperdrive_charging || t.fsd_jump || semantic.flight_status === "hyperspace");
    setSystemNameField(stationContext ? "Station System" : "Current System", t.system, jumpTextActive);
    setText(el.systemAddress, t.system_address ? `ADDR ${t.system_address}` : "-");
    setField(el.station, stationContext ? "Station" : "Station", stationContext ? stationName : "");
    setField(el.body, stationContext ? "Local Body" : "Body", t.body);
    setField(el.systemAllegiance, "Allegiance", system.allegiance);
    setField(el.systemFaction, stationContext ? "Faction" : "Control", system.station_faction || system.faction);
    setField(el.systemPower, "Power", system.controlling_power);
    setField(el.systemPowerState, "State", system.civil_war ? "Civil War" : (system.powerplay_state || system.faction_state));
    setField(el.systemGovernment, "Government", system.station_government || system.government);
    setField(el.systemEconomy, "Economy", system.station_economy || system.economy);
    setField(el.systemSecurity, "Security", system.security);
    setField(el.systemPopulation, "Population", formatInteger(system.population));
    const currentStarClass = system.primary_star_class || system.star_class || t.star_class || "-";
    setText(el.currentStarClass, currentStarClass === "-" ? "-" : `Class ${currentStarClass}`);
    setText(el.currentRefuel, scoopableStarClass(currentStarClass) ? "Fuel star" : (currentStarClass === "-" ? "-" : "Not scoopable"));
  }

  function renderTargetContext(t, target, system, semantic) {
    const showSrv = Boolean(t.in_srv || (t.srv && t.srv.active));
    const showFootStation = Boolean(t.on_foot_in_station || t.on_foot_in_hangar || t.on_foot_social_space);
    const showRoute = Boolean(!showSrv && !showFootStation && hasHyperspaceDestination(t, semantic || {}));
    if (el.routePane) {
      el.routePane.hidden = !showRoute;
    }
    if (el.targetPane) {
      el.targetPane.hidden = showSrv || showFootStation || showRoute;
    }
    if (el.srvPane) {
      el.srvPane.hidden = !showSrv;
    }
    if (el.footStationPane) {
      el.footStationPane.hidden = !showFootStation;
    }
    if (showSrv) {
      renderSrvPane(t);
      return;
    }
    if (showFootStation) {
      renderOnFootStationPane(t, system || {}, semantic || {});
      return;
    }
    if (showRoute) {
      renderRoutePane(t, semantic || {});
      return;
    }
    const activeVehicle = String(t.active_vehicle || "").toLowerCase();
    const rawTargetModel = target.ship || target.ship_localised || t.target || "";
    const rawMothershipModel = t.mothership_model || t.ship_model || "";
    const targetShipKey = rawTargetModel ? shipAssetName(rawTargetModel) : "";
    const mothershipKey = rawMothershipModel ? shipAssetName(rawMothershipModel) : "";
    const targetNameKey = String(target.ship_localised || target.ship || t.target || "").trim().toLowerCase();
    const mothershipNameKey = String(t.mothership_name || t.ship_name || "").trim().toLowerCase();
    const staleMothershipTarget = Boolean(
      activeVehicle !== "fighter"
      && (
        (targetShipKey && mothershipKey && targetShipKey === mothershipKey)
        || (targetNameKey && mothershipNameKey && targetNameKey === mothershipNameKey)
      )
    );
    const targetLocked = Boolean(target.locked && !staleMothershipTarget);
    const targetName = targetLocked
      ? (target.ship_localised || target.ship || t.target || "Unknown contact")
      : "No target";
    const targetHostility = String(target.hostility || "").trim().toLowerCase();
    const rawTargetLegal = String(target.legal_status || "").trim();
    const scanStage = Number(target.scan_stage ?? 0);
    const targetScanning = Boolean(targetLocked && (!rawTargetLegal || scanStage < 3));
    const targetLegal = targetLocked
      ? (targetHostility === "enemy" ? "Enemy" : (rawTargetLegal || "Scanning"))
      : "Clear";
    const rawLegalKey = String(targetLegal || "unknown").toLowerCase();
    const targetLegalKey = targetHostility === "enemy"
      ? "enemy"
      : (rawLegalKey.includes("wanted") ? "wanted" : (rawLegalKey.includes("clean") ? "clean" : (targetScanning ? "scanning" : rawLegalKey)));
    if (el.targetPane) {
      el.targetPane.dataset.locked = targetLocked ? "true" : "false";
      el.targetPane.dataset.legal = targetLegalKey;
      el.targetPane.dataset.scanning = targetScanning ? "true" : "false";
    }
    setText(el.targetName, targetName);
    setText(el.targetPilot, targetLocked ? (target.pilot_name || "Pilot unknown") : "-");
    setText(el.targetLegal, targetLegal);
    setField(el.targetScan, "Scan", targetLocked ? (targetScanning ? `Stage ${scanStage}...` : `Stage ${scanStage}`) : "-");
    setField(el.targetRank, "Rank", target.pilot_rank);
    setField(el.targetFaction, "Faction", target.faction);
    setField(el.targetPower, "Power", target.power);
    setField(el.targetShield, "Shield", formatPercent(target.shield_health_percent));
    setField(el.targetHull, "Hull", formatPercent(target.hull_health_percent));
    setMeter(el.targetShieldBar, target.shield_health_percent);
    setMeter(el.targetHullBar, target.hull_health_percent);
    setTargetSchematic(target.ship || target.ship_localised || t.target, targetLocked);
    setText(el.targetStatus, t.in_danger ? "Danger" : (t.being_interdicted ? "Interdicted" : (targetLocked ? (targetHostility === "enemy" ? "Hostile power" : "Contact locked") : "Clear")));
  }

  async function setShieldEnvelope(name) {
    const ship = slug(name) || "sidewinder";
    if (currentShieldEnvelope === ship) {
      return;
    }
    currentShieldEnvelope = ship;
    if (shipsWithoutShieldEnvelope.has(ship)) {
      if (el.shipCanvas) {
        el.shipCanvas.dataset.shieldImage = "false";
      }
      if (el.shieldImage) {
        el.shieldImage.removeAttribute("src");
      }
      el.shieldBands.forEach((node) => node?.removeAttribute("points"));
      return;
    }
    const hasPairedShield = pairedSchematicShips.has(ship);
    if (el.shipCanvas) {
      el.shipCanvas.dataset.shieldImage = hasPairedShield ? "true" : "false";
    }
    if (el.shieldImage) {
      if (hasPairedShield) {
        el.shieldImage.src = `Schematics/paired/${ship}-shield-outline.png?v=${pairedSchematicVersion}`;
      } else {
        el.shieldImage.removeAttribute("src");
      }
    }
    if (hasPairedShield) {
      el.shieldBands.forEach((node) => node?.removeAttribute("points"));
      return;
    }
    try {
      const data = await apiGet(`/Schematics/shields/${ship}.json?v=${shieldEnvelopeVersion}`);
      const width = Number(data.width) || 100;
      const height = Number(data.height) || 100;
      if (el.shieldEnvelope) {
        el.shieldEnvelope.setAttribute("viewBox", `0 0 ${width} ${height}`);
      }
      const bands = Array.isArray(data.bands) ? data.bands : [];
      bands.forEach((band, index) => {
        const node = el.shieldBands[index];
        const points = Array.isArray(band.points) ? band.points : [];
        if (!node || !points.length) {
          return;
        }
        node.setAttribute(
          "points",
          points.map((p) => `${(Number(p.x) / 100) * width},${(Number(p.y) / 100) * height}`).join(" "),
        );
      });
    } catch {
      if (ship !== "sidewinder") {
        currentShieldEnvelope = "";
        setShieldEnvelope("sidewinder");
      }
    }
  }

  function pct(value, max) {
    const n = Number(value);
    const m = Number(max || 100);
    if (!Number.isFinite(n) || !Number.isFinite(m) || m <= 0) {
      return 0;
    }
    return Math.max(0, Math.min(100, (n / m) * 100));
  }

  function formatInteger(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) {
      return "-";
    }
    return Math.round(n).toLocaleString();
  }

  function formatPercent(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) {
      return "-";
    }
    return `${Math.max(0, Math.min(100, Math.round(n)))}%`;
  }

  function normalizePipValue(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) {
      return 0;
    }
    return Math.max(0, Math.min(8, n));
  }

  function formatPips(value) {
    if (!Array.isArray(value) || value.length < 3) {
      return "-";
    }
    return value.slice(0, 3).map((pip) => (normalizePipValue(pip) / 2).toFixed(0)).join(" / ");
  }

  function formatDistanceLy(value) {
    const n = Number(value);
    if (!Number.isFinite(n)) {
      return "-";
    }
    return `${n.toFixed(n >= 100 ? 0 : 1)} ly`;
  }

  function destinationSystemName(t, semantic = {}) {
    return text(
      t.nav_route_destination ||
      semantic.nav_route_destination ||
      t.destination_name ||
      semantic.destination_name ||
      ""
    );
  }

  function hasHyperspaceDestination(t, semantic = {}) {
    if (t.docked || t.landed) {
      return false;
    }
    const type = String(t.destination_body_type || semantic.destination_body_type || "").toLowerCase();
    const stationish = /\b(station|outpost|fleet|carrier|settlement|port|base)\b/.test(type);
    const destinationName = String(t.destination_name || semantic.destination_name || "").trim();
    const destinationKey = destinationName.toLowerCase();
    const destinationSystem = String(t.destination_system || semantic.destination_system || "").trim();
    const currentSystemAddress = String(t.system_address || semantic.system_address || "").trim();
    const localNames = [
      t.system,
      t.station,
      t.body,
      semantic.system,
      semantic.station,
      semantic.body
    ].map((value) => String(value || "").trim().toLowerCase()).filter(Boolean);
    const remoteNamedTarget = Boolean(destinationKey && !localNames.includes(destinationKey));
    const routeJumps = Number(t.nav_route_remaining_jumps ?? semantic.nav_route_remaining_jumps ?? NaN);
    const remainingJumps = Number(t.destination_remaining_jumps ?? semantic.remaining_jumps ?? NaN);
    const routeActive = Boolean(
      t.nav_route_next_jump ||
      semantic.nav_route_next_jump
    );
    const navDestination = String(t.nav_route_destination || semantic.nav_route_destination || "").trim().toLowerCase();
    const currentSystemName = String(t.system || semantic.system || "").trim().toLowerCase();
    if (navDestination && currentSystemName && navDestination === currentSystemName) {
      return false;
    }
    if (Number.isFinite(routeJumps) && routeJumps <= 0) {
      return false;
    }
    const arrivedAtRouteDestination = Boolean(
      destinationSystem
      && currentSystemAddress
      && destinationSystem === currentSystemAddress
      && !t.nav_route_next_jump
      && (!Number.isFinite(routeJumps) || routeJumps <= 0)
      && (!Number.isFinite(remainingJumps) || remainingJumps <= 0)
      && !remoteNamedTarget
    );
    if (arrivedAtRouteDestination) {
      return false;
    }
    if (type.includes("hyperspace") && !routeActive) {
      return false;
    }
    return Boolean(
      !stationish &&
      (
        (routeActive && (t.nav_route_destination || semantic.nav_route_destination)) ||
        (t.destination_system && !t.destination_body) ||
        t.destination_star_class ||
        t.destination_remaining_jumps ||
        t.nav_route_next_jump ||
        t.nav_route_remaining_jumps ||
        type.includes("hyperspace") ||
        remoteNamedTarget
      )
    );
  }

  function scoopableStarClass(value) {
    const starClass = String(value || "").trim().toUpperCase().charAt(0);
    return Boolean(starClass && "KGBFOAM".includes(starClass));
  }

  function renderRoutePane(t, semantic = {}) {
    const targetSystem = destinationSystemName(t, semantic);
    const distance = t.nav_route_distance_ly || t.destination_distance_ly || semantic.destination_distance_ly;
    const jumps = t.destination_remaining_jumps ?? t.nav_route_remaining_jumps ?? semantic.remaining_jumps;
    const nextJump = t.nav_route_next_jump || semantic.nav_route_next_jump || targetSystem;
    const starClass = t.destination_star_class || semantic.destination_star_class || "-";
    const upcomingJumps = Array.isArray(t.nav_route_upcoming_jumps)
      ? t.nav_route_upcoming_jumps
      : (Array.isArray(semantic.nav_route_upcoming_jumps) ? semantic.nav_route_upcoming_jumps : []);
    setText(el.routeTargetSystem, targetSystem);
    setText(el.routeTargetAddress, t.destination_system ? `ADDR ${t.destination_system}` : (t.nav_route || "-"));
    setText(el.routeDistance, formatDistanceLy(distance));
    setText(el.routeJumps, Number.isFinite(Number(jumps)) ? String(Math.max(0, Math.round(Number(jumps)))) : "-");
    setText(el.routeNextJump, nextJump);
    setText(el.routeStarClass, starClass === "-" ? "-" : `Class ${starClass} - ${scoopableStarClass(starClass) ? "Fuel star" : "Not scoopable"}`);
    setText(el.routeUpcoming, upcomingJumps.length ? upcomingJumps.slice(0, 3).map((name, index) => `${index + 1}. ${name}`).join(" / ") : "-");
  }

  function setMeter(node, value) {
    if (!node) {
      return;
    }
    const n = Number(value);
    node.style.width = `${Number.isFinite(n) ? Math.max(0, Math.min(100, n)) : 0}%`;
  }

  function makeBar(value, max) {
    const bar = document.createElement("span");
    const fill = document.createElement("span");
    bar.className = "mfd-bar";
    fill.className = "mfd-bar-fill";
    fill.style.width = `${pct(value, max)}%`;
    bar.appendChild(fill);
    return bar;
  }

  function makeSegmentMeter(value, max, segments, vertical) {
    const meter = document.createElement("span");
    const lit = Math.round((pct(value, max) / 100) * segments);
    meter.className = `mfd-segment-meter ${vertical ? "vertical" : "horizontal"}`;
    for (let i = 0; i < segments; i += 1) {
      const segment = document.createElement("span");
      segment.className = `mfd-segment ${i < lit ? "on" : "off"}`;
      meter.appendChild(segment);
    }
    return meter;
  }

  function renderFuelStrip(t) {
    if (!el.fuelSegments) {
      return;
    }
    el.fuelSegments.innerHTML = "";
    const fuel = Number(t.fuel_main);
    const max = 32;
    const lit = Math.round((pct(Number.isFinite(fuel) ? fuel : 0, max) / 100) * 16);
    for (let i = 0; i < 16; i += 1) {
      const segment = document.createElement("span");
      segment.className = `mfd-segment ${i < lit ? "on" : "off"}`;
      el.fuelSegments.appendChild(segment);
    }
  }

  function renderStatusIcons(t) {
    if (!el.statusIcons) {
      return;
    }
    const icons = [
      { on: t.night_vision, src: "icons/night-vision.png", label: "Night vision" },
      { on: t.lights_on, src: "icons/lights.png", label: "Lights" },
      { on: t.flight_assist_off, src: "icons/Flight-assist.png", label: "Flight assist off" },
      { on: t.landing_gear_down, src: "icons/landing-gear.png", label: "Landing gear deployed" },
    ];
    el.statusIcons.innerHTML = "";
    for (const item of icons) {
      if (!item.on) {
        continue;
      }
      const img = document.createElement("img");
      img.src = item.src;
      img.alt = item.label;
      img.title = item.label;
      el.statusIcons.appendChild(img);
    }
  }

  function makeVerticalMeter(value, max, label) {
    const wrap = document.createElement("span");
    const labelEl = document.createElement("span");
    labelEl.className = "mfd-meter-label";
    labelEl.textContent = label;
    wrap.className = "mfd-vertical-meter";
    wrap.appendChild(makeSegmentMeter(value, max, 12, true));
    wrap.appendChild(labelEl);
    return wrap;
  }

  function shortModuleName(module) {
    const slot = String(module.slot || "").trim();
    const item = String(module.item || "").trim();
    const slotMap = {
      PowerPlant: "PWR",
      MainEngines: "ENG",
      FrameShiftDrive: "FSD",
      LifeSupport: "LIFE",
      PowerDistributor: "DIST",
      Radar: "SENS",
      FuelTank: "FUEL",
      Armour: "HULL",
      ShipCockpit: "CANOPY",
      CargoHatch: "CARGO",
      PlanetaryApproachSuite: "PAS",
    };
    if (slotMap[slot]) {
      return slotMap[slot];
    }
    if (/Hardpoint/i.test(slot)) {
      return slot.replace(/(Tiny|Small|Medium|Large|Huge)?Hardpoint/i, "HP ");
    }
    if (/Slot\d+_Size\d+/i.test(slot)) {
      return slot.replace(/Slot(\d+)_Size(\d+)/i, "OPT $1");
    }
    return slot || item || "MOD";
  }

  function moduleItemName(module) {
    const item = String(module.item || "").trim();
    if (!item) {
      return "Module";
    }
    if (/^hpt_/i.test(item)) {
      const weapon = item
        .replace(/^hpt_/i, "")
        .replace(/_(tiny|small|medium|large|huge)$/i, "")
        .replace(/_/g, " ")
        .replace(/\bbeamlaser\b/i, "beam laser")
        .replace(/\bpulselaser\b/i, "pulse laser")
        .replace(/\bburstlaser\b/i, "burst laser")
        .replace(/\bmulticannon\b/i, "multi cannon")
        .replace(/\brailgun\b/i, "rail gun")
        .trim();
      return weapon
        .split(/\s+/)
        .slice(0, 3)
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ") || "Weapon";
    }
    const cleaned = item
      .replace(/^hpt_/i, "")
      .replace(/^int_/i, "")
      .replace(/_size\d+_class\d+/i, "")
      .replace(/_tiny/i, "")
      .replace(/_/g, " ")
      .trim();
    return cleaned
      .split(/\s+/)
      .slice(0, 3)
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ") || "Module";
  }

  function isWeaponModule(module) {
    const slot = String(module.slot || "").toLowerCase();
    const item = String(module.item || "").toLowerCase();
    const isWeaponSlot = /(small|medium|large|huge)hardpoint\d+/i.test(slot);
    const isUtilitySlot = /tinyhardpoint\d+/i.test(slot);
    const isUtilityItem = /shieldbooster|chaff|heatsink|pointdefence|pointdefense|ecm|killwarrant|wake|xenoscanner|manifest|shutdownfield|causticsink|pulsewave|dockingcomputer|supercruiseassist/i.test(item);
    return !isUtilitySlot && !isUtilityItem && (isWeaponSlot || item.startsWith("hpt_"));
  }

  function moduleSortScore(module, group) {
    const slot = String(module.slot || "");
    const coreOrder = [
      "PowerPlant",
      "MainEngines",
      "FrameShiftDrive",
      "PowerDistributor",
      "LifeSupport",
      "Radar",
      "FuelTank",
      "ShipCockpit",
      "CargoHatch",
    ];
    if (group === "weapons") {
      const match = slot.match(/hardpoint(\d+)/i);
      return match ? Number(match[1]) : 99;
    }
    const index = coreOrder.indexOf(slot);
    return index === -1 ? 80 : index;
  }

  function moduleHardpointNumber(module) {
    const slot = String(module && module.slot || "");
    const match = slot.match(/(?:small|medium|large|huge)?hardpoint(\d+)/i);
    return match ? Number(match[1]) : null;
  }

  function hardpointSizeCode(value) {
    const normalized = String(value || "").toLowerCase();
    if (normalized === "huge") return "H";
    if (normalized === "large") return "L";
    if (normalized === "medium") return "M";
    if (normalized === "small") return "S";
    return "";
  }

  function moduleHardpointSize(module, fallbackSize) {
    const slot = String(module && module.slot || "");
    const item = String(module && module.item || "");
    if (fallbackSize) {
      return fallbackSize;
    }
    const itemMatch = item.match(/(?:^|_)(small|medium|large|huge)(?:_|$)/i);
    if (itemMatch) {
      return hardpointSizeCode(itemMatch[1]);
    }
    const slotMatch = slot.match(/(small|medium|large|huge)hardpoint\d+/i);
    if (slotMatch) {
      return hardpointSizeCode(slotMatch[1]);
    }
    return fallbackSize || "";
  }

  function weaponHardpointEntries(ordered, shipHardpointSizes) {
    const parsed = ordered.map((module) => moduleHardpointNumber(module));
    const counts = parsed.reduce((acc, number) => {
      if (Number.isFinite(number)) {
        acc[number] = (acc[number] || 0) + 1;
      }
      return acc;
    }, {});
    const hasBadPositions = parsed.some((number) => !Number.isFinite(number) || number < 1 || number > Math.max(ordered.length, shipHardpointSizes.length));
    const hasDuplicates = parsed.some((number) => Number.isFinite(number) && counts[number] > 1);
    return ordered.map((module, index) => {
      const parsedPosition = parsed[index];
      const position = hasBadPositions || hasDuplicates ? index + 1 : parsedPosition;
      const fallbackSize = shipHardpointSizes[position - 1] || "";
      return {
        module,
        position,
        size: moduleHardpointSize(module, fallbackSize),
      };
    });
  }

  function activeShipHardpointSizes() {
    const ship = shipAssetName(latestTelemetry.ship_model || latestTelemetry.ship || latestTelemetry.mothership_model || "");
    return edsaHardpointSizes[ship] || [];
  }

  function activeShipHardpointPoints() {
    const ship = shipAssetName(latestTelemetry.ship_model || latestTelemetry.ship || latestTelemetry.mothership_model || "");
    return physicalHardpointPoints[ship] || edsaHardpointPoints[ship] || [];
  }

  function fallbackHardpointPoint(position, count) {
    const spread = Math.max(0, count - 1);
    const row = spread ? (position - 1) / spread : 0.5;
    const side = position % 2 === 0 ? 1 : -1;
    return [
      50 + side * (5 + (position % 3) * 2),
      18 + row * 34,
    ];
  }

  function schematicPointToCanvas(point) {
    const x = Math.max(0, Math.min(100, Number(point[0]) || 50));
    const y = Math.max(0, Math.min(100, Number(point[1]) || 26));
    if (!el.shipSchematic || !el.shipCanvas) {
      return [x, y];
    }
    const imageRect = el.shipSchematic.getBoundingClientRect();
    const canvasRect = el.shipCanvas.getBoundingClientRect();
    if (!imageRect.width || !imageRect.height || !canvasRect.width || !canvasRect.height) {
      return [x, y];
    }
    const naturalWidth = Number(el.shipSchematic.naturalWidth) || imageRect.width;
    const naturalHeight = Number(el.shipSchematic.naturalHeight) || imageRect.height;
    const imageAspect = naturalWidth / naturalHeight;
    const boxAspect = imageRect.width / imageRect.height;
    let renderedWidth = imageRect.width;
    let renderedHeight = imageRect.height;
    let renderedLeft = imageRect.left;
    let renderedTop = imageRect.top;
    if (Number.isFinite(imageAspect) && imageAspect > 0 && Number.isFinite(boxAspect) && boxAspect > 0) {
      if (boxAspect > imageAspect) {
        renderedWidth = imageRect.height * imageAspect;
        renderedLeft = imageRect.left + (imageRect.width - renderedWidth) / 2;
      } else {
        renderedHeight = imageRect.width / imageAspect;
        renderedTop = imageRect.top + (imageRect.height - renderedHeight) / 2;
      }
    }
    const left = ((renderedLeft - canvasRect.left) / canvasRect.width) * 100;
    const top = ((renderedTop - canvasRect.top) / canvasRect.height) * 100;
    const width = (renderedWidth / canvasRect.width) * 100;
    const height = (renderedHeight / canvasRect.height) * 100;
    return [
      left + (x / 100) * width,
      top + (y / 100) * height,
    ];
  }

  function distributeWeaponLabels(items) {
    const minY = 12;
    const maxY = 84;
    const gap = items.length > 6 ? 10.5 : 12;
    const bySide = { left: [], right: [] };
    items.forEach((item) => bySide[item.side].push(item));
    Object.values(bySide).forEach((sideItems) => {
      sideItems.sort((a, b) => a.labelY - b.labelY);
      sideItems.forEach((item, index) => {
        const previous = sideItems[index - 1];
        item.labelY = Math.max(minY, Math.min(maxY, item.labelY));
        if (previous) {
          item.labelY = Math.max(item.labelY, previous.labelY + gap);
        }
      });
      const overflow = sideItems.length ? sideItems[sideItems.length - 1].labelY - maxY : 0;
      if (overflow > 0) {
        sideItems.forEach((item) => {
          item.labelY -= overflow;
        });
      }
    });
    return items;
  }

  function weaponHardpointLayout(entries) {
    const points = activeShipHardpointPoints();
    const count = entries.length;
    const shipKey = slug(latestTelemetry.ship_model || latestTelemetry.mothership_model || "");
    const fixedSides = {
      anaconda: {
        1: "left",
        2: "right",
        3: "left",
        4: "right",
        5: "left",
        6: "right",
        7: "right",
        8: "left",
      },
      "caspian-explorer": {
        1: "left",
        2: "right",
        5: "left",
        6: "right",
      },
    };
    const centerXBias = { left: 0, right: 0 };
    const layouts = entries.map((entry, index) => {
      const position = entry.position || index + 1;
      const point = schematicPointToCanvas(points[position - 1] || fallbackHardpointPoint(position, count));
      const markerX = Math.max(7, Math.min(93, Number(point[0]) || 50));
      const markerY = Math.max(8, Math.min(86, Number(point[1]) || 26));
      let side = fixedSides[shipKey]?.[position] || (markerX < 49 ? "left" : "right");
      if (!fixedSides[shipKey]?.[position] && markerX >= 47 && markerX <= 53) {
        side = centerXBias.left <= centerXBias.right ? "left" : "right";
        centerXBias[side] += 1;
      }
      const labelX = side === "left" ? 38 : 62;
      return {
        index,
        position,
        markerX,
        markerY,
        labelX,
        labelY: markerY,
        side,
      };
    });
    return distributeWeaponLabels(layouts);
  }

  function renderModuleHealth(raw) {
    const payload = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : { modules: raw };
    const group = payload.group === "weapons" ? "weapons" : "modules";
    const modules = Array.isArray(payload.modules) ? payload.modules : [];
    const hardpoints = Array.isArray(payload.hardpoints) && payload.hardpoints.length
      ? payload.hardpoints.filter((module) => isWeaponModule(module))
      : modules.filter((module) => isWeaponModule(module));
    const sourceModules = group === "weapons"
      ? hardpoints
      : modules.filter((module) => !isWeaponModule(module));
    const shipHardpointSizes = group === "weapons" ? activeShipHardpointSizes() : [];
    const ordered = sourceModules
      .sort((a, b) => {
        if (group === "weapons") {
          return moduleSortScore(a, group) - moduleSortScore(b, group);
        }
        const ah = Number.isFinite(Number(a.health_percent)) ? Number(a.health_percent) : 101;
        const bh = Number.isFinite(Number(b.health_percent)) ? Number(b.health_percent) : 101;
        if (ah !== bh) {
          return ah - bh;
        }
        const ai = moduleSortScore(a, group);
        const bi = moduleSortScore(b, group);
        return ai - bi;
      })
      .slice(0, group === "weapons" ? 8 : 10);
    const weaponEntries = group === "weapons" ? weaponHardpointEntries(ordered, shipHardpointSizes) : [];
    const wrap = document.createElement("div");
    wrap.className = "mfd-module-list";
    wrap.dataset.group = group;
    wrap.dataset.count = String(ordered.length);
    if (!ordered.length) {
      const empty = document.createElement("span");
      empty.className = "mfd-module-empty";
      empty.textContent = group === "weapons" ? "No weapon modules" : "No module health";
      wrap.appendChild(empty);
      return wrap;
    }
    const weaponLayout = group === "weapons" ? weaponHardpointLayout(weaponEntries) : [];
    const leaderSvg = group === "weapons" ? document.createElementNS("http://www.w3.org/2000/svg", "svg") : null;
    if (leaderSvg) {
      leaderSvg.classList.add("mfd-hardpoint-leaders");
      leaderSvg.setAttribute("viewBox", "0 0 100 100");
      leaderSvg.setAttribute("preserveAspectRatio", "none");
      wrap.appendChild(leaderSvg);
    }
    ordered.forEach((module, index) => {
      const health = Number(module.health_percent);
      const item = document.createElement("span");
      const header = document.createElement("span");
      const label = document.createElement("span");
      const name = document.createElement("span");
      const meter = document.createElement("span");
      const fill = document.createElement("span");
      const value = document.createElement("span");
      const pctValue = Number.isFinite(health) ? Math.max(0, Math.min(100, health)) : 0;
      const entry = group === "weapons" ? weaponEntries[index] : null;
      const position = entry ? entry.position : index + 1;
      const hardpointSize = entry ? entry.size : "";
      const layout = group === "weapons" ? weaponLayout[index] : null;
      item.className = "mfd-module-row";
      item.style.left = layout ? `${layout.labelX}%` : `var(--module-x-${position}, 50%)`;
      item.style.top = layout ? `${layout.labelY}%` : `var(--module-y-${position}, 50%)`;
      item.dataset.index = String(position);
      item.dataset.side = layout ? layout.side : (position % 2 === 0 ? "right" : "left");
      if (hardpointSize) {
        item.dataset.size = hardpointSize.toLowerCase();
      }
      if (layout && leaderSvg) {
        const marker = document.createElement("span");
        const leaderPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
        const leaderGlow = document.createElementNS("http://www.w3.org/2000/svg", "path");
        marker.className = "mfd-hardpoint-marker";
        marker.style.left = `${layout.markerX}%`;
        marker.style.top = `${layout.markerY}%`;
        marker.dataset.size = hardpointSize.toLowerCase();
        marker.dataset.leader = String(position);
        leaderGlow.classList.add("mfd-hardpoint-leader-glow");
        leaderGlow.dataset.leader = String(position);
        leaderGlow.dataset.size = hardpointSize.toLowerCase();
        leaderPath.classList.add("mfd-hardpoint-leader-line");
        leaderPath.dataset.leader = String(position);
        leaderPath.dataset.size = hardpointSize.toLowerCase();
        leaderSvg.appendChild(leaderGlow);
        leaderSvg.appendChild(leaderPath);
        wrap.appendChild(marker);
      }
      item.dataset.state = pctValue < 50 ? "bad" : (pctValue < 80 ? "warn" : "ok");
      if (layout) {
        item.dataset.leader = String(position);
      }
      header.className = "mfd-module-header";
      label.className = "mfd-module-slot";
      label.textContent = group === "weapons" ? `${hardpointSize ? `${hardpointSize} ` : ""}HP ${position}` : shortModuleName(module);
      name.className = "mfd-module-name";
      name.textContent = moduleItemName(module);
      meter.className = "mfd-module-meter";
      fill.style.width = `${pctValue}%`;
      value.className = "mfd-module-value";
      value.textContent = Number.isFinite(health) ? `${Math.round(pctValue)}%` : "-";
      header.appendChild(label);
      header.appendChild(value);
      meter.appendChild(fill);
      item.appendChild(header);
      item.appendChild(name);
      item.appendChild(meter);
      wrap.appendChild(item);
    });
    if (leaderSvg) {
      window.requestAnimationFrame(() => {
        renderHardpointLeaders(wrap);
        window.requestAnimationFrame(() => renderHardpointLeaders(wrap));
        window.setTimeout(() => renderHardpointLeaders(wrap), 120);
      });
    }
    return wrap;
  }

  function renderHardpointLeaders(wrap) {
    if (!wrap) {
      return;
    }
    const leaderSvg = wrap.querySelector(".mfd-hardpoint-leaders");
    const leaderRect = leaderSvg ? leaderSvg.getBoundingClientRect() : wrap.getBoundingClientRect();
    if (!leaderRect.width || !leaderRect.height) {
      return;
    }
    wrap.querySelectorAll(".mfd-module-row[data-leader]").forEach((row) => {
      const id = row.dataset.leader;
      const marker = wrap.querySelector(`.mfd-hardpoint-marker[data-leader="${id}"]`);
      const line = wrap.querySelector(`.mfd-hardpoint-leader-line[data-leader="${id}"]`);
      const glow = wrap.querySelector(`.mfd-hardpoint-leader-glow[data-leader="${id}"]`);
      if (!marker || !line || !glow) {
        return;
      }
      const markerRect = marker.getBoundingClientRect();
      const rowRect = row.getBoundingClientRect();
      const markerX = row.dataset.side === "left"
        ? ((markerRect.left - leaderRect.left) / leaderRect.width) * 100
        : ((markerRect.right - leaderRect.left) / leaderRect.width) * 100;
      const markerY = ((markerRect.top + markerRect.height / 2 - leaderRect.top) / leaderRect.height) * 100;
      const labelX = row.dataset.side === "left"
        ? ((rowRect.right - leaderRect.left) / leaderRect.width) * 100
        : ((rowRect.left - leaderRect.left) / leaderRect.width) * 100;
      const labelY = ((rowRect.top + rowRect.height / 2 - leaderRect.top) / leaderRect.height) * 100;
      const path = `M ${markerX.toFixed(2)} ${markerY.toFixed(2)} L ${labelX.toFixed(2)} ${labelY.toFixed(2)}`;
      line.setAttribute("d", path);
      glow.setAttribute("d", path);
    });
  }

  function renderReadoutValue(row, raw) {
    if (row.type === "mode") {
      const wrap = document.createElement("button");
      const icon = document.createElement("img");
      const value = document.createElement("span");
      wrap.className = "mfd-mode-icon";
      wrap.type = "button";
      wrap.dataset.action = "cockpit_mode";
      wrap.dataset.mode = raw === "Analysis" ? "analysis" : "combat";
      wrap.title = raw === "Analysis" ? "Switch to combat mode" : "Switch to analysis mode";
      icon.src = raw === "Analysis" ? "icons/analysis-mode.png" : "icons/combat-mode.png";
      icon.alt = "";
      value.className = "mfd-ship-readout-value";
      value.textContent = text(raw);
      wrap.appendChild(icon);
      wrap.appendChild(value);
      return wrap;
    }
    if (row.type === "bar") {
      const wrap = document.createElement("span");
      const value = document.createElement("span");
      value.className = "mfd-ship-readout-value";
      value.textContent = text(raw);
      wrap.appendChild(value);
      wrap.appendChild(makeBar(raw, row.max));
      return wrap;
    }
    if (row.type === "percent") {
      return makeVerticalMeter(raw, 100, row.label);
    }
    if (row.type === "switch") {
      const value = document.createElement("span");
      value.className = `mfd-ship-readout-value ${raw ? "mfd-status-on" : "mfd-status-off"}`;
      value.textContent = raw ? "On" : "Off";
      return value;
    }
    if (row.type === "pips") {
      const values = Array.isArray(raw) ? raw : [];
      const wrap = document.createElement("span");
      wrap.className = "mfd-pip-bars";
      ["SYS", "ENG", "WEP"].forEach((label, index) => {
        const rowEl = document.createElement("span");
        const labelEl = document.createElement("span");
        labelEl.textContent = label;
        rowEl.className = "mfd-pip-row";
        rowEl.appendChild(labelEl);
        rowEl.appendChild(makeSegmentMeter(normalizePipValue(values[index]), 8, 4, true));
        wrap.appendChild(rowEl);
      });
      return wrap;
    }
    if (row.type === "modules") {
      return renderModuleHealth(raw);
    }
    const value = document.createElement("span");
    value.className = "mfd-ship-readout-value";
    value.textContent = text(raw);
    return value;
  }

  function renderShipView() {
    const view = shipViews[shipViewIndex] || shipViews[0];
    setText(el.shipViewTitle, view.title);
    setText(el.shipName, latestTelemetry.ship_name || latestTelemetry.ship_model || "Vessel");
    if (!el.shipReadouts) {
      return;
    }
    el.shipReadouts.innerHTML = "";
    for (const row of view.rows) {
      const tile = document.createElement("div");
      const label = document.createElement("span");
      label.className = "mfd-label";
      label.textContent = row.label;
      tile.className = `mfd-ship-readout mfd-ship-readout-${slug(row.label)}`;
      if (row.type === "modules") {
        tile.classList.add("mfd-ship-readout-module-overlay");
      }
      tile.appendChild(label);
      tile.appendChild(renderReadoutValue(row, row.value(latestTelemetry || {})));
      el.shipReadouts.appendChild(tile);
    }
  }

  function cycleShipView(delta) {
    shipViewManual = true;
    shipViewIndex = (shipViewIndex + delta + shipViews.length) % shipViews.length;
    renderShipView();
  }

  function syncShipViewToMode(t) {
    if (shipViewManual) {
      return;
    }
    shipViewIndex = t.analysis_mode ? 1 : 0;
  }

  function setShieldBands(t) {
    if (!el.shipCanvas) {
      return;
    }
    const raw = Number(t.shield_percent ?? t.shields_percent ?? (t.shields_up === false ? 0 : 100));
    const value = Number.isFinite(raw) ? raw : 100;
    let bands = 0;
    if (value > 66) {
      bands = 3;
    } else if (value > 33) {
      bands = 2;
    } else if (value > 0) {
      bands = 1;
    }
    el.shipCanvas.dataset.shieldBands = String(bands);
  }

  function shieldPercent(t) {
    const raw = Number(t.shield_percent ?? t.shields_percent ?? (t.shields_up === false ? 0 : 100));
    return Number.isFinite(raw) ? raw : 100;
  }

  function setShieldTrend(t) {
    if (!el.shipCanvas) {
      return;
    }
    const value = shieldPercent(t);
    let trend = "stable";
    if (previousShieldPercent !== null) {
      if (value < previousShieldPercent) {
        trend = "down";
      } else if (value > previousShieldPercent) {
        trend = "up";
      }
    }
    previousShieldPercent = value;
    el.shipCanvas.dataset.shieldTrend = trend;
  }

  function setShipTemperatureColor(t) {
    if (!el.shipCanvas) {
      return;
    }
    const raw = Number(t.temperature);
    const temp = t.docked ? 0.58 : (Number.isFinite(raw) ? raw : (t.overheating ? 1.2 : 0.55));
    let hue = 0;
    let rgb = "255, 159, 26";
    if (temp < 0.35) {
      hue = 165;
      rgb = "80, 190, 255";
    } else if (temp < 0.5) {
      hue = 140;
      rgb = "115, 210, 255";
    } else if (temp > 1.0) {
      hue = 322;
      rgb = "255, 56, 35";
    } else if (temp > 0.75) {
      hue = 335;
      rgb = "255, 94, 34";
    }
    el.shipCanvas.style.setProperty("--ship-temp-hue", `${hue}deg`);
    el.shipCanvas.style.setProperty("--ship-temp-rgb", rgb);
  }

  function hapticsAvailable() {
    return Boolean(
      navigator.vibrate &&
      navigator.maxTouchPoints > 0 &&
      !/Windows/i.test(navigator.userAgent || "")
    );
  }

  function hapticTap(pattern = 18) {
    if (hapticsAvailable()) {
      navigator.vibrate(pattern);
    }
  }

  async function sendControl(action, button) {
    if (!action) {
      return;
    }
    if (button && button.dataset.dockLocked === "true") {
      el.safety.textContent = "Control unavailable while docked.";
      return;
    }
    const hyperspaceCancelWindow = action === "hyperspace" && Date.now() < hyperspaceGraceUntil;
    if (button && button.dataset.unavailable === "true" && !hyperspaceCancelWindow) {
      el.safety.textContent = "Control unavailable in current flight state.";
      return;
    }
    hapticTap();
    if (action === "hyperspace") {
      const wasCancelWindow = Date.now() < hyperspaceGraceUntil;
      if (!wasCancelWindow) {
        hyperspaceGraceUntil = Date.now() + HYPERSPACE_CANCEL_GRACE_MS;
        if (hyperspaceGraceTimer) {
          clearTimeout(hyperspaceGraceTimer);
        }
        hyperspaceGraceTimer = setTimeout(() => {
          hyperspaceGraceUntil = 0;
          hyperspaceGraceTimer = null;
          setControlState(latestTelemetry, {});
        }, HYPERSPACE_CANCEL_GRACE_MS + 50);
      } else {
        hyperspaceGraceUntil = 0;
        if (hyperspaceGraceTimer) {
          clearTimeout(hyperspaceGraceTimer);
          hyperspaceGraceTimer = null;
        }
      }
      setControlState(latestTelemetry, {});
    }
    const keepHyperspaceCancelable = action === "hyperspace" && Date.now() < hyperspaceGraceUntil;
    button.disabled = !keepHyperspaceCancelable;
    button.dataset.busy = "true";
    try {
      const result = await apiPost("/cockpit/control", {
        action,
        dry_run: false,
        session_id: "mfd-display",
      });
      if (result.warning && result.warning.message) {
        setSafetyMessage(result.warning.message, {
          force: true,
          pinMs: result.warning.code === "missing_limpets" ? 5000 : 2500,
          priority: result.warning.code === "missing_limpets" ? "limpets" : "warning",
        });
        return;
      }
      const first = result.execute && Array.isArray(result.execute.results) ? result.execute.results[0] : {};
      setSafetyMessage(`Sent ${result.label || action}: ${first.status || "ok"}`, { force: true });
    } catch (err) {
      setSafetyMessage(`Control error: ${String(err.message || err)}`, { force: true, priority: "warning", pinMs: 3000 });
    } finally {
      button.dataset.busy = "false";
      button.disabled = false;
      button.dataset.unavailable = button.dataset.dockLocked === "true" ? "true" : "false";
      if (action === "hyperspace") {
        setControlState(latestTelemetry, {});
      }
    }
  }

  async function confirmIntent(item, button) {
    const intent = item.cockpit_action_intent || {};
    const action = intent.recommended_action || {};
    const tool = String(action.tool || "").trim();
    if (!tool) {
      return;
    }
    button.disabled = true;
    button.textContent = "Confirmed";
    try {
      await apiPost("/confirm", {
        incident_id: `mfd-${String(item.id || Date.now()).replace(/[^a-zA-Z0-9_-]/g, "_")}`,
        tool_name: tool,
        request_id: `req-mfd-${Date.now().toString(36)}`,
        session_id: "mfd-display",
        mode: "game",
      });
    } catch (err) {
      button.disabled = false;
      button.textContent = "Confirm";
      el.safety.textContent = `Confirm error: ${String(err.message || err)}`;
    }
  }

  function renderInfoPane(data) {
    const integrations = data.integrations || {};
    const items = [];
    const obs = integrations.obs || {};
    if (obs.enabled && obs.status && obs.status !== "disabled") {
      items.push({
        priority: obs.ok ? "low" : "medium",
        message: `OBS ${obs.status}`,
        detail: obs.ok ? "OBS status feed connected." : "OBS status feed needs attention.",
      });
    }
    const twitch = integrations.twitch || {};
    if (twitch.latest_event) {
      items.push({
        priority: "low",
        message: "Twitch",
        detail: String(twitch.latest_event),
      });
    }
    const messages = Array.isArray(data.messages) ? data.messages : [];
    for (const message of messages.slice(0, 4)) {
      items.push({
        priority: "low",
        message: message.title || message.source || "Watchkeeper",
        detail: message.detail || message.message || "",
      });
    }
    el.adviceList.innerHTML = "";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "mfd-advice-card";
      empty.textContent = "No stream messages.";
      el.adviceList.appendChild(empty);
      return;
    }
    for (const item of items) {
      const card = document.createElement("div");
      card.className = `mfd-advice-card ${String(item.priority || "").toLowerCase()}`;
      const title = document.createElement("strong");
      title.textContent = String(item.message || item.id || "Advice").toUpperCase();
      card.appendChild(title);
      if (item.detail) {
        const detail = document.createElement("div");
        detail.textContent = String(item.detail);
        card.appendChild(detail);
      }
      el.adviceList.appendChild(card);
    }
  }

  function render(data) {
    const t = data.telemetry || {};
    const safety = data.safety || {};
    const system = data.system_detail || {};
    const target = data.target || {};
    latestTelemetry = t;
    latestSafety = safety;
    if (el.core) {
      el.core.dataset.routeLayout = hasHyperspaceDestination(t, data.semantic || {}) ? "true" : "false";
    }
    setText(el.updated, `Updated: ${text(data.updated_at_utc)}`);
    setSafetyMessage(safety.input_locked ? "Controls locked" : "Controls ready");
    renderSystemContext(t, system, data.semantic || {});
    setText(el.mode, t.supercruise ? "Supercruise" : (t.docked ? "Docked" : "Normal"));
    setText(el.shield, t.shields_up === false ? "Down" : "Nominal");
    setText(el.fuel, t.fuel_main);
    setText(el.cargo, t.cargo);
    setText(el.pips, formatPips(t.pips));
    setText(el.legal, t.legal_state);
    setText(el.lastEvent, t.last_event);
    renderTargetContext(t, target, system, data.semantic || {});
    setText(el.fireGroup, t.fire_group);
    setText(el.guiFocus, t.gui_focus);
    setText(el.analysisMode, t.analysis_mode ? "Analysis" : "Combat/Nav");
    setShipSchematic(t.ship_model);
    setShieldBands(t);
    setShieldTrend(t);
    setShipTemperatureColor(t);
    renderFuelStrip(t);
    renderStatusIcons(t);
    syncShipViewToMode(t);
    renderShipView();
    setControlState(t, data.semantic || {});
    renderInfoPane(data);
  }

  async function refresh() {
    el.clock.textContent = new Date().toLocaleTimeString();
    try {
      render(await apiGet("/mfd/state"));
    } catch (err) {
      el.safety.textContent = `MFD error: ${String(err.message || err)}`;
    }
  }

  function renderStreamPayload(raw) {
    try {
      const data = JSON.parse(raw);
      data.mfd_client_received_at = new Date().toISOString();
      lastStreamAt = Date.now();
      render(data);
    } catch (err) {
      el.safety.textContent = `MFD stream parse error: ${String(err.message || err)}`;
    }
  }

  function startFallbackPolling() {
    if (fallbackPollTimer) {
      return;
    }
    fallbackPollTimer = setInterval(() => {
      if (!lastStreamAt || Date.now() - lastStreamAt > 2500) {
        refresh();
      }
    }, 1000);
  }

  function startMfdStream() {
    if (!window.EventSource) {
      startFallbackPolling();
      return;
    }
    try {
      mfdStream = new EventSource("/mfd/stream");
      mfdStream.addEventListener("cockpit", (event) => {
        renderStreamPayload(event.data);
      });
      mfdStream.addEventListener("hello", () => {
        lastStreamAt = Date.now();
      });
      mfdStream.addEventListener("ping", () => {
        lastStreamAt = Date.now();
      });
      mfdStream.onerror = () => {
        startFallbackPolling();
      };
    } catch {
      mfdStream = null;
      startFallbackPolling();
    }
  }

  function isAppDisplayMode() {
    return Boolean(
      document.fullscreenElement ||
      window.matchMedia("(display-mode: fullscreen)").matches ||
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone
    );
  }

  function updateFullscreenGate() {
    if (!el.fullscreenGate) {
      return;
    }
    el.fullscreenGate.hidden = isAppDisplayMode();
  }

  async function requestWakeLock() {
    if (!("wakeLock" in navigator) || document.visibilityState !== "visible") {
      return;
    }
    try {
      wakeLock = await navigator.wakeLock.request("screen");
      wakeLock.addEventListener("release", () => {
        wakeLock = null;
      });
    } catch {
      wakeLock = null;
    }
  }

  async function enterFullscreen() {
    const root = document.documentElement;
    try {
      if (root.requestFullscreen && !document.fullscreenElement) {
        await root.requestFullscreen({ navigationUI: "hide" });
      }
    } catch (err) {
      el.safety.textContent = `Fullscreen blocked: ${String(err.message || err)}`;
    }
    try {
      if (screen.orientation && screen.orientation.lock) {
        await screen.orientation.lock("landscape");
      }
    } catch {
      // Android allows orientation lock most reliably from an installed fullscreen PWA.
    }
    await requestWakeLock();
    updateFullscreenGate();
  }

  function registerPwa() {
    if (!("serviceWorker" in navigator)) {
      return;
    }
    navigator.serviceWorker.register("/mfd-sw.js").catch(() => {});
  }

  function isInteractiveTarget(target) {
    return Boolean(target.closest("button, a, input, select, textarea, .mfd-control, .mfd-ship-view-controls"));
  }

  function isCentralPaneTap(event, pane) {
    const rect = pane.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;
    return x > 0.22 && x < 0.78 && y > 0.22 && y < 0.82;
  }

  function togglePaneFocus(pane) {
    if (!el.core || !pane) {
      return;
    }
    const focused = el.core.dataset.focusedPanel === pane.dataset.panelId;
    delete el.core.dataset.focusedPanel;
    for (const display of document.querySelectorAll(".mfd-display")) {
      display.dataset.focused = "false";
    }
    if (!focused) {
      el.core.dataset.focusedPanel = pane.dataset.panelId || "pane";
      pane.dataset.focused = "true";
      hapticTap(12);
    } else {
      hapticTap(8);
    }
  }

  for (const btn of document.querySelectorAll(".mfd-control")) {
    btn.addEventListener("click", () => {
      if (btn.dataset.syncId) {
        toggleLightSync();
        return;
      }
      sendControl(btn.dataset.action, btn);
    });
  }

  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) {
      return;
    }
    const button = event.target.closest(".mfd-mode-icon[data-action]");
    if (!button) {
      return;
    }
    sendControl(button.dataset.action, button);
  });

  for (const pane of document.querySelectorAll(".mfd-display")) {
    pane.addEventListener("pointerup", (event) => {
      if (isInteractiveTarget(event.target) || !isCentralPaneTap(event, pane)) {
        return;
      }
      togglePaneFocus(pane);
    });
  }

  if (el.fullscreenButton) {
    el.fullscreenButton.addEventListener("click", enterFullscreen);
  }
  if (el.shipViewPrev) {
    el.shipViewPrev.addEventListener("click", () => {
      hapticTap(10);
      cycleShipView(-1);
    });
  }
  if (el.shipViewNext) {
    el.shipViewNext.addEventListener("click", () => {
      hapticTap(10);
      cycleShipView(1);
    });
  }
  document.addEventListener("fullscreenchange", updateFullscreenGate);
  document.addEventListener("visibilitychange", () => {
    updateFullscreenGate();
    if (document.visibilityState === "visible") {
      requestWakeLock();
      if (!mfdStream || mfdStream.readyState === EventSource.CLOSED) {
        startMfdStream();
      }
    }
  });
  window.matchMedia("(display-mode: fullscreen)").addEventListener("change", updateFullscreenGate);
  window.matchMedia("(display-mode: standalone)").addEventListener("change", updateFullscreenGate);

  registerPwa();
  updateFullscreenGate();
  requestWakeLock();
  renderShipView();
  refreshRuntimeSettings()
    .catch(() => {})
    .finally(() => {
      forceLightSyncOffForSession().catch(() => {});
    });
  refresh();
  startMfdStream();
  setInterval(() => {
    refreshRuntimeSettings().catch(() => {});
  }, 10000);
  startFallbackPolling();
})();
