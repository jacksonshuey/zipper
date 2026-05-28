-- Zippering — generic schema (SQLite dialect).
--
-- Four core tables. Idempotent via IF NOT EXISTS. No domain-specific seed:
-- callers register their own global canonical columns at runtime.
--
-- SQLite dialect notes:
--   uuid        -> TEXT  (UUIDs generated in Python)
--   text[]      -> TEXT  (JSON-encoded array)
--   jsonb       -> TEXT  (JSON stored as TEXT)
--   timestamptz -> TEXT  (ISO 8601 strings; ordered lexicographically)

-- 1. global_canonical_columns — cross-pkey shared field registry
CREATE TABLE IF NOT EXISTS global_canonical_columns (
    id              TEXT PRIMARY KEY,
    workspace_key   TEXT NOT NULL DEFAULT 'default',
    name            TEXT NOT NULL,
    data_type       TEXT NOT NULL CHECK (data_type IN (
                        'text', 'integer', 'numeric', 'boolean',
                        'timestamp', 'jsonb', 'string[]'
                    )),
    description     TEXT,
    semantic_tags   TEXT NOT NULL DEFAULT '[]',   -- JSON array
    created_at      TEXT NOT NULL,
    UNIQUE (workspace_key, name)
);

CREATE INDEX IF NOT EXISTS global_canonical_columns_workspace_idx
    ON global_canonical_columns (workspace_key);

-- 2. zippering_schema — per-pkey canonical inventory (CURRENT state, mutable)
CREATE TABLE IF NOT EXISTS zippering_schema (
    id              TEXT PRIMARY KEY,
    workspace_key   TEXT NOT NULL DEFAULT 'default',
    pkey            TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    data_type       TEXT NOT NULL CHECK (data_type IN (
                        'text', 'integer', 'numeric', 'boolean',
                        'timestamp', 'jsonb', 'string[]'
                    )),
    description     TEXT,
    is_global       INTEGER NOT NULL DEFAULT 0,
    source_origin   TEXT,
    first_seen_at   TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (workspace_key, pkey, canonical_name)
);

CREATE INDEX IF NOT EXISTS zippering_schema_workspace_pkey_idx
    ON zippering_schema (workspace_key, pkey);

CREATE INDEX IF NOT EXISTS zippering_schema_canonical_idx
    ON zippering_schema (workspace_key, canonical_name);

-- 3. zippering_decisions — APPEND-ONLY routing + operator audit
CREATE TABLE IF NOT EXISTS zippering_decisions (
    id                  TEXT PRIMARY KEY,
    workspace_key       TEXT NOT NULL DEFAULT 'default',
    pkey                TEXT NOT NULL,
    source              TEXT NOT NULL,
    source_column       TEXT NOT NULL,
    source_data_type    TEXT,
    source_description  TEXT,
    source_samples      TEXT,            -- JSON array
    verdict             TEXT NOT NULL CHECK (verdict IN ('join', 'append', 'unclear')),
    canonical_name      TEXT NOT NULL,
    is_global_target    INTEGER NOT NULL DEFAULT 0,
    similarity_score    REAL,
    reason              TEXT,
    needs_review        INTEGER NOT NULL DEFAULT 0,
    decided_by          TEXT NOT NULL DEFAULT 'llm',
    decided_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS zippering_decisions_lookup_idx
    ON zippering_decisions (workspace_key, pkey, source, source_column, decided_at DESC);

CREATE INDEX IF NOT EXISTS zippering_decisions_needs_review_idx
    ON zippering_decisions (workspace_key, needs_review)
    WHERE needs_review = 1;

CREATE INDEX IF NOT EXISTS zippering_decisions_canonical_idx
    ON zippering_decisions (workspace_key, pkey, canonical_name);

-- 4. zippered_signals — the wide reconciled rows
CREATE TABLE IF NOT EXISTS zippered_signals (
    id              TEXT PRIMARY KEY,
    workspace_key   TEXT NOT NULL DEFAULT 'default',
    pkey            TEXT NOT NULL,
    source          TEXT NOT NULL,
    external_id     TEXT,
    occurred_at     TEXT NOT NULL,
    columns         TEXT NOT NULL DEFAULT '{}',   -- JSON object
    ingested_at     TEXT NOT NULL,
    UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS zippered_signals_pkey_time_idx
    ON zippered_signals (workspace_key, pkey, occurred_at DESC);

CREATE INDEX IF NOT EXISTS zippered_signals_source_idx
    ON zippered_signals (workspace_key, source, occurred_at DESC);
