"""Recall: a regex query router plus retrieval modes, without a completion step.

The Host Model does the completion over retrieved context, so recall collapses onto modes
that return raw, ranked material: entities, facts, chunks, summaries, rules. Lexical (FTS5
bm25) and vector (local embeddings) hits are fused per channel with reciprocal rank fusion,
multiplied by memify weights, superseded facts are dropped unless asked, and top entities
are expanded through the graph.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from ..store.embeddings import Embedder
from ..store.sqlite_store import Hit, RelationRow, SqliteStore

MODES = ("hybrid", "facts", "neighbourhood", "lexical", "summaries", "temporal", "rules", "session")


@dataclass
class Route:
    mode: str
    confidence: float
    runner_up: str = "hybrid"
    matched: list[str] | None = None


class Router:
    """Picks a retrieval mode from the wording of the query. Highest summed weight wins; default hybrid."""

    RULES: list[tuple[re.Pattern, str, float]] = [
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

    def route(self, query: str) -> Route:
        scores: dict[str, float] = defaultdict(float)
        matched: list[str] = []
        for pattern, mode, weight in self.RULES:
            if pattern.search(query):
                scores[mode] += weight
                matched.append(pattern.pattern[:40])
        if not scores:
            return Route("hybrid", 0.5, "facts", [])
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        runner_up = ranked[1][0] if len(ranked) > 1 else "hybrid"
        return Route(ranked[0][0], round(ranked[0][1] / sum(scores.values()), 3), runner_up, matched)


class Recaller:
    RRF_K = 60.0
    _DATE = re.compile(r"\b((?:19|20)\d{2})(?:-(\d{2}))?(?:-(\d{2}))?\b")
    _WORD = re.compile(r"[A-Za-z0-9_]+")
    _LEXICAL_CUE = re.compile(r"\b(exact|verbatim|literal|word for word)\b", re.I)

    def __init__(self, store: SqliteStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder
        self.router = Router()

    def recall(self, query: str, mode: str | None = None, limit: int = 10, include_superseded: bool = False, hops: int = 1) -> dict:
        route = self.router.route(query)
        mode = mode or route.mode
        if mode not in MODES:
            raise ValueError(f"Unknown search mode {mode!r}. Use one of: {', '.join(MODES)}.")
        payload = getattr(self, f"_mode_{mode}")(query, limit, include_superseded, hops)
        return {"query": query, "mode": mode, "route": {"suggested": route.mode, "confidence": route.confidence, "runner_up": route.runner_up}, **payload}

    # ----- modes ------------------------------------------------------------------
    def _mode_hybrid(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        by = self._fused(query, ("entity", "relation", "chunk"), limit * 12)
        entity_hits = by.get("entity", [])[: max(3, limit // 2)]
        fact_scores = self._facts_around(by, entity_hits, inc, boost=0.9, per_entity=10)
        return {
            "entities": self._entities_payload(entity_hits),
            "facts": self._facts_payload(fact_scores, limit, inc),
            "chunks": self._chunks_payload(by.get("chunk", [])[:limit]),
        }

    def _mode_facts(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        by = self._fused(query, ("relation", "entity", "chunk"), limit * 6)
        fact_scores = self._facts_around(by, by.get("entity", [])[:3], inc, boost=0.8, per_entity=10)
        return {"entities": [], "facts": self._facts_payload(fact_scores, limit, inc), "chunks": self._chunks_payload(by.get("chunk", [])[:limit])}

    def _mode_neighbourhood(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        by = self._fused(query, ("entity",), limit * 4)
        seeds = by.get("entity", [])[: max(2, limit // 3)]
        frontier = [eid for eid, _ in seeds]
        seen = set(frontier)
        fact_scores: dict[str, float] = {}
        for hop in range(max(1, hops)):
            decay = 0.9 / (hop + 1)
            next_frontier: list[str] = []
            for rel in self.store.relations_for_entities(frontier, limit_per_entity=10, include_superseded=inc):
                fact_scores[rel.id] = max(fact_scores.get(rel.id, 0.0), decay)
                for other in (rel.source_id, rel.target_id):
                    if other not in seen:
                        seen.add(other)
                        next_frontier.append(other)
            frontier = next_frontier
        neighbours = self.store.get_entities(seen)
        seed_ids = dict(seeds)
        return {
            "entities": self._entities_payload(seeds) + [
                {"id": e.id, "name": e.name, "type": e.type, "description": e.description, "mentions": e.mentions, "score": 0.0}
                for eid, e in neighbours.items() if eid not in seed_ids
            ][: limit * 2],
            "facts": self._facts_payload(fact_scores, limit * 2, inc),
            "chunks": self._chunks_payload(self._fused(query, ("chunk",), limit * 2).get("chunk", [])[:limit]),
        }

    def _mode_lexical(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        query = query.strip()
        phrase = query.startswith('"') and query.endswith('"')
        text = query.strip('"') if phrase else self._LEXICAL_CUE.sub("", query)
        hits = self.store.phrase_search(text, limit=limit, kinds=("chunk",)) if phrase else self.store.lexical_search(text, limit=limit, kinds=("chunk",))
        return {"entities": [], "facts": [], "chunks": self._chunks_payload([(h.ref_id, h.score) for h in hits])}

    def _mode_summaries(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        chunk_hits = self._fused(query, ("chunk",), limit * 4).get("chunk", [])
        chunks = self.store.get_chunks([cid for cid, _ in chunk_hits])
        summaries = [
            {"id": c.id, "summary": c.summary, "source": c.source, "score": round(s, 6)}
            for cid, s in chunk_hits if (c := chunks.get(cid)) and c.summary
        ][:limit]
        buckets = [
            {"id": b["id"], "label": b["label"], "summary": b["summary"], "stale": bool(b["summary_stale"]), "members": len(b["member_ids"])}
            for b in self.store.buckets() if b["summary"]
        ]
        return {"entities": [], "facts": [], "chunks": [], "summaries": summaries, "global_context": buckets[:limit]}

    def _mode_temporal(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        dates = self._dates_in(query)
        by = self._fused(query, ("relation", "entity", "chunk"), limit * 8)
        fact_scores = self._facts_around(by, by.get("entity", [])[:5], include_superseded=True, boost=0.8, per_entity=20)
        facts = self._facts_payload(fact_scores, limit * 3, True)
        chunks = self._chunks_payload(by.get("chunk", [])[:limit])
        if dates:
            chunks.sort(key=lambda c: (not any(d[:4] in (c["text"] or "") for d in dates), -c["score"]))
        dated = []
        for f in facts:
            f["when"] = f["valid_from"] or next(iter(self._dates_in(f"{f['description']} {f['target']} {f['source']}")), None)
            if dates and (f["when"] is None or not any(f["when"].startswith(d[:4]) for d in dates)):
                continue
            dated.append(f)
        dated.sort(key=lambda f: (f["when"] is None, f["when"] or "", -f["score"]))
        return {"entities": [], "facts": dated[:limit], "chunks": chunks, "query_dates": dates}

    def _mode_rules(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        words = self._words(query)
        context = self.store.context(sections=("rules", "preferences", "lessons_learned", "tool_rules", "success_patterns", "failure_lessons", "environment_facts"))
        scored = sorted(((len(words & self._words(c["content"])) * c["confidence"], c) for c in context), key=lambda x: x[0], reverse=True)
        rules = [
            {"id": c["id"], "section": c["section"], "content": c["content"], "confidence": c["confidence"], "session_id": c["session_id"], "score": s}
            for s, c in scored[:limit]
        ]
        lessons = [{"id": l["id"], "title": l["title"], "text": l["text"], "evidence": l["evidence"]} for l in self.store.lessons(limit)]
        by = self._fused(query, ("relation", "chunk"), limit * 2)
        fact_scores = {rid: s for rid, s in by.get("relation", []) if s > 0}
        return {"entities": [], "facts": self._facts_payload(fact_scores, limit // 2 or 1, inc), "chunks": self._chunks_payload(by.get("chunk", [])[:limit]), "rules": rules, "lessons": lessons}

    def _mode_session(self, query: str, limit: int, inc: bool, hops: int) -> dict:
        """Search the fast cache of recent turns by word overlap; fall through to hybrid when nothing matches."""
        words = self._words(query)
        hits = []
        for session in self.store.sessions(limit=5):
            for turn in self.store.turns(session["id"]):
                overlap = len(words & self._words(turn["text"]))
                if overlap:
                    hits.append((overlap, {"session_id": session["id"], "turn_id": turn["id"], "role": turn["role"], "text": turn["text"]}))
        hits.sort(key=lambda x: x[0], reverse=True)
        turns = [h for _, h in hits[:limit]]
        fallback = self._mode_hybrid(query, limit, inc, hops) if not turns else {"entities": [], "facts": [], "chunks": []}
        return {**fallback, "session_turns": turns}

    # ----- channels -------------------------------------------------------------
    def _fused(self, query: str, kinds: tuple[str, ...], pool: int) -> dict[str, list[tuple[str, float]]]:
        """Lexical and vector hits fused by reciprocal rank, split per kind and sorted best first."""
        lexical = self.store.lexical_search(query, limit=pool, kinds=kinds)
        vector = self.store.vector_search(self.embedder.embed([query])[0], self.embedder.name, limit=pool, kinds=kinds)
        by_kind: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for (kind, ref_id), score in self._rrf(lexical, vector).items():
            by_kind[kind].append((ref_id, score))
        for hits in by_kind.values():
            hits.sort(key=lambda x: x[1], reverse=True)
        return by_kind

    def _facts_around(self, by: dict, entity_hits: list[tuple[str, float]], include_superseded: bool, boost: float, per_entity: int) -> dict[str, float]:
        """Relation hits plus the relations of the top entities, each scored at a fraction of its entity's score."""
        fact_scores = {rid: s for rid, s in by.get("relation", [])}
        for eid, score in entity_hits:
            for rel in self.store.relations_for_entities([eid], limit_per_entity=per_entity, include_superseded=include_superseded):
                fact_scores[rel.id] = max(fact_scores.get(rel.id, 0.0), score * boost)
        return fact_scores

    @classmethod
    def _rrf(cls, *ranked_lists: list[Hit]) -> dict[tuple[str, str], float]:
        scores: dict[tuple[str, str], float] = defaultdict(float)
        for hits in ranked_lists:
            for rank, h in enumerate(hits):
                scores[(h.kind, h.ref_id)] += 1.0 / (cls.RRF_K + rank + 1)
        return scores

    @staticmethod
    def _weight(rel: RelationRow, weights: dict[str, tuple[float, float]]) -> float:
        source_freq, source_fb = weights.get(rel.source_id, (1.0, 1.0))
        target_freq, target_fb = weights.get(rel.target_id, (1.0, 1.0))
        frequency = 1.0 + 0.05 * min(20.0, (source_freq + target_freq) / 2.0 - 1.0)  # gentle boost, capped
        return rel.weight * frequency * ((source_fb + target_fb) / 2.0)

    # ----- payloads ---------------------------------------------------------------
    def _facts_payload(self, fact_scores: dict[str, float], limit: int, include_superseded: bool) -> list[dict]:
        relations = self.store.get_relations(list(fact_scores))
        if not include_superseded:
            relations = {k: v for k, v in relations.items() if not v.superseded}
        ids = {r.source_id for r in relations.values()} | {r.target_id for r in relations.values()}
        entities = self.store.get_entities(ids)
        weights = self.store.weights(ids)
        scored = sorted(
            ((rid, fact_scores[rid] * self._weight(r, weights)) for rid, r in relations.items() if r.source_id in entities and r.target_id in entities),
            key=lambda x: x[1], reverse=True,
        )[:limit]
        flagged = self.store.contradictions_for([rid for rid, _ in scored])
        contested = {c["first_relation_id"] for c in flagged} | {c["second_relation_id"] for c in flagged}
        out = []
        for rid, score in scored:
            r = relations[rid]
            source, target = entities[r.source_id].name, entities[r.target_id].name
            out.append({
                "id": r.id,
                "fact": r.fact(source, target),
                "source": source, "relation": r.name, "target": target,
                "description": r.description, "evidence": r.evidence,
                "valid_from": r.valid_from, "valid_to": r.valid_to,
                "superseded": r.superseded, "superseded_by": r.superseded_by,
                "contested": r.id in contested,
                "score": round(score, 6),
                **({"condition": r.condition, "advice": r.advice, "pitfall": r.pitfall, "outcomes": r.outcomes()} if (r.condition or r.advice or r.pitfall) else {}),
            })
        return out

    def _entities_payload(self, hits: list[tuple[str, float]]) -> list[dict]:
        entities = self.store.get_entities([eid for eid, _ in hits])
        weights = self.store.weights(list(entities))
        rows = [
            {"id": e.id, "name": e.name, "type": e.type, "description": e.description, "mentions": e.mentions, "score": round(s * weights.get(eid, (1.0, 1.0))[1], 6)}
            for eid, s in hits if (e := entities.get(eid))
        ]
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows

    def _chunks_payload(self, hits: list[tuple[str, float]]) -> list[dict]:
        chunks = self.store.get_chunks([cid for cid, _ in hits])
        return [{"id": c.id, "summary": c.summary, "text": c.text, "source": c.source, "score": round(s, 6)} for cid, s in hits if (c := chunks.get(cid))]

    @classmethod
    def _dates_in(cls, text: str) -> list[str]:
        return ["-".join(p for p in m.groups() if p) for m in cls._DATE.finditer(text)]

    @classmethod
    def _words(cls, text: str) -> set[str]:
        return {w.casefold() for w in cls._WORD.findall(text) if len(w) > 2}
