"""The Engine: validated writes and hybrid reads over one Dataset. No model calls."""

from __future__ import annotations

import os
from pathlib import Path

from .chunking import chunk_text
from .datasets import dataset_path, normalize_dataset_name, project_dataset_name
from .embeddings import Embedder, default_embedder
from .ids import chunk_id, entity_id, relation_id
from .models import EntityIn, RelationIn
from .ontology import DEFAULT_ENTITY_TYPES, EntityType, Ontology, OntologyError
from .retrieval import recall as hybrid_recall
from .retrieval import render_fact
from .store.sqlite_store import ChunkRow, EntityRow, RelationRow, SqliteStore


class Dataset:
    def __init__(self, name: str, store: SqliteStore, embedder: Embedder) -> None:
        self.name = name
        self.store = store
        self.embedder = embedder
        if not store.list_entity_types():
            for t in DEFAULT_ENTITY_TYPES:
                store.upsert_entity_type(t.name, t.description, builtin=True)
        self.ontology = Ontology([EntityType(n, d) for n, d, _ in store.list_entity_types()])

    # ----- ontology -----------------------------------------------------------
    def describe_ontology(self) -> dict:
        return {
            "dataset": self.name,
            "entity_types": [{"name": t.name, "description": t.description} for t in self.ontology.types],
            "relation_name_rule": "snake_case verb phrases such as works_at, depends_on, decided_on, replaced_by, happened_on.",
            "stats": self.store.stats(),
            "embedder": self.embedder.name,
        }

    def add_entity_type(self, name: str, description: str) -> dict:
        t = self.ontology.add_type(name, description)
        self.store.upsert_entity_type(t.name, t.description)
        return {"name": t.name, "description": t.description}

    # ----- remember -----------------------------------------------------------
    def remember(
        self,
        entities: list[EntityIn],
        relations: list[RelationIn],
        summary: str | None = None,
        source_text: str | None = None,
        source: str | None = None,
    ) -> dict:
        warnings: list[str] = []
        # 1. Validate everything before writing anything.
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
                    raise OntologyError(
                        f"Relation endpoint {label!r} is neither in `entities` nor already remembered. "
                        "Add it to `entities` with a type, or use the exact name of an existing entity (see recall)."
                    )
            if sid == tid:
                raise OntologyError(f"Relation {r.name!r} cannot connect {r.source!r} to itself.")
            rel_rows.append(RelationRow(relation_id(sid, self.ontology.validate_relation_name(r.name), tid), sid, tid, r.name.strip(), r.description.strip(), r.evidence))

        # 2. Chunks from the source text (retrieval material).
        chunk_rows: list[ChunkRow] = []
        if source_text and source_text.strip():
            pieces = chunk_text(source_text)
            for i, text in enumerate(pieces):
                chunk_rows.append(ChunkRow(chunk_id(text), text, summary if i == 0 else None, source))
        elif summary and summary.strip():
            chunk_rows.append(ChunkRow(chunk_id(summary), summary.strip(), summary.strip(), source))

        # 3. Write graph + indexes in one transaction.
        stored_entities, stored_relations = [], []
        texts_to_embed: list[tuple[str, str, str]] = []
        with self.store.conn:
            for row in typed:
                stored, merged = self.store.upsert_entity(row)
                stored_entities.append({"id": stored.id, "name": stored.name, "type": stored.type, "description": stored.description, "mentions": stored.mentions, "merged": merged})
                text = f"{stored.name} ({stored.type}). {stored.description}".strip()
                self.store.index_text("entity", stored.id, text)
                texts_to_embed.append(("entity", stored.id, text))
            all_endpoints = self.store.get_entities({r.source_id for r in rel_rows} | {r.target_id for r in rel_rows})
            first_chunk = chunk_rows[0].id if chunk_rows else None
            for r in rel_rows:
                r.chunk_id = first_chunk
                new = self.store.upsert_relation(r)
                fact = render_fact(all_endpoints[r.source_id].name, r.name, all_endpoints[r.target_id].name, r.description)
                stored_relations.append({"id": r.id, "fact": fact, "evidence": r.evidence, "new": new})
                self.store.index_text("relation", r.id, fact)
                texts_to_embed.append(("relation", r.id, fact))
            for c in chunk_rows:
                self.store.upsert_chunk(c, [t.id for t in typed])
                text = f"{c.summary}\n\n{c.text}" if c.summary and c.summary != c.text else c.text
                self.store.index_text("chunk", c.id, text)
                texts_to_embed.append(("chunk", c.id, text))
            if texts_to_embed:
                vectors = self.embedder.embed([t for _, _, t in texts_to_embed])
                for (kind, ref_id, _), vec in zip(texts_to_embed, vectors):
                    self.store.index_vector(kind, ref_id, self.embedder.name, vec)
        if not relations:
            warnings.append("No relations given: entities alone are weak memory. Prefer facts as source --relation--> target.")
        return {"dataset": self.name, "entities": stored_entities, "relations": stored_relations, "chunks_stored": len(chunk_rows), "warnings": warnings}

    # ----- recall -------------------------------------------------------------
    def recall(self, query: str, limit: int = 10) -> dict:
        if not query.strip():
            raise ValueError("recall needs a non-empty query.")
        result = hybrid_recall(self.store, self.embedder, query, entities_top_k=max(3, limit // 2), facts_top_k=limit, chunks_top_k=max(2, limit // 3))
        return {"dataset": self.name, "query": query, **result, "embedder": self.embedder.name}

    # ----- forget -------------------------------------------------------------
    def forget_entity(self, name: str) -> int:
        return self.store.delete_entity(entity_id(name))

    def forget_relation(self, relation_id_: str) -> int:
        return self.store.delete_relation(relation_id_)


class Engine:
    """Opens Datasets lazily and caches them for the life of the server process."""

    def __init__(self, embedder: Embedder | None = None, data_dir: Path | None = None) -> None:
        self.embedder = embedder or default_embedder()
        if data_dir is not None:
            os.environ["MNEMOTH_DATA_DIR"] = str(data_dir)
        self._open: dict[str, Dataset] = {}

    def default_dataset_name(self) -> str:
        return project_dataset_name()

    def dataset(self, name: str | None = None) -> Dataset:
        name = normalize_dataset_name(name) if name else self.default_dataset_name()
        if name not in self._open:
            self._open[name] = Dataset(name, SqliteStore(dataset_path(name)), self.embedder)
        return self._open[name]

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
