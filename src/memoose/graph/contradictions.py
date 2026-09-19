"""Contradiction candidates and supersession.

Gather the facts around the nodes an ingestion touched, drop structural relations, and hand
the candidate pairs to the Host Model through the memoose-upkeep skill; the judgment
comes back through `mark_contradiction`. Functional (single-valued) relations are superseded
automatically inside remember. Nothing is ever deleted.
"""

from __future__ import annotations

from collections import defaultdict

from ..store.sqlite_store import RelationRow, SqliteStore


class Contradictions:
    STRUCTURAL_RELATIONS = {"contains", "is_part_of", "made_from", "exists_in", "contradicts", "mentions", "distilled_from"}
    GUIDANCE = (
        "Two facts contradict only when they cannot both be true of the same subject at the same time "
        "(mutually exclusive values, direct negations, logically incompatible statements). Do not report facts "
        "that are merely different but compatible, more or less specific versions of one another, or paraphrases. "
        "Prefer supersede when the newer fact replaces the older one in time; use mark_contradiction when both "
        "claim to be current and the user must decide."
    )

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    def candidates(self, entity_ids: list[str], max_per_entity: int = 15) -> dict:
        """Facts touching the given entities, grouped by subject so the agent compares like with like."""
        relations = [
            r for r in self.store.relations_for_entities(entity_ids, limit_per_entity=max_per_entity, include_superseded=False)
            if r.name not in self.STRUCTURAL_RELATIONS
        ]
        entities = self.store.get_entities({r.source_id for r in relations} | {r.target_id for r in relations})
        facts: list[dict] = []
        by_subject: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
        for i, r in enumerate(relations):
            if r.source_id not in entities or r.target_id not in entities:
                continue
            subject, obj = entities[r.source_id].name, entities[r.target_id].name
            fact = {
                "fact_id": f"F{i}",
                "relation_id": r.id,
                "subject": subject,
                "relation": r.name,
                "object": obj,
                "text": r.fact(subject, obj),
                "evidence": r.evidence,
                "valid_from": r.valid_from,
                "valid_to": r.valid_to,
                "updated_at": r.updated_at,
            }
            facts.append(fact)
            if entities[r.source_id].type == "Procedure" and entities[r.target_id].type == "Procedure":
                continue  # a Procedure with several Transitions is a branch, never a Hotspot (ADR 0005)
            by_subject[(r.source_id, r.name, f"{subject} --{r.name}")].append(fact)
        # Same subject + same relation with different objects is the hot spot; surface it first.
        # `key` is stable across runs so a judgment ("these coexist, fine") can be recorded once.
        hotspots = [
            {"key": f"hotspot:{source_id}:{relation}", "subject_relation": label, "facts": group}
            for (source_id, relation, label), group in by_subject.items()
            if len(group) > 1
        ]
        already_flagged = self.store.contradictions_for([r.id for r in relations])
        return {"facts": facts, "hotspots": hotspots, "already_flagged": already_flagged, "guidance": self.GUIDANCE}

    def supersede_functional(self, new_rel: RelationRow, functional: set[str]) -> list[dict]:
        """If new_rel's name is functional, keep exactly one current value for the subject.

        Usually the arriving fact wins and the stored one becomes history. When the stored fact
        states a later value, the arriving one is backfilled history and is superseded instead,
        so learning the past does not overwrite the present.
        """
        if new_rel.name not in functional:
            return []
        superseded = []
        for old in self.store.relations_from(new_rel.source_id, new_rel.name):
            if old.id == new_rel.id or old.superseded:
                continue
            if self._states_later_value(old, new_rel):
                loser, winner = new_rel, old
                reason = f"functional relation {new_rel.name!r}: {old.id} states a later value ({old.valid_from or 'later assertion'}), so this fact is backfilled history"
            else:
                loser, winner = old, new_rel
                reason = f"functional relation {new_rel.name!r}: newer assertion {new_rel.id} replaces this one"
            if self.store.supersede(loser.id, winner.id, reason):
                self.store.resolve_contradiction(loser.id, f"superseded_by:{winner.id}")
                superseded.append({"relation_id": loser.id, "superseded_by": winner.id, "reason": reason})
        return superseded

    @staticmethod
    def _states_later_value(a: RelationRow, b: RelationRow) -> bool:
        """True when `a` describes a later state of the world than `b`.

        `valid_from` decides when both facts carry one, because facts are not always learned in
        the order they became true. Only when a date is missing does write order stand in, and an
        undated arrival is presumed current. Equal write times fall to the arriving fact.
        """
        if a.valid_from and b.valid_from and a.valid_from != b.valid_from:
            return a.valid_from > b.valid_from
        return bool(a.updated_at and b.updated_at) and a.updated_at > b.updated_at
