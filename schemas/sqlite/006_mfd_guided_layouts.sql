-- Guided MFD layout editor persistence.

CREATE TABLE IF NOT EXISTS mfd_layouts (
  layout_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  orientation TEXT NOT NULL CHECK (orientation IN ('landscape','portrait')),
  pane_mode TEXT NOT NULL CHECK (pane_mode IN ('four','single')),
  buttons_visible INTEGER NOT NULL CHECK (buttons_visible IN (0,1)),
  layout_json TEXT NOT NULL,
  is_template INTEGER NOT NULL DEFAULT 0 CHECK (is_template IN (0,1)),
  created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_mfd_layouts_name
ON mfd_layouts(name);

CREATE TABLE IF NOT EXISTS mfd_outputs (
  output_id INTEGER PRIMARY KEY CHECK (output_id BETWEEN 1 AND 5),
  label TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0,1)),
  active_layout_id TEXT,
  created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  FOREIGN KEY(active_layout_id) REFERENCES mfd_layouts(layout_id) ON DELETE SET NULL
);

INSERT OR IGNORE INTO mfd_outputs(output_id,label,enabled)
VALUES
  (1,'Output 1',1),
  (2,'Output 2',0),
  (3,'Output 3',0),
  (4,'Output 4',0),
  (5,'Output 5',0);
