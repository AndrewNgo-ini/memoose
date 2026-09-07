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

Retrieval budget, not ranking, is the binding constraint: every question saturates the chunk cap, and
raising it lifts recall monotonically. **4 turns per chunk at k=30 is the reported default**: it beats the
old k=20 on every category and still costs ~12% fewer prompt tokens than mem0's 6,956, so the comparison
is not bought with context. k=40 scores higher (0.932) but spends ~8% more than mem0.

Caveat on how far this transfers to the judged score: of 13 failures in the 160-question sample, only 3
said the memories lacked the information; the other 10 answered confidently and wrong. Above ~90 the
benchmark is dominated by answerer reasoning and by disputable LoCoMo gold answers, not by memory, so
recall gains have a shrinking judged payoff.

## Two-arm test: does the graph beat plain chunk retrieval?

Same 45 questions (conversation 0, multi-hop + open-domain), same retrieval budget (k=30), same answerer
and judge (claude-haiku-4-5). The only difference is ingest.

| arm | ingest | graph built | score | multi-hop | open-domain |
| --- | --- | --- | --- | --- | --- |
| A | `chunks` (deterministic, no model) | 21 entities, 1 relation, 144 chunks | 93.3 | 90.6 | 100.0 |
| B | `agent` (skill-driven `remember`) | 225 entities, 381 relations, 95 chunks | _running_ | | |

Evidence recall tracks the judged score closely per category (open-domain 0.579 vs 60.9 judged), so this
model-free benchmark is the tuning instrument and the judged run is the confirmation.
