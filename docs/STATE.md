# State of play

Last updated 2026-09-09, after shipping the CLI, the upkeep pass, and the numpy scoring path.

## The procedural vocabulary is schema, not convention (2026-09-18)

Grilled the ADR 0004 adoption against the paper and found it partial: the Engine could not answer
"what comes next" (only the hook could, with its own queries), the three edge attributes were one
packed sentence nobody could query or revise separately, the lexical matcher fired on token overlap
and steered toward an unrelated procedure (observed live in this repo), nothing recorded where the
agent was or how a session ended, and every branching Procedure was flagged as a hotspot. ADR 0005
closes those: `condition`, `advice`, `pitfall` columns on relations (`remember --when/--do/--avoid`;
old packed descriptions are unpacked once on open), `guidance(procedure)` as Engine method, MCP tool
and CLI command returning the two-hop outgoing neighbourhood raw, a `position` on session turns
that returns the guidance from there and builds the Trace, an `outcome` on `session_end` that counts
on every traversed Transition (`succeeded`/`failed`/`abandoned` columns, plus a `traverse` event
per Transition in provenance), the hotspot rule skipping Transitions, and `dismiss` widened to
`transition:<id>`. The hint hook no longer reads the transcript; it keys on the latest declared
Position of an open Session and is silent otherwise. CONTEXT.md gains Transition, Condition,
Advice, Pitfall, Start, Position, Trace, Outcome. Skills and the keeper agent teach the loop; the
keeper is told never to write Procedures. Still not adopted: a validation gate (counts are shown,
not enforced), a guidance model call, named procedure graphs. Not yet verified live: whether an
agent declares its Position often enough for the Trace to be useful. Version 0.4.0, 97 tests.

`memoose install <host>` now installs what the skills need and nothing they do not: the skills on
every host, and on Claude Code the hooks (copied to `.claude/memoose/hooks/`, registered in
`settings.json`, removed by `uninstall`) and the `memory-keeper` agent with `tools: Bash` so it
works through the CLI. The MCP server is opt-in (`--mcp`) for an agent without a shell. When the
plugin is installed the hooks and agent are skipped rather than registered twice. The wheel now
carries the harness. 99 tests.

`skills/`, `hooks/` and `agents/` moved under `harness/`, which is what the project has always
called that half of memoose. The plugin manifest now points at all three (`skills`, `agents`,
`hooks` fields); Claude Code loads the root locations by convention, and the docs say `agents`
and `hooks` replace their defaults while `skills` adds to it, so nothing may be left at the root or
it loads twice. The wheel force-includes `harness/` as one tree. The installed plugin copy only
refreshes on a version change or a reinstall.

Six skills became four, split by the moment that triggers them rather than by store feature:
`memoose` (recall, extraction, procedures, and now the ontology section), `memoose-sessions` (the
working loop), `memoose-upkeep` (contradictions and memify merged: everything `maintain` lists,
one reader, one set of verbs), `memoose-onboard`. The ontology skill fired once per project and
paid a resident description every turn; the two maintenance skills covered one worklist. Onboard
gained the first fill: on a project with history and an empty store it asks once, then reads the
README, glossary, ADRs, CI and recent log and writes facts with evidence, standing rules, and
documented workflows as Procedures, under a precision rule.

## Installed on itself as a plugin; two manifest bugs found (2026-09-10)

Dogfooding the plugin route surfaced two defects that `claude plugin validate` does not catch. The
manifest declared `"hooks": "./hooks/hooks.json"`, but Claude Code loads that file by convention, so
the declaration was a *duplicate* and the whole plugin failed to load; the key is removed. And the
manifest pointed the MCP server's `MEMOOSE_DATA_DIR` at `${CLAUDE_PLUGIN_DATA}` while the CLI and the
hooks use `~/.memoose`, so the server would have read an empty store while everything else read the
real one; the override is removed and every surface shares one store. `.claude-plugin/marketplace.json`
now lets a checkout be added as its own marketplace (`claude plugin marketplace add <checkout>`,
`claude plugin install memoose@memoose`). The install is a copy, refreshed by `claude plugin update`
only when the version changes, so the version is bumped to 0.3.0 and must be bumped again to ship
changes to an installed plugin. The user-scope `memoose install claude` copy was removed as a
duplicate. `memoose view` writes the graph as one self-contained HTML file with the drawing library
inlined and cached; its first version drew nothing because vis-network hides the canvas until
stabilisation and nothing forced a fit.

