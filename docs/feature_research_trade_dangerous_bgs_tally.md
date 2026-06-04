# Feature Research - Trade Dangerous and BGS-Tally

This note captures useful Watchkeeper vNext feature directions inspired by two mature Elite Dangerous tools:

- Trade Dangerous: https://github.com/eyeonus/Trade-Dangerous
- BGS-Tally: https://github.com/aussig/BGS-Tally

The goal is not to clone either project. The useful Watchkeeper translation is to turn their strengths into shipboard roles:

- Trade Dangerous becomes route, market, station, and cargo intelligence.
- BGS-Tally becomes an operations ledger, campaign tracker, and after-action system.

## Trade Dangerous

Trade Dangerous is a Python command/tooling stack with a local database and a route optimiser. Its core idea is that useful trading advice needs local market data, ship constraints, cargo capacity, available credits, station distance, jump range, and route limits.

Useful concepts for Watchkeeper:

- Local market intelligence cache
  - commodity prices
  - station services
  - pad size
  - market age/staleness
  - station distance from arrival star

- Route officer mode
  - "best next sell"
  - "best nearby buy"
  - "profitable two-hop route"
  - "nearest station with service X"
  - "nearest large pad with market/refuel/repair"

- Cargo-aware recommendations
  - compare current cargo against known demand
  - suggest sell station candidates
  - warn when cargo is illegal or risky in the target jurisdiction
  - identify stale market data before giving confident advice

- Query grammar for Major Tom
  - "Where can I sell this cargo?"
  - "Find repair within two jumps."
  - "Find large pad with outfitting near the route."
  - "What should I buy here?"

- Import/update pipeline
  - cache-first local DB
  - provider update health state
  - explicit stale-data warnings
  - no dependency on retired EDDB endpoints

Watchkeeper fit:

- Add a Cargo / Trade Officer pane.
- Add a Station Services Resolver used by system, target, and docking panes.
- Add read-only Major Tom tools backed by local data:
  - `find_trade_sell_candidates`
  - `find_station_service`
  - `summarize_market_opportunity`
  - `explain_market_data_age`

## BGS-Tally

BGS-Tally is an EDMC plugin that tracks and reports Background Simulation, colonisation, Powerplay merits, Thargoid War activity, commander interactions, and fleet carrier activity. It writes local JSON activity data by tick and only sends data externally when configured.

Useful concepts for Watchkeeper:

- Tick-bucketed activity ledger
  - one operational period per BGS tick
  - current tick, previous tick, and session rollups
  - local storage by default

- BGS contribution tracking
  - missions
  - trade profit
  - bounties
  - combat bonds
  - exploration data
  - black market profit
  - murder/notoriety-style negative actions where applicable
  - on-foot and space conflict zones

- Objective/campaign layer
  - target faction
  - target system
  - desired action
  - progress against a commander-defined goal

- Reporting
  - Discord-ready summaries
  - CSV/export-ready session reports
  - optional API push to external aggregators

- Privacy model
  - local-first storage
  - external posting only when explicitly configured
  - clear network behavior documentation

Watchkeeper fit:

- Add an Operations Ledger table family:
  - `ed_activity_ticks`
  - `ed_activity_events`
  - `ed_activity_rollups`
  - `ed_campaign_objectives`
  - `ed_external_report_targets`

- Add an After Action Report pane:
  - "This sortie moved cargo, completed missions, claimed bonds, scanned systems."
  - "Likely BGS impacts by faction/system."
  - "Powerplay merits earned."
  - "Carrier operations logged."

- Add Major Tom tools:
  - `summarize_current_sortie`
  - `summarize_bgs_activity`
  - `list_active_objectives`
  - `explain_faction_activity`
  - `prepare_discord_report`

## Watchkeeper Feature Candidates

### 1. Cargo / Trade Officer

Primary screen:

- current cargo
- nearby sell candidates
- station pad/service compatibility
- expected profit
- confidence/staleness indicator

Context triggers:

- cargo changed
- station targeted
- docked at market
- route destination selected

### 2. Route Intel Pane

Primary screen:

- current system
- destination
- next three jumps
- scoopable stars
- nearest repair/refuel options
- route warnings

Context triggers:

- nav route set
- hyperspace countdown
- hyperspace entry/exit
- fuel low

### 3. Operations Ledger

Primary screen:

- session events grouped by system and faction
- trade, combat, mission, exploration, Powerplay, Thargoid, colonisation totals
- "needs confirmation" rows where journal data is ambiguous

Context triggers:

- mission completed
- voucher redeemed
- market sold
- exploration data sold
- Powerplay merit event
- conflict-zone state

### 4. Campaign Objectives

Primary screen:

- commander-defined campaign cards
- target system/faction
- desired actions
- progress this tick
- report export

This should be guided, not freeform, matching the layout editor philosophy.

### 5. Major Tom Data Discipline

Major Tom should avoid stale generic replies by using local tools first:

1. check current ship/location state
2. check latest journal-derived station/system context
3. check local provider cache
4. check BGS/activity ledger
5. only then produce an answer, with an explicit "I do not know yet" path

Example answer shape:

- "You are docked at Blackstar's Cove, a Coriolis in Puppis Sector ON-T b3-5."
- "Local cache knows allegiance, economy, security, population, controlling faction, and Powerplay state."
- "I do not yet have fresh market data for this station."
- "This session logged one docking event and no market sales."

## Implementation Notes

- Keep external provider lookups cache-first and rate-budgeted.
- Keep commander-linked APIs opt-in.
- Do not resurrect EDDB as a dependency.
- Separate system security state from faction/system/powerplay state in stored data and UI labels.
- Store activity facts even before there is a final UI. The ledger becomes useful as soon as Major Tom can query it.
- Prefer journal-derived facts over UI inference.
- Label stale data aggressively. A quiet wrong answer is worse than a useful "not enough data yet."

## Near-Term Build Order

1. Add an activity-ledger schema migration and append-only event writer.
2. Add a station service resolver backed by journal, local cache, and EDSM/provider lookups.
3. Add Major Tom read-only tool wrappers for current location, station details, route, cargo, and recent activity.
4. Add a simple Operations Ledger pane.
5. Add Cargo / Trade Officer as a later pane once commodity data has a reliable provider/update story.
