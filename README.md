<p align="center"><img src="assets/memoose-mascot.png" alt="the Memoose mascot" width="240"></p>
<h1 align="center">Memoose</h1>
<p align="center"><b>A memory harness for coding agents.</b><br>
Pick up where you left off — in whichever agent you open tomorrow.</p>

```sh
uv run memoose install claude      # or: codex | opencode | cursor
```

## Overview

You explained the architecture, the conventions, and the reason behind last week's decision. Memoose is
how your agent still knows them today — a harness rather than a database: a deterministic store reached
through MCP tools, plus skills that teach the model you are already running how to use it. The judgment
(what counts as an entity, which facts conflict, what a session taught) lives in the skills and runs on
the host's model, so Memoose ships no model of its own and needs no API key
([ADR 0001](./docs/adr/0001-skills-and-mcp-only.md)). Your memory is a typed knowledge graph in one
SQLite file on your machine; recalled facts become context for your host's model, the same as anything
else it reads. It is built for long-lived project work — the decisions, conventions and ownership facts
that have to stay true for months, each able to carry an evidence pointer back to where it came from.
The core is portable, being skills plus an MCP server on any host that speaks MCP; the capture and
recall that happen without you asking sit on top of it and depend on what your host supports.

## Install

Memoose is not on PyPI yet, so install from a checkout:

```sh
git clone https://github.com/AndrewNgo-ini/mnemoth.git && cd mnemoth && uv sync
uv run memoose install claude               # or: codex | opencode | cursor
uv run memoose install claude --project .   # this project only, instead of user scope
uv run memoose status                       # what is installed where
```

`install` writes one MCP server entry into the host's own config and copies the skills into its skills
directory; `uninstall` reverses both. In Claude Code, `claude --plugin-dir .` loads the whole plugin —
skills, hooks and server — straight from the checkout. Extras: `--extra fastembed` for local embeddings
(a keyless hashed fallback is used otherwise), `--extra ontology` for full RDF parsing. Memory lives in
`~/.memoose/<dataset>.sqlite` (`MEMOOSE_DATA_DIR` overrides it): one dataset per project, plus a `user`
dataset for facts that hold everywhere. Upgrading from mnemoth — `MNEMOTH_*` is still read and an
existing `~/.mnemoth` is reused.

## Features

**Facts, not blobs.** `alice --owns--> billing-service` is a typed fact with a validity date and an
evidence pointer like `repo://src/auth.py#L40-L82`, so a later run can re-check where it came from.

**History stays queryable, disagreement stays visible.** Declare a relation functional and a new value
supersedes the old one instead of erasing it; conflicting facts come back as candidates with a
`contradicts` edge, for the model to judge rather than the store to guess. A model-free suite of 18
cases asserts exactly this on what the tools return, in about a second
([`benchmarks/maintained/`](./benchmarks/maintained/README.md)).

**Retrieval that routes itself.** `recall` picks one of eight modes from the shape of the query, over
chunks, entities and facts, merging lexical and vector channels against the local file. Bring your own
ontology if you have one: import OWL/RDF/Turtle, add entity types, declare functional relations.

**Sessions become lessons.** Turns and typed context sections (goals, rules, preferences) distill into
durable lessons that join the graph, so the next session starts with what the last one learned.

### Tools

24 MCP tools; every capability is reachable through a tool call on any MCP host. A rejected write comes
back with a message written for the model: which type to use, which relation name.

| area | tools |
| --- | --- |
| ontology | `describe_ontology`, `add_entity_type`, `import_ontology` (OWL/RDF/Turtle), `declare_functional_relations` |
| write | `remember`, `mark_contradiction`, `supersede`, `merge_entities`, `cross_connect`, `set_bucket_summary`, `forget` |
| read | `recall` (hybrid, facts, neighbourhood, lexical, summaries, temporal, rules, session), `contradiction_candidates`, `history`, `memify_candidates`, `global_context`, `list_datasets` |
| sessions | `session_start`, `session_add_turn`, `session_set_context`, `session_get`, `session_timeline`, `publish_lessons`, `session_end` |

