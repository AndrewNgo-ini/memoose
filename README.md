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

**Recommendation as a memory.** Reading has the same problem: an agent only recalls when it thinks
to. So mnemoth reads each prompt, searches memory locally, and hands the agent a hint *before* it
starts thinking — what is already known, and the `recall` that would fetch the rest. Pure BM25 over a
local index, so it costs no model call and a few milliseconds, and stays silent when nothing
matches.

**Fast, and cheap by design.** Memory work never blocks your conversation and never runs on the
expensive model. Extraction and maintenance are delegated to a small model in the background, while
retrieval itself takes about 35 ms against a local file.

**Private and inspectable.** One SQLite file per project, plus one for facts about you that hold
everywhere. Open it, copy it, back it up, delete it. Nothing is uploaded.

**Memory that stays true — and a benchmark that proves it.** Facts are typed and carry evidence
pointers, so an agent can re-check where a claim came from. When a fact changes, the old one is
superseded rather than deleted, and history stays queryable. When two sources disagree, the system
says so instead of silently picking one. Those are the claims every memory system makes and none of
them measures, so we wrote the suite that checks them: 18 cases, no model, about a second, running
in CI on every commit ([`benchmarks/maintained/`](./benchmarks/maintained/README.md)). It caught a
real bug in our own supersession on its first run. The knowledge-graph philosophy is adapted from
[cognee](https://github.com/topoteretes/cognee); what is new is that none of it needs a key.

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

## What runs without you asking

| when | what happens | cost |
| --- | --- | --- |
| you submit a prompt | memory is searched locally; a short hint is injected if something matches | ~ms, no model |
| a session starts | standing rules, preferences and recent lessons are put in front of the agent | ~ms, no model |
| a turn ends, or before compaction | a background job on a small model stores what was learned | small model, off your critical path |

Every one of these is a convenience over the tools, never a replacement: on a host without hooks you
lose the automation and keep every capability. Switches are documented in the `mnemoth-onboard`
skill; `MNEMOTH_HINTS=0`, `MNEMOTH_AUTO_RECALL=0` and `MNEMOTH_AUTO_CAPTURE=0` turn the three off.

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
| `mnemoth-onboard` | what is live on this host, what is stored, and how to turn any of it off |
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

Two questions, and it matters which one a number answers.

**Does memory stay true as facts change?** Our own suite, because nothing published asks it:
[`benchmarks/maintained/`](./benchmarks/maintained/README.md) — 18 cases, 66 assertions, **no model,
no API key, ~1 second**, so it runs in CI on every commit. A fact was revised, two sources disagree,
where did this come from, we learned this before. mnemoth scores 18/18; three of the cases are
negative controls that fail if a system over-reacts. Passing our own benchmark proves little, and the
README says so — what it did prove is a real supersession bug it caught at 14/18 on the first run.
The cases are written against behaviour any memory system could implement, so port them and use them
against us.

```sh
uv run python benchmarks/maintained/run_maintained.py    # ~1 s, no key
```

**Can you find a fact that was stated once?** LoCoMo, under mem0's protocol with their answerer and
judge prompts vendored verbatim, host model via Claude Code. On a 160-question stratified sample:
**91.9** (95% CI 86.6–95.2) against mem0's published **92.5**, using **4,728 prompt tokens vs their
6,956** and a much smaller answerer (Claude Haiku 4.5). Retrieval takes 35 ms against a local SQLite
file. That is parity, not a win.

Two LoCoMo results worth stating plainly: the knowledge graph does *not* beat plain chunk retrieval
there (paired McNemar p = 1.00) at 77% more tokens, and raising the retrieval budget lifts evidence
recall without lifting the judged score. LoCoMo asks needle questions over conversations that fit in
a context window, so it does not test what the graph is for — which is why `maintained/` exists. See
`benchmarks/locomo/RESULTS.md` for the tables, `benchmarks/SETUP.md` to reproduce, and
`docs/STATE.md` for where the work stands.

## Develop

```sh
uv sync --extra fastembed --group dev
uv run pytest                                            # 73 tests, includes the maintained-memory suite
claude plugin validate .
```