## Procedural memory, after the Procedural Graphs paper (2026-09-10)

Read arXiv:2609.09153 (Lu et al., Google) end to end and adopted the parts that fit a store with no
model of its own (ADR 0004). A `Procedure` entity type (seeded additively, so existing stores gain
it), transitions as ordinary relations with `When <condition>: <guidance>. Avoid: <pitfall>.` in
the description, and the hint hook now localises the agent's **last tool call** on a Procedure and
injects its outgoing two-hop neighbourhood grouped by hop, before the prompt-keyed BM25 hint. The
paper's ablation (local subgraph beats full graph; full-graph injection hurt ALFWorld) is the reason
it is a local subgraph and not the store. Rejection memory landed as `dismiss` events in provenance:
`maintain` and `contradiction_candidates` filter dismissed candidates and show the reasons. The
periodic pass also now needs two shared chunks for a cross-connect candidate, which removes the
"every entity co-occurs with every other" noise on a young store. Not adopted: the held-out
validation gate (no task distribution to score against) and a per-step guidance model call.

`--json` output is never spilled to a file; a consumer of JSON needs all of it. 89 tests.

## The CLI, the upkeep pass, and what they cost (2026-09-09)

**`memoose` is now a CLI as well as an MCP server**, over the same `Engine`. `recall`, `remember`
(with a `source[:Type] --relation--> target[:Type]` DSL), `history`, `contradictions`, `ontology`,
`datasets`, `context`, `session *`, `forget`, `maintain`, plus `tool <name> --stdin` as the escape
hatch to any remaining engine method. Compact text by default, `--json` for the exact MCP payload,
and output over `--max-inline` (2000 chars) spills to a file whose path is printed.

Why: measured against the server's own tool list, the MCP tool schemas are **16,988 chars ≈ 4,250
tokens resident on every turn** once the server is connected; a command costs nothing until it runs
(90 ms startup). `mcp` is imported only inside `serve`, so a CLI call starts in 87 ms instead of 307.
Both surfaces stay: the skills teach the CLI first, the server remains for restricted shells.

**Background capture writes through the CLI.** `hooks/capture.py` now runs the keeper with
`--allowedTools Bash` and an *empty* `--mcp-config`, so a capture no longer starts an MCP server or
pays for its schemas. Not yet verified live end to end — the prompt changed shape, so capture quality
should be re-checked the way it was in the 2026-09-07 run.

**The upkeep pass exists.** `memoose maintain` (`Dataset.maintenance()`) sweeps the store into one
worklist — hotspots, open contradictions, consolidate and cross-connect candidates, stale bucket
summaries, sessions that ended without lessons — and decides none of it. On hosts with hooks,
`session_start.py` offers it at most once a day per project via a stamp file
(`MEMOOSE_AUTO_MAINTAIN=0`, `MEMOOSE_MAINTAIN_EVERY_HOURS`). There is no daemon and no cron: a
session opening is the only regular event a hook can observe.

**Scoring is numpy.** `vector_search` was a pure-Python loop over every embedding row: 51 ms at 5k
rows, 506 ms at 50k. It is now one matrix multiply, with ties broken on `ref_id` so the same store
answers the same way on any machine. numpy is a base dependency. Retrieval reproduces to ±0.003 per
category and identically overall; median p50 query latency halved (2.1 ms → 0.9 ms, hash embedder).
Storage was investigated and **SQLite stays**: DuckDB's HNSW is still experimental with a static FTS
index and single-writer concurrency, Kuzu was archived in Oct 2025, and sqlite-vec is pre-1.0,
brute-force only, and slower than numpy. Revisit only past ~200k vectors per project.

**The embedder is lazy.** `Engine` no longer builds it at construction, so a fresh CLI process doing
lexical work never loads the ONNX model. Measured: fastembed loads in 0.39 s and embeds a query in
7 ms, so a vector recall from cold is ~480 ms and a lexical one ~90 ms.

95 tests pass; `claude plugin validate .` passes.

## What is done

**The memory core is complete and released (v0.2.0):** 24 MCP
tools plus 5 skills, packaged as an Agent Plugin, with no model call anywhere in the library
(ADR 0001) and one SQLite file per Dataset (ADR 0002). 77 tests pass, including one that drives the
server over MCP stdio the way a host does. `claude plugin validate .` passes. Verified end to end
inside Claude Code via `--plugin-dir`. `memoose install claude|codex|opencode|cursor` writes one MCP
entry and copies the skills into each host's own locations.

