"""memify: maintenance passes over an existing graph.

Cross-connect entities that co-occur, consolidate duplicate entities, keep a global-context
index of bucket summaries. The deterministic parts live here; what needs a model (which pair
deserves a relation, which names are the same thing, what a bucket says) is a proposal the
Host Model judges through the memoose-upkeep skill.
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict

from .ids import Ids
from ..store.sqlite_store import EntityRow, SqliteStore


class Memify:
    _TOKEN = re.compile(r"[a-z0-9]+")

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    def cross_connect_candidates(self, limit: int = 20, min_shared: int = 1) -> list[dict]:
        """Entity pairs that share chunks but have no direct relation, with the shared context."""
        pairs = self.store.cooccurring_pairs(limit, min_shared=min_shared)
        entities = self.store.get_entities({a for a, _, _ in pairs} | {b for _, b, _ in pairs})
        out = []
        for a, b, shared in pairs:
            if a not in entities or b not in entities:
                continue
            chunk_ids = [row["chunk_id"] for row in self.store.conn.execute(
                "SELECT a.chunk_id FROM entity_chunks a JOIN entity_chunks b ON a.chunk_id=b.chunk_id WHERE a.entity_id=? AND b.entity_id=? LIMIT 3", (a, b))]
            chunks = self.store.get_chunks(chunk_ids)
            out.append({
                "key": f"cross_connect:{a}:{b}",
                "a": self._brief(entities[a]),
                "b": self._brief(entities[b]),
                "shared_chunks": shared,
                "context": [c.summary or c.text[:400] for c in chunks.values()],
            })
        return out

    def consolidate_candidates(self, limit: int = 20, cutoff: float = 0.84) -> list[dict]:
        """Near-duplicate entity names: same tokens, acronym vs expansion, or high string similarity."""
        entities = self.store.all_entities()
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()

        by_tokens: dict[str, list[EntityRow]] = defaultdict(list)
        for e in entities:
            by_tokens[" ".join(sorted(self._TOKEN.findall(Ids.normalize(e.name))))].append(e)
        for group in by_tokens.values():
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    seen.add((group[i].id, group[j].id))
                    out.append(self._pair(group[i], group[j], 1.0, "same tokens"))

        named = [(e, Ids.normalize(e.name)) for e in entities]
        for i in range(len(named)):
            for j in range(i + 1, len(named)):
                (a, a_name), (b, b_name) = named[i], named[j]
                if (a.id, b.id) in seen or (b.id, a.id) in seen or a.type != b.type:
                    continue
                ratio = difflib.SequenceMatcher(None, a_name, b_name).ratio()
                if ratio >= cutoff:
                    out.append(self._pair(a, b, round(ratio, 3), "similar spelling"))
                elif self._acronym(a_name) == b_name or self._acronym(b_name) == a_name:
                    out.append(self._pair(a, b, 0.9, "acronym"))
        out.sort(key=lambda p: p["similarity"], reverse=True)
        return out[:limit]

    def rebuild_buckets(self, max_members: int = 25) -> list[dict]:
        """Bucket entities by type; a bucket whose members changed is marked as needing a new summary."""
        result = []
        for t in self.store.list_entity_types():
            members = self.store.entities_by_type(t["name"])
            for start in range(0, len(members), max_members):
                part = members[start : start + max_members]
                index = start // max_members
                label = t["name"] + (f" (part {index + 1})" if len(members) > max_members else "")
                bucket_id, changed = self.store.upsert_bucket(f"type:{t['name']}:{index}", label, [e.id for e in part])
                result.append({"id": bucket_id, "label": label, "members": len(part), "changed": changed})
        self.store.commit()
        return result

    def stale_bucket_inputs(self, limit: int = 5) -> list[dict]:
        """For each stale bucket, the entities and facts a summary should be written from."""
        out = []
        for bucket in self.store.buckets(stale_only=True)[:limit]:
            members = self.store.get_entities(bucket["member_ids"])
            relations = self.store.relations_for_entities(list(members), limit_per_entity=4)
            named = self.store.get_entities({r.source_id for r in relations} | {r.target_id for r in relations} | set(members))
            out.append({
                "bucket_id": bucket["id"],
                "label": bucket["label"],
                "entities": [{"name": e.name, "type": e.type, "description": e.description} for e in members.values()],
                "facts": [r.fact(named[r.source_id].name, named[r.target_id].name) for r in relations if r.source_id in named and r.target_id in named][:60],
                "summary_shape": "This bucket is about:\n- <Category>: <names>\nFacts:\n- <self-contained sentence>",
            })
        return out

    @classmethod
    def _acronym(cls, name: str) -> str:
        parts = cls._TOKEN.findall(name)
        return "".join(p[0] for p in parts) if len(parts) > 1 else ""

    @staticmethod
    def _brief(e: EntityRow) -> dict:
        return {"id": e.id, "name": e.name, "type": e.type, "description": e.description}

    @staticmethod
    def _pair(a: EntityRow, b: EntityRow, similarity: float, why: str) -> dict:
        keep, drop = (a, b) if (a.mentions, len(a.name)) >= (b.mentions, len(b.name)) else (b, a)
        return {
            "key": f"consolidate:{min(a.id, b.id)}:{max(a.id, b.id)}",
            "keep": {**Memify._brief(keep), "mentions": keep.mentions},
            "drop": {**Memify._brief(drop), "mentions": drop.mentions},
            "similarity": similarity,
            "why": why,
        }
