"""memify: maintenance passes over an existing graph, after cognee's memify tasks.

cognee's default memify pipeline cross-connects entities that co-occur, consolidates
duplicate entities, applies frequency and feedback weights, and keeps a global context
index of bucket summaries. The deterministic parts live here; the parts that needed a
model (which pair deserves a relation, which names are the same thing, what a bucket
says) are proposals the Host Model judges through the memoose-memify skill.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict

from .ids import normalize_name
from .store.sqlite_store import SqliteStore

_TOKEN = re.compile(r"[a-z0-9]+")


def cross_connect_candidates(store: SqliteStore, limit: int = 20, min_shared: int = 1) -> list[dict]:
    pairs = store.cooccurring_pairs(limit, min_shared=min_shared)
    ents = store.get_entities({x for x, _, _ in pairs} | {y for _, y, _ in pairs})
    out = []
    for x, y, shared in pairs:
        if x in ents and y in ents:
            chunk_ids = [r["chunk_id"] for r in store.conn.execute(
                "SELECT a.chunk_id FROM entity_chunks a JOIN entity_chunks b ON a.chunk_id=b.chunk_id WHERE a.entity_id=? AND b.entity_id=? LIMIT 3", (x, y))]
            chunks = store.get_chunks(chunk_ids)
            out.append({
                "key": f"cross_connect:{x}:{y}",
                "a": {"id": x, "name": ents[x].name, "type": ents[x].type, "description": ents[x].description},
                "b": {"id": y, "name": ents[y].name, "type": ents[y].type, "description": ents[y].description},
                "shared_chunks": shared,
                "context": [c.summary or c.text[:400] for c in chunks.values()],
            })
    return out


def consolidate_candidates(store: SqliteStore, limit: int = 20, cutoff: float = 0.84) -> list[dict]:
    """Near-duplicate entity names: same normalised tokens, acronym vs expansion, or high string similarity."""
    ents = store.all_entities()
    by_tokens: dict[str, list] = defaultdict(list)
    for e in ents:
        toks = sorted(_TOKEN.findall(normalize_name(e.name)))
        by_tokens[" ".join(toks)].append(e)
    out = []
    seen: set[tuple[str, str]] = set()
    for group in by_tokens.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                seen.add((a.id, b.id))
                out.append(_pair(a, b, 1.0, "same tokens"))
    names = [(e, normalize_name(e.name)) for e in ents]
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i][0], names[j][0]
            if (a.id, b.id) in seen or (b.id, a.id) in seen:
                continue
            if a.type != b.type:
                continue
            ratio = difflib.SequenceMatcher(None, names[i][1], names[j][1]).ratio()
            if ratio >= cutoff:
                out.append(_pair(a, b, round(ratio, 3), "similar spelling"))
            elif _acronym(names[i][1]) == names[j][1] or _acronym(names[j][1]) == names[i][1]:
                out.append(_pair(a, b, 0.9, "acronym"))
    out.sort(key=lambda p: p["similarity"], reverse=True)
    return out[:limit]


def _acronym(name: str) -> str:
    parts = _TOKEN.findall(name)
    return "".join(p[0] for p in parts) if len(parts) > 1 else ""


def _pair(a, b, sim: float, why: str) -> dict:
    keep, drop = (a, b) if (a.mentions, len(a.name)) >= (b.mentions, len(b.name)) else (b, a)
    return {
        "key": f"consolidate:{min(a.id, b.id)}:{max(a.id, b.id)}",
        "keep": {"id": keep.id, "name": keep.name, "type": keep.type, "mentions": keep.mentions, "description": keep.description},
        "drop": {"id": drop.id, "name": drop.name, "type": drop.type, "mentions": drop.mentions, "description": drop.description},
        "similarity": sim,
        "why": why,
    }


def rebuild_buckets(store: SqliteStore, max_members: int = 25) -> list[dict]:
    """cognee's global context index buckets by entity type; a bucket whose members changed needs a new summary."""
    result = []
    for t in store.list_entity_types():
        members = store.entities_by_type(t["name"])
        if not members:
            continue
        for i in range(0, len(members), max_members):
            part = members[i : i + max_members]
            key = f"type:{t['name']}:{i // max_members}"
            label = f"{t['name']}" + (f" (part {i // max_members + 1})" if len(members) > max_members else "")
            bid, changed = store.upsert_bucket(key, label, [e.id for e in part])
            result.append({"id": bid, "label": label, "members": len(part), "changed": changed})
    store.commit()
    return result


def stale_bucket_inputs(store: SqliteStore, limit: int = 5) -> list[dict]:
    out = []
    for b in store.buckets(stale_only=True)[:limit]:
        ents = store.get_entities(b["member_ids"])
        rels = store.relations_for_entities(list(ents), limit_per_entity=4)
        all_ents = store.get_entities({r.source_id for r in rels} | {r.target_id for r in rels} | set(ents))
        out.append({
            "bucket_id": b["id"],
            "label": b["label"],
            "entities": [{"name": e.name, "type": e.type, "description": e.description} for e in ents.values()],
            "facts": [f"{all_ents[r.source_id].name} --{r.name}--> {all_ents[r.target_id].name}: {r.description}" for r in rels if r.source_id in all_ents and r.target_id in all_ents][:60],
            "summary_shape": "This bucket is about:\n- <Category>: <names>\nFacts:\n- <self-contained sentence>",
        })
    return out
