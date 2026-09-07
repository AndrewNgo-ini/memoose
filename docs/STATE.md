# State of play

Last updated 2026-09-07, at the point of moving benchmark work to a VPS.

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

## Next steps, in priority order

1. **Finish the headline sample at k=20** on all 10 conversations for a clean, comparable number.
   The k=30 run was abandoned once the paired test showed k=30 is not better; its partial rows
   (conv 0–6, 97 questions) are kept for that comparison only.
2. **One model-matched run.** Everything so far used Haiku as answerer; mem0 used a GPT-4o-class
   stack. Run the same 160 sampled questions with `--answerer sonnet` and report both, so the
   comparison is like-for-like rather than flattering in either direction.
3. **Benchmark what the graph is actually for.** LoCoMo cannot show it. A benchmark that would:
   conflicting facts asserted over time (does recall return the current one?), superseded history
   (`include_superseded`), provenance-checkable claims, cross-session lesson reuse. This is the
   honest way to justify the graph, and none of the published memory benchmarks test it.
4. **Consider LongMemEval** (mem0 reports 94.4) as a second, less saturated dataset.

## Traps already hit, do not rediscover

- A usage limit mid-run once recorded the limit error as 1,492 answers. The harness now pauses and
  retries on limits and never writes a failed call as a row.
- Claude Code must run with cwd outside the repo, with `--mcp-config … --strict-mcp-config`, because
  the plugin manifest pins `MNEMOTH_DATA_DIR` and a project-level config inside the repo clashes.
- `pkill -f run_locomo` from inside a Claude Code session kills the agent's own shell. Kill by PID.
- Parallel agent-ingest sessions write one SQLite file; embeddings are computed outside the write
  transaction and the store has a 60 s busy timeout so they do not deadlock.
