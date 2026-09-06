---
name: mnemoth
description: Persistent project memory as a typed knowledge graph. Use when the user says remember, recall, "what did we decide", "last time", "as before", refers to people, systems, decisions, or dates from earlier work, or when you learn a durable fact about the project, the team, or the user's preferences. Companion skills: mnemoth-sessions, mnemoth-contradictions, mnemoth-memify, mnemoth-ontology.
---

# mnemoth memory

mnemoth stores memory as a typed knowledge graph plus source text and recalls it by hybrid
search. It never calls a model. You do the extraction and the judgment; the tools validate and
store. Memory is scoped to a **dataset**: the current project by default, plus a `user` dataset
for facts about the user that hold in every project (preferences, identity, standing rules).
`recall` searches both; pass `dataset="user"` to `remember` for cross-project facts.

## When to recall

Call `recall` before you rely on the past, not after:

- at the start of a task that touches names, decisions, conventions, or people you may have met before
- whenever the user says "remember", "last time", "as we agreed", "what did we decide", or names something without explaining it
- before `remember`, to reuse the exact names of existing entities and to notice contradictions

`recall` routes the query to a mode (hybrid, facts, neighbourhood, lexical, summaries,
temporal, rules, session) and tells you which in `route`; pass `mode` to override. Quote a phrase
for exact lexical search. Ask "when" for temporal ordering. Ask for rules or conventions to get
session rules and lessons.

Treat results as raw material. Synthesise the answer yourself. When a fact carries `evidence`
(a file range, URL, or date) and the decision matters, re-check the evidence before acting on it.
`contested: true` means an open contradiction touches the fact (see mnemoth-contradictions).
Facts have a `score`; low scores are hints, not truths.

## When to remember

Remember durable facts, not chatter. Good: decisions and their reasons, who owns what, how
systems relate, conventions, preferences the user states, dates things happened, open issues.
Bad: transient task state, things already in the code and easy to grep, guesses.

Ask before storing anything personal or sensitive that the user did not explicitly ask you to keep.

## How to extract (adapted from cognee)

1. Call `describe_ontology` once per session. Use only its entity types. If nothing fits,
   call `add_entity_type` with a basic PascalCase name and a one-line description, then proceed.
2. **Entities** are things a Wikipedia page could be about. Use the most complete name in the
   text ("Albert Einstein", "PostgreSQL", "auth-service"). Never use pronouns or fragments.
   Resolve coreference: one entity per real thing, even if the text names it three ways.
3. **Types are basic.** A mathematician is a `Person`; a Postgres cluster is a `System`;
   a library is a `Technology`; a rule the code must follow is a `Requirement`. Put the
   specifics in `description`.
4. **Dates** are `Date` entities written `YYYY-MM-DD`, or `YYYY-MM` / `YYYY` when that is all
   the text gives. Link them with relations such as `happened_on`, `decided_on`, `due_on`.
5. **Relations** are `snake_case` verb phrases: `works_at`, `owns`, `depends_on`, `replaced_by`,
   `decided_on`, `blocked_by`, `prefers`. Source and target must be entity names from this call
   or from recall results.
6. **Every relation gets a description**: one dry, self-contained sentence using the endpoint
   names, with qualifiers from the source. Good: "Alice leads the search team at Acme since 2025."
   Bad: "This edge describes employment."
7. **Evidence**: put where the fact comes from in `evidence`: `repo://path/file.py#L10-L40`,
   a URL, an issue id, or `user said 2026-09-06`. Recall returns it so a later run can re-verify.
   When the text says since when or until when a fact held, set `valid_from` / `valid_to`.
8. **Do not add outside knowledge.** Only what the source supports.
9. Pass the original text as `source_text` when you have it (a message, a doc, a diff summary)
   and a `summary` in this shape so lexical recall works well:

   ```
   This chunk is about:
   - People: ...
   - Systems: ...
   Facts:
   - <self-contained sentence>
   - <self-contained sentence>
   ```

## Contradictions and history

`remember` returns `hotspots` when a subject now holds several values for one relation, and
`superseded` when a functional relation replaced an older value automatically. Follow the
mnemoth-contradictions skill: judge with `contradiction_candidates`, record with `supersede` or
`mark_contradiction`. Never `forget` a fact that was once true; supersede it so history stays.
`history(entity=...)` shows the provenance ledger.

## Merging

`remember` merges entities by name. If the result marks an entity `merged: true`, it already
existed; check that your type and description still fit. If a recall shows the same thing under
two spellings, pick the fuller one, re-state the facts against it, and `forget` the duplicate
after confirming with the user.

## Example

User: "We moved auth to JWT last week. Bao owns auth-service now, Linh moved to billing."

```
recall("auth JWT auth-service owner")        # reuse names, spot conflicts
remember(
  entities=[
    {name: "auth-service", type: "System", description: "Authentication service of this project."},
    {name: "JWT", type: "Technology", description: "JSON Web Tokens, used for auth since 2026-08."},
    {name: "Bao", type: "Person", description: "Engineer, owns auth-service."},
    {name: "Linh", type: "Person", description: "Engineer, moved to billing."},
    {name: "billing", type: "Component", description: "Billing area of the project."},
    {name: "2026-08-30", type: "Date", description: "Week auth moved to JWT."}
  ],
  relations=[
    {source: "auth-service", name: "uses", target: "JWT", description: "auth-service authenticates with JWT since 2026-08-30.", evidence: "user said 2026-09-06"},
    {source: "auth-service", name: "migrated_on", target: "2026-08-30", description: "auth-service moved from sessions to JWT around 2026-08-30."},
    {source: "Bao", name: "owns", target: "auth-service", description: "Bao owns auth-service as of 2026-09-06.", evidence: "user said 2026-09-06"},
    {source: "Linh", name: "works_on", target: "billing", description: "Linh moved from auth to billing in 2026-09.", evidence: "user said 2026-09-06"}
  ],
  summary="This chunk is about:\n- People: Bao, Linh\n- Systems: auth-service, billing\n- Technologies: JWT\nFacts:\n- auth-service switched to JWT around 2026-08-30.\n- Bao owns auth-service.\n- Linh moved to billing.",
  source_text="We moved auth to JWT last week. Bao owns auth-service now, Linh moved to billing."
)
```
