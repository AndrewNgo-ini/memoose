# State of play

Last updated 2026-09-07, after building the maintained-memory benchmark and verifying the proactive
path live.

## What is done

**The port is complete and released (v0.2.0).** cognee's memory core is reimplemented as 24 MCP
tools plus 5 skills, packaged as an Agent Plugin, with no model call anywhere in the library
(ADR 0001) and one SQLite file per Dataset (ADR 0002). 33 tests pass, including one that drives the
server over MCP stdio the way a host does. `claude plugin validate .` passes. Verified end to end
inside Claude Code via `--plugin-dir`. `mnemoth install claude|codex|opencode|cursor` writes one MCP
entry and copies the skills into each host's own locations.

Covered: ontology with OWL/RDF/Turtle import and basic-type collapse, deterministic entity ids and
merge-by-name, functional-relation supersession, contradiction candidates with `contradicts` edges,
the ported regex query router with 8 retrieval modes, memify weights, provenance ledger, sessions
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
| what is live here, what is stored, how to opt out | `skills/mnemoth-onboard/SKILL.md` | — |

Kill switches: `MNEMOTH_HINTS`, `MNEMOTH_AUTO_RECALL`, `MNEMOTH_AUTO_CAPTURE`. Every hook exits 0 on
any failure. 73 tests.

Note for benchmarking: none of this is visible to the LoCoMo harness, which calls the MCP tools
directly and never goes through a hook. The benchmark measures the store and the retrieval, not the
automation.

## What the benchmarking established

Protocol: LoCoMo under mem0's memory-benchmarks methodology, with mem0's answerer and judge prompts
vendored verbatim, Claude Code as the host model. Numbers and tables live in
`benchmarks/locomo/RESULTS.md`; how to run it lives in `benchmarks/SETUP.md`.

1. **Parity, not superiority.** 91.9 on a 160-question stratified sample (95% CI 86.6–95.2) against
   mem0's published 92.5 on the full 1,540, using 32% fewer prompt tokens (4,728 vs 6,956) and a much
   smaller answerer (Claude Haiku 4.5 vs a GPT-4o-class stack). Ahead on temporal (96.9 vs 92.0) and
   single-hop (93.3 vs 91.2), behind on open-domain (66.7 vs 72.7).
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

## The maintained-memory benchmark (roadmap item 3, done)

`benchmarks/maintained/` — 18 cases, 66 assertions, **no model, no API key, ~1 s**, wired into
pytest. It asks the five questions mnemoth claims and LoCoMo cannot: a fact changed (does recall
return the current one), can the old one still be shown and why it changed, do two disagreeing
sources get reported or silently resolved, does evidence survive, does an earlier session's lesson
come back. Full write-up in `benchmarks/maintained/README.md`.

Result: **18/18 cases, 66/66 checks**, identical on the `hash` and `fastembed` embedders, ~1 s.
Three cases are negative controls (must *not* supersede a multi-valued relation, must *not* flag
compatible facts, must *not* invent evidence) so a system that says yes to everything scores 0 on
them.

**Passing our own suite is not evidence of superiority and the README says so.** Its value is (a) the
claims are now checked on every commit rather than asserted, and (b) what it caught on the first
run, at 14/18 before anything was tuned. Three of those failures were bugs in the cases. One was
real:

> Functional supersession was decided by **write order alone**. Backfilling a fact that was true in
> 2024, after the 2025 value was already known, silently made the 2024 value current again — learning
> the past overwrote the present. Fixed by `states_later_value` in `src/mnemoth/contradictions.py`:
> `valid_from` decides when both facts carry one, and a backfilled arrival is stored as superseded
> history. Write order still decides when a date is missing, and an undated arrival is presumed
> current, so the ordinary path is unchanged.

Pre-fix rows are kept at `benchmarks/maintained/results/baseline-prefix-hash.json`.

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
three surfaces that drive extraction (`hooks/capture.py`'s prompt, `skills/mnemoth/SKILL.md`,
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

Note that `states_later_value` (the backfill fix) is only load-bearing when facts carry `valid_from`,
which is why the same instruction asks for it. Before this, the live path produced no `valid_from` at
all and the fix was inert in production while passing in the benchmark.

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
5. **Real-project soak.** Run mnemoth on its own development and report what it gets wrong. The two
   bugs above were both found by one live run, which is the argument for doing this continuously
   rather than in bursts.
6. **Consider LongMemEval** (mem0 reports 94.4) as a second, less saturated retrieval dataset — lower
   priority than everything above, since it measures the half we are already at parity on.

## Traps already hit, do not rediscover

- A usage limit mid-run once recorded the limit error as 1,492 answers. The harness now pauses and
  retries on limits and never writes a failed call as a row.
- Claude Code must run with cwd outside the repo, with `--mcp-config … --strict-mcp-config`, because
  the plugin manifest pins `MNEMOTH_DATA_DIR` and a project-level config inside the repo clashes.
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
