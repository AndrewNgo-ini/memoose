---
name: mnemoth-ontology
description: Shape mnemoth's ontology. Use when the user has an OWL, RDF, or Turtle ontology to import, wants domain-specific entity types, or when relations like owner, version, or location should hold a single current value.
---

# Ontology in mnemoth (adapted from cognee)

The Ontology is the set of entity types facts are resolved against, plus rules for relation
names. Defaults are basic (Person, Organization, System, Component, Technology, Concept,
Decision, Requirement, Issue, Event, Date, Place, Role, Topic, Lesson). Specifics belong in
descriptions, not in new types.

## Extending

- `add_entity_type(name, description, parent?, aliases?)`: PascalCase, one line. Give a
  `parent` so it collapses onto a basic type (`ApiEndpoint` → `Component`). Aliases let the
  agent use either spelling.
- Only add a type when many facts will use it and no basic type fits. Ten well-used types beat
  fifty rare ones.

## Importing

`import_ontology(text, name, format?)` accepts Turtle, RDF/XML, N3, or JSON-LD text. Each
`owl:Class` becomes a type; `rdfs:subClassOf` becomes its parent; `rdfs:label` becomes an
alias; `rdfs:comment` becomes the description. Parent chains end on a basic type by name hints
(a class named `*Person*` or `*Employee*` lands on Person, `*Service*` on System, `*Location*`
on Place) or on Concept. Report to the user what was added and where each type landed.
Read the file with your own file tools and pass its text.

## Functional relations

Some relations hold one current value per subject: `owned_by`, `reports_to`,
`current_version`, `deployed_in`, `located_in`, `status`. Declare them once with
`declare_functional_relations([...])`. A new assertion then supersedes the older one
automatically and history keeps both. Never declare many-valued relations
(`uses`, `depends_on`, `knows`) as functional.

## Naming

Relation names are snake_case verb phrases: `works_at`, `depends_on`, `decided_on`,
`replaced_by`, `happened_on`, `applies_to`. Entity names are the most complete form found in
the source. Dates are `Date` entities written `YYYY-MM-DD`.
