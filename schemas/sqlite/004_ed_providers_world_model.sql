-- Watchkeeper vNext external ED providers world model schema v1

CREATE TABLE IF NOT EXISTS provider_health (
  provider TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('ok', 'degraded', 'throttled', 'down', 'misconfigured')),
  checked_at TEXT NOT NULL,
  latency_ms INTEGER,
  http_code INTEGER,
  rate_limit_state TEXT NOT NULL DEFAULT 'unknown'
    CHECK (rate_limit_state IN ('ok', 'unknown', 'throttled', 'cooldown')),
  retry_after_s INTEGER,
  tool_calls_allowed INTEGER NOT NULL DEFAULT 0 CHECK (tool_calls_allowed IN (0,1)),
  degraded_readonly INTEGER NOT NULL DEFAULT 0 CHECK (degraded_readonly IN (0,1)),
  message TEXT NOT NULL DEFAULT '',
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS provider_cache (
  cache_key TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  operation TEXT NOT NULL,
  stored_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  etag TEXT,
  normalized_json TEXT NOT NULL,
  raw_json TEXT,
  last_accessed_at_utc TEXT,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_provider_cache_lookup
ON provider_cache(provider, operation, expires_at);

CREATE INDEX IF NOT EXISTS idx_provider_cache_expiry
ON provider_cache(expires_at);

CREATE TABLE IF NOT EXISTS ed_systems (
  system_address INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  coords_x REAL,
  coords_y REAL,
  coords_z REAL,
  allegiance TEXT,
  government TEXT,
  security TEXT,
  economy TEXT,
  population INTEGER,
  extras_json TEXT,
  first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  last_refreshed_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  primary_source TEXT NOT NULL,
  source_confidence INTEGER,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_ed_systems_name
ON ed_systems(name);

CREATE INDEX IF NOT EXISTS idx_ed_systems_expires
ON ed_systems(expires_at);

CREATE TABLE IF NOT EXISTS ed_bodies (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  body_id64 INTEGER UNIQUE,
  system_address INTEGER NOT NULL,
  name TEXT NOT NULL,
  body_type TEXT NOT NULL,
  subtype TEXT,
  distance_to_arrival_ls REAL,
  terraform_state TEXT,
  atmosphere TEXT,
  gravity REAL,
  radius REAL,
  mass REAL,
  mapped_fields_json TEXT,
  last_refreshed_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  source TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(system_address, name),
  FOREIGN KEY(system_address) REFERENCES ed_systems(system_address) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ed_bodies_system
ON ed_bodies(system_address);

CREATE INDEX IF NOT EXISTS idx_ed_bodies_name
ON ed_bodies(name);

CREATE INDEX IF NOT EXISTS idx_ed_bodies_expires
ON ed_bodies(expires_at);

CREATE TABLE IF NOT EXISTS ed_stations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_id INTEGER UNIQUE,
  station_id64 INTEGER UNIQUE,
  system_address INTEGER NOT NULL,
  name TEXT NOT NULL,
  station_type TEXT,
  distance_to_arrival_ls REAL,
  has_docking INTEGER CHECK (has_docking IN (0,1)),
  services_json TEXT,
  last_refreshed_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  source TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(system_address, name),
  FOREIGN KEY(system_address) REFERENCES ed_systems(system_address) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_ed_stations_system
ON ed_stations(system_address);

CREATE INDEX IF NOT EXISTS idx_ed_stations_name
ON ed_stations(name);

CREATE INDEX IF NOT EXISTS idx_ed_stations_market
ON ed_stations(market_id);

CREATE INDEX IF NOT EXISTS idx_ed_stations_expires
ON ed_stations(expires_at);
