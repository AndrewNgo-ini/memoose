"""The SQLite schema of one Dataset. Applied on every open; every statement is idempotent."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- ontology
CREATE TABLE IF NOT EXISTS entity_types (
    name TEXT PRIMARY KEY, description TEXT NOT NULL, builtin INTEGER NOT NULL DEFAULT 0,
    parent TEXT, source_id TEXT, aliases TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS functional_relations (name TEXT PRIMARY KEY, declared_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS ontology_sources (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL, imported_at REAL NOT NULL,
    class_count INTEGER NOT NULL);

-- graph
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, description TEXT NOT NULL,
    mentions INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', evidence TEXT,
    chunk_id TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
    superseded INTEGER NOT NULL DEFAULT 0, superseded_by TEXT, supersession_reason TEXT,
    weight REAL NOT NULL DEFAULT 1.0, valid_from TEXT, valid_to TEXT);
CREATE INDEX IF NOT EXISTS relations_source ON relations(source_id);
CREATE INDEX IF NOT EXISTS relations_target ON relations(target_id);
CREATE TABLE IF NOT EXISTS entity_weights (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    frequency REAL NOT NULL DEFAULT 1.0, feedback REAL NOT NULL DEFAULT 1.0);
CREATE TABLE IF NOT EXISTS contradictions (
    id TEXT PRIMARY KEY, first_relation_id TEXT NOT NULL, second_relation_id TEXT NOT NULL,
    reason TEXT NOT NULL, confidence REAL NOT NULL, created_at REAL NOT NULL, resolved_by TEXT);

-- source text and search
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY, text TEXT NOT NULL, summary TEXT, source TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS entity_chunks (
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    PRIMARY KEY (entity_id, chunk_id));
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    kind UNINDEXED, ref_id UNINDEXED, text, tokenize='porter unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS embeddings (
    kind TEXT NOT NULL, ref_id TEXT NOT NULL, model TEXT NOT NULL, vector BLOB NOT NULL,
    PRIMARY KEY (kind, ref_id));
CREATE TABLE IF NOT EXISTS context_buckets (
    id TEXT PRIMARY KEY, key TEXT NOT NULL, label TEXT NOT NULL, member_ids TEXT NOT NULL,
    summary TEXT, summary_stale INTEGER NOT NULL DEFAULT 1, updated_at REAL NOT NULL);

-- sessions and lessons
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, started_at REAL NOT NULL, ended_at REAL, distilled_at REAL);
CREATE TABLE IF NOT EXISTS session_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL, text TEXT NOT NULL, created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS session_turns_session ON session_turns(session_id);
CREATE TABLE IF NOT EXISTS session_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    section TEXT NOT NULL, content TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 1.0,
    created_at REAL NOT NULL, retired_at REAL);
CREATE TABLE IF NOT EXISTS lessons (
    id TEXT PRIMARY KEY, session_id TEXT, title TEXT NOT NULL, text TEXT NOT NULL, evidence TEXT,
    accepted_at REAL NOT NULL, entity_id TEXT, chunk_id TEXT);

-- append-only ledger of every write
CREATE TABLE IF NOT EXISTS provenance (
    id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
    kind TEXT NOT NULL, ref_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS provenance_ref ON provenance(kind, ref_id);
"""

# Columns added after a table shipped. SQLite has no ADD COLUMN IF NOT EXISTS, so the store
# checks table_info and adds what is missing; the list is the migration history.
COLUMNS = [
    # Procedural Graphs (ADR 0005): a Transition's attributes, and how its traversals ended.
    ("relations", "condition", "TEXT"),
    ("relations", "advice", "TEXT"),
    ("relations", "pitfall", "TEXT"),
    ("relations", "succeeded", "INTEGER NOT NULL DEFAULT 0"),
    ("relations", "failed", "INTEGER NOT NULL DEFAULT 0"),
    ("relations", "abandoned", "INTEGER NOT NULL DEFAULT 0"),
    ("session_turns", "position", "TEXT"),  # the Procedure the agent declared it was at
    ("sessions", "outcome", "TEXT"),  # succeeded | failed | abandoned
]
