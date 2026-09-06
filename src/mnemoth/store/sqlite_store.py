"""One SQLite file per Dataset (ADR 0002).

Holds the graph (entities, relations), the retrieval material (chunks, summaries),
an FTS5 index over all of it, and embeddings as blobs. The interface is shaped
after cognee's graph/vector engines so another backend can be slotted in later.
"""

from __future__ import annotations

import array
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

_FTS_TOKEN = re.compile(r"[A-Za-z0-9_]+")

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entity_types (
    name TEXT PRIMARY KEY, description TEXT NOT NULL, builtin INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, description TEXT NOT NULL,
    mentions INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS relations (
    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', evidence TEXT,
    chunk_id TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS relations_source ON relations(source_id);
CREATE INDEX IF NOT EXISTS relations_target ON relations(target_id);
CREATE TABLE IF NOT EXISTS chunks (
    id TEXT PRIMARY KEY, text TEXT NOT NULL, summary TEXT, source TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS entity_chunks (
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    PRIMARY KEY (entity_id, chunk_id));
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(kind UNINDEXED, ref_id UNINDEXED, text);
CREATE TABLE IF NOT EXISTS embeddings (
    kind TEXT NOT NULL, ref_id TEXT NOT NULL, model TEXT NOT NULL, vector BLOB NOT NULL,
    PRIMARY KEY (kind, ref_id));
"""


@dataclass
class EntityRow:
    id: str
    name: str
    type: str
    description: str
    mentions: int = 1


@dataclass
class RelationRow:
    id: str
    source_id: str
    target_id: str
    name: str
    description: str = ""
    evidence: str | None = None
    chunk_id: str | None = None


@dataclass
class ChunkRow:
    id: str
    text: str
    summary: str | None = None
    source: str | None = None


@dataclass
class Hit:
    kind: str
    ref_id: str
    score: float
    extra: dict = field(default_factory=dict)


class SqliteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL") if str(self.path) != ":memory:" else None
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # ----- meta / ontology -------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
        self.conn.commit()

    def list_entity_types(self) -> list[tuple[str, str, bool]]:
        rows = self.conn.execute("SELECT name, description, builtin FROM entity_types ORDER BY name")
        return [(r["name"], r["description"], bool(r["builtin"])) for r in rows]

    def upsert_entity_type(self, name: str, description: str, builtin: bool = False) -> None:
        self.conn.execute(
            "INSERT INTO entity_types(name, description, builtin) VALUES (?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET description=excluded.description",
            (name, description, int(builtin)),
        )
        self.conn.commit()

    # ----- graph ------------------------------------------------------------
    def get_entity(self, entity_id: str) -> EntityRow | None:
        r = self.conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        return EntityRow(r["id"], r["name"], r["type"], r["description"], r["mentions"]) if r else None

    def get_entities(self, ids: Iterable[str]) -> dict[str, EntityRow]:
        ids = list(ids)
        if not ids:
            return {}
        q = f"SELECT * FROM entities WHERE id IN ({','.join('?' * len(ids))})"
        return {
            r["id"]: EntityRow(r["id"], r["name"], r["type"], r["description"], r["mentions"])
            for r in self.conn.execute(q, ids)
        }

    def upsert_entity(self, e: EntityRow) -> tuple[EntityRow, bool]:
        """Insert or merge. Returns (stored row, merged_with_existing)."""
        now = time.time()
        existing = self.get_entity(e.id)
        if existing is None:
            self.conn.execute(
                "INSERT INTO entities VALUES (?,?,?,?,?,?,?)",
                (e.id, e.name, e.type, e.description, 1, now, now),
            )
            return e, False
        # Merge: keep the longer description, bump mention count, keep type unless it was generic.
        description = e.description if len(e.description) > len(existing.description) else existing.description
        self.conn.execute(
            "UPDATE entities SET description=?, type=?, mentions=mentions+1, updated_at=? WHERE id=?",
            (description, e.type, now, e.id),
        )
        return EntityRow(e.id, existing.name, e.type, description, existing.mentions + 1), True

    def upsert_relation(self, r: RelationRow) -> bool:
        """Returns True if the relation was new."""
        now = time.time()
        exists = self.conn.execute("SELECT 1 FROM relations WHERE id=?", (r.id,)).fetchone()
        if exists:
            self.conn.execute(
                "UPDATE relations SET description=CASE WHEN length(?)>length(description) THEN ? ELSE description END,"
                " evidence=COALESCE(?, evidence), chunk_id=COALESCE(?, chunk_id), updated_at=? WHERE id=?",
                (r.description, r.description, r.evidence, r.chunk_id, now, r.id),
            )
            return False
        self.conn.execute(
            "INSERT INTO relations VALUES (?,?,?,?,?,?,?,?,?)",
            (r.id, r.source_id, r.target_id, r.name, r.description, r.evidence, r.chunk_id, now, now),
        )
        return True

    def relations_for_entities(self, entity_ids: Iterable[str], limit_per_entity: int = 10) -> list[RelationRow]:
        out: list[RelationRow] = []
        seen: set[str] = set()
        for eid in entity_ids:
            rows = self.conn.execute(
                "SELECT * FROM relations WHERE source_id=? OR target_id=? ORDER BY updated_at DESC LIMIT ?",
                (eid, eid, limit_per_entity),
            )
            for r in rows:
                if r["id"] in seen:
                    continue
                seen.add(r["id"])
                out.append(RelationRow(r["id"], r["source_id"], r["target_id"], r["name"], r["description"], r["evidence"], r["chunk_id"]))
        return out

    def get_relations(self, ids: Iterable[str]) -> dict[str, RelationRow]:
        ids = list(ids)
        if not ids:
            return {}
        q = f"SELECT * FROM relations WHERE id IN ({','.join('?' * len(ids))})"
        return {
            r["id"]: RelationRow(r["id"], r["source_id"], r["target_id"], r["name"], r["description"], r["evidence"], r["chunk_id"])
            for r in self.conn.execute(q, ids)
        }

    def delete_entity(self, entity_id: str) -> int:
        self._delete_index("entity", [entity_id])
        rel_ids = [r["id"] for r in self.conn.execute("SELECT id FROM relations WHERE source_id=? OR target_id=?", (entity_id, entity_id))]
        self._delete_index("relation", rel_ids)
        cur = self.conn.execute("DELETE FROM entities WHERE id=?", (entity_id,))
        self.conn.commit()
        return cur.rowcount

    def delete_relation(self, relation_id: str) -> int:
        self._delete_index("relation", [relation_id])
        cur = self.conn.execute("DELETE FROM relations WHERE id=?", (relation_id,))
        self.conn.commit()
        return cur.rowcount

    # ----- chunks -----------------------------------------------------------
    def upsert_chunk(self, c: ChunkRow, entity_ids: Iterable[str] = ()) -> bool:
        new = self.conn.execute("SELECT 1 FROM chunks WHERE id=?", (c.id,)).fetchone() is None
        self.conn.execute(
            "INSERT INTO chunks VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
            "summary=COALESCE(excluded.summary, summary), source=COALESCE(excluded.source, source)",
            (c.id, c.text, c.summary, c.source, time.time()),
        )
        for eid in entity_ids:
            self.conn.execute("INSERT OR IGNORE INTO entity_chunks VALUES (?,?)", (eid, c.id))
        return new

    def get_chunks(self, ids: Iterable[str]) -> dict[str, ChunkRow]:
        ids = list(ids)
        if not ids:
            return {}
        q = f"SELECT * FROM chunks WHERE id IN ({','.join('?' * len(ids))})"
        return {r["id"]: ChunkRow(r["id"], r["text"], r["summary"], r["source"]) for r in self.conn.execute(q, ids)}

    # ----- indexes ----------------------------------------------------------
    def index_text(self, kind: str, ref_id: str, text: str) -> None:
        self.conn.execute("DELETE FROM fts WHERE kind=? AND ref_id=?", (kind, ref_id))
        self.conn.execute("INSERT INTO fts(kind, ref_id, text) VALUES (?,?,?)", (kind, ref_id, text))

    def index_vector(self, kind: str, ref_id: str, model: str, vector: list[float]) -> None:
        blob = array.array("f", vector).tobytes()
        self.conn.execute(
            "INSERT OR REPLACE INTO embeddings(kind, ref_id, model, vector) VALUES (?,?,?,?)",
            (kind, ref_id, model, blob),
        )

    def _delete_index(self, kind: str, ref_ids: list[str]) -> None:
        for rid in ref_ids:
            self.conn.execute("DELETE FROM fts WHERE kind=? AND ref_id=?", (kind, rid))
            self.conn.execute("DELETE FROM embeddings WHERE kind=? AND ref_id=?", (kind, rid))

    def lexical_search(self, query: str, limit: int = 20, kinds: Iterable[str] | None = None) -> list[Hit]:
        toks = [t for t in _FTS_TOKEN.findall(query) if len(t) > 1]
        if not toks:
            return []
        match = " OR ".join(f'"{t}"' for t in dict.fromkeys(toks))
        kind_sql, params = "", [match]
        if kinds:
            kinds = list(kinds)
            kind_sql = f" AND kind IN ({','.join('?' * len(kinds))})"
            params += kinds
        params.append(limit)
        rows = self.conn.execute(
            f"SELECT kind, ref_id, bm25(fts) AS rank FROM fts WHERE fts MATCH ?{kind_sql} ORDER BY rank LIMIT ?",
            params,
        )
        return [Hit(r["kind"], r["ref_id"], -float(r["rank"])) for r in rows]

    def vector_search(self, query_vec: list[float], model: str, limit: int = 20, kinds: Iterable[str] | None = None) -> list[Hit]:
        kind_sql, params = "", [model]
        if kinds:
            kinds = list(kinds)
            kind_sql = f" AND kind IN ({','.join('?' * len(kinds))})"
            params += kinds
        rows = self.conn.execute(f"SELECT kind, ref_id, vector FROM embeddings WHERE model=?{kind_sql}", params)
        q = array.array("f", query_vec)
        scored: list[Hit] = []
        for r in rows:
            v = array.array("f")
            v.frombytes(r["vector"])
            if len(v) != len(q):
                continue
            scored.append(Hit(r["kind"], r["ref_id"], sum(a * b for a, b in zip(q, v))))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:limit]

    def commit(self) -> None:
        self.conn.commit()

    # ----- stats ------------------------------------------------------------
    def stats(self) -> dict:
        one = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "entities": one("SELECT count(*) FROM entities"),
            "relations": one("SELECT count(*) FROM relations"),
            "chunks": one("SELECT count(*) FROM chunks"),
            "entity_types": one("SELECT count(*) FROM entity_types"),
        }

    def dump_json(self) -> str:
        return json.dumps(self.stats())
