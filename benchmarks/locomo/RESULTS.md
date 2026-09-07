# LoCoMo results

Protocol: mem0 memory-benchmarks (categories 1–4, binary LLM judge, mem0's answerer and judge prompts verbatim).
Host model via Claude Code `claude -p`. Retrieval = mnemoth `recall` (auto-routed mode, `limit=k` per channel).

## Model-free retrieval (evidence recall@k, all 10 conversations, 1,540 questions)

| embedder | k | overall | multi-hop | temporal | open-domain | single-hop |
| --- | --- | --- | --- | --- | --- | --- |
| fastembed bge-small | 20 | 0.876 | 0.689 | 0.919 | 0.579 | 0.956 |
| hash (no model) | 20 | 0.804 | 0.561 | 0.857 | 0.441 | 0.905 |

## LLM judge

| run | conversations | ingest | k | answerer | judge | n | score | multi-hop | temporal | open-domain | single-hop | mean prompt tokens | cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pilot-chunks-k20-haiku | 0 | chunks (no model) | 20 | claude-haiku-4-5 | claude-haiku-4-5 | 152 | **94.7** | 90.6 | 100.0 | 100.0 | 92.9 | 4,941 | $8.34 |
| sample16-chunks-k20-haiku | all 10 (16 sampled each, seed 1) | chunks (no model) | 20 | claude-haiku-4-5 | claude-haiku-4-5 | 160 | **91.9** (95% CI 86.6–95.2) | 92.6 | 96.9 | 66.7 | 93.3 | 4,728 | $8.61 |
| full-chunks-k20-haiku (partial, conv 0–4) | 0–4 | chunks (no model) | 20 | claude-haiku-4-5 | claude-haiku-4-5 | 676 | 90.2 | 88.7 | 94.9 | 60.9 | 92.8 | ~4,700 | — |
| sample16-chunks-k30-haiku (partial, conv 0–6) | 0–6 (16 each) | chunks (no model) | 30 | claude-haiku-4-5 | claude-haiku-4-5 | 97 | 89.7 | — | — | — | — | ~6,200 | $6.5 |

Published (all 10 conversations): mem0 2026 92.5 (top-200, gpt-4o class), Zep 75.1, full-context ~73, mem0 2025 66.9.
mem0 per-category (avg top_10–200): single-hop 91.2, multi-hop 91.3, temporal 92.0, open-domain 72.7, mean 6,956 prompt tokens.

**Read**: the stratified 160-question sample puts mnemoth level with mem0 overall (91.9 vs 92.5, inside the
interval) while showing 32% fewer prompt tokens, ahead on temporal and single-hop, behind only on
open-domain. Open-domain failures are needle retrieval misses (a gold such as "Jo", "Indiana", or
"Nintendo Switch" lives in one turn that never surfaces): every question saturates the 20-chunk cap, so the
budget, not the ranking, is the binding constraint. `chunks` ingest is the model-free floor of the system;
the graph channel that should answer needle questions is empty in it (1 fact per question) and is what the
skill-driven `agent` ingest fills.

## Retrieval sweep (model-free, all 10 conversations, fastembed)

| turns per chunk | k | evidence recall | multi-hop | temporal | open-domain | single-hop | prompt tokens |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | 20 | 0.876 | 0.688 | 0.919 | 0.579 | 0.956 | ~4,730 |
| 2 | 20 | 0.806 | 0.581 | 0.844 | 0.504 | 0.900 | — |
| 2 | 40 | 0.879 | 0.712 | 0.914 | 0.587 | 0.955 | — |
| 3 | 30 | 0.894 | 0.727 | 0.930 | 0.624 | 0.965 | — |
| **4** | **30** | **0.906** | 0.768 | 0.930 | 0.635 | 0.974 | **~6,130** |
| 6 | 30 | 0.926 | 0.806 | 0.962 | 0.686 | 0.979 | ~8,180 |
| 4 | 40 | 0.932 | 0.824 | 0.950 | 0.702 | 0.987 | ~7,500 |

Every question saturates the chunk cap, and raising it lifts *evidence recall* monotonically. **It does
not lift the judged score.** The same 97 sampled questions scored at k=20 and k=30 give:

| | k=20 | k=30 |
| --- | --- | --- |
| judged score (paired, n=97) | 90.7 | 89.7 |
| evidence recall (all 10 conv) | 0.876 | 0.906 |
| prompt tokens | ~4,730 | ~6,200 |

Discordant pairs: 2 only-k20, 1 only-k30, **McNemar exact p = 1.00**. Retrieval depth is therefore *not*
the bottleneck, and the extra ~30% of context is wasted. **k=20 stays the default.**

This is the central lesson of the sweep: evidence recall is a proxy, and past ~0.88 it decouples from the
judged score. The reason is visible in the failures — of 13 wrong answers in the 160-question sample, only
3 said the memories lacked the information; the other 10 answered confidently and wrong. Above ~90 the
benchmark is dominated by answerer reasoning and by disputable LoCoMo gold answers, not by memory. Tuning
retrieval further optimises the wrong quantity.

## Two-arm test: does the graph beat plain chunk retrieval?

Same 45 questions (conversation 0, multi-hop + open-domain), same retrieval budget (k=30), same answerer
and judge (claude-haiku-4-5). The only difference is ingest.

| arm | ingest | graph built | score | multi-hop | open-domain | prompt tokens | facts returned |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A | `chunks` (deterministic, no model) | 21 entities, 1 relation, 144 chunks | 93.3 | 90.6 | 100.0 | 5,451 | 1.0 |
| B | `agent` (skill-driven `remember`) | 225 entities, 381 relations, 95 chunks | 95.6 | 96.9 | 92.3 | 9,654 | 29.7 |

Because both arms answered the same 45 questions, the paired (McNemar) test is the right one, and it is
unambiguous:

| both right | only chunks | only graph | neither |
| --- | --- | --- | --- |
| 40 | 2 | 3 | 0 |

**Exact two-sided p = 1.00.** The graph does not measurably beat plain chunk retrieval here, and it costs
77% more prompt tokens. The three questions only the graph answered are all multi-hop ("Where did Caroline
move from 4 years ago?", "What kind of art does Caroline make?", "How many times has Melanie gone to the
beach in 2023?"), which is the direction a graph should help; the two only chunks answered are an
open-domain inference and a multi-hop detail. Three against two on 45 questions is noise.

Read this as a scoping result, not a defect. LoCoMo asks needle questions over conversations of 16k–26k
tokens; chunk retrieval already finds the needles, and the answerer does the multi-hop joining itself from
raw text. What the graph is actually for — contradiction detection, temporal supersession, provenance,
cross-session consolidation, typed ontology queries — LoCoMo does not test at all. On this benchmark the
cheaper `chunks` path is the better engineering choice, and that is the configuration reported above.
One conversation is also the limit of this experiment: it has the power to rule out a large effect, not a
small one.

Evidence recall tracks the judged score closely per category (open-domain 0.579 vs 60.9 judged), so this
model-free benchmark is the tuning instrument and the judged run is the confirmation.
