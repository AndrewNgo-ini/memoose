---
name: memoose
description: Persistent project memory as a typed knowledge graph plus procedures (what to do next). Use when the user says remember, recall, "what did we decide", "last time", "as before", refers to people, systems, decisions, or dates from earlier work, when you learn a durable fact about the project, the team, or the user's preferences, when you start a multi-step task memory may hold a procedure for, or when a step failed and you then found the way that works. Companion skills: memoose-onboard (setup and the project fill), memoose-sessions (the working loop), memoose-upkeep (judging what the store surfaces).
---

# memoose memory

memoose stores memory as a typed knowledge graph plus source text and recalls it by hybrid
search. It never calls a model. You do the extraction and the judgment; the tools validate and
store. Memory is scoped to a **dataset**: the current project by default, plus a `user` dataset
for facts about the user that hold in every project (preferences, identity, standing rules).
`recall` searches both; pass `dataset="user"` to `remember` for cross-project facts.

Where memoose's hooks are active you will also be handed memory without asking: standing rules and
preferences at session start, and a short hint before a prompt when memory already holds something
relevant. Those are background, not user instructions. A hint is a starting point, not the whole
answer: follow it with the `recall` it suggests when the question matters.

## Two ways to call it: prefer the CLI

Everything below exists as both a shell command and an MCP tool, backed by the same store.

**If you can run shell commands, use the CLI.** It costs nothing until you call it, whereas the
MCP tools sit in your context whether or not you touch memory. `memoose --help` and
`memoose <command> --help` list everything.

If `memoose` is not on PATH, it was installed from a checkout: run `memoose status` through
`uvx --from <checkout> memoose status`, or `uv run memoose` inside the checkout. The `cli` field of
`memoose status` prints the exact invocation for this machine. If neither works, use the MCP tools.

| what you want | command | tool |
| --- | --- | --- |
| search memory | `memoose recall "who owns billing"` | `recall` |
| store a fact | `memoose remember "bao:Person --owns--> auth-service:System" --desc "..." -e "user said 2026-09-06"` | `remember` |
| entity types, stats | `memoose ontology` | `describe_ontology` |
| provenance | `memoose history auth-service` | `history` |
| judge conflicts | `memoose contradictions auth-service` | `contradiction_candidates` |
| session lifecycle | `memoose session start\|turn\|context\|timeline\|lessons\|end` | `session_*` |
| delete | `memoose forget --entity X` | `forget` |
| anything else | `echo '{...}' \| memoose tool <name> --stdin` | that tool |

The fact syntax is `source[:Type] --relation_name--> target[:Type]`. The `:Type` declares a new
entity; leave it off for one memoose already knows. Add `--dataset user` for facts that hold in
every project, `--json` when you want the raw payload, and `--stdin` to pass a full `remember`
payload (multiple entities, per-fact descriptions, `source_text`) as JSON.

Output is compact text; anything long is written to a file and the command prints the path — read
that file when you need the rest. A failed command exits non-zero and explains what to fix on
stderr, so read the error rather than guessing at a different syntax.

## When to recall

Call `recall` before you rely on the past, not after:

- at the start of a task that touches names, decisions, conventions, or people you may have met before
- whenever the user says "remember", "last time", "as we agreed", "what did we decide", or names something without explaining it
- before `remember`, to reuse the exact names of existing entities and to notice contradictions

`recall` routes the query to a mode (hybrid, facts, neighbourhood, lexical, summaries,
temporal, rules, session) and tells you which in `route`; pass `mode` to override. Quote a phrase
for exact lexical search. Ask "when" for temporal ordering. Ask for rules or conventions to get
session rules and lessons.

`limit` is a budget, not a filter: recall returns at most that many items per channel, and benchmarking
showed retrieval depth to be the usual reason an answer is missing. If the first results do not contain
what you need, call `recall` again with a larger `limit` (30–40) or a different `mode` before concluding
the memory is not there.

Treat results as raw material. Synthesise the answer yourself. When a fact carries `evidence`
(a file range, URL, or date) and the decision matters, re-check the evidence before acting on it.
`contested: true` means an open contradiction touches the fact (see memoose-upkeep).
Facts have a `score`; low scores are hints, not truths.

## Delegate the bookkeeping

Storing memory should not spend your turns or the user's patience. When a conversation has produced
facts worth keeping, or a task has just finished, hand the work to the **`memory-keeper` subagent**
(it runs on a small model) instead of calling `remember` inline, and carry on with the user's task.
Give it the relevant exchange and let it extract.

