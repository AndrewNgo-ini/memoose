"""One SQLite file per Dataset (ADR 0002).

Graph (entities, relations with supersession and weights), retrieval material
(chunks, summaries, FTS5, embeddings), contradictions, an append-only provenance
ledger, sessions (fast cache + context sections), lessons, memify weights and
global-context buckets, ontology sources. Interfaces are shaped after cognee's
graph/vector engines so another backend can be slotted in later.
"""

from __future__ import annotations

import array
import json
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .migrations import migrate

_FTS_TOKEN = re.compile(r"[A-Za-z0-9_]+")


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
    superseded: bool = False
    superseded_by: str | None = None
    supersession_reason: str | None = None
    weight: float = 1.0
    valid_from: str | None = None
    valid_to: str | None = None
    updated_at: float = 0.0


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


def _rel(r: sqlite3.Row) -> RelationRow:
    return RelationRow(
        r["id"], r["source_id"], r["target_id"], r["name"], r["description"], r["evidence"], r["chunk_id"],
        bool(r["superseded"]), r["superseded_by"], r["supersession_reason"], float(r["weight"]),
        r["valid_from"], r["valid_to"], float(r["updated_at"]),
    )


def _ent(r: sqlite3.Row) -> EntityRow:
    return EntityRow(r["id"], r["name"], r["type"], r["description"], r["mentions"])


class SqliteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        mem = str(self.path) == ":memory:"
        if not mem:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        if not mem:
            self.conn.execute("PRAGMA journal_mode = WAL")
        self.schema_version = migrate(self.conn)

    def close(self) -> None:
        self.conn.close()

    def commit(self) -> None:
        self.conn.commit()

    # ----- meta / ontology -------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
        self.conn.commit()

    def list_entity_types(self) -> list[dict]:
        rows = self.conn.execute("SELECT name, description, builtin, parent, source_id, aliases FROM entity_types ORDER BY name")
        return [
            {"name": r["name"], "description": r["description"], "builtin": bool(r["builtin"]), "parent": r["parent"], "source_id": r["source_id"], "aliases": json.loads(r["aliases"] or "[]")}
            for r in rows
        ]

    def upsert_entity_type(self, name: str, description: str, builtin: bool = False, parent: str | None = None, source_id: str | None = None, aliases: list[str] | None = None) -> None:
        self.conn.execute(
            "INSERT INTO entity_types(name, description, builtin, parent, source_id, aliases) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET description=excluded.description, parent=COALESCE(excluded.parent, parent), "
            "source_id=COALESCE(excluded.source_id, source_id), aliases=excluded.aliases",
            (name, description, int(builtin), parent, source_id, json.dumps(aliases or [])),
        )
        self.conn.commit()

    def add_ontology_source(self, name: str, fmt: str, class_count: int) -> str:
        sid = str(uuid.uuid4())
        self.conn.execute("INSERT INTO ontology_sources VALUES (?,?,?,?,?)", (sid, name, fmt, time.time(), class_count))
        self.conn.commit()
        return sid

    def list_ontology_sources(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM ontology_sources ORDER BY imported_at")]

    def functional_relations(self) -> set[str]:
        return {r["name"] for r in self.conn.execute("SELECT name FROM functional_relations")}

    def declare_functional(self, names: Iterable[str]) -> None:
        now = time.time()
        self.conn.executemany("INSERT OR IGNORE INTO functional_relations VALUES (?,?)", [(n, now) for n in names])
        self.conn.commit()

    # ----- graph ------------------------------------------------------------
    def get_entity(self, entity_id: str) -> EntityRow | None:
        r = self.conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        return _ent(r) if r else None

    def get_entities(self, ids: Iterable[str]) -> dict[str, EntityRow]:
        ids = list(ids)
        if not ids:
            return {}
        q = f"SELECT * FROM entities WHERE id IN ({','.join('?' * len(ids))})"
        return {r["id"]: _ent(r) for r in self.conn.execute(q, ids)}

    def all_entities(self) -> list[EntityRow]:
        return [_ent(r) for r in self.conn.execute("SELECT * FROM entities ORDER BY name")]

    def entities_by_type(self, type_name: str) -> list[EntityRow]:
        return [_ent(r) for r in self.conn.execute("SELECT * FROM entities WHERE type=? ORDER BY mentions DESC, name", (type_name,))]

    def upsert_entity(self, e: EntityRow) -> tuple[EntityRow, bool]:
        now = time.time()
        existing = self.get_entity(e.id)
        if existing is None:
            self.conn.execute("INSERT INTO entities VALUES (?,?,?,?,?,?,?)", (e.id, e.name, e.type, e.description, 1, now, now))
            self.conn.execute("INSERT OR IGNORE INTO entity_weights(entity_id) VALUES (?)", (e.id,))
            return e, False
        description = e.description if len(e.description) > len(existing.description) else existing.description
        self.conn.execute(
            "UPDATE entities SET description=?, type=?, mentions=mentions+1, updated_at=? WHERE id=?",
            (description, e.type, now, e.id),
        )
        return EntityRow(e.id, existing.name, e.type, description, existing.mentions + 1), True

    def upsert_relation(self, r: RelationRow) -> bool:
        now = time.time()
        exists = self.conn.execute("SELECT 1 FROM relations WHERE id=?", (r.id,)).fetchone()
        if exists:
            self.conn.execute(
                "UPDATE relations SET description=CASE WHEN length(?)>length(description) THEN ? ELSE description END,"
                " evidence=COALESCE(?, evidence), chunk_id=COALESCE(?, chunk_id), valid_from=COALESCE(?, valid_from),"
                " valid_to=COALESCE(?, valid_to), superseded=0, superseded_by=NULL, supersession_reason=NULL, updated_at=? WHERE id=?",
                (r.description, r.description, r.evidence, r.chunk_id, r.valid_from, r.valid_to, now, r.id),
            )
            return False
        self.conn.execute(
            "INSERT INTO relations(id, source_id, target_id, name, description, evidence, chunk_id, created_at, updated_at, weight, valid_from, valid_to)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (r.id, r.source_id, r.target_id, r.name, r.description, r.evidence, r.chunk_id, now, now, r.weight, r.valid_from, r.valid_to),
        )
        return True

    def get_relation(self, relation_id: str) -> RelationRow | None:
        r = self.conn.execute("SELECT * FROM relations WHERE id=?", (relation_id,)).fetchone()
        return _rel(r) if r else None

    def get_relations(self, ids: Iterable[str]) -> dict[str, RelationRow]:
        ids = list(ids)
        if not ids:
            return {}
        q = f"SELECT * FROM relations WHERE id IN ({','.join('?' * len(ids))})"
        return {r["id"]: _rel(r) for r in self.conn.execute(q, ids)}

    def relations_for_entities(self, entity_ids: Iterable[str], limit_per_entity: int = 10, include_superseded: bool = False) -> list[RelationRow]:
        out: list[RelationRow] = []
        seen: set[str] = set()
        sup = "" if include_superseded else " AND superseded=0"
        for eid in entity_ids:
            rows = self.conn.execute(
                f"SELECT * FROM relations WHERE (source_id=? OR target_id=?){sup} ORDER BY updated_at DESC LIMIT ?",
                (eid, eid, limit_per_entity),
            )
            for r in rows:
                if r["id"] not in seen:
                    seen.add(r["id"])
                    out.append(_rel(r))
        return out

    def relations_from(self, source_id: str, name: str, include_superseded: bool = False) -> list[RelationRow]:
        sup = "" if include_superseded else " AND superseded=0"
        rows = self.conn.execute(f"SELECT * FROM relations WHERE source_id=? AND name=?{sup} ORDER BY updated_at DESC", (source_id, name))
        return [_rel(r) for r in rows]

    def supersede(self, old_id: str, new_id: str, reason: str) -> bool:
        cur = self.conn.execute(
            "UPDATE relations SET superseded=1, superseded_by=?, supersession_reason=?, updated_at=? WHERE id=? AND id<>?",
            (new_id, reason, time.time(), old_id, new_id),
        )
        return cur.rowcount > 0

    def set_relation_weight(self, relation_id: str, weight: float) -> None:
        self.conn.execute("UPDATE relations SET weight=? WHERE id=?", (weight, relation_id))

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

    def repoint_entity(self, drop_id: str, keep_id: str) -> list[str]:
        """Move every relation and chunk link from drop_id to keep_id. Returns touched relation ids."""
        touched: list[str] = []
        for r in self.conn.execute("SELECT * FROM relations WHERE source_id=? OR target_id=?", (drop_id, drop_id)):
            src = keep_id if r["source_id"] == drop_id else r["source_id"]
            tgt = keep_id if r["target_id"] == drop_id else r["target_id"]
            if src == tgt:
                self.delete_relation(r["id"])
                continue
            self.conn.execute("UPDATE relations SET source_id=?, target_id=?, updated_at=? WHERE id=?", (src, tgt, time.time(), r["id"]))
            touched.append(r["id"])
        self.conn.execute("INSERT OR IGNORE INTO entity_chunks(entity_id, chunk_id) SELECT ?, chunk_id FROM entity_chunks WHERE entity_id=?", (keep_id, drop_id))
        return touched

    # ----- contradictions ----------------------------------------------------
    def add_contradiction(self, first_id: str, second_id: str, reason: str, confidence: float) -> str:
        cid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"contradiction:{min(first_id, second_id)}:{max(first_id, second_id)}"))
        self.conn.execute(
            "INSERT INTO contradictions VALUES (?,?,?,?,?,?,NULL) ON CONFLICT(id) DO UPDATE SET reason=excluded.reason, confidence=excluded.confidence",
            (cid, first_id, second_id, reason, confidence, time.time()),
        )
        return cid

    def resolve_contradiction(self, relation_id: str, resolved_by: str) -> None:
        self.conn.execute(
            "UPDATE contradictions SET resolved_by=? WHERE resolved_by IS NULL AND (first_relation_id=? OR second_relation_id=?)",
            (resolved_by, relation_id, relation_id),
        )

    def contradictions_for(self, relation_ids: Iterable[str], open_only: bool = True) -> list[dict]:
        ids = list(relation_ids)
        if not ids:
            return []
        ph = ",".join("?" * len(ids))
        sql = f"SELECT * FROM contradictions WHERE (first_relation_id IN ({ph}) OR second_relation_id IN ({ph}))"
        if open_only:
            sql += " AND resolved_by IS NULL"
        return [dict(r) for r in self.conn.execute(sql, ids + ids)]

    def open_contradictions(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM contradictions WHERE resolved_by IS NULL ORDER BY created_at DESC LIMIT ?", (limit,))]

    # ----- provenance ----------------------------------------------------------
    def record(self, actor: str, action: str, kind: str, ref_id: str, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO provenance(at, actor, action, kind, ref_id, payload) VALUES (?,?,?,?,?,?)",
            (time.time(), actor, action, kind, ref_id, json.dumps(payload, default=str)),
        )

    def history(self, kind: str, ref_id: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute("SELECT at, actor, action, kind, ref_id, payload FROM provenance WHERE kind=? AND ref_id=? ORDER BY at DESC LIMIT ?", (kind, ref_id, limit))
        return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]

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

    def chunk_summaries(self, limit: int = 20) -> list[ChunkRow]:
        rows = self.conn.execute("SELECT * FROM chunks WHERE summary IS NOT NULL ORDER BY created_at DESC LIMIT ?", (limit,))
        return [ChunkRow(r["id"], r["text"], r["summary"], r["source"]) for r in rows]

    def cooccurring_pairs(self, limit: int = 20) -> list[tuple[str, str, int]]:
        """Entity pairs sharing chunks but with no direct relation: cognee's cross-connect candidates."""
        rows = self.conn.execute(
            """
            SELECT a.entity_id AS x, b.entity_id AS y, count(*) AS shared
            FROM entity_chunks a JOIN entity_chunks b ON a.chunk_id=b.chunk_id AND a.entity_id < b.entity_id
            WHERE NOT EXISTS (SELECT 1 FROM relations r WHERE (r.source_id=a.entity_id AND r.target_id=b.entity_id)
                                                          OR (r.source_id=b.entity_id AND r.target_id=a.entity_id))
            GROUP BY x, y ORDER BY shared DESC, x LIMIT ?
            """,
            (limit,),
        )
        return [(r["x"], r["y"], r["shared"]) for r in rows]

    # ----- weights -------------------------------------------------------------
    def bump_frequency(self, entity_ids: Iterable[str]) -> None:
        for eid in entity_ids:
            self.conn.execute("INSERT INTO entity_weights(entity_id, frequency) VALUES (?, 1.0) ON CONFLICT(entity_id) DO UPDATE SET frequency=frequency+1.0", (eid,))

    def set_feedback(self, entity_id: str, delta: float) -> float:
        self.conn.execute("INSERT INTO entity_weights(entity_id) VALUES (?) ON CONFLICT DO NOTHING", (entity_id,))
        self.conn.execute("UPDATE entity_weights SET feedback=max(0.1, min(3.0, feedback+?)) WHERE entity_id=?", (delta, entity_id))
        return float(self.conn.execute("SELECT feedback FROM entity_weights WHERE entity_id=?", (entity_id,)).fetchone()[0])

    def weights(self, entity_ids: Iterable[str]) -> dict[str, tuple[float, float]]:
        ids = list(entity_ids)
        if not ids:
            return {}
        q = f"SELECT * FROM entity_weights WHERE entity_id IN ({','.join('?' * len(ids))})"
        return {r["entity_id"]: (float(r["frequency"]), float(r["feedback"])) for r in self.conn.execute(q, ids)}

    # ----- global context buckets -------------------------------------------------
    def upsert_bucket(self, key: str, label: str, member_ids: list[str]) -> tuple[str, bool]:
        bid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bucket:{key}"))
        row = self.conn.execute("SELECT member_ids FROM context_buckets WHERE id=?", (bid,)).fetchone()
        members = json.dumps(sorted(member_ids))
        changed = row is None or row["member_ids"] != members
        self.conn.execute(
            "INSERT INTO context_buckets(id, key, label, member_ids, summary_stale, updated_at) VALUES (?,?,?,?,1,?) "
            "ON CONFLICT(id) DO UPDATE SET member_ids=excluded.member_ids, label=excluded.label, "
            "summary_stale=CASE WHEN excluded.member_ids<>context_buckets.member_ids THEN 1 ELSE context_buckets.summary_stale END, updated_at=excluded.updated_at",
            (bid, key, label, members, time.time()),
        )
        return bid, changed

    def set_bucket_summary(self, bucket_id: str, summary: str) -> bool:
        cur = self.conn.execute("UPDATE context_buckets SET summary=?, summary_stale=0, updated_at=? WHERE id=?", (summary, time.time(), bucket_id))
        return cur.rowcount > 0

    def buckets(self, stale_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM context_buckets" + (" WHERE summary_stale=1" if stale_only else "") + " ORDER BY key"
        return [{**dict(r), "member_ids": json.loads(r["member_ids"])} for r in self.conn.execute(sql)]

    # ----- sessions -------------------------------------------------------------
    def session_start(self, session_id: str) -> bool:
        cur = self.conn.execute("INSERT OR IGNORE INTO sessions(id, started_at) VALUES (?,?)", (session_id, time.time()))
        self.conn.commit()
        return cur.rowcount > 0

    def session(self, session_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(r) if r else None

    def sessions(self, limit: int = 20) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,))]

    def session_end(self, session_id: str) -> None:
        self.conn.execute("UPDATE sessions SET ended_at=? WHERE id=? AND ended_at IS NULL", (time.time(), session_id))
        self.conn.commit()

    def session_mark_distilled(self, session_id: str) -> None:
        self.conn.execute("UPDATE sessions SET distilled_at=? WHERE id=?", (time.time(), session_id))
        self.conn.commit()

    def add_turn(self, session_id: str, role: str, text: str) -> int:
        cur = self.conn.execute("INSERT INTO session_turns(session_id, role, text, created_at) VALUES (?,?,?,?)", (session_id, role, text, time.time()))
        self.conn.commit()
        return int(cur.lastrowid)

    def turns(self, session_id: str) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM session_turns WHERE session_id=? ORDER BY id", (session_id,))]

    def add_context(self, session_id: str, section: str, content: str, confidence: float) -> int:
        cur = self.conn.execute(
            "INSERT INTO session_context(session_id, section, content, confidence, created_at) VALUES (?,?,?,?,?)",
            (session_id, section, content, confidence, time.time()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def retire_context(self, entry_id: int) -> bool:
        cur = self.conn.execute("UPDATE session_context SET retired_at=? WHERE id=? AND retired_at IS NULL", (time.time(), entry_id))
        self.conn.commit()
        return cur.rowcount > 0

    def context(self, session_id: str | None = None, sections: Iterable[str] | None = None, active_only: bool = True) -> list[dict]:
        sql, params = "SELECT * FROM session_context WHERE 1=1", []
        if session_id:
            sql += " AND session_id=?"
            params.append(session_id)
        if sections:
            sections = list(sections)
            sql += f" AND section IN ({','.join('?' * len(sections))})"
            params += sections
        if active_only:
            sql += " AND retired_at IS NULL"
        sql += " ORDER BY created_at"
        return [dict(r) for r in self.conn.execute(sql, params)]

    def delete_session(self, session_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        self.conn.commit()
        return cur.rowcount > 0

    # ----- lessons ----------------------------------------------------------------
    def add_lesson(self, lesson_id: str, session_id: str | None, title: str, text: str, evidence: str | None, entity_id: str, chunk_id: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO lessons VALUES (?,?,?,?,?,?,?,?)",
            (lesson_id, session_id, title, text, evidence, time.time(), entity_id, chunk_id),
        )

    def lessons(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM lessons ORDER BY accepted_at DESC LIMIT ?", (limit,))]

    # ----- indexes ----------------------------------------------------------
    def index_text(self, kind: str, ref_id: str, text: str) -> None:
        self.conn.execute("DELETE FROM fts WHERE kind=? AND ref_id=?", (kind, ref_id))
        self.conn.execute("INSERT INTO fts(kind, ref_id, text) VALUES (?,?,?)", (kind, ref_id, text))

    def index_vector(self, kind: str, ref_id: str, model: str, vector: list[float]) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO embeddings(kind, ref_id, model, vector) VALUES (?,?,?,?)",
            (kind, ref_id, model, array.array("f", vector).tobytes()),
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
        rows = self.conn.execute(f"SELECT kind, ref_id, bm25(fts) AS rank FROM fts WHERE fts MATCH ?{kind_sql} ORDER BY rank LIMIT ?", params)
        return [Hit(r["kind"], r["ref_id"], -float(r["rank"])) for r in rows]

    def phrase_search(self, phrase: str, limit: int = 20, kinds: Iterable[str] | None = None) -> list[Hit]:
        toks = _FTS_TOKEN.findall(phrase)
        if not toks:
            return []
        match = '"' + " ".join(toks) + '"'
        kind_sql, params = "", [match]
        if kinds:
            kinds = list(kinds)
            kind_sql = f" AND kind IN ({','.join('?' * len(kinds))})"
            params += kinds
        params.append(limit)
        rows = self.conn.execute(f"SELECT kind, ref_id, bm25(fts) AS rank FROM fts WHERE fts MATCH ?{kind_sql} ORDER BY rank LIMIT ?", params)
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
            if len(v) == len(q):
                scored.append(Hit(r["kind"], r["ref_id"], sum(a * b for a, b in zip(q, v))))
        scored.sort(key=lambda h: h.score, reverse=True)
        return scored[:limit]

    # ----- stats ------------------------------------------------------------
    def stats(self) -> dict:
        one = lambda sql: self.conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "entities": one("SELECT count(*) FROM entities"),
            "relations": one("SELECT count(*) FROM relations WHERE superseded=0"),
            "superseded_relations": one("SELECT count(*) FROM relations WHERE superseded=1"),
            "chunks": one("SELECT count(*) FROM chunks"),
            "entity_types": one("SELECT count(*) FROM entity_types"),
            "open_contradictions": one("SELECT count(*) FROM contradictions WHERE resolved_by IS NULL"),
            "sessions": one("SELECT count(*) FROM sessions"),
            "lessons": one("SELECT count(*) FROM lessons"),
            "schema_version": self.schema_version,
        }
