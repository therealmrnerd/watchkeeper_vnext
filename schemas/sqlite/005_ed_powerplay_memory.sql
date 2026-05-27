-- Elite Dangerous Powerplay reference data kept local for MFD art and Major Tom retrieval.

CREATE TABLE IF NOT EXISTS ed_powerplay_powers (
  power_key TEXT PRIMARY KEY,
  power_name TEXT NOT NULL UNIQUE,
  headquarters TEXT NOT NULL,
  allegiance TEXT NOT NULL,
  acquisition_ethos TEXT NOT NULL,
  reinforcement_ethos TEXT NOT NULL,
  undermining_ethos TEXT NOT NULL,
  symbol_asset_path TEXT NOT NULL,
  source_url TEXT NOT NULL,
  source_as_of_date TEXT NOT NULL,
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_ed_powerplay_powers_name
ON ed_powerplay_powers(power_name);

CREATE INDEX IF NOT EXISTS idx_ed_powerplay_powers_allegiance
ON ed_powerplay_powers(allegiance);

INSERT INTO ed_powerplay_powers(
  power_key,power_name,headquarters,allegiance,
  acquisition_ethos,reinforcement_ethos,undermining_ethos,
  symbol_asset_path,source_url,source_as_of_date
)
VALUES
  ('aisling-duval','Aisling Duval','Cubeo','Empire','Social','Finance','Social','icons/powers/aisling-duval.svg','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22'),
  ('archon-delaine','Archon Delaine','Harma','Independent','Combat','Combat','Social','icons/powers/archon-delaine.svg','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22'),
  ('arissa-lavigny-duval','Arissa Lavigny-Duval','Kamadhenu','Empire','Social','Combat','Combat','icons/powers/arissa-lavigny-duval.svg','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22'),
  ('denton-patreus','Denton Patreus','Eotienses','Empire','Combat','Finance','Combat','icons/powers/denton-patreus.svg','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22'),
  ('edmund-mahon','Edmund Mahon','Gateway','Alliance','Finance','Social','Social','icons/powers/edmund-mahon.svg','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22'),
  ('felicia-winters','Felicia Winters','Rhea','Federation','Social','Finance','Social','icons/powers/felicia-winters.svg','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22'),
  ('jerome-archer','Jerome Archer','Nanomam','Federation','Combat','Combat','Combat','icons/powers/jerome-archer.svg','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22'),
  ('li-yong-rui','Li Yong-Rui','Lembava','Independent','Social','Finance','Finance','icons/powers/li-yong-rui.svg','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22'),
  ('nakato-kaine','Nakato Kaine','Tionisla','Alliance','Social','Covert','Social','icons/powers/nakato-kaine.svg','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22'),
  ('pranav-antal','Pranav Antal','Polevnic','Independent','Social','Social','Covert','icons/powers/pranav-antal.svg','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22'),
  ('yuri-grom','Yuri Grom','Clayakarma','Independent','Covert','Combat','Covert','icons/powers/yuri-grom.png','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22'),
  ('zemina-torval','Zemina Torval','Synteini','Empire','Finance','Finance','Covert','icons/powers/zemina-torval.svg','https://elite-dangerous.fandom.com/wiki/Powerplay','2026-05-22')
ON CONFLICT(power_key) DO UPDATE SET
  power_name=excluded.power_name,
  headquarters=excluded.headquarters,
  allegiance=excluded.allegiance,
  acquisition_ethos=excluded.acquisition_ethos,
  reinforcement_ethos=excluded.reinforcement_ethos,
  undermining_ethos=excluded.undermining_ethos,
  symbol_asset_path=excluded.symbol_asset_path,
  source_url=excluded.source_url,
  source_as_of_date=excluded.source_as_of_date,
  updated_at_utc=strftime('%Y-%m-%dT%H:%M:%fZ','now');

INSERT OR IGNORE INTO facts_triples(
  triple_id,subject,predicate,object,source,as_of_date,confidence,metadata_json
)
SELECT
  'ed.powerplay.' || power_key || '.profile',
  power_name,
  'ed.powerplay.profile',
  'Powerplay power. Headquarters: ' || headquarters ||
    '. Allegiance: ' || allegiance ||
    '. Ethos: acquisition ' || acquisition_ethos ||
    ', reinforcement ' || reinforcement_ethos ||
    ', undermining ' || undermining_ethos || '.',
  'gameplay:elite-dangerous:fandom-powerplay',
  source_as_of_date,
  0.9,
  '{"kind":"powerplay_power","table":"ed_powerplay_powers"}'
FROM ed_powerplay_powers;