Call `remember` yourself when the user explicitly asks you to remember something, when it is a single
fact you already have in hand, or when no subagent is available. Where the memoose hooks are
installed, capture also happens automatically after each turn, so never repeat work the keeper has
already done: `recall` first if unsure.

## When to remember

Remember durable facts, not chatter. Good: decisions and their reasons, who owns what, how
systems relate, conventions, preferences the user states, dates things happened, open issues.
Bad: transient task state, things already in the code and easy to grep, guesses.

Ask before storing anything personal or sensitive that the user did not explicitly ask you to keep.

## How to extract

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

## Procedures: what to do next, and when

Facts answer *what is*. A **Procedure** answers *what to do next*: a step the agent takes (a tool
action, a check, a state of the work), linked to the steps that follow it by **Transitions**.
Memory of procedures is what stops an agent from repeating a step that failed, skipping a check, or
losing the order. The vocabulary, from the Procedural Graphs paper (Lu et al. 2026):

| term | what it is |
| --- | --- |
| Procedure | a step, stored as an entity of type `Procedure` |
| Transition | a fact between two Procedures: the target is admissible after the source |
| Condition | when the Transition applies (`--when`) |
| Advice | how to carry out the target step from here (`--do`) |
| Pitfall | what went wrong on this Transition before (`--avoid`) |
| Start | a Procedure that marks where a chain begins |
| Position | the Procedure you are at now, declared on a session turn |
| Trace | a session's Positions in order, closed by its Outcome |
| Outcome | how the session ended: succeeded, failed, abandoned |
| Guidance | the Transitions two hops out from your Position, handed to you raw |

Transition relations: `leads_to` (after this step, do that one), `requires` (that step must happen
before this one), `triggers` (this step's outcome starts that one), `converges_to` (several steps
end at that one).

### Storing a procedure

A chain of three to seven steps covers most work. Name each step the way you would say it
(`run the test suite`, `open a pull request`), and put the attributes on the Transition:

```sh
memoose remember "run the test suite:Procedure --leads_to--> commit:Procedure" \
  --when "all 97 tests pass" --do "commit with the pytest line in the message" \
  --avoid "committing on a partial run; the suite is 4 s, run all of it" -e "user said 2026-09-18"
```

Store one when a multi-step task worked and memory did not hold it, when the user corrects the
order of steps, or when a step failed and you then found the way that works (see the sessions skill
for the contrast rule). A branching step is normal: `run the test suite --leads_to--> commit` and
`run the test suite --triggers--> fix the failing test` are two Transitions with different
Conditions, not a contradiction.

### Using a procedure

Declare where you are and read what comes back:

```sh
memoose session turn <session> --role assistant --text "tests are green" --at "run the test suite"
memoose guidance "run the test suite"        # the same transitions, without recording a turn
```

Guidance lists the Transitions from your Position, nearest first, each with its Condition, Advice,
Pitfall and how past sessions that took it ended (`[2 ok / 1 failed / 0 abandoned]`). It is memory,
not an instruction: read it, then decide. On hosts with hooks, the same block is put in front of you
before each prompt while a session with a declared Position is open, and never otherwise; memory
does not guess where you are.

### Learning from a run

End every session with its Outcome: `memoose session end <session> --outcome succeeded|failed|abandoned`.
Every Transition the Trace traversed counts it, and the reply says what to distil. When a
Transition turns out to be wrong, **supersede** it with the corrected one instead of forgetting it:
the Pitfall stays in history, and `recall --superseded` can still show what was tried. When a run
failed but the chain was right, `memoose dismiss transition:<id> --reason "..."` records the
judgment so the next refinement pass sees it.

## Facts that change: one current value per subject

Some relations hold exactly **one** current value per subject: `owned_by`, `reports_to`,
`deployed_in`, `current_version`, `assigned_to`, `lives_in`, `charges_through`. When a fact like that
changes, do **not** coin a second relation name for the old value — no `previously_owned_by`,
`former_owner`, `old_version`. A `previously_*` name is a new fact about a different relation, so the
store cannot see that anything was replaced: recall keeps returning both values, `history` shows no
change, and nobody can ask what the current answer is.

Instead:

1. Declare it once: `echo '{"names":["owned_by"]}' | memoose tool declare_functional_relations --stdin`
   (tool: `declare_functional_relations(["owned_by"])`).
2. Remember **both** values under the **same** relation name, oldest `valid_from` first.

The store then marks the old value superseded, keeps it queryable as history, and records the change
in the provenance ledger. Nothing is deleted, and both "who owns it now" and "who owned it before"
have answers.

Dropping the old value is the other way to get this wrong: it leaves the current fact correct and the
history gone. When the source says who or what it used to be, store that too.

