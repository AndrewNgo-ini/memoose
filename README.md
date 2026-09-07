# mnemoth

**Persistent memory for coding agents. No API key. Nothing leaves your machine.**

Your agent forgets everything between sessions, and every fix for that costs you a second LLM
subscription, ships your project's context to someone else's server, or only works in one tool.
mnemoth is memory that runs on the model your agent is *already paying for*, stores everything in a
single SQLite file on your disk, and installs the same way into Claude Code, Codex, OpenCode, and
Cursor.

```sh
mnemoth install claude      # or: codex | opencode | cursor
```

## Why it is different

**No API key, ever.** Not a fallback, not an optional path. mnemoth's library contains no code that
calls a model. The thinking is written down as skills and done by the model your host is already
running, so there is no second inference bill and no second vendor.

**Seamless, not another chore.** Memory that waits to be asked is memory that never gets written: the
agent is busy with your actual task, so bookkeeping is the first thing dropped. mnemoth captures on
its own through host hooks, and where hooks do not exist its skills tell the agent to hand the work
to a background subagent.

**Fast, and cheap by design.** Memory work never blocks your conversation and never runs on the
expensive model. Extraction and maintenance are delegated to a small model in the background, while
retrieval itself takes about 35 ms against a local file.

**Private and inspectable.** One SQLite file per project, plus one for facts about you that hold
everywhere. Open it, copy it, back it up, delete it. Nothing is uploaded.

**Memory that stays true.** Facts are typed and carry evidence pointers, so an agent can re-check
where a claim came from. When a fact changes, the old one is superseded rather than deleted, and
history stays queryable. When two sources disagree, the system says so instead of silently picking
one. The knowledge-graph philosophy is adapted from [cognee](https://github.com/topoteretes/cognee);
what is new is that none of it needs a key.

**[VISION.md](./VISION.md)** explains the bet in full. `CONTEXT.md` is the glossary, `docs/adr/` the
decisions, `docs/STATE.md` the current state of the work.

## Install

From a source checkout (until the package is on PyPI):

```sh
uv run mnemoth install claude      # or: codex | opencode | cursor
uv run mnemoth install claude --project .   # project scope instead of user scope
uv run mnemoth status
```

`install` writes one MCP server entry into the host's own config and copies the
`mnemoth` skill into the host's skills directory. Nothing else is touched.

Or load it as a plugin directly in Claude Code:

```sh
claude --plugin-dir /path/to/mnemoth
```

## Tools

| area | tools |
| --- | --- |
| ontology | `describe_ontology`, `add_entity_type`, `import_ontology` (OWL/RDF/Turtle), `declare_functional_relations` |
| write | `remember`, `mark_contradiction`, `supersede`, `merge_entities`, `cross_connect`, `set_bucket_summary`, `forget` |
| read | `recall` (modes: hybrid, facts, neighbourhood, lexical, summaries, temporal, rules, session), `contradiction_candidates`, `history`, `memify_candidates`, `global_context`, `list_datasets` |
| sessions | `session_start`, `session_add_turn`, `session_set_context`, `session_get`, `session_timeline`, `publish_lessons`, `session_end` |

## Skills

| skill | teaches the host model |
| --- | --- |
| `mnemoth` | when to recall, how to extract entities, relations, evidence, summaries (cognee's extraction rules) |
| `mnemoth-contradictions` | judging hotspots, supersede vs mark_contradiction, functional relations |
| `mnemoth-sessions` | context sections during work, curator and writer rules for distilling lessons |
| `mnemoth-memify` | cross-connect, consolidate, global-context summaries, feedback weights |
| `mnemoth-ontology` | extending and importing ontologies, declaring functional relations |

## What is ported from cognee

Typed graph with deterministic entity ids, ontology-constrained extraction with OWL import,
chunk + summary retrieval material, hybrid retrieval (lexical + vector, reciprocal rank
fusion) over chunk, entity, and fact channels, the regex query router, contradiction detection
as candidate facts around touched nodes with `contradicts` edges, temporal supersession for
functional relations, an append-only provenance ledger, sessions with a fast cache and typed
context sections, session distillation into lessons, memify passes (cross-connect,
consolidate, frequency and feedback weights, global context buckets), datasets with a
project-then-user merge and reserve. Every step that called a model in cognee is a skill
instruction here. See `docs/plan.md` and `docs/inspirations.md`.

Data lives in `~/.mnemoth/<dataset>.sqlite` (override with `MNEMOTH_DATA_DIR`). The default
dataset is derived from the directory the host launched the server in; `user` is the
cross-project dataset. Embeddings use `fastembed` when the extra is installed and a keyless
hashed fallback otherwise (`MNEMOTH_EMBEDDER=hash|fastembed|auto`). Install the `ontology`
extra for full RDF parsing; a Turtle/RDF-XML fallback parser is built in.

## Benchmarks

LoCoMo, under mem0's protocol with their answerer and judge prompts vendored verbatim, host model
via Claude Code. On a 160-question stratified sample: **91.9** (95% CI 86.6–95.2) against mem0's
published **92.5**, using **4,728 prompt tokens vs their 6,956** and a much smaller answerer
(Claude Haiku 4.5). Retrieval takes 35 ms against a local SQLite file.

Two results worth stating plainly: the knowledge graph does *not* beat plain chunk retrieval on
LoCoMo (paired McNemar p = 1.00) at 77% more tokens, and raising the retrieval budget lifts evidence
recall without lifting the judged score. LoCoMo asks needle questions over conversations that fit in
a context window, so it does not test what the graph is for. See `benchmarks/locomo/RESULTS.md` for
the tables, `benchmarks/SETUP.md` to reproduce, and `docs/STATE.md` for where the work stands.

## Develop

```sh
uv sync --group dev
uv run pytest
claude plugin validate .
```