Covered: ontology with OWL/RDF/Turtle import and basic-type collapse, deterministic entity ids and
merge-by-name, functional-relation supersession, contradiction candidates with `contradicts` edges,
the regex query router with 8 retrieval modes, memify weights, provenance ledger, sessions
with typed context sections and lesson distillation, memify cross-connect/consolidate/global-context
buckets, project plus user Datasets with a reserve merge.

**Proactive memory is implemented and verified live (ADR 0003).** Layered over the skills-plus-MCP
core, never replacing it, so a host without hooks loses automation and keeps every capability:

| surface | file | verified |
| --- | --- | --- |
| hint before each prompt (*recommendation as a memory*): BM25 over the local index, no model, silent when nothing matches | `hooks/recommend.py` | live — the agent answered from hints alone with tools forbidden |
| standing rules, preferences and lessons at session start | `hooks/session_start.py` | live — the agent repeated a seeded rule verbatim |
| background capture on a small model after a turn and before compaction, async and non-blocking, behind a relevance gate, a per-session lock and a resume offset | `hooks/capture.py` | unit-tested; does **not** fire in `-p` print mode |
| in-session delegation for hosts without hooks | `agents/memory-keeper.md` (`model: haiku`) | wired, not yet exercised live |
| **the write→read loop, end to end** | `hooks/capture.py` → `hooks/recommend.py` | **live — see "What the live run established" below** |
| what is live here, what is stored, how to opt out | `skills/memoose-onboard/SKILL.md` | — |

Kill switches: `MEMOOSE_HINTS`, `MEMOOSE_AUTO_RECALL`, `MEMOOSE_AUTO_CAPTURE`. Every hook exits 0 on
any failure. 77 tests.

Renamed from mnemoth. `MEMOOSE_*` is canonical; the `MNEMOTH_*` name of each variable is still read
as a fallback, `data_dir()` keeps using `~/.mnemoth` when that is the only store on disk, and
`install` clears a pre-rename MCP entry so a host never runs both servers. Nothing is migrated.

Note for benchmarking: none of this is visible to the LoCoMo harness, which calls the MCP tools
directly and never goes through a hook. The benchmark measures the store and the retrieval, not the
automation.

## What the benchmarking established

Protocol: LoCoMo under mem0's memory-benchmarks methodology, with mem0's answerer and judge prompts
vendored verbatim, Claude Code as the host model. Numbers and tables live in
`benchmarks/locomo/RESULTS.md`; how to run it lives in `benchmarks/SETUP.md`.

1. **Full run: 90.4** on all 1,540 questions (95% CI 88.8–91.8), 4,699 mean prompt tokens, $88.55,
   Haiku answerer and judge — single-hop 93.5, temporal 89.7, multi-hop 88.7, open-domain 70.8. It
   supersedes the sampled figure below, which was optimistic by 1.5 points.
1. **Superseded — the sample.** 91.9 on a 160-question stratified sample (95% CI 86.6–95.2) against
   mem0's published 92.5 on the full 1,540, using 32% fewer prompt tokens (4,728 vs 6,956) and a much
   smaller answerer (Claude Haiku 4.5). Its per-category read — ahead on temporal and single-hop —
   did not survive the full run: it compared a sample against mem0's paper averages rather than
   their headline figures. Full run is behind mem0 in every category, ahead only on token cost.
2. **The graph does not help on this benchmark.** Two-arm paired test, same 45 questions, same
   retrieval budget, same answerer and judge, only ingest differing: chunks 93.3, graph 95.6, but
   40 both-right / 2 only-chunks / 3 only-graph, **McNemar p = 1.00**, at 77% more prompt tokens.
   LoCoMo asks needle questions over 16k–26k-token conversations; chunk retrieval finds the needles
   and the answerer does the multi-hop joining itself. What the graph is for — contradictions,
   supersession, provenance, consolidation, typed queries — LoCoMo does not test.
3. **Retrieval depth is not the bottleneck.** Raising k lifts evidence recall (0.876 → 0.906 at
   k=30, → 0.932 at k=40) but not the judged score: paired on 97 questions, k=20 90.7 vs k=30 89.7,
   p = 1.00, at 30% more tokens. Evidence recall decouples from the judged score past ~0.88. Of 13
   failures, only 3 were retrieval misses; 10 were answerer reasoning or disputable gold answers.
   **k=20, 4 turns per chunk, stays the default.**
