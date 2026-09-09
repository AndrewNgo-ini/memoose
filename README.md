<div align="center">

<img src="assets/memoose-mascot.png" alt="the Memoose mascot" width="220">

# Memoose: Memory for Coding Agents

<p><i>Typed knowledge graph &nbsp;•&nbsp; One local SQLite file &nbsp;•&nbsp; No API key &nbsp;•&nbsp; Works across Claude Code, Codex, opencode and Cursor</i></p>

```sh
uv run memoose install claude      # or: codex | opencode | cursor
```

</div>

---

# What is Memoose

**Memoose** gives a coding agent memory that survives the session — and survives switching agents.
It is two parts: an **engine** that stores, indexes and retrieves a typed knowledge graph in one
SQLite file on your machine, and a **harness** — skills, MCP tools, rules and hooks — that teaches
the model your host is already running how to use it.

It is built for long-lived project work: the decisions, conventions and ownership facts that have to
stay correct for months, each carrying an evidence pointer back to where it came from.

### Vision

**Memory is upkeep, not storage.** A house stays livable two ways: you put things where they belong
as you use them, and you clean periodically. Memory does both. As you work, facts are written when
they surface — commands the model runs and hooks that capture a turn without being asked. Then
`memoose maintain` sweeps the store and returns one worklist: contradictions to judge, duplicates to
merge, finished sessions to distil, summaries to rewrite. It decides nothing itself; the engine
proposes and a model disposes. On hosts with hooks the pass is offered once a day at session start
(`MEMOOSE_AUTO_MAINTAIN=0` to stop that), and you do not do the cleaning yourself: it goes to the
[`memory-keeper`](./agents/memory-keeper.md) subagent on a small model, so upkeep costs neither your
attention nor the main conversation's turns.

**Search and recommendation are the two ways anything gets found.** Search answers a question you
thought to ask. Recommendation puts something in front of you that you did not. A memory system that
only does search is only half of one — it works when the agent already suspects there is something to
recall, and stays silent every other time. Memoose does both: `recall` for the asked question, and a
hint injected before the prompt for the unasked one.

Longer form in the docs: [Vision](./docs/site/vision.html).

### Features

- **A knowledge graph with an ontology.** Typed entities and facts rather than text blobs, each fact
  carrying a validity date and an evidence pointer; import OWL/RDF/Turtle or extend the types
  in place. → [Tools](./docs/site/tools.html)
- **Recommendation, not only search.** `recall` answers the question the agent thought to ask; a hint
  before each prompt covers the ones it did not. → [Automatic memory](./docs/site/automatic.html)
- **Two ways in, one store.** A CLI the agent runs like any other command — `memoose recall "who owns
  billing"` — and 24 MCP tools for hosts where the shell is restricted. The CLI is the default: the MCP
  server's schemas measure ~4,250 tokens resident every turn, a command costs nothing until it runs.
  → [Tools](./docs/site/tools.html)
- **Local, one file per project.** One SQLite file, no service, no API key, nothing leaving the
  machine — inspect it, copy it, delete it. Measured room to roughly a million rows per project
  before anything needs rethinking. → [Configuration](./docs/site/configuration.html)

Changes stay visible rather than being overwritten, disagreements are reported rather than resolved,
and sessions distill into lessons: [Evidence & history](./docs/site/trust.html).

# Getting Started

### Install

Memoose is not on PyPI yet, so install from a checkout:

```sh
git clone https://github.com/AndrewNgo-ini/mnemoth.git && cd mnemoth && uv sync
uv run memoose install claude               # or: codex | opencode | cursor
uv run memoose status                       # what is installed where
```

`install` writes one MCP server entry into the host's own config and copies the skills into its
skills directory. `uninstall <host>` reverses both.

<details>
<summary><b><i>Other install options:</i></b></summary>
<br>

