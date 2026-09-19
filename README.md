<div align="center">

<img src="assets/memoose-mascot.png" alt="the Memoose mascot" width="220">

# Memoose: A Dual-Path Memory System for Proactive Agents

---

# What is Memoose

**Memoose** is a dual-path memory system for proactive agents: memory that survives the session and
survives switching agents, found by search when the agent asks and by recommendation when it does not.
It is two parts. An **engine** stores, indexes and retrieves a typed knowledge graph on your
machine. A **harness** of skills, MCP tools, rules and hooks teaches the model your
host is already running how to use it.

It is built for long-lived project work: the decisions, conventions and ownership facts that have to
stay correct for months, each carrying an evidence pointer back to where it came from.

### Vision

**Memory is upkeep.** Facts are written as they surface, and `memoose maintain` periodically
sweeps the store into one worklist of things to judge. The pass decides nothing; a model makes every
call, on a small subagent so it costs neither your attention nor the conversation's turns.

**Search and recommendation are the two ways anything gets found.** Search answers a question you
thought to ask. Recommendation puts something in front of you that you did not. A memory system with
only search works when the agent already suspects there is something to recall, and stays silent
every other time. Memoose does both: `recall` for the asked question, and a hint injected before the
prompt for the unasked one.

**The context an agent most often lacks is procedural.** It knows what things are and still loses
the order of steps, skips a check, or repeats a step that already failed. So Memoose stores
procedures as a graph, after Google's [Procedural Graphs paper](https://arxiv.org/abs/2609.09153):
steps as nodes, transitions as edges carrying a condition, an advice and a pitfall. The agent
declares where it is, gets the transitions two hops out, and decides; when the session ends with an
outcome, every transition it took counts it, so the next run learns from the last. See
[ADR 0005](./docs/adr/0005-procedural-vocabulary-as-first-class-schema.md).

Read more: [Vision](./docs/site/vision.html).

# Quick start

Memoose needs Python 3.11 or newer and nothing else. Pick one:

```sh
pip install memoose            # any Python
pipx install memoose           # an isolated install, the `npm install -g` of Python
uvx memoose --help             # with uv, no install step at all
```

Store a fact, ask a question, look at the graph:

```sh
memoose remember "Bao:Person --owns--> auth-service:System" -e "user said 2026-09-18"
memoose remember "auth-service --uses--> PostgreSQL:Technology" -e "repo://src/db.py#L1-L20"
memoose recall "who owns auth and what does it run on"
memoose view                   # the knowledge graph in your browser, one HTML file, nothing uploaded
```

A fact is `source[:Type] --relation--> target[:Type]`. The `:Type` is needed only the first time an
entity is seen; after that the name alone is enough, and a name Memoose has not met comes back with
a message saying so. Every fact can carry `-e/--evidence`, `--valid-from` and `--desc`.

Later, when the store has grown:

```sh
memoose maintain               # one worklist: conflicts to judge, duplicates to merge, sessions to distil
memoose history auth-service   # every change to an entity or a fact, with who wrote it and why
```

