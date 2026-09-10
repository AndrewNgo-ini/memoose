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

**Memoose** gives a coding agent memory that survives the session, and survives switching agents.
It is two parts. An **engine** stores, indexes and retrieves a typed knowledge graph in one SQLite
file on your machine. A **harness** of skills, MCP tools, rules and hooks teaches the model your
host is already running how to use it.

It is built for long-lived project work: the decisions, conventions and ownership facts that have to
stay correct for months, each carrying an evidence pointer back to where it came from.

### Vision

**Memory is upkeep.** A house stays livable two ways: you put things where they belong as you use
them, and you clean periodically. Memory works the same. As you work, facts are written when they
surface, through commands the model runs and hooks that capture a turn without being asked. Then
`memoose maintain` sweeps the store and returns one worklist: contradictions to judge, duplicates to
merge, finished sessions to distil, summaries to rewrite. The pass gathers the work and judges none
of it; a model makes every call. On hosts with hooks it is offered once a day at session start
(`MEMOOSE_AUTO_MAINTAIN=0` stops that), and you do not do the cleaning yourself. It goes to the
[`memory-keeper`](./agents/memory-keeper.md) subagent on a small model, so upkeep costs neither your
attention nor the main conversation's turns.

**Search and recommendation are the two ways anything gets found.** Search answers a question you
thought to ask. Recommendation puts something in front of you that you did not. A memory system with
only search works when the agent already suspects there is something to recall, and stays silent
every other time. Memoose does both: `recall` for the asked question, and a hint injected before the
prompt for the unasked one.

Longer form in the docs: [Vision](./docs/site/vision.html).

### Features

- **A knowledge graph with an ontology.** Typed entities and facts instead of text blobs, each fact
  carrying a validity date and an evidence pointer. Import OWL/RDF/Turtle, or extend the types in
  place. See [Tools](./docs/site/tools.html).
- **Recommendation as well as search.** `recall` answers the question the agent thought to ask; a
  hint before each prompt covers the ones it did not. See
  [Automatic memory](./docs/site/automatic.html).
- **Two ways in, one store.** A CLI the agent runs like any other command,
  `memoose recall "who owns billing"`, and 25 MCP tools for hosts where the shell is restricted. The
  CLI is the default: the MCP server's schemas measure about 4,250 tokens resident every turn, while
  a command costs nothing until it runs. See [Tools](./docs/site/tools.html).
- **Local, one file per project.** One SQLite file, no service, no API key, nothing leaving the
  machine. Inspect it, copy it, delete it. Measured room to roughly a million rows per project
  before anything needs rethinking. See [Configuration](./docs/site/configuration.html).

Changes stay visible instead of being overwritten, disagreements are reported for a model to judge,
and sessions distil into lessons. See [Evidence & history](./docs/site/trust.html).

# Getting started

### Install

Memoose is not on PyPI yet, so install from a checkout:

```sh
git clone https://github.com/AndrewNgo-ini/mnemoth.git && cd mnemoth && uv sync
uv run memoose install claude               # or: codex | opencode | cursor
uv run memoose status                       # what is installed where
```

`install` writes one MCP server entry into the host's own config and copies the skills into its
skills directory. `uninstall <host>` reverses both.

On Claude Code, install the checkout as a plugin instead: it is the only route that also loads the
hooks (hints before a prompt, capture after a turn, the daily upkeep offer), and it keeps one copy
of everything.

```sh
claude plugin marketplace add /path/to/mnemoth     # the checkout is its own marketplace
claude plugin install memoose@memoose
# then restart Claude Code; after code changes, bump the version and `claude plugin update memoose@memoose`
```

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
`user` dataset for facts that hold everywhere. `recall` searches the project dataset first and
reserves room for user-scoped results.

> Upgrading from mnemoth: `MNEMOTH_*` variables are still read, an existing `~/.mnemoth` store is
> reused, and `install` clears the pre-rename MCP entry so a host never runs both servers.

### Onboarding

Memoose cannot see how your machine is configured, so ask your agent to onboard it. The
[`memoose-onboard`](./skills/memoose-onboard/SKILL.md) skill walks through what is reachable on this
host, which automatic parts are live, what is stored, how to inspect it (`recall`, `history`) or
remove it (`forget`), where the switches are, and how to seed the first memories.

# How Memoose works

### The two layers

| layer | what it is | who runs it |
| --- | --- | --- |
| Engine | a SQLite knowledge graph (entities, facts, chunks, sessions, provenance) behind 25 MCP tools | Memoose, deterministically, with no model |
| Harness | skills, rules and hooks: when to recall, how to extract entities and evidence, how to judge a contradiction | the model your host is already running |

