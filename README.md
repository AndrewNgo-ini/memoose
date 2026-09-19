<div align="center">

<img src="assets/memoose-mascot.png" alt="the Memoose mascot" width="220">

# Memoose: A Dual-Path Memory System for Proactive Agents

</div>

---

## Contents

- [What is Memoose](#what-is-memoose)
- [Quick start](#quick-start)
- [Give your agent memory](#give-your-agent-memory)
- [How Memoose works](#how-memoose-works)
- [Usage](#usage): [tools](#tools) · [skills](#skills) · [CLI](#cli)
- [Benchmarks](#benchmarks)
- [Learn more](#learn-more): [documentation](#documentation) · [inspiration](#inspiration) · [contributing](#contributing) · [license](#license)

# What is Memoose

**Memoose** is a dual-path memory system for proactive agents. Memory survives the session and
survives switching agents. It is found two ways: by search when the agent asks, and by
recommendation when it does not. An **engine** keeps a typed knowledge graph on your machine; a
**harness** of skills, hooks and tools teaches the model your host already runs how to use it.

It is built for long-lived project work: decisions, conventions and ownership facts that must stay
correct for months, each with an evidence pointer back to its source.

### Vision

**Memory is upkeep.** Facts are written as they surface. `memoose maintain` sweeps the store into
one worklist of things to judge and decides nothing itself; a model makes every call, on a small
subagent that costs neither your attention nor the conversation's turns.

**Search and recommendation are the two ways anything gets found.** Search answers a question you
thought to ask. Recommendation surfaces what you did not. A search-only memory stays silent unless
the agent already suspects something is there. Memoose does both: `recall`, and a hint before each
prompt.

**The context an agent most often lacks is procedural.** It knows what things are and still runs
steps out of order, skips a check, or repeats a step that already failed. Memoose stores procedures
as a graph, after Google's [Procedural Graphs](https://arxiv.org/abs/2609.09153): steps as nodes,
transitions carrying a condition, an advice and a pitfall. The agent declares where it is, reads the
transitions two hops out, and decides. When the session ends with an outcome, every transition it
took counts it, so the next run learns from the last.

Read more: [Vision](https://andrewngo-ini.github.io/mnemoth/vision.html).

# Quick start

Python 3.11 or newer, nothing else:

```sh
pip install memoose            # or: pipx install memoose, or uvx memoose --help
```

Store a fact, ask a question, look at the graph:

```sh
memoose remember "Bao:Person --owns--> auth-service:System" -e "user said 2026-09-18"
memoose remember "auth-service --uses--> PostgreSQL:Technology" -e "repo://src/db.py#L1-L20"
memoose recall "who owns auth and what does it run on"
memoose view                   # the graph in your browser, nothing uploaded
```

A fact is `source[:Type] --relation--> target[:Type]`. Give the `:Type` the first time an entity
appears; after that the name is enough. Every fact takes `-e/--evidence`, `--valid-from` and
`--desc`. Later:

```sh
memoose maintain               # one worklist: conflicts, duplicates, sessions to distil
memoose history auth-service   # every change to an entity or fact, by whom and why
```

Memory lives in `~/.memoose/<dataset>.sqlite`: one dataset per project plus a `user` dataset for
facts that hold everywhere. `MEMOOSE_DATA_DIR` moves it. Full command table under [CLI](#cli).

# Give your agent memory

The CLI is enough for an agent with a shell. To add the skills, and on Claude Code the hooks and the
`memory-keeper` subagent:

```sh
memoose install claude         # or: codex | opencode | cursor
memoose status                 # what is installed where
```

`install` copies the skills into the host. On Claude Code it also registers the hooks in
`~/.claude/settings.json` and drops the agent into `~/.claude/agents/`. It is user-scoped;
`--project .` scopes it to one repository; `uninstall <host>` reverses it. No MCP server is wired
unless the agent has no shell: `install <host> --mcp` adds `uvx memoose serve`, which needs
[uv](https://docs.astral.sh/uv/).

On **Claude Code** the plugin is the simplest route and keeps one copy of everything:

```
/plugin marketplace add AndrewNgo-ini/mnemoth
/plugin install memoose@memoose
```

<details>
<summary><b>Working from a checkout</b></summary>
<br>

```sh
git clone https://github.com/AndrewNgo-ini/mnemoth.git && cd mnemoth && uv sync
uv run memoose install claude          # skills, hooks and agent from this checkout
claude --plugin-dir .                  # or load the checkout as a plugin
uv sync --extra fastembed              # local embeddings (a keyless hash fallback is used otherwise)
uv sync --extra ontology               # full RDF parsing
uv run pytest
```

</details>

> Upgrading from mnemoth: `MNEMOTH_*` variables are still read, an existing `~/.mnemoth` store is
> reused, and `install` clears the old MCP entry.

**Onboarding.** Ask your agent to onboard Memoose. The
[`memoose-onboard`](./harness/skills/memoose-onboard/SKILL.md) skill checks what works on this host,
installs what is missing, then fills the project's memory from its README, docs and git log so the
next session starts with context.

# How Memoose works

Two layers. A deterministic **engine**: a knowledge graph behind a CLI and 26 MCP tools, no model.
A **harness** of skills, hooks and a subagent that carries the judgment, run by the model your host
already has.

- [Overview](https://andrewngo-ini.github.io/mnemoth/) explains the split.
- [Automatic memory](https://andrewngo-ini.github.io/mnemoth/automatic.html): what runs without being asked, on which hosts.
- [Evidence & history](https://andrewngo-ini.github.io/mnemoth/trust.html): what a fact carries and how it changes.
- [Configuration](https://andrewngo-ini.github.io/mnemoth/configuration.html): the switches.

# Usage

### Tools

26 MCP tools; every capability is a tool call on any MCP host.

| area     | tools |
| -------- | ----- |
| ontology | `describe_ontology`, `add_entity_type`, `import_ontology` (OWL/RDF/Turtle), `declare_functional_relations` |
| write    | `remember`, `mark_contradiction`, `supersede`, `merge_entities`, `cross_connect`, `set_bucket_summary`, `forget` |
| read     | `recall`, `guidance`, `contradiction_candidates`, `history`, `memify_candidates`, `global_context`, `list_datasets` |
| sessions | `session_start`, `session_add_turn`, `session_set_context`, `session_get`, `session_timeline`, `publish_lessons`, `session_end` |

### Skills

| skill | teaches the host model |
| ----- | ---------------------- |
| [`memoose`](./harness/skills/memoose/SKILL.md) | when to recall; how to extract facts with evidence, store procedures, shape the ontology |
| [`memoose-sessions`](./harness/skills/memoose-sessions/SKILL.md) | the working loop: position and guidance, context sections, outcome, distilling lessons |
| [`memoose-upkeep`](./harness/skills/memoose-upkeep/SKILL.md) | judging what the store surfaces: contradictions, duplicates, connections, stale summaries |
| [`memoose-onboard`](./harness/skills/memoose-onboard/SKILL.md) | check what works, install what is missing, then fill this project's memory from its docs and history |

### CLI

Memory operations, the same ones the tools expose:

| command | what it does |
| ------- | ------------ |
| `memoose recall "who owns billing"` | search memory; `--mode`, `--limit`, `--superseded`, `--json` |
| `memoose remember "bao:Person --owns--> auth:System"` | store a fact; `--desc`, `-e`, `--valid-from`; `--when`, `--do`, `--avoid` on a transition; `--stdin` for a JSON batch |
| `memoose guidance "run the test suite"` | what comes next from a procedure: transitions two hops out, with how past runs ended |
| `memoose history auth-service` | the provenance ledger for an entity or fact |
| `memoose contradictions [names]` | hotspots and open contradictions to judge |
| `memoose ontology` · `memoose datasets` · `memoose context` | entity types and stats · memory scopes · global context |
| `memoose session start\|turn\|context\|get\|timeline\|lessons\|end` | session lifecycle; `turn --at <procedure>` declares position, `end --outcome` records how it went |
| `memoose maintain` | the periodic pass: everything that needs judging, in one worklist |
| `memoose dismiss <key> --reason "..."` | decline a candidate so it is not proposed again |
| `memoose view` | the graph in your browser as one HTML file (`--superseded` draws history dashed) |
| `memoose forget --entity X` | delete an entity, fact, session or dataset |
| `memoose tool <name> --stdin` | any remaining tool, arguments as JSON on stdin |

Output is compact text; over `--max-inline` (2000 chars) it goes to a file whose path is printed.
`--json` gives the exact tool payload, never cut. Setup:

| command | what it does |
| ------- | ------------ |
| `memoose install <host>` | skills, hooks and the agent into a host (`--project`, `--mcp`) |
| `memoose uninstall <host>` | reverse it |
| `memoose status` | what is installed where |
| `memoose serve` | the stdio MCP server, for a host that launches one |

# Benchmarks

Memoose has no model of its own, so its score is inseparable from the model driving it. We report
the number that matches how it is meant to run: a small, fast model throughout.

LoCoMo is the standard conversational-memory benchmark: long multi-session conversations, then
questions about them. One model answers from what the memory system retrieves; another grades. We
run mem0's protocol with their prompts verbatim, so the memory system is the only difference.

### Our run

**Claude Haiku 4.5** as answerer and judge, all 1,540 questions: **90.4% correct** at **4,699 mean
prompt tokens** ($88.55, September 2026). A reference point, not a competitive entry.

| category    | questions | score |
| ----------- | --------- | ----- |
| single-hop  | 841       | 93.5  |
| temporal    | 321       | 89.7  |
| multi-hop   | 282       | 88.7  |
| open-domain | 96        | 70.8  |

Open-domain is the weak category: its gold answers are single turns that never reach the retrieved
context.

### What others report

Every figure is **self-reported by its vendor** on a different model, judge and retrieval setup.
They are not comparable with each other or with ours; they are context.

| system                  | reported    | notes |
| ----------------------- | ----------- | ----- |
| ZeroMemory              | 96.1        | unverified |
| Zep                     | 94.7        | third-party testing found 75.1 |
| ByteRover               | 92.2 / 96.1 | two conflicting figures published |
| mem0                    | 92.5        | single-hop 94.6, multi-hop 95.4, temporal 92.5, open-domain 82.3; 6,956 prompt tokens |
| **Memoose (Haiku 4.5)** | **90.4**    | the run above; per-category scores, CI, cost and raw rows published |
| Dakera                  | 88.2        | no LLM reranking |
| full context, no memory | ~73         | the whole conversation in the prompt |

mem0 is the only entry with a per-category breakdown; we trail it everywhere, most on multi-hop
(−6.7) and open-domain (−11.5), at a third fewer prompt tokens with a much smaller answerer.
Swapping the answerer moves a score more than swapping the memory system, so treat the ordering as
noise.

Two findings cut against us and are published anyway: the knowledge graph does **not** beat plain
chunk retrieval on LoCoMo (paired McNemar p = 1.00) and costs 77% more tokens, and a larger
retrieval budget does not lift the score. LoCoMo asks needle questions over conversations that fit
in a context window; it does not test what a graph is for.

Protocol, full tables and raw rows: [`benchmarks/`](./benchmarks/README.md). Setup and traps:
[`benchmarks/SETUP.md`](./benchmarks/SETUP.md).

# Learn more

### Documentation

[Site](https://andrewngo-ini.github.io/mnemoth/)

### Inspiration

- [**cognee**](https://github.com/topoteretes/cognee) for the memory philosophy: a typed graph,
  ontology-constrained extraction, deterministic ids, hybrid retrieval, contradictions and
  supersession as first-class concepts. Where cognee calls a model, Memoose has a skill.
- [**OpenWiki**](https://github.com/langchain-ai/openwiki) for grounded claims: every fact carries a
  checkable evidence pointer.
- [**mem0**](https://github.com/mem0ai/mem0) for the LoCoMo protocol, with prompts vendored verbatim
  from [memory-benchmarks](https://github.com/mem0ai/memory-benchmarks).

### Contributing

Pull requests and [issues](https://github.com/AndrewNgo-ini/mnemoth/issues) are welcome; open an
issue first for larger changes. `uv run pytest` runs the suite.

### License

Apache 2.0. See [LICENSE](./LICENSE).
