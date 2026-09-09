"""The Engine: validated writes and hybrid reads over Datasets. No model calls, ever."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from . import contradictions as contra
from . import memify as mem
from . import sessions as sess
from .chunking import chunk_text
from .datasets import dataset_path, normalize_dataset_name, project_dataset_name
from .embeddings import Embedder, LazyEmbedder
from .ids import chunk_id, entity_id, relation_id
from .models import CrossConnectIn, EntityIn, LessonIn, RelationIn
from .ontology import DEFAULT_ENTITY_TYPES, EntityType, Ontology, OntologyError, parse_ontology, plan_import
from .retrieval import MODES, Recaller, merge_ranked, render_fact
from .store.sqlite_store import ChunkRow, EntityRow, RelationRow, SqliteStore

USER_DATASET = "user"
ACTOR = "host-model"


class Dataset:
    def __init__(self, name: str, store: SqliteStore, embedder: Embedder) -> None:
        self.name = name
        self.store = store
        self.embedder = embedder
        if not store.list_entity_types():
            for t in DEFAULT_ENTITY_TYPES:
                store.upsert_entity_type(t.name, t.description, builtin=True)
        self.ontology = self._load_ontology()
        self.recaller = Recaller(store, embedder)

    def _load_ontology(self) -> Ontology:
        return Ontology([EntityType(r["name"], r["description"], r["parent"], r["aliases"], r["builtin"], r["source_id"]) for r in self.store.list_entity_types()])

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
        self.store.record(ACTOR, "add_entity_type", "entity_type", t.name, {"description": t.description, "parent": t.parent})
        self.store.commit()
        return {"name": t.name, "description": t.description, "parent": t.parent, "aliases": t.aliases, "basic_type": self.ontology.basic_type(t.name)}

    def import_ontology(self, text: str, name: str, fmt: str | None = None) -> dict:
        classes = parse_ontology(text, fmt)
        planned = plan_import(self.ontology, classes)
        source_id = self.store.add_ontology_source(name, fmt or "auto", len(classes))
        added = []
        for t in planned:
            t.source_id = source_id
            try:
                self.ontology.add_type(t.name, t.description, parent=t.parent, aliases=t.aliases, source_id=source_id)
            except OntologyError:
                continue
            self.store.upsert_entity_type(t.name, t.description, parent=t.parent, source_id=source_id, aliases=t.aliases)
            added.append({"name": t.name, "parent": t.parent, "basic_type": self.ontology.basic_type(t.name), "aliases": t.aliases})
        self.store.record(ACTOR, "import_ontology", "ontology_source", source_id, {"name": name, "classes": len(classes), "types_added": len(added)})
        self.store.commit()
        return {"dataset": self.name, "source_id": source_id, "classes_found": len(classes), "types_added": added}

    def declare_functional_relations(self, names: list[str]) -> dict:
        clean = [self.ontology.validate_relation_name(n) for n in names]
        self.store.declare_functional(clean)
        for n in clean:
            self.store.record(ACTOR, "declare_functional", "relation_name", n, {})
        self.store.commit()
        return {"dataset": self.name, "functional_relations": sorted(self.store.functional_relations())}

    # ----- remember -----------------------------------------------------------
    def remember(self, entities: list[EntityIn], relations: list[RelationIn], summary: str | None = None, source_text: str | None = None, source: str | None = None, session_id: str | None = None) -> dict:
        warnings: list[str] = []
        typed: list[EntityRow] = []
        for e in entities:
            if not e.name.strip():
                raise OntologyError("Every entity needs a non-empty name.")
            typed.append(EntityRow(entity_id(e.name), e.name.strip(), self.ontology.resolve_type(e.type), e.description.strip()))
        names = {t.id: t.name for t in typed}
        rel_rows: list[RelationRow] = []
        for r in relations:
            sid, tid = entity_id(r.source), entity_id(r.target)
            for eid, label in ((sid, r.source), (tid, r.target)):
                if eid not in names and self.store.get_entity(eid) is None:
                    raise OntologyError(f"Relation endpoint {label!r} is neither in `entities` nor already remembered. Add it to `entities` with a type, or use the exact name of an existing entity (see recall).")
            if sid == tid:
                raise OntologyError(f"Relation {r.name!r} cannot connect {r.source!r} to itself.")
            rname = self.ontology.validate_relation_name(r.name)
            rel_rows.append(RelationRow(relation_id(sid, rname, tid), sid, tid, rname, r.description.strip(), r.evidence, valid_from=r.valid_from, valid_to=r.valid_to))

        chunk_rows: list[ChunkRow] = []
        if source_text and source_text.strip():
            for i, text in enumerate(chunk_text(source_text)):
                chunk_rows.append(ChunkRow(chunk_id(text), text, summary if i == 0 else None, source))
        elif summary and summary.strip():
            chunk_rows.append(ChunkRow(chunk_id(summary), summary.strip(), summary.strip(), source))

        stored_entities, stored_relations, superseded = [], [], []
        functional = self.store.functional_relations()
        # Embed outside the write transaction so concurrent servers hold the SQLite lock briefly.
        pre_entities = self.store.get_entities([t.id for t in typed])
        for t in typed:
            if t.id in pre_entities:
                ex = pre_entities[t.id]
                t.description = t.description if len(t.description) > len(ex.description) else ex.description
                t.name = ex.name
        endpoints_pre = self.store.get_entities({r.source_id for r in rel_rows} | {r.target_id for r in rel_rows})
        for t in typed:
            endpoints_pre.setdefault(t.id, t)
        to_embed: list[tuple[str, str, str]] = []
        for t in typed:
            to_embed.append(("entity", t.id, f"{t.name} ({t.type}). {t.description}".strip()))
        for r in rel_rows:
            to_embed.append(("relation", r.id, render_fact(endpoints_pre[r.source_id].name, r.name, endpoints_pre[r.target_id].name, r.description)))
        for c in chunk_rows:
            to_embed.append(("chunk", c.id, f"{c.summary}\n\n{c.text}" if c.summary and c.summary != c.text else c.text))
        vectors = dict(zip([(k, i) for k, i, _ in to_embed], self.embedder.embed([t for _, _, t in to_embed]))) if to_embed else {}
        with self.store.conn:
            for row in typed:
                stored, merged = self.store.upsert_entity(row)
                stored_entities.append({"id": stored.id, "name": stored.name, "type": stored.type, "description": stored.description, "mentions": stored.mentions, "merged": merged})
                text = f"{stored.name} ({stored.type}). {stored.description}".strip()
                self.store.index_text("entity", stored.id, text)
                self.store.index_vector("entity", stored.id, self.embedder.name, vectors[("entity", stored.id)])
                self.store.record(ACTOR, "merge" if merged else "create", "entity", stored.id, {"name": stored.name, "type": stored.type, "session_id": session_id, "source": source})
            self.store.bump_frequency([t.id for t in typed])
            endpoints = self.store.get_entities({r.source_id for r in rel_rows} | {r.target_id for r in rel_rows})
            first_chunk = chunk_rows[0].id if chunk_rows else None
            for r in rel_rows:
                r.chunk_id = first_chunk
                new = self.store.upsert_relation(r)
                r = self.store.get_relation(r.id) or r
                fact = render_fact(endpoints[r.source_id].name, r.name, endpoints[r.target_id].name, r.description)
                stored_relations.append({"id": r.id, "fact": fact, "evidence": r.evidence, "new": new})
                self.store.index_text("relation", r.id, fact)
                self.store.index_vector("relation", r.id, self.embedder.name, vectors[("relation", r.id)])
                self.store.record(ACTOR, "assert" if new else "reassert", "relation", r.id, {"fact": fact, "evidence": r.evidence, "session_id": session_id, "source": source})
                for s_ in contra.apply_functional_supersession(self.store, r, functional):
                    superseded.append(s_)
                    self.store.record(ACTOR, "supersede", "relation", s_["relation_id"], s_)
            for c in chunk_rows:
                self.store.upsert_chunk(c, [t.id for t in typed])
                text = f"{c.summary}\n\n{c.text}" if c.summary and c.summary != c.text else c.text
                self.store.index_text("chunk", c.id, text)
                self.store.index_vector("chunk", c.id, self.embedder.name, vectors[("chunk", c.id)])
        if not relations:
            warnings.append("No relations given: entities alone are weak memory. Prefer facts as source --relation--> target.")
        touched = list(dict.fromkeys([t.id for t in typed] + [r.source_id for r in rel_rows] + [r.target_id for r in rel_rows]))
        hot = contra.candidate_facts(self.store, touched)["hotspots"] if rel_rows else []
        if hot:
            warnings.append(f"{len(hot)} subject(s) now hold several values for one relation; run contradiction_candidates and judge them.")
        return {"dataset": self.name, "entities": stored_entities, "relations": stored_relations, "superseded": superseded, "chunks_stored": len(chunk_rows), "hotspots": hot, "warnings": warnings}

    # ----- recall -------------------------------------------------------------
    def recall(self, query: str, mode: str | None = None, limit: int = 10, include_superseded: bool = False, hops: int = 1) -> dict:
        if not query.strip():
            raise ValueError("recall needs a non-empty query.")
        out = self.recaller.recall(query, mode=mode, limit=limit, include_superseded=include_superseded, hops=hops)
        return {"dataset": self.name, **out, "embedder": self.embedder.name}

    # ----- contradictions --------------------------------------------------------
    def contradiction_candidates(self, entity_names: list[str] | None = None, relation_ids: list[str] | None = None) -> dict:
        ids = [entity_id(n) for n in (entity_names or [])]
        for rid in relation_ids or []:
            r = self.store.get_relation(rid)
            if r:
                ids += [r.source_id, r.target_id]
        if not ids:
            return {"dataset": self.name, "open_contradictions": self.store.open_contradictions(), "facts": [], "hotspots": [], "guidance": contra.GUIDANCE}
        return {"dataset": self.name, **contra.candidate_facts(self.store, list(dict.fromkeys(ids)))}

    def mark_contradiction(self, first_relation_id: str, second_relation_id: str, reason: str, confidence: float) -> dict:
        a, b = self.store.get_relation(first_relation_id), self.store.get_relation(second_relation_id)
        if not a or not b:
            raise ValueError("Both relation ids must exist.")
        if a.id == b.id:
            raise ValueError("A fact cannot contradict itself.")
        cid = self.store.add_contradiction(a.id, b.id, reason.strip(), max(0.0, min(1.0, confidence)))
        # cognee also writes a `contradicts` edge between the two subjects when they differ.
        edge = None
        if a.source_id != b.source_id:
            eid = relation_id(a.source_id, "contradicts", b.source_id)
            self.store.upsert_relation(RelationRow(eid, a.source_id, b.source_id, "contradicts", reason.strip(), f"contradiction:{cid}"))
            edge = eid
        self.store.record(ACTOR, "mark_contradiction", "contradiction", cid, {"first": a.id, "second": b.id, "reason": reason, "confidence": confidence})
        self.store.commit()
        return {"dataset": self.name, "contradiction_id": cid, "contradicts_edge": edge}

    def supersede(self, old_relation_id: str, new_relation_id: str, reason: str) -> dict:
        if not self.store.get_relation(old_relation_id) or not self.store.get_relation(new_relation_id):
            raise ValueError("Both relation ids must exist.")
        ok = self.store.supersede(old_relation_id, new_relation_id, reason.strip())
        self.store.resolve_contradiction(old_relation_id, f"superseded_by:{new_relation_id}")
        self.store.record(ACTOR, "supersede", "relation", old_relation_id, {"superseded_by": new_relation_id, "reason": reason})
        self.store.commit()
        return {"dataset": self.name, "superseded": ok, "old": old_relation_id, "new": new_relation_id}

    def history(self, entity: str | None = None, relation_id: str | None = None, limit: int = 50) -> dict:
        if relation_id:
            return {"dataset": self.name, "kind": "relation", "ref_id": relation_id, "events": self.store.history("relation", relation_id, limit)}
        if entity:
            eid = entity_id(entity)
            rels = self.store.relations_for_entities([eid], limit_per_entity=100, include_superseded=True)
            events = self.store.history("entity", eid, limit)
            for r in rels:
                events += self.store.history("relation", r.id, limit)
            events.sort(key=lambda e: e["at"], reverse=True)
            return {"dataset": self.name, "kind": "entity", "ref_id": eid, "events": events[:limit]}
        raise ValueError("Pass entity or relation_id.")

    # ----- sessions -------------------------------------------------------------
    def session_start(self, session_id: str | None = None) -> dict:
        sid = session_id or uuid.uuid4().hex[:12]
        new = self.store.session_start(sid)
        active = self.store.context(sections=("goals", "rules", "preferences", "lessons_learned", "tool_rules", "environment_facts"))
        return {"dataset": self.name, "session_id": sid, "new": new, "standing_context": [{"section": c["section"], "content": c["content"], "session_id": c["session_id"]} for c in active[-30:]], "recent_lessons": self.store.lessons(10)}

    def session_add_turn(self, session_id: str, role: str, text: str) -> dict:
        self.store.session_start(session_id)
        if role not in ("user", "assistant", "tool", "system"):
            raise ValueError("role must be user, assistant, tool, or system.")
        tid = self.store.add_turn(session_id, role, text.strip())
        return {"dataset": self.name, "session_id": session_id, "turn_id": tid}

    def session_set_context(self, session_id: str, section: str, content: str, confidence: float = 1.0, retire_entry_id: int | None = None) -> dict:
        self.store.session_start(session_id)
        sec = sess.validate_section(section)
        if retire_entry_id is not None:
            self.store.retire_context(retire_entry_id)
        cid = self.store.add_context(session_id, sec, content.strip(), max(0.0, min(1.0, confidence)))
        if sec == "feedback":
            # cognee's feedback weights: "+name" / "-name" adjusts an entity's feedback weight.
            for tok in content.split():
                if tok[:1] in "+-" and len(tok) > 1:
                    eid = entity_id(tok[1:])
                    if self.store.get_entity(eid):
                        self.store.set_feedback(eid, 0.25 if tok[0] == "+" else -0.25)
            self.store.commit()
        self.store.record(ACTOR, "set_context", "session", session_id, {"section": sec, "content": content, "entry_id": cid})
        self.store.commit()
        return {"dataset": self.name, "session_id": session_id, "entry_id": cid, "section": sec}

    def session_get(self, session_id: str, sections: list[str] | None = None, include_turns: bool = True) -> dict:
        s = self.store.session(session_id)
        if s is None:
            raise ValueError(f"Unknown session {session_id!r}.")
        return {"dataset": self.name, "session": s, "turns": self.store.turns(session_id) if include_turns else [], "context": self.store.context(session_id=session_id, sections=[sess.validate_section(x) for x in sections] if sections else None)}

    def session_timeline(self, session_id: str, batch_chars: int = 6000) -> dict:
        return {"dataset": self.name, **sess.timeline(self.store, session_id, batch_chars)}

    def publish_lessons(self, session_id: str | None, lessons: list[LessonIn]) -> dict:
        published = []
        for l in lessons:
            lid = sess.lesson_id(l.title)
            ents = [EntityIn(name=l.title.strip(), type="Lesson", description=l.text.strip())]
            rels: list[RelationIn] = []
            for name in l.applies_to:
                if self.store.get_entity(entity_id(name)) is None:
                    t = l.entity_types.get(name)
                    if not t:
                        raise OntologyError(f"Lesson {l.title!r} applies to unknown entity {name!r}; give its type in entity_types or remember it first.")
                    ents.append(EntityIn(name=name, type=t, description=""))
                rels.append(RelationIn(source=l.title.strip(), name="applies_to", target=name, description=f"Lesson '{l.title.strip()}' applies to {name}.", evidence=l.evidence))
            out = self.remember(ents, rels, summary=l.text.strip(), source_text=l.text.strip(), source=f"session:{session_id}" if session_id else "distillation", session_id=session_id)
            lesson_entity = out["entities"][0]["id"]
            self.store.add_lesson(lid, session_id, l.title.strip(), l.text.strip(), l.evidence, lesson_entity, chunk_id(l.text.strip()))
            self.store.record(ACTOR, "publish_lesson", "lesson", lid, {"title": l.title, "session_id": session_id})
            published.append({"id": lid, "title": l.title.strip(), "entity_id": lesson_entity, "applies_to": l.applies_to})
        if session_id and self.store.session(session_id):
            self.store.session_mark_distilled(session_id)
        self.store.commit()
        return {"dataset": self.name, "published": published}

    def session_end(self, session_id: str) -> dict:
        if self.store.session(session_id) is None:
            raise ValueError(f"Unknown session {session_id!r}.")
        self.store.session_end(session_id)
        s = self.store.session(session_id)
        return {"dataset": self.name, "session": s, "distilled": s["distilled_at"] is not None, "next": "Run session_timeline and distill lessons if not yet distilled."}

    def session_forget(self, session_id: str) -> dict:
        return {"dataset": self.name, "deleted": self.store.delete_session(session_id)}

    # ----- memify ------------------------------------------------------------------
    def memify_candidates(self, kind: str, limit: int = 20) -> dict:
        if kind == "cross_connect":
            return {"dataset": self.name, "kind": kind, "candidates": mem.cross_connect_candidates(self.store, limit), "guidance": "For each pair, add a relation only if the shared context states a real relationship; describe it in one sentence with evidence. Skip pairs that merely co-occur."}
        if kind == "consolidate":
            return {"dataset": self.name, "kind": kind, "candidates": mem.consolidate_candidates(self.store, limit), "guidance": "Merge only when both names denote the same real thing. Keep the fuller, more-mentioned name. Call merge_entities(keep, drop)."}
        if kind == "stale_summaries":
            mem.rebuild_buckets(self.store)
            return {"dataset": self.name, "kind": kind, "candidates": mem.stale_bucket_inputs(self.store, limit), "guidance": "Write each bucket summary in the given shape from the listed facts only, then call set_bucket_summary."}
        raise ValueError("kind must be cross_connect, consolidate, or stale_summaries.")

    def maintenance(self, limit: int = 10) -> dict:
        """Everything in this dataset that currently needs a judgment call, in one sweep.

        Storing facts as they arrive is half of keeping memory; the other half is going back over
        it — judging conflicts, merging duplicates, distilling finished sessions, rewriting stale
        summaries. This gathers that worklist deterministically and decides nothing: the model
        working through it makes every call. `stale_summaries` rebuilds the bucket index as it
        goes, so this is not a read-only command.
        """
        ids = [e.id for e in self.store.all_entities()]
        work = {
            "hotspots": (contra.candidate_facts(self.store, ids)["hotspots"][:limit] if ids else []),
            "open_contradictions": self.store.open_contradictions(limit),
            "consolidate": mem.consolidate_candidates(self.store, limit),
            "cross_connect": mem.cross_connect_candidates(self.store, limit),
            "stale_summaries": (mem.rebuild_buckets(self.store), mem.stale_bucket_inputs(self.store, limit))[1],
            "undistilled_sessions": [
                s for s in self.store.sessions(50) if s.get("ended_at") and not s.get("distilled_at")
            ][:limit],
        }
        return {
            "dataset": self.name,
            "pending": sum(len(v) for v in work.values()),
            **work,
            "guidance": (
                "Judge each item; do not accept them wholesale. hotspots and open_contradictions: "
                "memoose-contradictions (supersede when the newer fact replaces the older, "
                "mark_contradiction when both claim to be current). consolidate and cross_connect: "
                "memoose-memify, and only when the names denote the same thing or the relation is "
                "real. undistilled_sessions: session_timeline then publish_lessons. "
                "stale_summaries: write each from the listed facts only, then set_bucket_summary."
            ),
        }

    def cross_connect(self, relations: list[CrossConnectIn]) -> dict:
        rels = [RelationIn(source=r.source, name=r.name, target=r.target, description=r.description, evidence=r.evidence) for r in relations]
        return self.remember([], rels, source="memify:cross_connect")

    def merge_entities(self, keep: str, drop: str) -> dict:
        keep_id, drop_id = entity_id(keep), entity_id(drop)
        k, d = self.store.get_entity(keep_id), self.store.get_entity(drop_id)
        if not k or not d:
            raise ValueError("Both entities must exist.")
        if keep_id == drop_id:
            raise ValueError("keep and drop are the same entity.")
        with self.store.conn:
            touched = self.store.repoint_entity(drop_id, keep_id)
            desc = k.description if len(k.description) >= len(d.description) else d.description
            self.store.conn.execute("UPDATE entities SET description=?, mentions=mentions+?, updated_at=strftime('%s','now') WHERE id=?", (desc, d.mentions, keep_id))
            alias_note = f" Also known as {d.name}."
            if d.name.casefold() != k.name.casefold() and alias_note.strip() not in desc:
                self.store.conn.execute("UPDATE entities SET description=description||? WHERE id=?", (alias_note, keep_id))
            ents = self.store.get_entities({r.source_id for r in self.store.get_relations(touched).values()} | {r.target_id for r in self.store.get_relations(touched).values()} | {keep_id})
            texts = []
            for r in self.store.get_relations(touched).values():
                fact = render_fact(ents[r.source_id].name, r.name, ents[r.target_id].name, r.description)
                self.store.index_text("relation", r.id, fact)
                texts.append(("relation", r.id, fact))
            ke = self.store.get_entity(keep_id)
            etext = f"{ke.name} ({ke.type}). {ke.description}"
            self.store.index_text("entity", keep_id, etext)
            texts.append(("entity", keep_id, etext))
            for (kind, rid, _), vec in zip(texts, self.embedder.embed([t for _, _, t in texts])):
                self.store.index_vector(kind, rid, self.embedder.name, vec)
            self.store.delete_entity(drop_id)
            self.store.record(ACTOR, "merge_entities", "entity", keep_id, {"dropped": drop_id, "dropped_name": d.name, "relations_repointed": len(touched)})
        return {"dataset": self.name, "kept": keep_id, "dropped": drop_id, "relations_repointed": len(touched)}

    def set_bucket_summary(self, bucket_id: str, summary: str) -> dict:
        ok = self.store.set_bucket_summary(bucket_id, summary.strip())
        if not ok:
            raise ValueError("Unknown bucket id.")
        self.store.index_text("bucket", bucket_id, summary.strip())
        self.store.record(ACTOR, "set_bucket_summary", "bucket", bucket_id, {"chars": len(summary)})
        self.store.commit()
        return {"dataset": self.name, "bucket_id": bucket_id, "updated": True}

    def global_context(self, limit: int = 20) -> dict:
        mem.rebuild_buckets(self.store)
        bs = self.store.buckets()
        return {"dataset": self.name, "buckets": [{"id": b["id"], "label": b["label"], "members": len(b["member_ids"]), "summary": b["summary"], "stale": bool(b["summary_stale"])} for b in bs[:limit]], "stale_count": sum(1 for b in bs if b["summary_stale"])}

    # ----- forget -------------------------------------------------------------
    def forget_entity(self, name: str) -> int:
        n = self.store.delete_entity(entity_id(name))
        self.store.record(ACTOR, "forget", "entity", entity_id(name), {"name": name})
        self.store.commit()
        return n

    def forget_relation(self, rid: str) -> int:
        n = self.store.delete_relation(rid)
        self.store.record(ACTOR, "forget", "relation", rid, {})
        self.store.commit()
        return n


class Engine:
    """Opens Datasets lazily and caches them for the life of the server process."""

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
        """Project Dataset first, user Dataset second with a reserve (cognee's conversational_reserve)."""
        names = [normalize_dataset_name(d) for d in datasets] if datasets else [self.default_dataset_name()]
        if include_user and USER_DATASET not in names and not datasets:
            names.append(USER_DATASET)
        results = [self.dataset(n).recall(query, mode=mode, limit=limit, include_superseded=include_superseded, hops=hops) for n in names]
        primary, rest = results[0], results[1:]
        merged = dict(primary)
        merged["datasets"] = names
        reserve = max(1, limit // 4)
        for key in ("entities", "facts", "chunks", "summaries", "rules", "lessons", "session_turns", "global_context"):
            lists = [r.get(key) for r in results if r.get(key) is not None]
            if not lists:
                continue
            acc = [dict(x, dataset=names[0]) for x in lists[0]]
            for i, other in enumerate(lists[1:], start=1):
                acc = merge_ranked(acc, [dict(x, dataset=names[i]) for x in other], limit=limit if key != "entities" else max(3, limit // 2), reserve=reserve)
            merged[key] = acc
        merged.pop("dataset", None)
        return merged

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
        from .datasets import data_dir as _dd

        d = _dd()
        return sorted(p.stem for p in d.glob("*.sqlite")) if d.exists() else []

    def close(self) -> None:
        for ds in self._open.values():
            ds.store.close()
        self._open.clear()


__all__ = ["Engine", "Dataset", "MODES", "USER_DATASET"]
