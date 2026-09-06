"""Contradiction candidates and supersession, after cognee's detect_contradictions and
resolve_temporal_contradictions.

cognee gathers the facts around the nodes an ingestion touched, excludes structural
relations, and asks a model which pairs are incompatible. mnemoth builds that same
candidate list and hands it to the Host Model through the skill; the judgment comes
back through `mark_contradiction`. Functional (single-valued) relations are superseded
automatically inside remember, exactly like cognee, and nothing is ever deleted.
"""

from __future__ import annotations

from collections import defaultdict

from .retrieval import render_fact
from .store.sqlite_store import RelationRow, SqliteStore

STRUCTURAL_RELATIONS = {"contains", "is_part_of", "made_from", "exists_in", "contradicts", "mentions", "distilled_from"}


def candidate_facts(store: SqliteStore, entity_ids: list[str], max_per_entity: int = 15) -> dict:
    """Facts touching the given entities, grouped by subject so the agent compares like with like."""
    rels = [r for r in store.relations_for_entities(entity_ids, limit_per_entity=max_per_entity, include_superseded=False) if r.name not in STRUCTURAL_RELATIONS]
    ids = {r.source_id for r in rels} | {r.target_id for r in rels}
    ents = store.get_entities(ids)
    by_subject: dict[str, list[dict]] = defaultdict(list)
    facts: list[dict] = []
    for i, r in enumerate(rels):
        if r.source_id not in ents or r.target_id not in ents:
            continue
        item = {
            "fact_id": f"F{i}",
            "relation_id": r.id,
            "subject": ents[r.source_id].name,
            "relation": r.name,
            "object": ents[r.target_id].name,
            "text": render_fact(ents[r.source_id].name, r.name, ents[r.target_id].name, r.description),
            "evidence": r.evidence,
            "valid_from": r.valid_from,
            "valid_to": r.valid_to,
            "updated_at": r.updated_at,
        }
        facts.append(item)
        by_subject[f"{ents[r.source_id].name} --{r.name}"].append(item)
    # Same subject + same relation with different objects is the hot spot; surface it first.
    hotspots = [{"subject_relation": k, "facts": v} for k, v in by_subject.items() if len(v) > 1]
    open_ = store.contradictions_for([r.id for r in rels])
    return {"facts": facts, "hotspots": hotspots, "already_flagged": open_, "guidance": GUIDANCE}


GUIDANCE = (
    "Two facts contradict only when they cannot both be true of the same subject at the same time "
    "(mutually exclusive values, direct negations, logically incompatible statements). Do not report facts "
    "that are merely different but compatible, more or less specific versions of one another, or paraphrases. "
    "Prefer supersede when the newer fact replaces the older one in time; use mark_contradiction when both "
    "claim to be current and the user must decide."
)


def apply_functional_supersession(store: SqliteStore, new_rel: RelationRow, functional: set[str]) -> list[dict]:
    """If new_rel's name is functional, supersede older non-superseded targets of the same subject."""
    if new_rel.name not in functional:
        return []
    superseded = []
    for old in store.relations_from(new_rel.source_id, new_rel.name):
        if old.id == new_rel.id or old.superseded:
            continue
        if old.updated_at > new_rel.updated_at and new_rel.updated_at:
            continue  # the stored one is newer; keep it
        reason = f"functional relation {new_rel.name!r}: newer assertion {new_rel.id} replaces this one"
        if store.supersede(old.id, new_rel.id, reason):
            store.resolve_contradiction(old.id, f"superseded_by:{new_rel.id}")
            superseded.append({"relation_id": old.id, "superseded_by": new_rel.id, "reason": reason})
    return superseded
