# Domain Helper Plan - Exobiology, AX, BGS, Trade

Watchkeeper should treat these as shipboard roles, not generic chat topics. Each role needs:

- local journal facts first
- provider enrichment second
- explicit stale/unknown labels
- MFD pane hooks
- read-only Major Tom tools before automation

## Provider Reality

- EDSM (`https://www.edsm.net/en/api-v1`): useful for systems, coordinates, stations, celestial bodies, minor factions, station markets/outfitting, and faction influence history.
- EDDN (`https://github.com/EDCD/EDDN`): live data stream, not a query database. Good indirect source through aggregators or future listener/cache work.
- EliteBGS (`https://elitebgs.app/api/ebgs/v5`): useful BGS-focused API surface for faction/system state and EDDB-style access.
- Spansh (`https://spansh.co.uk/`): useful for galaxy dumps, route/search tooling, and whole-galaxy datasets. Best as cached bulk/provider data, not hot per-frame queries.
- Inara (`https://inara.cz/elite/inara-api/`): useful for commander/station/market style workflows when authenticated or when public pages/API access is available.
- DCoH Overwatch (`https://dcoh.watch/`): useful AX/thargoid-war reference, currently read-only while no systems are affected by active Thargoid war states.
- AXI Wiki (`https://wiki.antixenoinitiative.com/`): tactics, ship/build, encounter guidance, and AX-specific advisory content.

## Xeno Biology / Exobiology Helper

### Local Inputs

- `SAASignalsFound`: body biological signals and genuses.
- `ScanOrganic`: organic sampling lifecycle, with `Log`, `Sample`, and `Analyse`.
- `CodexEntry`: species/codex discoveries, coordinates, voucher values, and traits.
- `Touchdown`, `Liftoff`, `ApproachBody`, `LeaveBody`: surface session boundaries.
- Status flags: on foot, on planet, latitude, longitude, altitude, heading, selected tool/weapon if available.

### External Inputs

- EDSM bodies for known body metadata and coordinates.
- Spansh dumps/search for body biological candidates and regional lookup.
- Community value tables for organic species value estimates.

### Helper Behaviour

- Track current body biological survey state.
- Show scan sequence progress: `not logged`, `logged`, `sample 1/3`, `sample 2/3`, `analyse complete`.
- Warn if the commander scans the same species too close to a previous sample, once distance rules are encoded.
- Present body/genus checklist from `SAASignalsFound`.
- Record species, variant, coordinates, voucher amount, and completion.
- Major Tom questions:
  - "What biology is left on this body?"
  - "What did I scan here?"
  - "Is this body worth finishing?"
  - "Show my exobio haul this session."

## Anti-Xeno Combat Helper

### Local Inputs

- `FSSSignalDiscovered`: non-human signal sources, threat levels, spawning faction/power.
- `USSDrop`: NHSS or AX combat-zone drop context.
- `ShipTargeted`: target ship/type/faction/legal status; likely snapshot only.
- `Bounty`, `FactionKillBond`, `RedeemVoucher`: AX bonds and combat outcomes.
- `Interdicted`: `IsThargoid` flag for hyperdiction/interdiction.
- `Died`: death attribution and ship/rank context.
- Status flags: hardpoints, fire group, danger, heat, hull, oxygen/canopy if available.

### External Inputs

- AXI Wiki for tactics/build/target recognition knowledge.
- DCoH Overwatch API/status for active war systems if/when relevant.
- EDSM/Inara/Spansh for station repair/rescue proximity.

### Helper Behaviour

- Detect AX context from Thargoid interdiction, NHSS, Thargoid war system data, or target/faction naming.
- Present AX engagement card:
  - threat level
  - signal type
  - target class if known
  - repair/rearm nearest station
  - current heat/hull/canopy risk
- Post-combat ledger:
  - kills/bonds
  - voucher claims
  - death events
- Major Tom questions:
  - "What AX signal did I drop into?"
  - "Nearest repair/rearm?"
  - "Summarise this AX sortie."
  - "What should I target next?"

## BGS Helper

### Local Inputs

- `Location`, `FSDJump`, `CarrierJump`: system faction, faction state, conflicts, powerplay state.
- `MissionAccepted`, `MissionCompleted`, `MissionFailed`: faction, influence, reputation, reward, destination, donation.
- `MarketSell`, `MarketBuy`, `SearchAndRescue`: economic activity.
- `Bounty`, `FactionKillBond`, `RedeemVoucher`: combat influence activity.
- `CommitCrime`, deaths, fines, bounties: negative/hostile activity signals.
- Docking and station context for station faction/economy/security.

### External Inputs

- EDSM faction/system APIs for faction influence and history.
- EliteBGS API for faction/system BGS records and EDDB-style lookup.
- Inara where useful for public faction/system snapshots.

### Helper Behaviour

- Build a local append-only Operations Ledger.
- Bucket activity by tick/session, system, faction, and action type.
- Track objective cards:
  - target faction
  - target system
  - desired direction
  - helpful actions
  - harmful actions
- Produce an after-action report with confidence levels:
  - "confirmed by journal"
  - "estimated BGS effect"
  - "provider state stale/unknown"
- Major Tom questions:
  - "What did I do for Blackstar this session?"
  - "Which faction did these missions help?"
  - "What BGS actions are useful here?"
  - "Prepare a Discord report."

## Space Trucking / Trade Helper

### Local Inputs

- `Cargo.json` and `Cargo`: current hold.
- `Market`: current station market snapshot and market id.
- `MarketBuy`, `MarketSell`: transaction ledger with price, count, black-market/illegal flags.
- `CargoDepot`: mission cargo collection/delivery progress.
- `CollectCargo`, `EjectCargo`: salvage/piracy/mining/mission cargo movement.
- Station services from `Docked` and station/provider data.

### External Inputs

- EDSM station market endpoint for market/station details where available.
- EDDN indirectly through community aggregators or a future Watchkeeper cache listener.
- Spansh dumps/search for station/station-service and commodity data.
- Inara/API where configured.

### Helper Behaviour

- Current cargo manifest with mission/non-mission split.
- Local buy/sell ledger and realised profit.
- Station compatibility:
  - market present
  - pad size
  - distance from arrival star
  - black market
  - repair/refuel/rearm
- Provider-backed route suggestions:
  - where to sell current cargo
  - what to buy here
  - nearby two-hop trade route
  - warn when data age is too stale
- Major Tom questions:
  - "Where can I sell this cargo?"
  - "What should I buy here?"
  - "How much did this haul make?"
  - "Find a large-pad market near the route."

## Near-Term Build Order

1. Expand journal harvesting for the four domains.
2. Add an append-only `ed_activity_events` table and rollup writer.
3. Add exobiology session projection from `ScanOrganic` and `SAASignalsFound`.
4. Add cargo/trade session projection from `Cargo`, `Market`, `MarketBuy`, and `MarketSell`.
5. Add BGS ledger projection from missions, vouchers, faction bonds, and market sales.
6. Add AX context projection from `Interdicted`, `USSDrop`, `FSSSignalDiscovered`, `Bounty`, and `RedeemVoucher`.
7. Add provider capability registry so Major Tom can say which APIs are available, stale, or missing.
8. Add read-only Major Tom tools for each helper before adding richer MFD panes.

## Data Discipline

- Never present provider data as live unless it came from current journal files.
- Attach `source`, `observed_at`, `provider`, and `stale_after` metadata to every enriched fact.
- Separate snapshot values from live values.
- Keep commander/API-authenticated providers opt-in.
- Prefer "I do not know yet" over confident guesses.
