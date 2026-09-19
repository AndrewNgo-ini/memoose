"""The Engine: validated writes and hybrid reads over Datasets. No model calls, ever."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from .graph.chunking import Chunker
from .graph.contradictions import Contradictions
from .graph.ids import Ids
from .graph.memify import Memify
from .graph.models import CrossConnectIn, EntityIn, LessonIn, RelationIn
from .graph.ontology import DEFAULT_ENTITY_TYPES, EntityType, Ontology, OntologyError, OntologyImporter
from .graph.procedures import Procedures
from .graph.retrieval import MODES, Recaller
from .graph.sessions import Sessions
from .store.datasets import data_dir, dataset_path, normalize_dataset_name, project_dataset_name
from .store.embeddings import Embedder, LazyEmbedder
from .store.sqlite_store import ChunkRow, EntityRow, RelationRow, SqliteStore

USER_DATASET = "user"
ACTOR = "host-model"
STANDING_SECTIONS = ("goals", "rules", "preferences", "lessons_learned", "tool_rules", "environment_facts")


class Dataset:
    """One memory scope: a SQLite file, its ontology, and the operations the MCP tools expose."""

    def __init__(self, name: str, store: SqliteStore, embedder: Embedder) -> None:
        self.name = name
        self.store = store
        self.embedder = embedder
        self._seed_builtin_types()
        self.ontology = self._load_ontology()
        self.recaller = Recaller(store, embedder)
        self.chunker = Chunker()
        self.contradictions = Contradictions(store)
        self.memify = Memify(store)
        self.sessions = Sessions(store)
        self.procedures = Procedures(store)
        if self.store.get_meta("transitions_unpacked") is None:  # one pass per store, then never again
            self.procedures.migrate_packed()
            self.store.set_meta("transitions_unpacked", "1")
            self.store.commit()

    def _seed_builtin_types(self) -> None:
        # Additive, so a store opened before a type existed still gains it.
        have = {t["name"] for t in self.store.list_entity_types()}
        for t in DEFAULT_ENTITY_TYPES:
            if t.name not in have:
                self.store.upsert_entity_type(t.name, t.description, builtin=True)

    def _load_ontology(self) -> Ontology:
        return Ontology([EntityType(r["name"], r["description"], r["parent"], r["aliases"], r["builtin"], r["source_id"]) for r in self.store.list_entity_types()])

    def _record(self, action: str, kind: str, ref_id: str, payload: dict) -> None:
        self.store.record(ACTOR, action, kind, ref_id, payload)

    # ----- ontology -----------------------------------------------------------
    def describe_ontology(self) -> dict:
        return {
            "dataset": self.name,
            "entity_types": [{"name": t.name, "description": t.description, **({"parent": t.parent} if t.parent else {}), **({"aliases": t.aliases} if t.aliases else {})} for t in self.ontology.types],
            "relation_name_rule": "snake_case verb phrases such as works_at, depends_on, decided_on, replaced_by, happened_on.",
            "functional_relations": sorted(self.store.functional_relations()),
            "ontology_sources": self.store.list_ontology_sources(),
            "stats": self.store.stats(),
            "embedder": self.embedder.name,
        }

    def add_entity_type(self, name: str, description: str, parent: str | None = None, aliases: list[str] | None = None) -> dict:
        t = self.ontology.add_type(name, description, parent=parent, aliases=aliases)
        self.store.upsert_entity_type(t.name, t.description, parent=t.parent, aliases=t.aliases)
        self._record("add_entity_type", "entity_type", t.name, {"description": t.description, "parent": t.parent})
        self.store.commit()
        return {"name": t.name, "description": t.description, "parent": t.parent, "aliases": t.aliases, "basic_type": self.ontology.basic_type(t.name)}

    def import_ontology(self, text: str, name: str, fmt: str | None = None) -> dict:
        importer = OntologyImporter(self.ontology)
        classes = importer.parse(text, fmt)
        source_id = self.store.add_ontology_source(name, fmt or "auto", len(classes))
        added = []
        for t in importer.plan(classes):
            try:
                self.ontology.add_type(t.name, t.description, parent=t.parent, aliases=t.aliases, source_id=source_id)
            except OntologyError:
                continue
            self.store.upsert_entity_type(t.name, t.description, parent=t.parent, source_id=source_id, aliases=t.aliases)
            added.append({"name": t.name, "parent": t.parent, "basic_type": self.ontology.basic_type(t.name), "aliases": t.aliases})
        self._record("import_ontology", "ontology_source", source_id, {"name": name, "classes": len(classes), "types_added": len(added)})
        self.store.commit()
        return {"dataset": self.name, "source_id": source_id, "classes_found": len(classes), "types_added": added}

    def declare_functional_relations(self, names: list[str]) -> dict:
        clean = [self.ontology.validate_relation_name(n) for n in names]
        self.store.declare_functional(clean)
        for n in clean:
            self._record("declare_functional", "relation_name", n, {})
        self.store.commit()
        return {"dataset": self.name, "functional_relations": sorted(self.store.functional_relations())}

    # ----- remember -----------------------------------------------------------
    def remember(self, entities: list[EntityIn], relations: list[RelationIn], summary: str | None = None, source_text: str | None = None, source: str | None = None, session_id: str | None = None) -> dict:
        entity_rows = self._entity_rows(entities)
        relation_rows = self._relation_rows(relations, known={e.id: e.type for e in entity_rows})
        chunk_rows = self._chunk_rows(summary, source_text, source)
        # Embed before the write transaction so concurrent servers hold the SQLite lock briefly.
        vectors = self._vectors(entity_rows, relation_rows, chunk_rows)
        provenance = {"session_id": session_id, "source": source}

        stored_entities, stored_relations, superseded = [], [], []
        functional = self.store.functional_relations()
        entity_ids = [e.id for e in entity_rows]
        with self.store.conn:
            for row in entity_rows:
                stored, merged = self.store.upsert_entity(row)
                stored_entities.append({"id": stored.id, "name": stored.name, "type": stored.type, "description": stored.description, "mentions": stored.mentions, "merged": merged})
                self._index("entity", stored.id, stored.index_text(), vectors)
                self._record("merge" if merged else "create", "entity", stored.id, {"name": stored.name, "type": stored.type, **provenance})
            self.store.bump_frequency(entity_ids)

            endpoints = self.store.get_entities({r.source_id for r in relation_rows} | {r.target_id for r in relation_rows})
            for row in relation_rows:
                row.chunk_id = chunk_rows[0].id if chunk_rows else None
                new = self.store.upsert_relation(row)
                r = self.store.get_relation(row.id) or row
                fact = r.fact(endpoints[r.source_id].name, endpoints[r.target_id].name)
                stored_relations.append({"id": r.id, "fact": fact, "evidence": r.evidence, "new": new})
                self._index("relation", r.id, fact, vectors)
                self._record("assert" if new else "reassert", "relation", r.id, {"fact": fact, "evidence": r.evidence, **provenance})
                for s in self.contradictions.supersede_functional(r, functional):
                    superseded.append(s)
                    self._record("supersede", "relation", s["relation_id"], s)

            for c in chunk_rows:
                self.store.upsert_chunk(c, entity_ids)
                self._index("chunk", c.id, c.index_text(), vectors)

        warnings: list[str] = []
        if not relations:
            warnings.append("No relations given: entities alone are weak memory. Prefer facts as source --relation--> target.")
        touched = list(dict.fromkeys(entity_ids + [r.source_id for r in relation_rows] + [r.target_id for r in relation_rows]))
        hotspots = self.contradictions.candidates(touched)["hotspots"] if relation_rows else []
        if hotspots:
            warnings.append(f"{len(hotspots)} subject(s) now hold several values for one relation; run contradiction_candidates and judge them.")
        return {"dataset": self.name, "entities": stored_entities, "relations": stored_relations, "superseded": superseded, "chunks_stored": len(chunk_rows), "hotspots": hotspots, "warnings": warnings}

    def _entity_rows(self, entities: list[EntityIn]) -> list[EntityRow]:
        """Typed rows for the incoming entities, keeping the stored name and the longer description when one already exists."""
        rows = []
        for e in entities:
            if not e.name.strip():
                raise OntologyError("Every entity needs a non-empty name.")
            rows.append(EntityRow(Ids.entity(e.name), e.name.strip(), self.ontology.resolve_type(e.type), e.description.strip()))
        existing = self.store.get_entities([r.id for r in rows])
        for row in rows:
            if row.id in existing:
                row.name = existing[row.id].name
                if len(existing[row.id].description) >= len(row.description):
                    row.description = existing[row.id].description
        return rows

    def _relation_rows(self, relations: list[RelationIn], known: dict[str, str]) -> list[RelationRow]:
        """Rows for the incoming relations; `known` maps the ids of entities in this call to their types."""
        rows = []
        for r in relations:
            source_id, target_id = Ids.entity(r.source), Ids.entity(r.target)
            types = {}
            for eid, label in ((source_id, r.source), (target_id, r.target)):
                stored = self.store.get_entity(eid)
                if eid not in known and stored is None:
                    raise OntologyError(f"Relation endpoint {label!r} is neither in `entities` nor already remembered. Add it to `entities` with a type, or use the exact name of an existing entity (see recall).")
                types[eid] = known.get(eid) or stored.type
            if source_id == target_id:
                raise OntologyError(f"Relation {r.name!r} cannot connect {r.source!r} to itself.")
            attrs = [a.strip() or None for a in (r.condition or "", r.advice or "", r.pitfall or "")]
            if any(attrs) and not all(t == Procedures.TYPE for t in types.values()):
                raise OntologyError(f"condition, advice and pitfall belong on a Transition: both {r.source!r} and {r.target!r} must be Procedures.")
            name = self.ontology.validate_relation_name(r.name)
            rows.append(RelationRow(Ids.relation(source_id, name, target_id), source_id, target_id, name, r.description.strip(), r.evidence,
                                    valid_from=r.valid_from, valid_to=r.valid_to, condition=attrs[0], advice=attrs[1], pitfall=attrs[2]))
        return rows

    def _chunk_rows(self, summary: str | None, source_text: str | None, source: str | None) -> list[ChunkRow]:
        """Source text chunked, the summary on the first chunk; or the summary alone as a single chunk."""
        if source_text and source_text.strip():
            return [ChunkRow(Ids.chunk(text), text, summary if i == 0 else None, source) for i, text in enumerate(self.chunker.split(source_text))]
        if summary and summary.strip():
            return [ChunkRow(Ids.chunk(summary), summary.strip(), summary.strip(), source)]
        return []

    def _vectors(self, entity_rows: list[EntityRow], relation_rows: list[RelationRow], chunk_rows: list[ChunkRow]) -> dict[tuple[str, str], list[float]]:
        """One embedding per row, keyed by (kind, id), computed in a single batch."""
        names = {e.id: e.name for e in self.store.get_entities({r.source_id for r in relation_rows} | {r.target_id for r in relation_rows}).values()}
        names.update({e.id: e.name for e in entity_rows})
        items = [("entity", e.id, e.index_text()) for e in entity_rows]
        items += [("relation", r.id, r.fact(names[r.source_id], names[r.target_id])) for r in relation_rows]
        items += [("chunk", c.id, c.index_text()) for c in chunk_rows]
        if not items:
            return {}
        embeddings = self.embedder.embed([text for _, _, text in items])
        return {(kind, ref_id): vector for (kind, ref_id, _), vector in zip(items, embeddings)}

    def _index(self, kind: str, ref_id: str, text: str, vectors: dict[tuple[str, str], list[float]]) -> None:
        self.store.index_text(kind, ref_id, text)
        self.store.index_vector(kind, ref_id, self.embedder.name, vectors[(kind, ref_id)])

    # ----- recall -------------------------------------------------------------
    def recall(self, query: str, mode: str | None = None, limit: int = 10, include_superseded: bool = False, hops: int = 1) -> dict:
        if not query.strip():
            raise ValueError("recall needs a non-empty query.")
        out = self.recaller.recall(query, mode=mode, limit=limit, include_superseded=include_superseded, hops=hops)
        return {"dataset": self.name, **out, "embedder": self.embedder.name}

    # ----- contradictions --------------------------------------------------------
    def contradiction_candidates(self, entity_names: list[str] | None = None, relation_ids: list[str] | None = None) -> dict:
        ids = [Ids.entity(n) for n in (entity_names or [])]
        for rid in relation_ids or []:
            r = self.store.get_relation(rid)
            if r:
                ids += [r.source_id, r.target_id]
        if not ids:
            return {"dataset": self.name, "open_contradictions": self.store.open_contradictions(), "facts": [], "hotspots": [], "guidance": Contradictions.GUIDANCE}
        out = self.contradictions.candidates(list(dict.fromkeys(ids)))
        dismissed = self.store.dismissed()
        out["hotspots"] = [h for h in out["hotspots"] if h["key"] not in dismissed]
        return {"dataset": self.name, **out}

    def dismiss(self, key: str, reason: str) -> dict:
        """Record that a candidate was judged and declined, so it is not proposed again.

        Procedural Graphs (Lu et al. 2026) keep rejected edits on file and hand them back to the
        refiner as negative evidence. Same idea here: a dismissal goes into the provenance ledger
        with its reason, `maintenance` filters on it and shows the recent reasons, `guidance` shows
        the ones about its Transitions (`transition:<relation_id>`), and nothing about the graph
        itself changes.
        """
        key, reason = key.strip(), reason.strip()
        if not key or ":" not in key:
            raise ValueError("key must be a candidate key from maintain or contradiction_candidates, e.g. 'consolidate:<id>:<id>', or 'transition:<relation_id>' for a declined change to a Transition.")
        if not reason:
            raise ValueError("Give the reason the candidate was declined; it is shown next time so the judgment is not redone.")
        self._record("dismiss", "candidate", key, {"reason": reason})
        self.store.commit()
        return {"dataset": self.name, "dismissed": key, "reason": reason}

    # ----- procedures (ADR 0005) -----------------------------------------------------
    def guidance(self, procedure: str, hops: int = 2, per_hop: int = 6) -> dict:
        """What memory says comes next from a Procedure: its outgoing Transitions two hops out, raw. The Host Model decides.

        Local on purpose. The paper's ablation is that the two-hop neighbourhood beat the whole
        graph on every benchmark and that injecting the whole graph lowered task success on the
        embodied one; guidance is keyed on where the agent is, and it is small.
        """
        node = self.procedures.resolve(Ids.entity(procedure), procedure)
        transitions = self.procedures.guidance(node.id, hops=max(1, hops), per_hop=max(1, per_hop))
        ids = {t["id"] for t in transitions}
        dismissed = {k: v for k, v in self.store.dismissed().items() if k.startswith("transition:") and k.split(":", 1)[1] in ids}
        return {
            "dataset": self.name, "procedure": {"id": node.id, "name": node.name, "description": node.description},
            "transitions": transitions, "dismissed": [{"key": k, "reason": v} for k, v in dismissed.items()], "note": Procedures.NOTE,
        }

    def mark_contradiction(self, first_relation_id: str, second_relation_id: str, reason: str, confidence: float) -> dict:
        a, b = self.store.get_relation(first_relation_id), self.store.get_relation(second_relation_id)
        if not a or not b:
            raise ValueError("Both relation ids must exist.")
        if a.id == b.id:
            raise ValueError("A fact cannot contradict itself.")
        reason = reason.strip()
        cid = self.store.add_contradiction(a.id, b.id, reason, max(0.0, min(1.0, confidence)))
        edge = None
        if a.source_id != b.source_id:  # also link the two subjects with a `contradicts` edge
            edge = Ids.relation(a.source_id, "contradicts", b.source_id)
            self.store.upsert_relation(RelationRow(edge, a.source_id, b.source_id, "contradicts", reason, f"contradiction:{cid}"))
        self._record("mark_contradiction", "contradiction", cid, {"first": a.id, "second": b.id, "reason": reason, "confidence": confidence})
        self.store.commit()
        return {"dataset": self.name, "contradiction_id": cid, "contradicts_edge": edge}

    def supersede(self, old_relation_id: str, new_relation_id: str, reason: str) -> dict:
        if not self.store.get_relation(old_relation_id) or not self.store.get_relation(new_relation_id):
            raise ValueError("Both relation ids must exist.")
        ok = self.store.supersede(old_relation_id, new_relation_id, reason.strip())
        self.store.resolve_contradiction(old_relation_id, f"superseded_by:{new_relation_id}")
        self._record("supersede", "relation", old_relation_id, {"superseded_by": new_relation_id, "reason": reason})
        self.store.commit()
        return {"dataset": self.name, "superseded": ok, "old": old_relation_id, "new": new_relation_id}

    def history(self, entity: str | None = None, relation_id: str | None = None, limit: int = 50) -> dict:
        if relation_id:
            return {"dataset": self.name, "kind": "relation", "ref_id": relation_id, "events": self.store.history("relation", relation_id, limit)}
        if entity:
            eid = Ids.entity(entity)
            events = self.store.history("entity", eid, limit)
            for r in self.store.relations_for_entities([eid], limit_per_entity=100, include_superseded=True):
                events += self.store.history("relation", r.id, limit)
            events.sort(key=lambda e: e["at"], reverse=True)
            return {"dataset": self.name, "kind": "entity", "ref_id": eid, "events": events[:limit]}
        raise ValueError("Pass entity or relation_id.")

    # ----- sessions -------------------------------------------------------------
    def session_start(self, session_id: str | None = None) -> dict:
        sid = session_id or uuid.uuid4().hex[:12]
        new = self.store.session_start(sid)
        standing = self.store.context(sections=STANDING_SECTIONS)[-30:]
        return {
            "dataset": self.name, "session_id": sid, "new": new,
            "standing_context": [{"section": c["section"], "content": c["content"], "session_id": c["session_id"]} for c in standing],
            "recent_lessons": self.store.lessons(10),
        }

    def session_add_turn(self, session_id: str, role: str, text: str, position: str | None = None) -> dict:
        """Append a turn; with `position`, the Procedure the agent is at, and the Guidance from there comes back with it."""
        self.store.session_start(session_id)
        if role not in ("user", "assistant", "tool", "system"):
            raise ValueError("role must be user, assistant, tool, or system.")
        node = self.procedures.resolve(Ids.entity(position), position) if position and position.strip() else None
        turn_id = self.store.add_turn(session_id, role, text.strip(), node.id if node else None)
        out = {"dataset": self.name, "session_id": session_id, "turn_id": turn_id}
        if node:
            out["position"] = node.name
            out["guidance"] = self.procedures.guidance(node.id)
            out["note"] = Procedures.NOTE
        return out

    def session_set_context(self, session_id: str, section: str, content: str, confidence: float = 1.0, retire_entry_id: int | None = None) -> dict:
        self.store.session_start(session_id)
        section = Sessions.validate_section(section)
        if retire_entry_id is not None:
            self.store.retire_context(retire_entry_id)
        entry_id = self.store.add_context(session_id, section, content.strip(), max(0.0, min(1.0, confidence)))
        if section == "feedback":
            self._apply_feedback(content)
        self._record("set_context", "session", session_id, {"section": section, "content": content, "entry_id": entry_id})
        self.store.commit()
        return {"dataset": self.name, "session_id": session_id, "entry_id": entry_id, "section": section}

    def _apply_feedback(self, content: str) -> None:
        """'+name' / '-name' tokens nudge an entity's feedback weight up or down."""
        for token in content.split():
            if token[:1] in "+-" and len(token) > 1:
                eid = Ids.entity(token[1:])
                if self.store.get_entity(eid):
                    self.store.set_feedback(eid, 0.25 if token[0] == "+" else -0.25)

    def session_get(self, session_id: str, sections: list[str] | None = None, include_turns: bool = True) -> dict:
        session = self.store.session(session_id)
        if session is None:
            raise ValueError(f"Unknown session {session_id!r}.")
        wanted = [Sessions.validate_section(s) for s in sections] if sections else None
        return {
            "dataset": self.name, "session": session, "turns": self.store.turns(session_id) if include_turns else [],
            "context": self.store.context(session_id=session_id, sections=wanted), "trace": self.store.trace(session_id),
        }

    def session_timeline(self, session_id: str, batch_chars: int = 6000) -> dict:
        return {"dataset": self.name, **self.sessions.timeline(session_id, batch_chars)}

    def publish_lessons(self, session_id: str | None, lessons: list[LessonIn]) -> dict:
        published = []
        for lesson in lessons:
            title, text = lesson.title.strip(), lesson.text.strip()
            entities = [EntityIn(name=title, type="Lesson", description=text)]
            relations: list[RelationIn] = []
            for name in lesson.applies_to:
                if self.store.get_entity(Ids.entity(name)) is None:
                    entity_type = lesson.entity_types.get(name)
                    if not entity_type:
                        raise OntologyError(f"Lesson {lesson.title!r} applies to unknown entity {name!r}; give its type in entity_types or remember it first.")
                    entities.append(EntityIn(name=name, type=entity_type, description=""))
                relations.append(RelationIn(source=title, name="applies_to", target=name, description=f"Lesson '{title}' applies to {name}.", evidence=lesson.evidence))
            out = self.remember(entities, relations, summary=text, source_text=text, source=f"session:{session_id}" if session_id else "distillation", session_id=session_id)
            lesson_entity = out["entities"][0]["id"]
            lesson_id = Sessions.lesson_id(title)
            self.store.add_lesson(lesson_id, session_id, title, text, lesson.evidence, lesson_entity, Ids.chunk(text))
            self._record("publish_lesson", "lesson", lesson_id, {"title": lesson.title, "session_id": session_id})
            published.append({"id": lesson_id, "title": title, "entity_id": lesson_entity, "applies_to": lesson.applies_to})
        if session_id and self.store.session(session_id):
            self.store.session_mark_distilled(session_id)
        self.store.commit()
        return {"dataset": self.name, "published": published}

    def session_end(self, session_id: str, outcome: str | None = None) -> dict:
        """Close a Session. With an Outcome, every Transition its Trace traversed counts it, and the reply says what to distil."""
        if self.store.session(session_id) is None:
            raise ValueError(f"Unknown session {session_id!r}.")
        outcome = self.procedures.validate_outcome(outcome)
        self.store.session_end(session_id, outcome)
        traversed: list[str] = []
        if outcome:
            traversed = self.procedures.record_outcome(session_id, outcome)
            for rid in traversed:
                self._record("traverse", "relation", rid, {"session_id": session_id, "outcome": outcome})
            self.store.commit()
        session = self.store.session(session_id)
        trace = self.store.trace(session_id)
        steps = ["Run session_timeline and distill lessons if not yet distilled."]
        if trace and outcome == "failed":
            steps.append("The Trace failed: compare it with guidance() from its first Position, then supersede the Transition that led astray with the corrected one (remember it with condition, advice, pitfall) or dismiss('transition:<id>', reason) if the chain was right and the run was not.")
        elif trace and outcome == "succeeded":
            steps.append("The Trace succeeded: if a Transition it took is not in memory yet, remember it so the next run has it.")
        elif outcome and not trace:
            steps.append("No Position was declared this Session, so nothing procedural can be learned from it; declare positions with session_add_turn(position=...) next time.")
        return {
            "dataset": self.name, "session": session, "outcome": outcome, "trace": [t["name"] for t in trace],
            "transitions_counted": traversed, "distilled": session["distilled_at"] is not None, "next": " ".join(steps),
        }

    def session_forget(self, session_id: str) -> dict:
        return {"dataset": self.name, "deleted": self.store.delete_session(session_id)}

    # ----- memify ------------------------------------------------------------------
    def memify_candidates(self, kind: str, limit: int = 20) -> dict:
        if kind == "cross_connect":
            candidates = self.memify.cross_connect_candidates(limit)
            guidance = "For each pair, add a relation only if the shared context states a real relationship; describe it in one sentence with evidence. Skip pairs that merely co-occur."
        elif kind == "consolidate":
            candidates = self.memify.consolidate_candidates(limit)
            guidance = "Merge only when both names denote the same real thing. Keep the fuller, more-mentioned name. Call merge_entities(keep, drop)."
        elif kind == "stale_summaries":
            self.memify.rebuild_buckets()
            candidates = self.memify.stale_bucket_inputs(limit)
            guidance = "Write each bucket summary in the given shape from the listed facts only, then call set_bucket_summary."
        else:
            raise ValueError("kind must be cross_connect, consolidate, or stale_summaries.")
        return {"dataset": self.name, "kind": kind, "candidates": candidates, "guidance": guidance}

    def maintenance(self, limit: int = 10) -> dict:
        """Everything in this dataset that currently needs a judgment call, in one sweep.

        Storing facts as they arrive is half of keeping memory; the other half is going back over
        it: judging conflicts, merging duplicates, distilling finished sessions, rewriting stale
        summaries. This gathers that worklist deterministically and decides nothing; the model
        working through it makes every call. `stale_summaries` rebuilds the bucket index as it
        goes, so this is not a read-only command.
        """
        dismissed = self.store.dismissed()

        def not_dismissed(items: list[dict]) -> list[dict]:
            return [c for c in items if c.get("key") not in dismissed][:limit]

        entity_ids = [e.id for e in self.store.all_entities()]
        undistilled = [{**s, "key": f"session:{s['id']}"} for s in self.store.sessions(50) if s.get("ended_at") and not s.get("distilled_at")]
        self.memify.rebuild_buckets()
        work = {
            "hotspots": not_dismissed(self.contradictions.candidates(entity_ids)["hotspots"] if entity_ids else []),
            "open_contradictions": self.store.open_contradictions(limit),
            "consolidate": not_dismissed(self.memify.consolidate_candidates(limit * 2)),
            # Two shared chunks at least: in a young store seeded from one chunk, every pair co-occurs.
            "cross_connect": not_dismissed(self.memify.cross_connect_candidates(limit * 2, min_shared=2)),
            "stale_summaries": self.memify.stale_bucket_inputs(limit),
            "undistilled_sessions": not_dismissed(undistilled),
        }
        return {
            "dataset": self.name,
            "pending": sum(len(v) for v in work.values()),
            **work,
            "dismissed": [{"key": k, "reason": r} for k, r in list(dismissed.items())[:limit]],
            "guidance": (
                "Judge each item; do not accept them wholesale. When you decline one, call dismiss(key, reason) "
                "so it is not proposed again; `dismissed` lists earlier judgments for the same store. "
                "hotspots and open_contradictions: "
                "memoose-upkeep (supersede when the newer fact replaces the older, "
                "mark_contradiction when both claim to be current). consolidate and cross_connect: "
                "memoose-upkeep, and only when the names denote the same thing or the relation is "
                "real. undistilled_sessions: session_timeline then publish_lessons. "
                "stale_summaries: write each from the listed facts only, then set_bucket_summary."
            ),
        }

    def cross_connect(self, relations: list[CrossConnectIn]) -> dict:
        rels = [RelationIn(source=r.source, name=r.name, target=r.target, description=r.description, evidence=r.evidence) for r in relations]
        return self.remember([], rels, source="memify:cross_connect")

    def merge_entities(self, keep: str, drop: str) -> dict:
        keep_id, drop_id = Ids.entity(keep), Ids.entity(drop)
        kept, dropped = self.store.get_entity(keep_id), self.store.get_entity(drop_id)
        if not kept or not dropped:
            raise ValueError("Both entities must exist.")
        if keep_id == drop_id:
            raise ValueError("keep and drop are the same entity.")
        with self.store.conn:
            touched = self.store.repoint_entity(drop_id, keep_id)
            description = max(kept.description, dropped.description, key=len)
            self.store.conn.execute("UPDATE entities SET description=?, mentions=mentions+?, updated_at=strftime('%s','now') WHERE id=?", (description, dropped.mentions, keep_id))
            alias_note = f" Also known as {dropped.name}."
            if dropped.name.casefold() != kept.name.casefold() and alias_note.strip() not in description:
                self.store.conn.execute("UPDATE entities SET description=description||? WHERE id=?", (alias_note, keep_id))
            self._reindex_after_merge(keep_id, touched)
            self.store.delete_entity(drop_id)
            self._record("merge_entities", "entity", keep_id, {"dropped": drop_id, "dropped_name": dropped.name, "relations_repointed": len(touched)})
        return {"dataset": self.name, "kept": keep_id, "dropped": drop_id, "relations_repointed": len(touched)}

    def _reindex_after_merge(self, keep_id: str, touched: list[str]) -> None:
        """Re-index the kept entity and every repointed relation, since their texts now carry the kept name."""
        relations = self.store.get_relations(touched).values()
        entities = self.store.get_entities({r.source_id for r in relations} | {r.target_id for r in relations} | {keep_id})
        items = [("relation", r.id, r.fact(entities[r.source_id].name, entities[r.target_id].name)) for r in relations]
        items.append(("entity", keep_id, entities[keep_id].index_text()))
        for (kind, ref_id, text), vector in zip(items, self.embedder.embed([text for _, _, text in items])):
            self.store.index_text(kind, ref_id, text)
            self.store.index_vector(kind, ref_id, self.embedder.name, vector)

    def set_bucket_summary(self, bucket_id: str, summary: str) -> dict:
        summary = summary.strip()
        if not self.store.set_bucket_summary(bucket_id, summary):
            raise ValueError("Unknown bucket id.")
        self.store.index_text("bucket", bucket_id, summary)
        self._record("set_bucket_summary", "bucket", bucket_id, {"chars": len(summary)})
        self.store.commit()
        return {"dataset": self.name, "bucket_id": bucket_id, "updated": True}

    def global_context(self, limit: int = 20) -> dict:
        self.memify.rebuild_buckets()
        buckets = self.store.buckets()
        return {
            "dataset": self.name,
            "buckets": [{"id": b["id"], "label": b["label"], "members": len(b["member_ids"]), "summary": b["summary"], "stale": bool(b["summary_stale"])} for b in buckets[:limit]],
            "stale_count": sum(1 for b in buckets if b["summary_stale"]),
        }

    # ----- forget -------------------------------------------------------------
    def forget_entity(self, name: str) -> int:
        eid = Ids.entity(name)
        deleted = self.store.delete_entity(eid)
        self._record("forget", "entity", eid, {"name": name})
        self.store.commit()
        return deleted

    def forget_relation(self, rid: str) -> int:
        deleted = self.store.delete_relation(rid)
        self._record("forget", "relation", rid, {})
        self.store.commit()
        return deleted


