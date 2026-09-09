"""Contradiction candidates and supersession, after cognee's detect_contradictions and
resolve_temporal_contradictions.

cognee gathers the facts around the nodes an ingestion touched, excludes structural
relations, and asks a model which pairs are incompatible. memoose builds that same
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


def states_later_value(a: RelationRow, b: RelationRow) -> bool:
    """True when `a` describes a later state of the world than `b`.

    `valid_from` decides it when both facts carry one, because facts are not always learned
    in the order they became true: a project's history is routinely backfilled long after the
    present is known. Only when a date is missing does write order stand in for it, and an
    undated arrival is presumed current. Equal write times fall to the arriving fact, so the
    ordinary "assert the new owner" path is unchanged.
    """
    if a.valid_from and b.valid_from and a.valid_from != b.valid_from:
        return a.valid_from > b.valid_from
    return bool(a.updated_at and b.updated_at) and a.updated_at > b.updated_at


def apply_functional_supersession(store: SqliteStore, new_rel: RelationRow, functional: set[str]) -> list[dict]:
    """If new_rel's name is functional, keep exactly one current value for the subject.

    Usually the arriving fact wins and the stored one becomes history. When the stored fact
    states a later value, the arriving one is backfilled history and is superseded instead —
    so learning the past does not overwrite the present. Nothing is deleted either way.
    """
    if new_rel.name not in functional:
        return []
    superseded = []
    for old in store.relations_from(new_rel.source_id, new_rel.name):
        if old.id == new_rel.id or old.superseded:
            continue
        if states_later_value(old, new_rel):
            loser, winner = new_rel, old
            reason = f"functional relation {new_rel.name!r}: {old.id} states a later value ({old.valid_from or 'later assertion'}), so this fact is backfilled history"
        else:
            loser, winner = old, new_rel
            reason = f"functional relation {new_rel.name!r}: newer assertion {new_rel.id} replaces this one"
        if store.supersede(loser.id, winner.id, reason):
            store.resolve_contradiction(loser.id, f"superseded_by:{winner.id}")
            superseded.append({"relation_id": loser.id, "superseded_by": winner.id, "reason": reason})
    return superseded
