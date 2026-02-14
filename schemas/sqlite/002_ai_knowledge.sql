-- Watchkeeper vNext AI Knowledge Schema v1

CREATE TABLE IF NOT EXISTS facts_triples (
  triple_id TEXT PRIMARY KEY,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object TEXT NOT NULL,
  source TEXT,
  as_of_date TEXT,
  confidence REAL CHECK (confidence >= 0 AND confidence <= 1),
  metadata_json TEXT,
  created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_unique
ON facts_triples(subject, predicate, object, ifnull(source, ''));

CREATE INDEX IF NOT EXISTS idx_facts_subject ON facts_triples(subject);
CREATE INDEX IF NOT EXISTS idx_facts_predicate ON facts_triples(predicate);
CREATE INDEX IF NOT EXISTS idx_facts_object ON facts_triples(object);

CREATE TABLE IF NOT EXISTS vector_documents (
  doc_id TEXT PRIMARY KEY,
  domain TEXT,
  title TEXT,
  text_content TEXT NOT NULL,
  source_id TEXT,
  metadata_json TEXT,
  embedding_json TEXT NOT NULL,
  embedding_model TEXT NOT NULL DEFAULT 'hash-v1',
  dimension INTEGER NOT NULL,
  created_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  updated_at_utc TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_vector_domain ON vector_documents(domain);
CREATE INDEX IF NOT EXISTS idx_vector_source ON vector_documents(source_id);
