"""Tool input shapes. These are the contract the skills teach the Host Model."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntityIn(BaseModel):
    name: str = Field(description="Most complete human-readable name, e.g. 'Albert Einstein', 'PostgreSQL'.")
    type: str = Field(description="An entity type from describe_ontology, e.g. 'Person', 'System'.")
    description: str = Field(default="", description="One or two sentences about this entity, from the source only.")


class RelationIn(BaseModel):
    source: str = Field(description="Name of the source entity (in `entities` or already remembered).")
    name: str = Field(description="snake_case relation name, e.g. 'works_at', 'depends_on', 'decided_on'.")
    target: str = Field(description="Name of the target entity (in `entities` or already remembered).")
    description: str = Field(default="", description="One-sentence fact using the endpoint names.")
    evidence: str | None = Field(default=None, description="Where this comes from: 'repo://src/auth.py#L40-L82', a URL, an issue id, 'user said 2026-09-06'.")
    valid_from: str | None = Field(default=None, description="ISO date when this fact became true, if known.")
    valid_to: str | None = Field(default=None, description="ISO date when this fact stopped being true, if known.")


class LessonIn(BaseModel):
    title: str = Field(description="Short title; also the lesson's identity.")
    text: str = Field(description="One to three sentences that stand alone without the session.")
    evidence: str | None = Field(default=None, description="Turn, file, or context line the lesson rests on.")
    applies_to: list[str] = Field(default_factory=list, description="Names of existing or new entities this lesson applies to.")
    entity_types: dict[str, str] = Field(default_factory=dict, description="Type for any name in applies_to that is not remembered yet.")


class CrossConnectIn(BaseModel):
    source: str
    name: str
    target: str
    description: str = ""
    evidence: str | None = None
