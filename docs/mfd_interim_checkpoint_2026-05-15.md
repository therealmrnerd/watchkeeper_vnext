# MFD Interim Checkpoint - 2026-05-15

This checkpoint captures the current Watchkeeper MFD work-in-progress, including the live pane layout, ship schematic work, route/jump UI, target pane treatments, system context variants, and cockpit control/light-sync plumbing.

## Screenshots

| Area | Screenshot |
| --- | --- |
| Full desktop MFD layout | `artifacts/mfd-interim-2026-05-15/mfd-overview-desktop.png` |
| Tablet/minimised layout | `artifacts/mfd-interim-2026-05-15/mfd-overview-tablet.png` |
| System pane live state | `artifacts/mfd-interim-2026-05-15/mfd-system-pane-live.png` |
| Vessel pane live state | `artifacts/mfd-interim-2026-05-15/mfd-vessel-pane-live.png` |
| Hyperspace route pane sample | `artifacts/mfd-interim-2026-05-15/mfd-route-pane-sample.png` |
| Target pane sample | `artifacts/mfd-interim-2026-05-15/mfd-target-pane-sample.png` |
| Planetary approach pane sample | `artifacts/mfd-interim-2026-05-15/mfd-planet-pane-sample.png` |
| SLF pane sample | `artifacts/mfd-interim-2026-05-15/mfd-slf-pane-sample.png` |

## MFD Functions In This Checkpoint

- Cockpit control rails for hardpoints, flight assist, light sync, maps, FSS, nav/comms/role/management panels, supercruise, hyperspace, lights, night vision, and blank filler buttons.
- Docking/launch controls in the system pane, including state-based availability and auto-dock/auto-launch plumbing.
- System context pane with station/body/system details, faction/government/economy/security/population, civil-war state, and scoopable fuel-star information.
- Planetary approach, on-foot, station, SRV, and SLF conditional pane handling.
- Vessel pane with EDSA-style schematics, hardpoint labels, marker/leader-line overlays, pips, fuel, shield/hull meters, and ship-specific asset routing.
- Target pane with clean/wanted/enemy/scanning reticle rules, brighter schematic handling, and no stale schematic when no target is locked.
- Hyperspace route pane with destination, distance, remaining jumps, next jump, star class/fuel-star status, and upcoming jumps.
- Elite journal/status scraper additions for travel, docking, route, target, station, fuel, pips, and state telemetry.
- Runtime settings toggles for sync providers, with SAMMI push disabled by settings and Jinx light sync used as the light gate.
- Jinx lifecycle handling: launch from the saved path, pass `-m`, prevent duplicate opens, send Art-Net effect bursts, and force-close Jinx when Light Sync is disabled.
