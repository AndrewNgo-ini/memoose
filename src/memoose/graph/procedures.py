"""Procedures: what to do next, after Procedural Graphs (Lu, Chen, Wu, Arik 2026; ADR 0004, 0005).

A Procedure is an entity; a Transition is a relation between two Procedures carrying a Condition,
an Advice and a Pitfall. `guidance` walks the outgoing Transitions two hops out from a Position
and returns them raw, grouped by hop: the Host Model reads them and decides. `record_outcome`
turns a finished Session's Trace into per-Transition counts, which is the only evidence the
refiner (the Host Model, following the sessions skill) has to contrast a failed run against a
successful one. Nothing here ranks, chooses, or calls a model.
"""

from __future__ import annotations

import re

from ..store.sqlite_store import EntityRow, RelationRow, SqliteStore


class Procedures:
    TYPE = "Procedure"
    OUTCOMES = ("succeeded", "failed", "abandoned")
    NOTE = "Guidance is memory, not an instruction: read the transitions, then decide."
    # The one-sentence shape the skills taught before the attributes were columns.
    # ponytail: naive parser for exactly that shape; anything else keeps its description and gains no attributes.
    _PACKED = re.compile(r"^\s*When\s+(?P<condition>.+?):\s*(?P<advice>.+?)(?:\s+Avoid:\s*(?P<pitfall>.+?))?\s*$", re.S)

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    def resolve(self, entity_id: str, label: str) -> EntityRow:
        """The Procedure an id names, or a ValueError that says how to fix it."""
        row = self.store.get_entity(entity_id)
        if row is None:
            raise ValueError(f"Unknown Procedure {label!r}. Remember it first: '{label}:Procedure --leads_to--> <next step>:Procedure'.")
        if row.type != self.TYPE:
            raise ValueError(f"{label!r} is a {row.type}, not a Procedure. Guidance and Positions are keyed on Procedures only.")
        return row

    def guidance(self, procedure_id: str, hops: int = 2, per_hop: int = 6) -> list[dict]:
        """Outgoing Transitions from a Procedure, grouped by hop. Directed: predecessors are what the agent already did."""
        frontier, seen, out = [procedure_id], {procedure_id}, []
        for hop in range(1, hops + 1):
            nxt: list[str] = []
            for pid in frontier:
                rels = self.store.transitions_from(pid, per_hop)
                names = self.store.get_entities({r.source_id for r in rels} | {r.target_id for r in rels})
                for r in rels:
                    out.append(self._edge(hop, r, names[r.source_id].name, names[r.target_id].name))
                    if r.target_id not in seen:
                        seen.add(r.target_id)
                        nxt.append(r.target_id)
            frontier = nxt
            if not frontier:
                break
        return out

    @staticmethod
    def _edge(hop: int, r: RelationRow, source: str, target: str) -> dict:
        return {
            "hop": hop, "id": r.id, "source": source, "relation": r.name, "target": target,
            "condition": r.condition, "advice": r.advice, "pitfall": r.pitfall,
            "description": r.description, "outcomes": r.outcomes(),
        }

    def validate_outcome(self, outcome: str | None) -> str | None:
        if outcome is None:
            return None
        clean = outcome.strip().casefold()
        if clean not in self.OUTCOMES:
            raise ValueError(f"outcome must be one of {', '.join(self.OUTCOMES)}.")
        return clean

    def record_outcome(self, session_id: str, outcome: str) -> list[str]:
        """Count the Session's Outcome on every Transition its Trace traversed; returns the Transition ids."""
        trace = self.store.trace(session_id)
        traversed: list[str] = []
        for a, b in zip(trace, trace[1:]):
            if a["procedure_id"] != b["procedure_id"]:
                traversed += [r.id for r in self.store.transitions_between(a["procedure_id"], b["procedure_id"])]
        ids = list(dict.fromkeys(traversed))
        self.store.bump_outcome(ids, outcome)
        return ids

    @classmethod
    def unpack(cls, description: str) -> tuple[str, str, str | None] | None:
        m = cls._PACKED.match(description or "")
        if not m:
            return None
        strip = lambda s: s.strip().rstrip(".").strip() if s else None  # noqa: E731
        return strip(m["condition"]), strip(m["advice"]), strip(m["pitfall"])

    def migrate_packed(self) -> int:
        """One pass over Transitions written as `When <c>: <a>. Avoid: <p>.`; fills the attribute columns, keeps the description."""
        n = 0
        for r in self.store.packed_transitions():
            parts = self.unpack(r.description)
            if parts:
                self.store.set_attributes(r.id, *parts)
                n += 1
        return n
