"""Hybrid recall, after cognee's HybridRetriever channels (chunks, entities, facts).

Lexical (FTS5, bm25) and vector (local embeddings) hits are fused per channel with
reciprocal rank fusion, then the top entities are expanded one hop into facts.
No model is involved: the Host Model synthesises from what is returned.
"""

from __future__ import annotations

from collections import defaultdict

from .embeddings import Embedder
from .store.sqlite_store import Hit, SqliteStore

RRF_K = 60.0


def rrf(*ranked_lists: list[Hit]) -> dict[tuple[str, str], float]:
    scores: dict[tuple[str, str], float] = defaultdict(float)
    for hits in ranked_lists:
        for rank, h in enumerate(hits):
            scores[(h.kind, h.ref_id)] += 1.0 / (RRF_K + rank + 1)
    return scores


def recall(
    store: SqliteStore,
    embedder: Embedder,
    query: str,
    *,
    entities_top_k: int = 5,
    facts_top_k: int = 10,
    chunks_top_k: int = 3,
    max_edges_per_entity: int = 10,
) -> dict:
    pool = max(entities_top_k, facts_top_k, chunks_top_k) * 4
    lexical = store.lexical_search(query, limit=pool * 3)
    qvec = embedder.embed([query])[0]
    vector = store.vector_search(qvec, embedder.name, limit=pool * 3)
    fused = rrf(lexical, vector)

    by_kind: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for (kind, ref_id), score in fused.items():
        by_kind[kind].append((ref_id, score))
    for kind in by_kind:
        by_kind[kind].sort(key=lambda x: x[1], reverse=True)

    entity_hits = by_kind.get("entity", [])[:entities_top_k]
    entities = store.get_entities([eid for eid, _ in entity_hits])

    # Facts: directly matched relations plus one-hop expansion from top entities.
    fact_scores: dict[str, float] = {rid: s for rid, s in by_kind.get("relation", [])}
    for rank, (eid, escore) in enumerate(entity_hits):
        for rel in store.relations_for_entities([eid], limit_per_entity=max_edges_per_entity):
            fact_scores[rel.id] = max(fact_scores.get(rel.id, 0.0), escore * 0.9)
    fact_ids = sorted(fact_scores, key=fact_scores.get, reverse=True)[:facts_top_k]
    relations = store.get_relations(fact_ids)
    endpoint_ids = {r.source_id for r in relations.values()} | {r.target_id for r in relations.values()}
    endpoints = store.get_entities(endpoint_ids - set(entities))
    endpoints.update(entities)

    chunk_hits = by_kind.get("chunk", [])[:chunks_top_k]
    chunks = store.get_chunks([cid for cid, _ in chunk_hits])

    return {
        "entities": [
            {"id": e.id, "name": e.name, "type": e.type, "description": e.description, "mentions": e.mentions, "score": round(s, 6)}
            for eid, s in entity_hits
            if (e := entities.get(eid))
        ],
        "facts": [
            {
                "id": r.id,
                "fact": render_fact(endpoints[r.source_id].name, r.name, endpoints[r.target_id].name, r.description),
                "source": endpoints[r.source_id].name,
                "relation": r.name,
                "target": endpoints[r.target_id].name,
                "description": r.description,
                "evidence": r.evidence,
                "score": round(fact_scores[r.id], 6),
            }
            for rid in fact_ids
            if (r := relations.get(rid)) and r.source_id in endpoints and r.target_id in endpoints
        ],
        "chunks": [
            {"id": c.id, "summary": c.summary, "text": c.text, "source": c.source, "score": round(s, 6)}
            for cid, s in chunk_hits
            if (c := chunks.get(cid))
        ],
    }


def render_fact(source: str, relation: str, target: str, description: str) -> str:
    base = f"{source} --{relation}--> {target}"
    return f"{base}: {description}" if description else base
