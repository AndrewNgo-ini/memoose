"""The Ontology: declared entity types, aliases, a parent hierarchy, and relation-name rules.

cognee resolves extracted nodes against an OWL/RDF ontology with closest-match lookup.
memoose ships basic default types (cognee's guidance: basic labels, specifics in
descriptions), lets a Dataset extend them, and imports OWL/RDF/Turtle class
hierarchies: imported classes become types whose parent chain collapses onto a
basic type for extraction, so the agent can use either the specific or the basic name.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

RELATION_NAME = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
TYPE_NAME = re.compile(r"^[A-Z][A-Za-z0-9]*$")


@dataclass
class EntityType:
    name: str
    description: str
    parent: str | None = None
    aliases: list[str] = field(default_factory=list)
    builtin: bool = False
    source_id: str | None = None


DEFAULT_ENTITY_TYPES: tuple[EntityType, ...] = tuple(
    EntityType(n, d, builtin=True)
    for n, d in (
        ("Person", "A human being, named as completely as the text allows."),
        ("Organization", "A company, team, institution, or community."),
        ("Project", "A named body of work with a goal, such as a repository or initiative."),
        ("Product", "Something built and offered to users."),
        ("System", "A running software or hardware system, service, or environment."),
        ("Component", "A part of a system: module, package, file, function, table, endpoint."),
        ("Technology", "A language, framework, library, protocol, tool, or standard."),
        ("Concept", "An abstract idea, pattern, or term of art."),
        ("Decision", "A choice that was made, with its rationale in the description."),
        ("Requirement", "Something the work must satisfy: constraint, rule, preference."),
        ("Issue", "A bug, incident, risk, or open problem."),
        ("Event", "Something that happened at a point in time."),
        ("Date", "A calendar date or period, written YYYY-MM-DD, YYYY-MM, or YYYY."),
        ("Place", "A physical or logical location: city, region, data centre, URL."),
        ("Role", "A function a Person or Organization performs."),
        ("Topic", "A subject area that facts cluster around."),
        ("Lesson", "A distilled, reusable learning from past work."),
        ("Procedure", "A step an agent takes: a tool action, a check, or a state of the work. Its outgoing "
                      "relations (leads_to, requires, triggers) say what comes next and under which condition."),
    )
)


class OntologyError(ValueError):
    """Raised when a fact does not fit the Ontology. The message is written for the agent."""


class Ontology:
    def __init__(self, types: list[EntityType] | None = None) -> None:
        self._types: dict[str, EntityType] = {}
        self._alias: dict[str, str] = {}
        for t in types if types is not None else DEFAULT_ENTITY_TYPES:
            self._add(t)

    def _add(self, t: EntityType) -> None:
        self._types[t.name.casefold()] = t
        for a in t.aliases:
            self._alias[a.casefold()] = t.name

    @property
    def types(self) -> list[EntityType]:
        return sorted(self._types.values(), key=lambda t: t.name)

    def get(self, name: str) -> EntityType | None:
        return self._types.get(name.casefold())

    def add_type(self, name: str, description: str, parent: str | None = None, aliases: list[str] | None = None, source_id: str | None = None) -> EntityType:
        name = name.strip()
        if not TYPE_NAME.fullmatch(name):
            raise OntologyError(f"Entity type {name!r} must be a single PascalCase word, e.g. 'Person' or 'ApiEndpoint'.")
        if parent and self.get(parent) is None:
            raise OntologyError(f"Parent type {parent!r} does not exist.")
        t = EntityType(name, description.strip(), parent=self.get(parent).name if parent else None, aliases=[a.strip() for a in (aliases or []) if a.strip()], source_id=source_id)
        self._add(t)
        return t

    def resolve_type(self, name: str) -> str:
        key = name.strip().casefold()
        t = self._types.get(key)
        if t is None and key in self._alias:
            t = self._types[self._alias[key].casefold()]
        if t is None:
            close = difflib.get_close_matches(name.strip(), [x.name for x in self.types], n=3, cutoff=0.75)
            hint = f" Did you mean {', '.join(close)}?" if close else ""
            allowed = ", ".join(x.name for x in self.types)
            raise OntologyError(
                f"Unknown entity type {name!r}.{hint} Use one of: {allowed}. "
                "Prefer a basic type and put specifics in the description (a 'Mathematician' is a Person). "
                "If none fits, call add_entity_type first."
            )
        return t.name

    def basic_type(self, name: str) -> str:
        """Walk the parent chain to the root: the basic type an imported class collapses onto."""
        t = self.get(name)
        seen: set[str] = set()
        while t and t.parent and t.name not in seen:
            seen.add(t.name)
            t = self.get(t.parent)
        return t.name if t else name

    @staticmethod
    def validate_relation_name(name: str) -> str:
        name = name.strip()
        if not RELATION_NAME.fullmatch(name):
            raise OntologyError(f"Relation name {name!r} must be snake_case, e.g. 'works_at', 'depends_on', 'decided_on'.")
        return name


# ----- import ------------------------------------------------------------------------------

_BASIC_HINTS = {
    "person": "Person", "human": "Person", "agent": "Person", "people": "Person",
    "organization": "Organization", "organisation": "Organization", "company": "Organization", "team": "Organization",
    "project": "Project", "product": "Product", "system": "System", "service": "System",
    "component": "Component", "module": "Component", "technology": "Technology", "tool": "Technology", "software": "Technology",
    "concept": "Concept", "decision": "Decision", "requirement": "Requirement", "issue": "Issue", "bug": "Issue",
    "event": "Event", "date": "Date", "time": "Date", "place": "Place", "location": "Place", "role": "Role", "topic": "Topic",
    "procedure": "Procedure", "step": "Procedure", "action": "Procedure", "workflow": "Procedure", "state": "Procedure",
}


@dataclass
class ImportedClass:
    name: str
    label: str | None
    parent: str | None
    comment: str | None


def parse_ontology(text: str, fmt: str | None = None) -> list[ImportedClass]:
    """Parse OWL/RDF class declarations. Uses rdflib when installed, else a Turtle/RDF-XML regex fallback."""
    try:
        return _parse_with_rdflib(text, fmt)
    except ImportError:
        return _parse_fallback(text)


def _local(uri: str) -> str:
    frag = re.split(r"[#/]", uri.rstrip("/#"))[-1]
    return frag


def _parse_with_rdflib(text: str, fmt: str | None) -> list[ImportedClass]:
    import rdflib  # type: ignore[import-not-found]
    from rdflib.namespace import OWL, RDF, RDFS  # type: ignore[import-not-found]

    g = rdflib.Graph()
    formats = [fmt] if fmt else ["turtle", "xml", "n3", "json-ld"]
    for f in formats:
        try:
            g.parse(data=text, format=f)
            break
        except Exception:  # noqa: BLE001
            continue
    else:
        raise OntologyError("Could not parse ontology text as Turtle, RDF/XML, N3, or JSON-LD.")
    classes: dict[str, ImportedClass] = {}
    for s in set(g.subjects(RDF.type, OWL.Class)) | set(g.subjects(RDF.type, RDFS.Class)):
        if not isinstance(s, rdflib.URIRef):
            continue
        parent = next((_local(str(o)) for o in g.objects(s, RDFS.subClassOf) if isinstance(o, rdflib.URIRef) and str(o) != str(OWL.Thing)), None)
        label = next((str(o) for o in g.objects(s, RDFS.label)), None)
        comment = next((str(o) for o in g.objects(s, RDFS.comment)), None)
        classes[_local(str(s))] = ImportedClass(_local(str(s)), label, parent, comment)
    return list(classes.values())


_TTL_CLASS = re.compile(r"(?P<subj>[<\w:][^\s]*)\s+(?:a|rdf:type)\s+(?:owl:Class|rdfs:Class)\b(?P<body>[^.]*)\.", re.S)
_TTL_SUB = re.compile(r"rdfs:subClassOf\s+(?P<obj>[<\w:][^\s;.]*)")
_TTL_LABEL = re.compile(r'rdfs:label\s+"(?P<v>[^"]*)"')
_TTL_COMMENT = re.compile(r'rdfs:comment\s+"(?P<v>[^"]*)"')
_XML_CLASS = re.compile(r'<owl:Class\s+rdf:about="(?P<subj>[^"]+)"(?P<body>.*?)</owl:Class>|<owl:Class\s+rdf:about="(?P<subj2>[^"]+)"\s*/>', re.S)
_XML_SUB = re.compile(r'<rdfs:subClassOf\s+rdf:resource="(?P<obj>[^"]+)"')
_XML_LABEL = re.compile(r"<rdfs:label[^>]*>(?P<v>[^<]*)</rdfs:label>")
_XML_COMMENT = re.compile(r"<rdfs:comment[^>]*>(?P<v>[^<]*)</rdfs:comment>")


def _strip(tok: str) -> str:
    tok = tok.strip("<>")
    return _local(tok.split(":", 1)[1] if ":" in tok and not tok.startswith("http") else tok)


def _parse_fallback(text: str) -> list[ImportedClass]:
    out: dict[str, ImportedClass] = {}
    if "<owl:Class" in text or "<rdf:RDF" in text:
        for m in _XML_CLASS.finditer(text):
            subj = m.group("subj") or m.group("subj2")
            body = m.group("body") or ""
            sub = _XML_SUB.search(body)
            lab = _XML_LABEL.search(body)
            com = _XML_COMMENT.search(body)
            name = _local(subj)
            out[name] = ImportedClass(name, lab.group("v") if lab else None, _local(sub.group("obj")) if sub else None, com.group("v") if com else None)
    else:
        for m in _TTL_CLASS.finditer(text):
            body = m.group("body")
            sub = _TTL_SUB.search(body)
            lab = _TTL_LABEL.search(body)
            com = _TTL_COMMENT.search(body)
            name = _strip(m.group("subj"))
            out[name] = ImportedClass(name, lab.group("v") if lab else None, _strip(sub.group("obj")) if sub else None, com.group("v") if com else None)
    if not out:
        raise OntologyError("No owl:Class or rdfs:Class declarations found. Install the 'ontology' extra for full RDF parsing.")
    return list(out.values())


def to_type_name(raw: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", raw)
    name = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return name if TYPE_NAME.fullmatch(name or "x") else "X" + re.sub(r"[^A-Za-z0-9]", "", name)


def plan_import(ontology: Ontology, classes: list[ImportedClass]) -> list[EntityType]:
    """Turn imported classes into EntityTypes with parents that end on a basic type."""
    by_name = {c.name: c for c in classes}
    planned: dict[str, EntityType] = {}

    def basic_for(c: ImportedClass, depth: int = 0) -> str:
        key = (c.label or c.name).casefold()
        for hint, basic in _BASIC_HINTS.items():
            if hint in key:
                return basic
        if c.parent and c.parent in by_name and depth < 20:
            return basic_for(by_name[c.parent], depth + 1)
        if c.parent and ontology.get(to_type_name(c.parent)):
            return ontology.basic_type(to_type_name(c.parent))
        return "Concept"

    for c in classes:
        name = to_type_name(c.name)
        if ontology.get(name) and ontology.get(name).builtin:
            continue
        parent = to_type_name(c.parent) if c.parent and (c.parent in by_name or ontology.get(to_type_name(c.parent))) else basic_for(c)
        if parent == name:
            parent = basic_for(c)
        aliases = [c.label] if c.label and c.label.casefold() != name.casefold() else []
        planned[name] = EntityType(name, c.comment or (c.label or c.name), parent=parent, aliases=aliases)
    # Order parents before children.
    ordered: list[EntityType] = []
    done: set[str] = set(t.name for t in ontology.types)
    pending = dict(planned)
    while pending:
        progressed = False
        for name, t in list(pending.items()):
            if t.parent is None or t.parent in done:
                ordered.append(t)
                done.add(name)
                del pending[name]
                progressed = True
        if not progressed:
            for name, t in pending.items():
                t.parent = "Concept"
                ordered.append(t)
            break
    return ordered