```sh
uv run memoose install claude --project .           # this project only, instead of user scope
uv run memoose install claude --command "uvx memoose serve"   # override the server command
claude --plugin-dir .                               # Claude Code: load skills, hooks and server from the checkout
uv sync --extra fastembed                           # local embeddings (a keyless hashed fallback is used otherwise)
uv sync --extra ontology                            # full RDF parsing
```

</details>

### Where memory lives

`~/.memoose/<dataset>.sqlite`, overridable with `MEMOOSE_DATA_DIR`. One dataset per project, plus a
`user` dataset for facts that hold everywhere; `recall` searches the project dataset first and
reserves room for user-scoped results.

> Upgrading from mnemoth: `MNEMOTH_*` variables are still read, an existing `~/.mnemoth` store is
> reused, and `install` clears the pre-rename MCP entry so a host never runs both servers.

### Onboarding

Memoose cannot see how your machine is configured, so ask your agent to onboard it. The
[`memoose-onboard`](./skills/memoose-onboard/SKILL.md) skill walks through what is reachable on this
host, which automatic parts are live, what is stored, how to inspect it (`recall`, `history`) or
remove it (`forget`), where the switches are, and how to seed the first memories.

# How Memoose Works

### The two layers

| layer | what it is | who runs it |
| --- | --- | --- |
| Engine | a SQLite knowledge graph — entities, facts, chunks, sessions, provenance — behind 24 MCP tools | Memoose, deterministically, with no model |
| Harness | skills, rules and hooks: when to recall, how to extract entities and evidence, how to judge a contradiction | the model your host is already running |

Because judgment lives in the harness, memory work can be delegated: the skills route bookkeeping to
the [`memory-keeper`](./agents/memory-keeper.md) subagent on a small model, so it does not spend the
main conversation's turns. That path needs no hooks and works on any MCP host.

### What gets stored

When the model calls `remember`, it writes entities resolved against the ontology and facts between
them. Each fact carries a one-sentence description, an optional `valid_from`, and an evidence
pointer — a file range, a URL, an issue id, or "user said &lt;date&gt;". A rejected write comes back
with a message written for the model: which type to use, which relation name.

<a id="what-runs-without-you-asking"></a>

### What runs without you asking

On hosts that run plugin hooks, memory does not wait to be asked
([ADR 0003](./docs/adr/0003-proactive-background-memory.md)):

| when | what happens | cost |
| --- | --- | --- |
| a prompt is submitted, before the agent processes it | memory is searched locally and a short hint is injected when something matches | milliseconds, no model call |
| a session starts | standing rules, preferences and recent lessons are put in front of the agent | milliseconds, no model call |
| a turn ends, or before compaction | a background job on a small model stores what the turn taught, writing through the CLI | small model, off your critical path |
| a session starts, at most once a day | the upkeep pass is offered when the store has work waiting | milliseconds, no model call |

The hint is a BM25 lookup with a relevance floor and a cap on how much it injects; it stays silent
when nothing matches, and the agent is free to ignore it. Hooks are host-specific — they ship as a
Claude Code plugin manifest today — and add no capability the tools do not already have, so on other
hosts you keep everything through the tools, the skills and the delegated subagent. Every hook exits
0 on failure.

Switches, all on by default: `MEMOOSE_HINTS=0`, `MEMOOSE_AUTO_RECALL=0`, `MEMOOSE_AUTO_CAPTURE=0`,
`MEMOOSE_AUTO_MAINTAIN=0` (and `MEMOOSE_MAINTAIN_EVERY_HOURS` to re-pace the last one).

# Usage

### Tools

24 MCP tools. Every capability is reachable through a tool call on any MCP host.

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

### CLI

Memory operations, the same ones the MCP tools expose:

