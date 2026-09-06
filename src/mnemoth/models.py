"""Tool input and output shapes. These are the contract the skill teaches the Host Model."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntityIn(BaseModel):
    name: str = Field(description="Most complete human-readable name, e.g. 'Albert Einstein', 'PostgreSQL'.")
    type: str = Field(description="An entity type from describe_ontology, e.g. 'Person', 'System'.")
    description: str = Field(default="", description="One or two sentences about this entity, from the source only.")


class RelationIn(BaseModel):
    source: str = Field(description="Name of the source entity (must be in `entities` or already remembered).")
    name: str = Field(description="snake_case relation name, e.g. 'works_at', 'depends_on', 'decided_on'.")
    target: str = Field(description="Name of the target entity (must be in `entities` or already remembered).")
    description: str = Field(default="", description="One-sentence fact using the endpoint names, e.g. 'Alice leads the search team at Acme.'")
    evidence: str | None = Field(default=None, description="Where this fact comes from, e.g. 'repo://src/auth.py#L40-L82', a URL, or 'user said on 2026-09-06'.")


class StoredEntity(BaseModel):
    id: str
    name: str
    type: str
    description: str
    mentions: int
    merged: bool = Field(description="True if this name already existed and was merged rather than created.")


class StoredRelation(BaseModel):
    id: str
    fact: str
    evidence: str | None = None
    new: bool


class RememberResult(BaseModel):
    dataset: str
    entities: list[StoredEntity]
    relations: list[StoredRelation]
    chunks_stored: int
    warnings: list[str] = Field(default_factory=list)


class RecalledEntity(BaseModel):
    id: str
    name: str
    type: str
    description: str
    mentions: int
    score: float


class RecalledFact(BaseModel):
    id: str
    fact: str
    source: str
    relation: str
    target: str
    description: str
    evidence: str | None
    score: float


class RecalledChunk(BaseModel):
    id: str
    summary: str | None
    text: str
    source: str | None
    score: float


class RecallResult(BaseModel):
    dataset: str
    query: str
    entities: list[RecalledEntity]
    facts: list[RecalledFact]
    chunks: list[RecalledChunk]
    embedder: str


class OntologyView(BaseModel):
    dataset: str
    entity_types: list[dict]
    relation_name_rule: str
    stats: dict
    embedder: str
