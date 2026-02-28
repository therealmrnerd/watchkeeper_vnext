-- Watchkeeper vNext Twitch ingest + user modelling schema v1

CREATE TABLE IF NOT EXISTS twitch_user (
  user_id TEXT PRIMARY KEY,
  login_name TEXT,
  display_name TEXT,
  flags_json TEXT NOT NULL DEFAULT '{}',
  first_seen_utc TEXT NOT NULL,
  last_seen_utc TEXT NOT NULL,
  message_count INTEGER NOT NULL DEFAULT 0,
  created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_twitch_user_last_seen ON twitch_user(last_seen_utc DESC);

CREATE TABLE IF NOT EXISTS twitch_user_recent_message (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  message_ts_utc TEXT NOT NULL,
  msg_id TEXT,
  message_text TEXT NOT NULL,
  created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(msg_id),
  FOREIGN KEY(user_id) REFERENCES twitch_user(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_twitch_recent_msg_user_ts
ON twitch_user_recent_message(user_id, message_ts_utc DESC, id DESC);

CREATE TABLE IF NOT EXISTS twitch_user_stats (
  user_id TEXT PRIMARY KEY,
  bits_total INTEGER NOT NULL DEFAULT 0,
  bits_count INTEGER NOT NULL DEFAULT 0,
  last_bits_ts_utc TEXT,
  redeem_total INTEGER NOT NULL DEFAULT 0,
  last_redeem_ts_utc TEXT,
  hype_total INTEGER NOT NULL DEFAULT 0,
  last_hype_ts_utc TEXT,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY(user_id) REFERENCES twitch_user(user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS twitch_user_redeem_summary (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  reward_id TEXT NOT NULL,
  reward_title TEXT,
  claim_count INTEGER NOT NULL DEFAULT 0,
  last_claim_utc TEXT NOT NULL,
  UNIQUE(user_id, reward_id),
  FOREIGN KEY(user_id) REFERENCES twitch_user(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_twitch_redeem_user_count
ON twitch_user_redeem_summary(user_id, claim_count DESC, last_claim_utc DESC);

CREATE TABLE IF NOT EXISTS twitch_event_cursor (
  event_type TEXT PRIMARY KEY,
  last_commit_ts TEXT NOT NULL DEFAULT '',
  last_seen_seq INTEGER NOT NULL DEFAULT 0,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS twitch_event_recent (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  commit_ts TEXT NOT NULL,
  user_id TEXT,
  payload_json TEXT NOT NULL,
  created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_twitch_event_recent_ts
ON twitch_event_recent(commit_ts DESC, id DESC);

CREATE TABLE IF NOT EXISTS twitch_cooldown (
  user_id TEXT NOT NULL,
  action_key TEXT NOT NULL,
  last_trigger_ts_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY(user_id, action_key)
);