class Engine:
    """Opens Datasets lazily and caches them for the life of the server process."""

    MERGED_KEYS = ("entities", "facts", "chunks", "summaries", "rules", "lessons", "session_turns", "global_context")

    def __init__(self, embedder: Embedder | None = None, data_dir: Path | None = None) -> None:
        self.embedder = embedder or LazyEmbedder()
        if data_dir is not None:
            os.environ["MEMOOSE_DATA_DIR"] = str(data_dir)
        self._open: dict[str, Dataset] = {}

    def default_dataset_name(self) -> str:
        return project_dataset_name()

    def dataset(self, name: str | None = None) -> Dataset:
        name = normalize_dataset_name(name) if name else self.default_dataset_name()
        if name not in self._open:
            self._open[name] = Dataset(name, SqliteStore(dataset_path(name)), self.embedder)
        return self._open[name]

    def user(self) -> Dataset:
        return self.dataset(USER_DATASET)

    def recall(self, query: str, datasets: list[str] | None = None, mode: str | None = None, limit: int = 10, include_superseded: bool = False, hops: int = 1, include_user: bool = True) -> dict:
        """Project Dataset first, user Dataset second with a fixed reserve of slots for user hits."""
        names = [normalize_dataset_name(d) for d in datasets] if datasets else [self.default_dataset_name()]
        if include_user and USER_DATASET not in names and not datasets:
            names.append(USER_DATASET)
        results = [self.dataset(n).recall(query, mode=mode, limit=limit, include_superseded=include_superseded, hops=hops) for n in names]
        merged = dict(results[0])
        merged["datasets"] = names
        reserve = max(1, limit // 4)
        for key in self.MERGED_KEYS:
            lists = [(name, r[key]) for name, r in zip(names, results) if r.get(key) is not None]
            if not lists:
                continue
            first_name, first = lists[0]
            acc = [dict(x, dataset=first_name) for x in first]
            for name, other in lists[1:]:
                acc = self._merge_ranked(acc, [dict(x, dataset=name) for x in other], limit=limit if key != "entities" else max(3, limit // 2), reserve=reserve)
            merged[key] = acc
        merged.pop("dataset", None)
        return merged

    @staticmethod
    def _merge_ranked(primary: list[dict], secondary: list[dict], limit: int, reserve: int) -> list[dict]:
        """Merge two ranked lists; the secondary always gets `reserve` slots if it has hits."""
        reserved = secondary[:reserve]
        cut = max(0, limit - len(reserved))
        seen: set = set()
        out: list[dict] = []
        for item in primary[:cut] + reserved + primary[cut:] + secondary[reserve:]:
            key = item.get("id") or item.get("fact") or id(item)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
            if len(out) >= limit:
                break
        return out

    def forget_dataset(self, name: str) -> bool:
        name = normalize_dataset_name(name)
        ds = self._open.pop(name, None)
        if ds:
            ds.store.close()
        path = dataset_path(name)
        existed = path.exists()
        for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            p.unlink(missing_ok=True)
        return existed

    def list_datasets(self) -> list[str]:
        d = data_dir()
        return sorted(p.stem for p in d.glob("*.sqlite")) if d.exists() else []

    def close(self) -> None:
        for ds in self._open.values():
            ds.store.close()
        self._open.clear()


__all__ = ["Engine", "Dataset", "MODES", "USER_DATASET"]