Because judgment lives in the harness, memory work can be delegated. The skills route bookkeeping to
the [`memory-keeper`](./agents/memory-keeper.md) subagent on a small model, so it does not spend the
main conversation's turns. That path needs no hooks and works on any MCP host.

### What gets stored

When the model calls `remember`, it writes entities resolved against the ontology and facts between
them. Each fact carries a one-sentence description, an optional `valid_from`, and an evidence
pointer: a file range, a URL, an issue id, or "user said &lt;date&gt;". A rejected write comes back
with a message written for the model, saying which type to use and which relation name.

<a id="what-runs-without-you-asking"></a>

### What runs without you asking

On hosts that run plugin hooks, memory does not wait to be asked
([ADR 0003](./docs/adr/0003-proactive-background-memory.md)):

| when | what happens | cost |
| --- | --- | --- |
| a prompt is submitted, before the agent processes it | the agent's last tool call is matched to a stored procedure and its next steps are injected; then memory is searched for the prompt and a short hint is injected when something matches | milliseconds, no model call |
| a session starts | standing rules, preferences and recent lessons are put in front of the agent | milliseconds, no model call |
| a turn ends, or before compaction | a background job on a small model stores what the turn taught, writing through the CLI | small model, off your critical path |
| a session starts, at most once a day | the upkeep pass is offered when the store has work waiting | milliseconds, no model call |

The procedural part follows the Procedural Graphs paper (Lu et al., 2026): a `Procedure` entity
whose name reads like the command the agent just ran, and its outgoing transitions two hops out,
grouped by hop. The hint is a BM25 lookup with a relevance floor and a cap on how much it injects.
Both stay silent when nothing matches, and the agent is free to ignore them. Hooks are host-specific, shipping as a
Claude Code plugin manifest today, and they add no capability the tools do not already have. On
other hosts you keep everything through the tools, the skills and the delegated subagent. Every hook
exits 0 on failure.

Switches, all on by default: `MEMOOSE_HINTS=0`, `MEMOOSE_AUTO_RECALL=0`, `MEMOOSE_AUTO_CAPTURE=0`,
`MEMOOSE_AUTO_MAINTAIN=0` (and `MEMOOSE_MAINTAIN_EVERY_HOURS` to re-pace the last one).

# Usage

### Tools

25 MCP tools. Every capability is reachable through a tool call on any MCP host.

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
| <code>memoose&nbsp;dismiss&nbsp;&lt;key&gt;&nbsp;--reason&nbsp;"..."</code> | decline a candidate from that worklist so it is not proposed again |
| `memoose view` | open the knowledge graph in your browser: one self-contained HTML file, nothing uploaded (`--superseded` draws history dashed) |
| <code>memoose&nbsp;forget&nbsp;--entity&nbsp;X</code> | delete an entity, a fact, a session, or a dataset |
| <code>memoose&nbsp;tool&nbsp;&lt;name&gt;&nbsp;--stdin</code> | any remaining tool, arguments as JSON on stdin |

Output is compact text, and text over `--max-inline` (2000 chars) is written to a file whose path is
printed. `--json` gives the exact MCP payload in full, never spilled. Setup:

| command | what it does |
| --- | --- |
| `memoose serve` | run the stdio MCP server (what a host launches) |
| <code>memoose&nbsp;install&nbsp;&lt;host&gt;</code> | write the MCP entry and copy the skills (`--project`, `--command`) |
| <code>memoose&nbsp;uninstall&nbsp;&lt;host&gt;</code> | remove both |
| `memoose status` | what is installed where, and the CLI invocation for this machine |

# Benchmarks

Memoose has no model of its own, so what it scores is inseparable from the model driving it. The
library holds only what is deterministic, every judgment runs on the host's model, and bookkeeping
goes to a small one. So the number we report is the one that matches how Memoose is meant to run: a
small, fast model throughout.

LoCoMo is the standard benchmark for conversational memory. It gives long multi-session
conversations, then asks questions about what was said. A model answers from whatever the memory
system retrieves, and a second model grades the answer. We run it under mem0's protocol with their
answerer and judge prompts verbatim, so the memory system is the only thing that differs.

### Our run, a sanity check on a lightweight model

This is a reference point rather than a competitive entry. It exists so there is a real,
reproducible number attached to Memoose running the way it is designed to run, with **Claude Haiku
4.5** as both answerer and judge, on the full benchmark.

