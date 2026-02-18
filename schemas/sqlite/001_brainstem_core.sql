-- Watchkeeper vNext Brainstem Core Schema v1
-- Apply with: sqlite3 data/watchkeeper_vnext.db ".read schemas/sqlite/001_brainstem_core.sql"

PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS config (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS capabilities (
  capability_name TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('available', 'degraded', 'unavailable')),
  source TEXT NOT NULL,
  details_json TEXT,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS state_current (
  state_key TEXT PRIMARY KEY,
  state_value_json TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence REAL CHECK (confidence >= 0 AND confidence <= 1),
  observed_at_utc TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS event_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id TEXT NOT NULL UNIQUE,
  timestamp_utc TEXT NOT NULL,
  event_type TEXT NOT NULL,
  source TEXT NOT NULL,
  profile TEXT,
  session_id TEXT,
  correlation_id TEXT,
  mode TEXT CHECK (mode IN ('game', 'work', 'standby', 'tutor')),
  severity TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('debug', 'info', 'warn', 'error')),
  payload_json TEXT NOT NULL,
  tags_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_event_log_timestamp ON event_log(timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_event_log_type ON event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_event_log_correlation ON event_log(correlation_id);
CREATE INDEX IF NOT EXISTS idx_event_log_session ON event_log(session_id);

CREATE TABLE IF NOT EXISTS intent_log (
  request_id TEXT PRIMARY KEY,
  schema_version TEXT NOT NULL,
  timestamp_utc TEXT NOT NULL,
  session_id TEXT,
  mode TEXT NOT NULL CHECK (mode IN ('game', 'work', 'standby', 'tutor')),
  domain TEXT NOT NULL,
  urgency TEXT NOT NULL CHECK (urgency IN ('low', 'normal', 'high')),
  user_text TEXT NOT NULL,
  needs_tools INTEGER NOT NULL CHECK (needs_tools IN (0,1)),
  needs_clarification INTEGER NOT NULL CHECK (needs_clarification IN (0,1)),
  clarification_questions_json TEXT,
  retrieval_json TEXT,
  proposed_actions_json TEXT NOT NULL,
  response_text TEXT,
  created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_intent_log_timestamp ON intent_log(timestamp_utc DESC);
CREATE INDEX IF NOT EXISTS idx_intent_log_mode_domain ON intent_log(mode, domain);

CREATE TABLE IF NOT EXISTS action_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL,
  action_id TEXT NOT NULL,
  tool_name TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued', 'approved', 'denied', 'executing', 'success', 'error', 'timeout')),
  safety_level TEXT NOT NULL CHECK (safety_level IN ('read_only', 'low_risk', 'high_risk')),
  mode_at_execution TEXT CHECK (mode_at_execution IN ('game', 'work', 'standby', 'tutor')),
  reason TEXT,
  parameters_json TEXT NOT NULL,
  output_json TEXT,
  error_code TEXT,
  error_message TEXT,
  started_at_utc TEXT,
  ended_at_utc TEXT,
  created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(request_id, action_id),
  FOREIGN KEY(request_id) REFERENCES intent_log(request_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_action_log_request ON action_log(request_id);
CREATE INDEX IF NOT EXISTS idx_action_log_tool_status ON action_log(tool_name, status);
CREATE INDEX IF NOT EXISTS idx_action_log_created ON action_log(created_at_utc DESC);

CREATE TABLE IF NOT EXISTS feedback_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT NOT NULL,
  rating INTEGER NOT NULL CHECK (rating IN (-1, 1)),
  correction_text TEXT,
  reviewer TEXT DEFAULT 'user',
  created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY(request_id) REFERENCES intent_log(request_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_feedback_request ON feedback_log(request_id);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback_log(created_at_utc DESC);

CREATE TABLE IF NOT EXISTS stt_bias_lexicon (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  phrase TEXT NOT NULL,
  normalized_phrase TEXT NOT NULL,
  mode TEXT CHECK (mode IN ('game', 'work', 'standby', 'tutor')),
  weight REAL NOT NULL DEFAULT 1.0 CHECK (weight >= 0),
  source TEXT NOT NULL DEFAULT 'manual',
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(normalized_phrase, mode)
);

CREATE INDEX IF NOT EXISTS idx_stt_bias_mode_active ON stt_bias_lexicon(mode, active);