The full command table is under [CLI](#cli). Memory lives in `~/.memoose/<dataset>.sqlite`, one
dataset per project plus a `user` dataset for facts that hold everywhere; `MEMOOSE_DATA_DIR` moves
it.

### Give your agent memory

The CLI above is already enough for an agent that can run shell commands. To also give it the
skills (when to recall, how to extract, how to judge a contradiction), and on Claude Code the hooks
and the `memory-keeper` subagent, point Memoose at the host:

```sh
memoose install claude         # or: codex | opencode | cursor
memoose status                 # what is installed where
```

`install` copies the skills into the host's skills directory; on Claude Code it also copies the
hooks beside `~/.claude/settings.json`, registers them there, and drops the agent into
`~/.claude/agents/`. User-scoped so one install works from every repository; `--project .` scopes
it to the current repository instead; `uninstall <host>` reverses all of it. No MCP server is
wired: the agent works through the CLI. For a host whose agent has no shell, `install <host> --mcp`
also registers `uvx memoose serve`, which needs [uv](https://docs.astral.sh/uv/) on the machine.

On **Claude Code**, install the plugin instead. It is the only route that also loads the hooks
(hints before a prompt, capture after a turn, the daily upkeep offer) and the `memory-keeper`
subagent, and it keeps one copy of everything:

```
/plugin marketplace add AndrewNgo-ini/mnemoth
/plugin install memoose@memoose
```

<details>
<summary><b><i>Working from a checkout:</i></b></summary>
<br>

```sh
git clone https://github.com/AndrewNgo-ini/mnemoth.git && cd mnemoth && uv sync
uv run memoose install claude          # skills, hooks and agent from this checkout
claude --plugin-dir .                  # Claude Code: skills, hooks and server from the checkout
uv sync --extra fastembed              # local embeddings (a keyless hashed fallback is used otherwise)
uv sync --extra ontology               # full RDF parsing
uv run pytest                          # the suite
```

</details>

> Upgrading from mnemoth: `MNEMOTH_*` variables are still read, an existing `~/.mnemoth` store is
> reused, and `install` clears the pre-rename MCP entry so a host never runs both servers.

### Onboarding

Memoose cannot see how your machine is configured, so ask your agent to onboard it. The
[`memoose-onboard`](./harness/skills/memoose-onboard/SKILL.md) skill walks through what is reachable on this
host, which automatic parts are live, what is stored, how to inspect it (`recall`, `history`) or
remove it (`forget`), where the switches are, and how to seed the first memories.

# How Memoose works

Two layers: a deterministic **engine** (a SQLite knowledge graph behind a CLI and 26 MCP tools, no
model) and a **harness** of skills, hooks and a subagent that carries the judgment, run by the model
your host already has. The [Overview](./docs/site/index.html) explains the split, [Automatic
memory](./docs/site/automatic.html) covers what runs without being asked and on which hosts,
[Evidence & history](./docs/site/trust.html) covers what a fact carries and how it changes, and
[Configuration](./docs/site/configuration.html) lists the switches.

# Usage

### Tools

26 MCP tools. Every capability is reachable through a tool call on any MCP host.


| area     | tools                                                                                                                                                                                |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| ontology | `describe_ontology`, `add_entity_type`, `import_ontology` (OWL/RDF/Turtle), `declare_functional_relations`                                                                           |
| write    | `remember`, `mark_contradiction`, `supersede`, `merge_entities`, `cross_connect`, `set_bucket_summary`, `forget`                                                                     |
| read     | `recall` (hybrid, facts, neighbourhood, lexical, summaries, temporal, rules, session), `contradiction_candidates`, `history`, `memify_candidates`, `global_context`, `list_datasets` |
| sessions | `session_start`, `session_add_turn`, `session_set_context`, `session_get`, `session_timeline`, `publish_lessons`, `session_end`                                                      |


### Skills


| skill                                                            | teaches the host model                                                                                             |
| ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| [`memoose`](./harness/skills/memoose/SKILL.md)                   | when to recall, how to extract entities, relations, evidence and summaries, procedures, and the ontology           |
| [`memoose-onboard`](./harness/skills/memoose-onboard/SKILL.md)   | what is live on this host, the first fill of an existing project, how to turn any of it off                        |
| [`memoose-sessions`](./harness/skills/memoose-sessions/SKILL.md) | position and guidance during work, context sections, outcome, curator and writer rules for lessons                 |
| [`memoose-upkeep`](./harness/skills/memoose-upkeep/SKILL.md)     | judging what the store surfaces: hotspots and contradictions, duplicates, connections, stale summaries, dismissals |


### CLI

Memory operations, the same ones the MCP tools expose:


| command                                                                                     | what it does                                                                                                                   |
| ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| <code>memoose&amp;nbsp;recall&amp;nbsp;"who owns billing"</code>                            | search memory; `--mode`, `--limit`, `--superseded`, `--json`                                                                   |
| <code>memoose&amp;nbsp;remember&amp;nbsp;"bao:Person --owns--&gt; auth:System"</code>       | store a fact; `--desc`, `-e/--evidence`, `--valid-from`, `--stdin` for a JSON batch                                            |
| <code>memoose&amp;nbsp;history&amp;nbsp;auth-service</code>                                 | the provenance ledger for an entity or a fact                                                                                  |
| <code>memoose&amp;nbsp;contradictions&amp;nbsp;\[names\]</code>                             | hotspots and open contradictions to judge                                                                                      |
| `memoose ontology` · `memoose datasets` · `memoose context`                                 | entity types and stats · memory scopes · global context                                                                        |
| <code>memoose&amp;nbsp;session&amp;nbsp;start|turn|context|timeline|lessons|end</code>      | session lifecycle                                                                                                              |
| `memoose maintain`                                                                          | the periodic pass: everything that needs judging, in one worklist                                                              |
| <code>memoose&amp;nbsp;dismiss&amp;nbsp;&lt;key&gt;&amp;nbsp;--reason&amp;nbsp;"..."</code> | decline a candidate from that worklist so it is not proposed again                                                             |
| `memoose view`                                                                              | open the knowledge graph in your browser: one self-contained HTML file, nothing uploaded (`--superseded` draws history dashed) |
| <code>memoose&amp;nbsp;forget&amp;nbsp;--entity&amp;nbsp;X</code>                           | delete an entity, a fact, a session, or a dataset                                                                              |
| <code>memoose&amp;nbsp;tool&amp;nbsp;&lt;name&gt;&amp;nbsp;--stdin</code>                   | any remaining tool, arguments as JSON on stdin                                                                                 |


Output is compact text, and text over `--max-inline` (2000 chars) is written to a file whose path is
printed. `--json` gives the exact MCP payload in full, never spilled. Setup:


| command                                                       | what it does                                                       |
| ------------------------------------------------------------- | ------------------------------------------------------------------ |
| `memoose serve`                                               | run the stdio MCP server (what a host launches)                    |
| <code>memoose&amp;nbsp;install&amp;nbsp;&lt;host&gt;</code>   | write the MCP entry and copy the skills (`--project`, `--command`) |
| <code>memoose&amp;nbsp;uninstall&amp;nbsp;&lt;host&gt;</code> | remove both                                                        |
| `memoose status`                                              | what is installed where, and the CLI invocation for this machine   |


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


| category    | questions | score |
| ----------- | --------- | ----- |
| single-hop  | 841       | 93.5  |
| temporal    | 321       | 89.7  |
| multi-hop   | 282       | 88.7  |
| open-domain | 96        | 70.8  |


Open-domain is the weak category. Those gold answers are single turns holding a name or a place that
never reach the retrieved context.

### For reference, what others report

Every figure below is **self-reported by its vendor**, on a different model stack, judge and
retrieval configuration. They are not comparable with each other or with ours. They are here so the
number above has context.


| system                  | reported    | notes                                                                                 |
| ----------------------- | ----------- | ------------------------------------------------------------------------------------- |
| ZeroMemory              | 96.1        | unverified                                                                            |
| Zep                     | 94.7        | third-party testing found 75.1 on the same benchmark                                  |
| ByteRover               | 92.2 / 96.1 | two conflicting figures published                                                     |
| mem0                    | 92.5        | single-hop 94.6, multi-hop 95.4, temporal 92.5, open-domain 82.3; 6,956 prompt tokens |
| **Memoose (Haiku 4.5)** | **90.4**    | the run above, with per-category scores, CI, cost and raw rows published              |
| Dakera                  | 88.2        | no LLM reranking                                                                      |
| full context, no memory | \~73        | the whole conversation in the prompt                                                  |


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
[**`benchmarks/`**](./benchmarks/README.md). Setup and the operational traps are in
[`benchmarks/SETUP.md`](./benchmarks/SETUP.md).

# Learn more

### Docs

The [documentation site](./docs/site/index.html) is the place to read about Memoose:
[Vision](./docs/site/vision.html) · [Features](./docs/site/features.html) · [Install](./docs/site/install.html) ·
[Tools](./docs/site/tools.html) · [Skills](./docs/site/skills.html) ·
[Automatic memory](./docs/site/automatic.html) ·
[Configuration](./docs/site/configuration.html) ·
[Evidence &amp; history](./docs/site/trust.html) ·
[Roadmap](./docs/site/roadmap.html)

For contributors, the repository also carries [CONTEXT.md](./CONTEXT.md) (glossary),
[docs/adr/](./docs/adr/) (decision records) and [docs/STATE.md](./docs/STATE.md) (what is done, what
the benchmarks established).

### Roadmap

What is done and what is next: [Roadmap](./docs/site/roadmap.html).

### Inspiration

- [**cognee**](https://github.com/topoteretes/cognee) inspired the memory philosophy: a typed
graph, ontology-constrained extraction, deterministic ids, hybrid retrieval, datasets as scope,
contradictions and supersession as first-class concepts. Where cognee calls a model, Memoose has
a skill.
- [**OpenWiki**](https://github.com/langchain-ai/openwiki) inspired grounded claims, so every fact
carries a checkable evidence pointer, and the one-command install into each host's own config.



- [**mem0**](https://github.com/mem0ai/mem0) provided the LoCoMo protocol we measure against. Their
answerer and judge prompts are vendored verbatim from
[mem0ai/memory-benchmarks](https://github.com/mem0ai/memory-benchmarks).

### Contributing

Pull requests and [issues](https://github.com/AndrewNgo-ini/mnemoth/issues) are welcome. For larger
changes, open an issue first to discuss the approach. Run the suite with `uv run pytest`.

### License

Apache 2.0. See [LICENSE](./LICENSE).