4. **LoCoMo is close to saturated** and is a weak discriminator: a no-memory full-context baseline
   scores ~73 and every credible system lands in the low 90s. Between-system gaps are smaller than
   the effect of swapping the answerer model.

## Honest summary

What is demonstrably better: cost and independence. Parity accuracy at a third fewer tokens, 35 ms
retrieval against a local SQLite file, no API key, no service, and retrieval quality measurable
without a model at all. The retrieval algorithm itself is conventional (BM25 + local embeddings fused
by reciprocal rank, plus one-hop graph expansion); the differentiator is the architecture, not the
ranking.

## The in-house maintained-memory suite (removed 2026-09-09)

A model-free suite lived at `benchmarks/maintained/` and asked the questions LoCoMo cannot: a fact
changed, does recall return the current one; can the old one still be shown; do two disagreeing
sources get reported or silently resolved; does evidence survive; does an earlier session's lesson
come back. It was removed because a benchmark only its author runs is not evidence, and publishing a
score from it invited exactly that reading. Proposing an eval other systems can run is now a roadmap
item instead. The cases remain in git history if the design is picked up again.

The bug it caught before removal is the reason to rebuild something like it, and the fix stands:

> Functional supersession was decided by **write order alone**. Backfilling a fact that was true in
> 2024, after the 2025 value was already known, silently made the 2024 value current again — learning
> the past overwrote the present. Fixed by `states_later_value` in `src/memoose/graph/contradictions.py`:
> `valid_from` decides when both facts carry one, and a backfilled arrival is stored as superseded
> history. Write order still decides when a date is missing, and an undated arrival is presumed
> current, so the ordinary path is unchanged.

Removing the suite means that class of regression is **no longer checked on every commit**.

## What the live run established

The proactive surface had never been driven end to end (the LoCoMo harness calls MCP tools directly
and bypasses every hook). Driving a real transcript through `hooks/capture.py` on haiku, then the
resulting store back through `hooks/recommend.py`:

**Capture works, and the extraction quality is good.** 42 s, exit 0, 7 entities and 5 facts, every
one with an evidence pointer: the decision *and its reason*, an ownership handover, and a convention
linked to the incident that motivated it. It correctly filed the user's own hard rule under the
`user` Dataset rather than the project one. Re-running on the same transcript was a **0.07 s no-op**,
so the resume offset holds and turns are never captured twice.

**The read half then dropped it on the floor, twice.** Both are fixed and regression-tested:

1. `recommend.py` opened only the project Dataset. `recall` searches project *then* user with a
   reserve; the hint did not, so it silently discarded the class of memory that applies to every
   prompt — the standing rules capture deliberately files under `user`. Now searched, with one
   reserved slot.
2. The relevance floor was an absolute `0.5` against a **corpus-relative** score. bm25's IDF term is
   zero for a token present in every indexed row, so in a small store a *perfect* keyword match
   scores 0.0 and was rejected. Measured: the floor admits nothing until the index holds ~5 rows. So
   hints stayed silent for the first sessions on a project, and *permanently* for the user Dataset,
   which by design never grows large — the feature looked broken exactly when someone first tried
   it. `score_floor` now drops the floor below 8 indexed rows and lets the FTS match be the gate.

**The capture/currency gap, found in the same run and now closed.** Capture originally expressed the
ownership handover as `previously_owned_by` and never called `declare_functional_relations`, so the
currency machinery the benchmark proves correct was *not exercised by the automatic path at all* —
the store did supersession properly and nothing asked it to. Fixed by one instruction added to all
three surfaces that drive extraction (`hooks/capture.py`'s prompt, `skills/memoose/SKILL.md`,
`agents/memory-keeper.md`): for a relation holding one current value per subject, declare it
functional and store **both** values under the **same** relation name, oldest `valid_from` first.

Two live iterations were needed, which is the useful part of the record:

| attempt | what capture produced |
| --- | --- |
| before | `previously_owned_by --> Duc` — a fake relation name, so the store saw no replacement |
| naming rule only | `owned_by` declared functional, `owned_by --> Mai` with `valid_from` — but Duc **dropped entirely**, trading a wrong name for lost history |
| final | `owned_by` functional; `owned_by --> Duc` **superseded**, `owned_by --> Mai` current with `valid_from=2026-08-07`; one supersede event in the ledger |