| command | what it does |
| --- | --- |
| <code>memoose&nbsp;recall&nbsp;"who owns billing"</code> | search memory; `--mode`, `--limit`, `--superseded`, `--json` |
| <code>memoose&nbsp;remember&nbsp;"bao:Person --owns--> auth:System"</code> | store a fact; `--desc`, `-e/--evidence`, `--valid-from`, `--stdin` for a JSON batch |
| <code>memoose&nbsp;history&nbsp;auth-service</code> | the provenance ledger for an entity or a fact |
| <code>memoose&nbsp;contradictions&nbsp;[names]</code> | hotspots and open contradictions to judge |
| `memoose ontology` · `memoose datasets` · `memoose context` | entity types and stats · memory scopes · global context |
| <code>memoose&nbsp;session&nbsp;start\|turn\|context\|timeline\|lessons\|end</code> | session lifecycle |
| `memoose maintain` | the periodic pass: everything that needs judging, in one worklist |
| <code>memoose&nbsp;forget&nbsp;--entity&nbsp;X</code> | delete an entity, a fact, a session, or a dataset |
| <code>memoose&nbsp;tool&nbsp;&lt;name&gt;&nbsp;--stdin</code> | any remaining tool, arguments as JSON on stdin |

Output is compact text; `--json` gives the exact MCP payload, and anything over `--max-inline`
(2000 chars) is written to a file whose path is printed. Setup:

| command | what it does |
| --- | --- |
| `memoose serve` | run the stdio MCP server (what a host launches) |
| <code>memoose&nbsp;install&nbsp;&lt;host&gt;</code> | write the MCP entry and copy the skills (`--project`, `--command`) |
| <code>memoose&nbsp;uninstall&nbsp;&lt;host&gt;</code> | remove both |
| `memoose status` | what is installed where, and the CLI invocation for this machine |

# Benchmarks

Memoose has no model of its own, so what it scores is inseparable from the model driving it. That is
the design, not a caveat: the library holds only what is deterministic, and every judgment runs on
the host's model, with bookkeeping delegated to a small one. So the number we report is the one that
matches how Memoose is meant to run — **a small, fast model throughout**.

LoCoMo is the standard benchmark for conversational memory: long multi-session conversations, then
questions about what was said. A model answers from whatever the memory system retrieves, and a
second model grades the answer. Run under mem0's protocol with their answerer and judge prompts
verbatim, so the memory system is the only thing that differs.

### Our run — a sanity check on a lightweight model

Not a competitive entry. It exists so there is a real, reproducible number attached to Memoose
running the way it is designed to run: **Claude Haiku 4.5** as both answerer and judge, on the full
benchmark.

**90.4% correct** across all 1,540 questions, at **4,699 mean prompt tokens** ($88.55, September
2026).

| category | questions | score |
| --- | --- | --- |
| single-hop | 841 | 93.5 |
| temporal | 321 | 89.7 |
| multi-hop | 282 | 88.7 |
| open-domain | 96 | 70.8 |

Open-domain is the weak category: those golds are single turns holding a name or a place that never
reach the retrieved context.

### For reference — what others report

Every figure below is **self-reported by its vendor**, on a different model stack, judge and
retrieval configuration. They are not comparable with each other or with ours; they are here so the
number above has context.

| system | reported | notes |
| --- | --- | --- |
| ZeroMemory | 96.1 | unverified |
| Zep | 94.7 | third-party testing found 75.1 on the same benchmark |
| ByteRover | 92.2 / 96.1 | two conflicting figures published |
| mem0 | 92.5 | single-hop 94.6, multi-hop 95.4, temporal 92.5, open-domain 82.3; 6,956 prompt tokens |
| **Memoose (Haiku 4.5)** | **90.4** | the run above — full 1,540 questions, per-category, CI, cost and raw rows all published |
| Dakera | 88.2 | no LLM reranking |
| full context, no memory | ~73 | the whole conversation in the prompt |

Against the one entry with a published per-category breakdown, mem0, we are behind everywhere —
most of all on multi-hop (−6.7) and open-domain (−11.5) — and ahead only on cost, at a third fewer
prompt tokens with a much smaller answerer. Swapping the answerer moves a score more than swapping
the memory system does, and most vendors above do not disclose theirs, so treat the ordering as
noise rather than a ranking.

