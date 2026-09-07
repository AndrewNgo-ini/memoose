# mnemoth

Memory harness for coding agents. mnemoth adapts the deterministic parts of
[cognee](https://github.com/topoteretes/cognee)'s memory-management logic
(typed knowledge graph, ontology, chunking, hybrid retrieval) and exposes them
as plain MCP tools plus a skill, packaged as an
[Agent Plugin](https://agent-plugins.org/). The library never calls a model:
the host model (Claude Code, Codex, ...) does the thinking while it calls the tools.

No API key. One SQLite file per dataset. Install once, works in any host that speaks
skills + MCP.

**[VISION.md](./VISION.md)** says why this exists and where it is going. `CONTEXT.md` is the
glossary, `docs/adr/` the decisions, `docs/STATE.md` the current state of the work.

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