Verified on the final store: default recall answers Mai and only Mai; `include_superseded=True`
returns Duc flagged superseded and pointing at Mai's relation id; `history` holds the supersede
event. So `currency` and `history` are now demonstrated on the **automatic** path, not only through
direct tool calls.

**What is *not* established about `valid_from` on the live path.** `states_later_value` (the backfill
fix) only decides anything when *both* facts carry `valid_from`; otherwise it falls through to write
order. Two live runs, with the previous owner mentioned last and then first:

| run | Duc `valid_from` | Mai `valid_from` | written first | outcome |
| --- | --- | --- | --- | --- |
| previous owner mentioned last | `None` | 2026-08-07 | Duc | Mai current, correct |
| previous owner mentioned first | 2026-08-07 | 2026-09-07 | Duc | Mai current, correct |

The outcome was right both times, but in neither run was the guard the deciding mechanism: in the
first only one side had a date, and in the second write order happened to agree with date order.
**The guard is proven by the benchmark case and unexercised in production.** Worse, the dates are
approximate — the second run gave Mai *today's* date although the exchange says she took over "last
month", and dated Duc's tenure from the day it ended. So a genuinely out-of-order capture (learn the
2025 owner, then learn the 2024 one) is not yet known to come out right on the automatic path. A
capture-path benchmark tier (next step 1) is what would settle it.

Still open, found in the same runs and **not** fixed:

- Capture writes the user's hard rule to the `user` Dataset as a **bare entity with no relations**,
  which `remember` itself warns about ("entities alone are weak memory"). The capture prompt does not
  act on that warning. The hint hook does surface it, so it is a quality gap rather than a hole.

## Next steps, in priority order

1. **A `maintained/` tier that drives the capture path.** The suite tests the tools directly and the
   capture/currency gap above was invisible to it — two halves each correct, not connected. A case
   that runs a transcript through `hooks/capture.py` and then asserts on the store would have caught
   it, and would keep catching it. Needs a model call, so it belongs in a second tier, not in the
   ~1 s CI suite.
2. **A model-graded tier for `maintained/`.** The suite proves the store hands over the lesson and
   flags the contradiction; it cannot show the host model *acts* on either. That needs a judge and is
   the honest remaining half of the `reuse` and `conflict` claims. Fold in (1).
3. **Teach capture to give the `user` Dataset relations, not bare entities** — the one quality gap
   left open above.
4. **One model-matched LoCoMo run** (`--answerer sonnet --judge sonnet`, same 160 sampled questions,
   new `--tag`) to retire the "flattering small answerer" confound, then stop touching LoCoMo. Not
   started: it shares the interactive usage limit, so it will pause whatever session launches it.
   Item 1 of the previous list — the k=20 headline sample — **was already complete**: 160 rows,
   147 correct, 91.9, in `RESULTS.md`.
5. **Real-project soak.** Run memoose on its own development and report what it gets wrong. The two
   bugs above were both found by one live run, which is the argument for doing this continuously
   rather than in bursts.
6. **Consider LongMemEval** (mem0 reports 94.4) as a second, less saturated retrieval dataset — lower
   priority than everything above, since it measures the half we are already at parity on.

## Traps already hit, do not rediscover

- A usage limit mid-run once recorded the limit error as 1,492 answers. The harness now pauses and
  retries on limits and never writes a failed call as a row.
- Claude Code must run with cwd outside the repo, with `--mcp-config … --strict-mcp-config`, because
  the plugin manifest pins `MEMOOSE_DATA_DIR` and a project-level config inside the repo clashes.
- `pkill -f run_locomo` from inside a Claude Code session kills the agent's own shell. Kill by PID.
- Parallel agent-ingest sessions write one SQLite file; embeddings are computed outside the write
  transaction and the store has a 60 s busy timeout so they do not deadlock.
- An absolute threshold on a bm25 score is a bug waiting to happen: bm25 is corpus-relative and
  collapses toward 0 on a small index. Gate on corpus size, or on token overlap, not on a bare score.
- `stats()["relations"]` counts **only non-superseded** rows; superseded ones are in
  `stats()["superseded_relations"]`. "Nothing was deleted" is the sum of the two.
- The provenance table's payload column is `payload`, not `data`.
- Telling an extraction prompt what *not* to do is half an instruction. "Do not invent
  `previously_owned_by`" made capture drop the old owner instead. Say what to produce as well.
