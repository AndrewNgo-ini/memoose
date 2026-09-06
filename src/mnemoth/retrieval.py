"""Recall: cognee's regex query router plus retrieval modes, without the completion step.

cognee's 20 search types mostly end in an LLM completion over retrieved context. Here the
Host Model is that completion, so the types collapse onto retrieval modes that return raw,
ranked material: entities, facts, chunks, summaries, rules. Lexical (FTS5 bm25) and vector
(local embeddings) hits are fused per channel with reciprocal rank fusion, multiplied by
memify weights, superseded facts are dropped unless asked, and top entities are expanded
through the graph.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from .embeddings import Embedder
from .store.sqlite_store import Hit, RelationRow, SqliteStore

RRF_K = 60.0
MODES = ("hybrid", "facts", "neighbourhood", "lexical", "summaries", "temporal", "rules", "session")

# Ported from cognee/api/v1/recall/query_router.py (patterns, targets, weights), minus Cypher/code.
_RULES: list[tuple[re.Pattern, str, float]] = [
    (re.compile(r'^"[^"]+"$'), "lexical", 3.0),
    (re.compile(r"\b(exact|verbatim|literal|word.for.word)\b", re.I), "lexical", 2.0),
    (re.compile(r"\b(rule|rules|convention|conventions|guideline|always|never|must|should|prefer|preference|lesson|lessons)\b", re.I), "rules", 2.0),
    (re.compile(r"\b(summar(y|ize|ise)|overview|big picture|report|what is this (project|repo|codebase) about)\b", re.I), "summaries", 2.0),
    (re.compile(r"\b(why|explain|reasoning|step.by.step|chain of thought)\b", re.I), "facts", 1.0),
    (re.compile(r"\b(because|therefore|consequently)\b", re.I), "facts", 0.5),
    (re.compile(r"\b(how (does|do|is|are) .* (relate|connect|interact|depend))\b", re.I), "neighbourhood", 2.0),
    (re.compile(r"\b(connection|relationship|related to|linked to|depends? on|neighbou?rs?)\b", re.I), "neighbourhood", 1.5),
    (re.compile(r"\b(when|before|after|during|since|until)\b", re.I), "temporal", 1.0),
    (re.compile(r"\b(timeline|chronolog|history|era|decade|century|last (week|month|year))\b", re.I), "temporal", 2.0),
    (re.compile(r"\b(19|20)\d{2}s?\b"), "temporal", 1.0),
    (re.compile(r"\bbetween\s+\d{4}\s+and\s+\d{4}\b", re.I), "temporal", 2.0),
]


@dataclass
class Route:
    mode: str
    confidence: float
    runner_up: str = "hybrid"
    matched: list[str] | None = None


def route(query: str) -> Route:
    scores: dict[str, float] = defaultdict(float)
    matched: list[str] = []
    for pat, mode, w in _RULES:
        if pat.search(query):
            scores[mode] += w
            matched.append(pat.pattern[:40])
    if not scores:
        return Route("hybrid", 0.5, "facts", [])
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    total = sum(scores.values())
    return Route(ranked[0][0], round(ranked[0][1] / total, 3), ranked[1][0] if len(ranked) > 1 else "hybrid", matched)


def rrf(*ranked_lists: list[Hit]) -> dict[tuple[str, str], float]:
    scores: dict[tuple[str, str], float] = defaultdict(float)
    for hits in ranked_lists:
        for rank, h in enumerate(hits):
            scores[(h.kind, h.ref_id)] += 1.0 / (RRF_K + rank + 1)
    return scores


def render_fact(source: str, relation: str, target: str, description: str) -> str:
    base = f"{source} --{relation}--> {target}"
    return f"{base}: {description}" if description else base


_DATE = re.compile(r"\b((?:19|20)\d{2})(?:-(\d{2}))?(?:-(\d{2}))?\b")


def _dates_in(text: str) -> list[str]:
    return ["-".join(p for p in m.groups() if p) for m in _DATE.finditer(text)]


class Recaller:
    def __init__(self, store: SqliteStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    # ----- channels -------------------------------------------------------------
    def _fused(self, query: str, kinds: tuple[str, ...], pool: int, phrase: bool = False) -> dict[str, list[tuple[str, float]]]:
        lexical = self.store.phrase_search(query.strip('"'), limit=pool, kinds=kinds) if phrase else self.store.lexical_search(query, limit=pool, kinds=kinds)
        vector: list[Hit] = []
        if not phrase:
            qvec = self.embedder.embed([query])[0]
            vector = self.store.vector_search(qvec, self.embedder.name, limit=pool, kinds=kinds)
        fused = rrf(lexical, vector)
        by_kind: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for (kind, ref_id), score in fused.items():
            by_kind[kind].append((ref_id, score))
        for kind in by_kind:
            by_kind[kind].sort(key=lambda x: x[1], reverse=True)
        return by_kind

    def _weight(self, rel: RelationRow, wmap: dict[str, tuple[float, float]]) -> float:
        fs, fb = wmap.get(rel.source_id, (1.0, 1.0))
        ft, tb = wmap.get(rel.target_id, (1.0, 1.0))
        freq = 1.0 + 0.05 * min(20.0, (fs + ft) / 2.0 - 1.0)  # cognee: gentle frequency boost, capped
        return rel.weight * freq * ((fb + tb) / 2.0)

    def _facts_payload(self, fact_scores: dict[str, float], limit: int, include_superseded: bool) -> list[dict]:
        rels = self.store.get_relations(list(fact_scores))
        if not include_superseded:
            rels = {k: v for k, v in rels.items() if not v.superseded}
        ids = {r.source_id for r in rels.values()} | {r.target_id for r in rels.values()}
        ents = self.store.get_entities(ids)
        wmap = self.store.weights(ids)
        scored = sorted(((rid, fact_scores[rid] * self._weight(r, wmap)) for rid, r in rels.items() if r.source_id in ents and r.target_id in ents), key=lambda x: x[1], reverse=True)[:limit]
        contradictions = {c["first_relation_id"] for c in self.store.contradictions_for([rid for rid, _ in scored])} | {c["second_relation_id"] for c in self.store.contradictions_for([rid for rid, _ in scored])}
        out = []
        for rid, s in scored:
            r = rels[rid]
            out.append({
                "id": r.id,
                "fact": render_fact(ents[r.source_id].name, r.name, ents[r.target_id].name, r.description),
                "source": ents[r.source_id].name, "relation": r.name, "target": ents[r.target_id].name,
                "description": r.description, "evidence": r.evidence,
                "valid_from": r.valid_from, "valid_to": r.valid_to,
                "superseded": r.superseded, "superseded_by": r.superseded_by,
                "contested": r.id in contradictions,
                "score": round(s, 6),
            })
        return out

    def _entities_payload(self, hits: list[tuple[str, float]]) -> list[dict]:
        ents = self.store.get_entities([eid for eid, _ in hits])
        wmap = self.store.weights(list(ents))
        rows = [
            {"id": e.id, "name": e.name, "type": e.type, "description": e.description, "mentions": e.mentions, "score": round(s * wmap.get(eid, (1.0, 1.0))[1], 6)}
            for eid, s in hits if (e := ents.get(eid))
        ]
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows

    def _chunks_payload(self, hits: list[tuple[str, float]]) -> list[dict]:
        chunks = self.store.get_chunks([cid for cid, _ in hits])
        return [{"id": c.id, "summary": c.summary, "text": c.text, "source": c.source, "score": round(s, 6)} for cid, s in hits if (c := chunks.get(cid))]

    # ----- modes ------------------------------------------------------------------
    def recall(self, query: str, mode: str | None = None, limit: int = 10, include_superseded: bool = False, hops: int = 1) -> dict:
        r = route(query)
        mode = mode or r.mode
        if mode not in MODES:
            raise ValueError(f"Unknown search mode {mode!r}. Use one of: {', '.join(MODES)}.")
        fn = getattr(self, f"_mode_{mode}")
        payload = fn(query, limit, include_superseded, hops)
        return {"query": query, "mode": mode, "route": {"suggested": r.mode, "confidence": r.confidence, "runner_up": r.runner_up}, **payload}

    def _mode_hybrid(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        pool = limit * 4
        by = self._fused(query, ("entity", "relation", "chunk"), pool * 3)
        entity_hits = by.get("entity", [])[: max(3, limit // 2)]
        fact_scores = {rid: s for rid, s in by.get("relation", [])}
        for eid, es in entity_hits:
            for rel in self.store.relations_for_entities([eid], limit_per_entity=10, include_superseded=inc):
                fact_scores[rel.id] = max(fact_scores.get(rel.id, 0.0), es * 0.9)
        return {
            "entities": self._entities_payload(entity_hits),
            "facts": self._facts_payload(fact_scores, limit, inc),
            "chunks": self._chunks_payload(by.get("chunk", [])[: max(2, limit // 3)]),
        }

    def _mode_facts(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        by = self._fused(query, ("relation", "entity"), limit * 6)
        fact_scores = {rid: s for rid, s in by.get("relation", [])}
        for eid, es in by.get("entity", [])[:3]:
            for rel in self.store.relations_for_entities([eid], limit_per_entity=10, include_superseded=inc):
                fact_scores[rel.id] = max(fact_scores.get(rel.id, 0.0), es * 0.8)
        return {"entities": [], "facts": self._facts_payload(fact_scores, limit, inc), "chunks": []}

    def _mode_neighbourhood(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        by = self._fused(query, ("entity",), limit * 4)
        seeds = by.get("entity", [])[: max(2, limit // 3)]
        frontier = [eid for eid, _ in seeds]
        fact_scores: dict[str, float] = {}
        seen = set(frontier)
        for hop in range(max(1, hops)):
            nxt: list[str] = []
            decay = 0.9 / (hop + 1)
            for rel in self.store.relations_for_entities(frontier, limit_per_entity=10, include_superseded=inc):
                fact_scores[rel.id] = max(fact_scores.get(rel.id, 0.0), decay)
                for other in (rel.source_id, rel.target_id):
                    if other not in seen:
                        seen.add(other)
                        nxt.append(other)
            frontier = nxt
        ents = self.store.get_entities(seen)
        return {
            "entities": self._entities_payload(seeds) + [{"id": e.id, "name": e.name, "type": e.type, "description": e.description, "mentions": e.mentions, "score": 0.0} for eid, e in ents.items() if eid not in dict(seeds)][: limit * 2],
            "facts": self._facts_payload(fact_scores, limit * 2, inc),
            "chunks": [],
        }

    def _mode_lexical(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        phrase = query.strip().startswith('"') and query.strip().endswith('"')
        q = query.strip().strip('"') if phrase else re.sub(r"\b(exact|verbatim|literal|word for word)\b", "", query, flags=re.I)
        hits = self.store.phrase_search(q, limit=limit, kinds=("chunk",)) if phrase else self.store.lexical_search(q, limit=limit, kinds=("chunk",))
        return {"entities": [], "facts": [], "chunks": self._chunks_payload([(h.ref_id, h.score) for h in hits])}

    def _mode_summaries(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        by = self._fused(query, ("chunk",), limit * 4)
        chunk_hits = [(cid, s) for cid, s in by.get("chunk", [])]
        chunks = self.store.get_chunks([cid for cid, _ in chunk_hits])
        summaries = [{"id": c.id, "summary": c.summary, "source": c.source, "score": round(s, 6)} for cid, s in chunk_hits if (c := chunks.get(cid)) and c.summary][:limit]
        buckets = [{"id": b["id"], "label": b["label"], "summary": b["summary"], "stale": bool(b["summary_stale"]), "members": len(b["member_ids"])} for b in self.store.buckets() if b["summary"]]
        return {"entities": [], "facts": [], "chunks": [], "summaries": summaries, "global_context": buckets[:limit]}

    def _mode_temporal(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        dates = _dates_in(query)
        by = self._fused(query, ("relation", "entity"), limit * 8)
        fact_scores = {rid: s for rid, s in by.get("relation", [])}
        for eid, es in by.get("entity", [])[:5]:
            for rel in self.store.relations_for_entities([eid], limit_per_entity=20, include_superseded=True):
                fact_scores[rel.id] = max(fact_scores.get(rel.id, 0.0), es * 0.8)
        facts = self._facts_payload(fact_scores, limit * 3, True)
        dated = []
        for f in facts:
            when = f["valid_from"] or next((d for d in _dates_in(f["description"] + " " + f["target"] + " " + f["source"])), None)
            f["when"] = when
            if dates and (when is None or not any(when.startswith(d[:4]) for d in dates)):
                continue
            dated.append(f)
        dated.sort(key=lambda f: (f["when"] is None, f["when"] or "", -f["score"]))
        return {"entities": [], "facts": dated[:limit], "chunks": [], "query_dates": dates}

    def _mode_rules(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        ctx = self.store.context(sections=("rules", "preferences", "lessons_learned", "tool_rules", "success_patterns", "failure_lessons", "environment_facts"))
        toks = {t.casefold() for t in re.findall(r"[A-Za-z0-9_]+", query) if len(t) > 2}
        scored = []
        for c in ctx:
            overlap = len(toks & {t.casefold() for t in re.findall(r"[A-Za-z0-9_]+", c["content"])})
            scored.append((overlap * c["confidence"], c))
        scored.sort(key=lambda x: x[0], reverse=True)
        rules = [{"id": c["id"], "section": c["section"], "content": c["content"], "confidence": c["confidence"], "session_id": c["session_id"], "score": s} for s, c in scored[:limit]]
        lessons = [{"id": l["id"], "title": l["title"], "text": l["text"], "evidence": l["evidence"]} for l in self.store.lessons(limit)]
        by = self._fused(query, ("relation",), limit * 2)
        fact_scores = {rid: s for rid, s in by.get("relation", []) if s > 0}
        return {"entities": [], "facts": self._facts_payload(fact_scores, limit // 2 or 1, inc), "chunks": [], "rules": rules, "lessons": lessons}

    def _mode_session(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        # Caller passes session turns via engine; here we search the fast cache lexically.
        toks = {t.casefold() for t in re.findall(r"[A-Za-z0-9_]+", query) if len(t) > 2}
        hits = []
        for s in self.store.sessions(limit=5):
            for t in self.store.turns(s["id"]):
                overlap = len(toks & {w.casefold() for w in re.findall(r"[A-Za-z0-9_]+", t["text"])})
                if overlap:
                    hits.append((overlap, {"session_id": s["id"], "turn_id": t["id"], "role": t["role"], "text": t["text"]}))
        hits.sort(key=lambda x: x[0], reverse=True)
        turns = [h for _, h in hits[:limit]]
        fallback = self._mode_hybrid(query, limit, inc, hops) if not turns else {"entities": [], "facts": [], "chunks": []}
        return {**fallback, "session_turns": turns}


def merge_ranked(primary: list[dict], secondary: list[dict], limit: int, reserve: int) -> list[dict]:
    """cognee's merge_ranked with a reserve: secondary always gets `reserve` slots if it has hits."""
    seen: set = set()
    out: list[dict] = []
    keep_secondary = secondary[:reserve]
    for item in primary[: max(0, limit - len(keep_secondary))] + keep_secondary + primary[max(0, limit - len(keep_secondary)):] + secondary[reserve:]:
        key = item.get("id") or item.get("fact") or id(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= limit:
            break
    return out