### Skills

| skill | teaches the host model |
| --- | --- |
| [`memoose`](./skills/memoose/SKILL.md) | when to recall, how to extract entities, relations, evidence and summaries |
| [`memoose-onboard`](./skills/memoose-onboard/SKILL.md) | what is live on this host, what is stored, how to turn any of it off |
| [`memoose-sessions`](./skills/memoose-sessions/SKILL.md) | context sections during work, curator and writer rules for lessons |
| [`memoose-contradictions`](./skills/memoose-contradictions/SKILL.md) | judging hotspots, supersede vs `mark_contradiction`, functional relations |
| [`memoose-memify`](./skills/memoose-memify/SKILL.md) | cross-connect, consolidate, global-context summaries, feedback weights |
| [`memoose-ontology`](./skills/memoose-ontology/SKILL.md) | extending and importing ontologies, declaring functional relations |

They also route memory work to the [`memory-keeper`](./agents/memory-keeper.md) subagent on a small
model, so bookkeeping does not spend the main conversation's turns — a path that needs no hooks.

### Onboarding

Memoose cannot see how your machine is configured, so ask your agent to onboard it:
[`memoose-onboard`](./skills/memoose-onboard/SKILL.md) walks through what is reachable, which automatic
parts are live here, what is stored and how to inspect (`recall`, `history`) or remove (`forget`) it,
the switches, and seeding the first memories.

### What runs without you asking

On hosts that run plugin hooks, memory does not wait to be asked:

| when | what happens | cost |
| --- | --- | --- |
| a prompt is submitted, before the agent processes it | memory is searched locally and a short hint is injected when something matches | milliseconds, no model call |
| a session starts | standing rules, preferences and recent lessons are put in front of the agent | milliseconds, no model call |
| a turn ends, or before compaction | a background job on a small model stores what the turn taught | small model, off your critical path |

The hint is deliberately dumb and therefore cheap: BM25 over the local index, a relevance floor, a cap
on how much it injects, silence when nothing matches; the agent stays free to ignore it. Hooks are
host-specific — they ship as a Claude Code plugin manifest today — and add no capability the
tools do not already have, so elsewhere you keep everything through the tools, the skills and the
delegated subagent; how much the automatic parts get right depends on the host's model following a
skill. Switches, all on by default: `MEMOOSE_HINTS=0`, `MEMOOSE_AUTO_RECALL=0`, `MEMOOSE_AUTO_CAPTURE=0`.

## Docs

[Documentation site](./docs/site/index.html) · [CONTEXT.md](./CONTEXT.md) (glossary) ·
[docs/adr/](./docs/adr/) · [docs/STATE.md](./docs/STATE.md) · [benchmarks/](./benchmarks/README.md)

## Inspiration

- **[cognee](https://github.com/topoteretes/cognee)** (Apache 2.0) — the memory philosophy and the most
  direct debt: typed graph, ontology-constrained extraction, deterministic ids, hybrid retrieval,
  datasets as scope, contradictions and supersession. The extraction and contradiction guidance in the
  skills is adapted from cognee's prompt templates; where cognee calls a model, Memoose has a skill.
- **[OpenWiki](https://github.com/langchain-ai/openwiki)** — grounded claims, so every fact carries a
  checkable evidence pointer; and the integration layer `memoose install <host>` mirrors.
- **[obsidian-skills](https://github.com/kepano/obsidian-skills)** — the skill packaging discipline:
  single-purpose, portable, concrete rules rather than vague guidance.
- **[mem0](https://github.com/mem0ai/mem0)** — the LoCoMo protocol we measure against; their answerer
  and judge prompts are vendored verbatim from [mem0ai/memory-benchmarks](https://github.com/mem0ai/memory-benchmarks).
- **[Chonkie](https://github.com/chonkie-inc/chonkie)** — the reason this README has a mascot at all.

[docs/inspirations.md](./docs/inspirations.md) records what was borrowed and what was not.
Apache 2.0 — see [LICENSE](./LICENSE) and [NOTICE.md](./NOTICE.md).
