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

| turns per chunk | k | evidence recall | multi-hop | temporal | open-domain | single-hop |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | 20 | 0.876 | 0.688 | 0.919 | 0.579 | 0.956 |
| 2 | 20 | 0.806 | 0.581 | 0.844 | 0.504 | 0.900 |
| 2 | 40 | 0.879 | 0.712 | 0.914 | 0.587 | 0.955 |

Evidence recall tracks the judged score closely per category (open-domain 0.579 vs 60.9 judged), so this
model-free benchmark is the tuning instrument and the judged run is the confirmation.
