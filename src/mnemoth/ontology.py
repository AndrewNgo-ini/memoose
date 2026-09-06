"""The Ontology: declared entity types and the rules relation names must follow.

cognee resolves extracted nodes against an ontology; mnemoth ships a small default
set of basic types (cognee's guidance: "use basic or elementary types for node
labels", keep specifics as descriptions) and lets a Dataset extend it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

RELATION_NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


@dataclass(frozen=True)
class EntityType:
    name: str
    description: str


DEFAULT_ENTITY_TYPES: tuple[EntityType, ...] = (
    EntityType("Person", "A human being, named as completely as the text allows."),
    EntityType("Organization", "A company, team, institution, or community."),
    EntityType("Project", "A named body of work with a goal, such as a repository or initiative."),
    EntityType("Product", "Something built and offered to users."),
    EntityType("System", "A running software or hardware system, service, or environment."),
    EntityType("Component", "A part of a system: module, package, file, function, table, endpoint."),
    EntityType("Technology", "A language, framework, library, protocol, tool, or standard."),
    EntityType("Concept", "An abstract idea, pattern, or term of art."),
    EntityType("Decision", "A choice that was made, with its rationale in the description."),
    EntityType("Requirement", "Something the work must satisfy: constraint, rule, preference."),
    EntityType("Issue", "A bug, incident, risk, or open problem."),
    EntityType("Event", "Something that happened at a point in time."),
    EntityType("Date", "A calendar date or period, written YYYY-MM-DD, YYYY-MM, or YYYY."),
    EntityType("Place", "A physical or logical location: city, region, data centre, URL."),
    EntityType("Role", "A function a Person or Organization performs."),
    EntityType("Topic", "A subject area that facts cluster around."),
)


class OntologyError(ValueError):
    """Raised when a fact does not fit the Ontology. The message is written for the agent."""


class Ontology:
    def __init__(self, types: list[EntityType] | None = None) -> None:
        self._types: dict[str, EntityType] = {}
        for t in types if types is not None else DEFAULT_ENTITY_TYPES:
            self._types[t.name.casefold()] = t

    @property
    def types(self) -> list[EntityType]:
        return sorted(self._types.values(), key=lambda t: t.name)

    def add_type(self, name: str, description: str) -> EntityType:
        name = name.strip()
        if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", name):
            raise OntologyError(
                f"Entity type {name!r} must be a single PascalCase word, e.g. 'Person' or 'ApiEndpoint'."
            )
        t = EntityType(name, description.strip())
        self._types[name.casefold()] = t
        return t

    def resolve_type(self, name: str) -> str:
        """Return the canonical spelling of an entity type, or raise a teaching error."""
        t = self._types.get(name.strip().casefold())
        if t is None:
            allowed = ", ".join(x.name for x in self.types)
            raise OntologyError(
                f"Unknown entity type {name!r}. Use one of: {allowed}. "
                "Prefer a basic type and put specifics in the description "
                "(a 'Mathematician' is a Person). If none fits, call add_entity_type first."
            )
        return t.name

    @staticmethod
    def validate_relation_name(name: str) -> str:
        name = name.strip()
        if not RELATION_NAME.fullmatch(name):
            raise OntologyError(
                f"Relation name {name!r} must be snake_case, e.g. 'works_at', 'depends_on', 'decided_on'."
            )
        return name