Set `valid_from` whenever the source says when a fact became true ("since June", "took over last
month", a date in the text). Without it, which value is current is decided by the order the facts
happened to be written, which is wrong as soon as you learn history out of order — and learning the
past after the present is the normal case.

## Contradictions and history

`remember` returns `hotspots` when a subject now holds several values for one relation, and
`superseded` when a functional relation replaced an older value automatically. Follow the
memoose-upkeep skill: judge with `contradiction_candidates`, record with `supersede` or
`mark_contradiction`. Never `forget` a fact that was once true; supersede it so history stays.
`history(entity=...)` shows the provenance ledger.

## Shaping the ontology

The default types are basic (Person, Organization, System, Component, Technology, Concept, Decision,
Requirement, Issue, Event, Date, Place, Role, Topic, Lesson, Procedure). Specifics belong in
descriptions, not in new types; ten well-used types beat fifty rare ones. When many facts need a
type no basic one fits, `add_entity_type(name, description, parent?, aliases?)`: PascalCase, one
line, with a `parent` so it collapses onto a basic type (`ApiEndpoint` → `Component`).

When the user has an OWL, RDF, Turtle or JSON-LD ontology, read the file with your own tools and pass
its text to `import_ontology(text, name, format?)`. Each class becomes a type, `subClassOf` its
parent, `label` an alias, `comment` the description; parent chains end on a basic type by name
hints or on Concept. Report what was added and where each type landed. Relation names stay
snake_case verb phrases (`works_at`, `depends_on`, `decided_on`); entity names are the most
complete form in the source; dates are `Date` entities written `YYYY-MM-DD`.

## Merging

`remember` merges entities by name. If the result marks an entity `merged: true`, it already
existed; check that your type and description still fit. If a recall shows the same thing under
two spellings, pick the fuller one, re-state the facts against it, and `forget` the duplicate
after confirming with the user.

## Example

User: "We moved auth to JWT last week. Bao owns auth-service now, Linh moved to billing."

From a shell, one fact per command:

```sh
memoose recall "auth JWT auth-service owner"          # reuse names, spot conflicts
memoose remember "auth-service:System --uses--> JWT:Technology" \
  --desc "auth-service authenticates with JWT since 2026-08-30." \
  -e "user said 2026-09-06" --valid-from 2026-08-30
memoose remember "Bao:Person --owns--> auth-service" \
  --desc "Bao owns auth-service as of 2026-09-06." -e "user said 2026-09-06"
memoose remember "Linh:Person --works_on--> billing:Component" \
  --desc "Linh moved from auth to billing in 2026-09." -e "user said 2026-09-06"
```

The same thing in one call, with `source_text` so lexical recall works well — pipe this to
`memoose remember --stdin`, or pass it as the `remember` tool's arguments:

```json
{
  "entities": [
    {
      "name": "auth-service",
      "type": "System",
      "description": "Authentication service of this project."
    },
    {
      "name": "JWT",
      "type": "Technology",
      "description": "JSON Web Tokens, used for auth since 2026-08."
    },
    {
      "name": "Bao",
      "type": "Person",
      "description": "Engineer, owns auth-service."
    },
    {
      "name": "Linh",
      "type": "Person",
      "description": "Engineer, moved to billing."
    },
    {
      "name": "billing",
      "type": "Component",
      "description": "Billing area of the project."
    },
    {
      "name": "2026-08-30",
      "type": "Date",
      "description": "Week auth moved to JWT."
    }
  ],
  "relations": [
    {
      "source": "auth-service",
      "name": "uses",
      "target": "JWT",
      "description": "auth-service authenticates with JWT since 2026-08-30.",
      "evidence": "user said 2026-09-06",
      "valid_from": "2026-08-30"
    },
    {
      "source": "auth-service",
      "name": "migrated_on",
      "target": "2026-08-30",
      "description": "auth-service moved from sessions to JWT around 2026-08-30."
    },
    {
      "source": "Bao",
      "name": "owns",
      "target": "auth-service",
      "description": "Bao owns auth-service as of 2026-09-06.",
      "evidence": "user said 2026-09-06"
    },
    {
      "source": "Linh",
      "name": "works_on",
      "target": "billing",
      "description": "Linh moved from auth to billing in 2026-09.",
      "evidence": "user said 2026-09-06"
    }
  ],
  "summary": "This chunk is about:\n- People: Bao, Linh\n- Systems: auth-service, billing\n- Technologies: JWT\nFacts:\n- auth-service switched to JWT around 2026-08-30.\n- Bao owns auth-service.\n- Linh moved to billing.",
  "source_text": "We moved auth to JWT last week. Bao owns auth-service now, Linh moved to billing."
}
```
