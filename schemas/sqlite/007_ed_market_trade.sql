-- Watchkeeper vNext ED market/trade helper schema v1

CREATE TABLE IF NOT EXISTS ed_market_commodities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  market_id INTEGER NOT NULL,
  station_name TEXT,
  station_type TEXT,
  system_address INTEGER,
  system_name TEXT,
  commodity_name TEXT NOT NULL,
  commodity_localised TEXT,
  category TEXT,
  buy_price INTEGER,
  sell_price INTEGER,
  mean_price INTEGER,
  stock INTEGER,
  demand INTEGER,
  stock_bracket INTEGER,
  demand_bracket INTEGER,
  distance_to_arrival_ls REAL,
  source TEXT NOT NULL,
  provider_updated_at TEXT,
  last_refreshed_at TEXT NOT NULL,
  expires_at TEXT,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(market_id, commodity_name, source)
);

CREATE INDEX IF NOT EXISTS idx_ed_market_commodities_market
ON ed_market_commodities(market_id);

CREATE INDEX IF NOT EXISTS idx_ed_market_commodities_commodity
ON ed_market_commodities(commodity_name);

CREATE INDEX IF NOT EXISTS idx_ed_market_commodities_system
ON ed_market_commodities(system_address);

CREATE INDEX IF NOT EXISTS idx_ed_market_commodities_source
ON ed_market_commodities(source, expires_at);