**90.4% correct** across all 1,540 questions, at **4,699 mean prompt tokens** ($88.55, September
2026).

| category | questions | score |
| --- | --- | --- |
| single-hop | 841 | 93.5 |
| temporal | 321 | 89.7 |
| multi-hop | 282 | 88.7 |
| open-domain | 96 | 70.8 |

Open-domain is the weak category. Those gold answers are single turns holding a name or a place that
never reach the retrieved context.

### For reference, what others report

Every figure below is **self-reported by its vendor**, on a different model stack, judge and
retrieval configuration. They are not comparable with each other or with ours. They are here so the
number above has context.

| system | reported | notes |
| --- | --- | --- |
| ZeroMemory | 96.1 | unverified |
| Zep | 94.7 | third-party testing found 75.1 on the same benchmark |
| ByteRover | 92.2 / 96.1 | two conflicting figures published |
| mem0 | 92.5 | single-hop 94.6, multi-hop 95.4, temporal 92.5, open-domain 82.3; 6,956 prompt tokens |
| **Memoose (Haiku 4.5)** | **90.4** | the run above, with per-category scores, CI, cost and raw rows published |
| Dakera | 88.2 | no LLM reranking |
| full context, no memory | ~73 | the whole conversation in the prompt |

mem0 is the only entry with a published per-category breakdown, and we are behind it everywhere,
most of all on multi-hop (−6.7) and open-domain (−11.5). We are ahead on cost, at a third fewer
prompt tokens with a much smaller answerer. Swapping the answerer moves a score more than swapping
the memory system does, and most vendors above do not disclose theirs, so treat the ordering as
noise rather than a ranking.

Two findings from those runs cut against us, and we publish them anyway. The knowledge graph does
**not** beat plain chunk retrieval on LoCoMo (paired McNemar p = 1.00) and costs 77% more tokens,
and raising the retrieval budget does not lift the score. LoCoMo asks needle questions over
conversations that fit in a context window, so it does not test what a graph is for.

Protocol, full tables, what other systems report, and the raw per-question rows are in
**[`benchmarks/`](./benchmarks/README.md)**. Setup and the operational traps are in
[`benchmarks/SETUP.md`](./benchmarks/SETUP.md).

# Learn more

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
  stays trustworthy as it changes: a fact was revised, two sources disagree, where did this come
  from. An eval only its author runs is not evidence, so this needs a design other systems can run
  before any number from it is worth publishing.
- [ ] **A token-cost benchmark.** Accuracy is reported everywhere and cost almost nowhere, though
  cost is what a memory system charges you per turn. No comparable methodology across systems exists
  yet.
- [ ] An ANN index, if a project ever passes ~200k vectors (SQLite itself has room well past that)
- [ ] Publish to PyPI so `uvx memoose` works without a checkout
- [ ] Exercise the delegated subagent path live on a host without hooks
- [ ] A live run of `maintain` end to end, the way capture was verified
- [ ] Migration from a pre-rename `~/.mnemoth` store

### Inspiration

- **[cognee](https://github.com/topoteretes/cognee)** (Apache 2.0) provided the memory philosophy
  and the most direct debt: typed graph, ontology-constrained extraction, deterministic ids, hybrid
  retrieval, datasets as scope, contradictions and supersession. The extraction and contradiction
  guidance in the skills is adapted from cognee's prompt templates. Where cognee calls a model,
  Memoose has a skill.
- **[OpenWiki](https://github.com/langchain-ai/openwiki)** provided grounded claims, so every fact
  carries a checkable evidence pointer, and the integration layer that `memoose install <host>`
  mirrors.
- **[obsidian-skills](https://github.com/kepano/obsidian-skills)** provided the skill packaging
  discipline: single-purpose, portable, with concrete rules instead of vague guidance.
- **[mem0](https://github.com/mem0ai/mem0)** provided the LoCoMo protocol we measure against. Their
  answerer and judge prompts are vendored verbatim from
  [mem0ai/memory-benchmarks](https://github.com/mem0ai/memory-benchmarks).
- **[Chonkie](https://github.com/chonkie-inc/chonkie)** provided the mascot.

[docs/inspirations.md](./docs/inspirations.md) records what was borrowed and what was not.

### Contributing

Pull requests and [issues](https://github.com/AndrewNgo-ini/mnemoth/issues) are welcome. For larger
changes, open an issue first to discuss the approach. Run the suite with `uv run pytest`.

### License

Apache 2.0. See [LICENSE](./LICENSE) and [NOTICE.md](./NOTICE.md).