Two findings from those runs that cut against us, published anyway: the knowledge graph does **not**
beat plain chunk retrieval on LoCoMo (paired McNemar p = 1.00) and costs 77% more tokens, and raising
the retrieval budget does not lift the score. LoCoMo asks needle questions over conversations that
fit in a context window, so it does not test what a graph is for.

Protocol, full tables, what other systems report, and the raw per-question rows are in
**[`benchmarks/`](./benchmarks/README.md)**; setup and the operational traps are in
[`benchmarks/SETUP.md`](./benchmarks/SETUP.md).

# Learn More

### Docs

The [documentation site](./docs/site/index.html) is the place to read about Memoose:
[Vision](./docs/site/vision.html) · [Install](./docs/site/install.html) ·
[Tools](./docs/site/tools.html) · [Skills](./docs/site/skills.html) ·
[Automatic memory](./docs/site/automatic.html) ·
[Configuration](./docs/site/configuration.html) ·
[Evidence & history](./docs/site/trust.html)

For contributors, the repository also carries [CONTEXT.md](./CONTEXT.md) (glossary),
[docs/adr/](./docs/adr/) (decision records) and [docs/STATE.md](./docs/STATE.md) (what is done, what
the benchmarks established).

### Roadmap

- [x] cognee's memory core as MCP tools plus skills, no model in the library
- [x] Proactive hints, session-start context and background capture on hosts with hooks
- [x] A CLI for the memory operations, alongside the MCP tools
- [x] Background capture writes through the CLI, not a per-capture MCP server
- [x] The periodic pass: `memoose maintain`, offered daily on hosts with hooks
- [ ] **Propose an eval for maintained memory.** No published benchmark asks whether a body of facts
  stays trustworthy as it changes — a fact was revised, two sources disagree, where did this come
  from. An eval only its author runs is not evidence, so this needs a design other systems can run
  before any number from it is worth publishing.
- [ ] **A token-cost benchmark.** Accuracy is reported everywhere and cost almost nowhere, though it
  is what a memory system actually charges you per turn. No comparable methodology across systems
  exists yet.
- [ ] An ANN index, if a project ever passes ~200k vectors (SQLite itself has room well past that)
- [ ] Publish to PyPI so `uvx memoose` works without a checkout
- [ ] Exercise the delegated subagent path live on a host without hooks
- [ ] A live run of `maintain` end to end, the way capture was verified
- [ ] Migration from a pre-rename `~/.mnemoth` store

### Inspiration

- **[cognee](https://github.com/topoteretes/cognee)** (Apache 2.0) — the memory philosophy and the
  most direct debt: typed graph, ontology-constrained extraction, deterministic ids, hybrid
  retrieval, datasets as scope, contradictions and supersession. The extraction and contradiction
  guidance in the skills is adapted from cognee's prompt templates; where cognee calls a model,
  Memoose has a skill.
- **[OpenWiki](https://github.com/langchain-ai/openwiki)** — grounded claims, so every fact carries a
  checkable evidence pointer; and the integration layer `memoose install <host>` mirrors.
- **[obsidian-skills](https://github.com/kepano/obsidian-skills)** — the skill packaging discipline:
  single-purpose, portable, concrete rules rather than vague guidance.
- **[mem0](https://github.com/mem0ai/mem0)** — the LoCoMo protocol we measure against; their answerer
  and judge prompts are vendored verbatim from
  [mem0ai/memory-benchmarks](https://github.com/mem0ai/memory-benchmarks).
- **[Chonkie](https://github.com/chonkie-inc/chonkie)** — the mascot.

[docs/inspirations.md](./docs/inspirations.md) records what was borrowed and what was not.

### Contributing

Pull requests and [issues](https://github.com/AndrewNgo-ini/mnemoth/issues) are welcome. For larger
changes, open an issue first to discuss the approach. Run the suite with `uv run pytest`.

### License

Apache 2.0. See [LICENSE](./LICENSE) and [NOTICE.md](./NOTICE.md).
