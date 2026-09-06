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
| pilot-chunks-k20-haiku | 0 | chunks (no model) | 20 | claude-haiku-4-5 | claude-haiku-4-5 | 152 | **94.7** | 90.6 | 97.3 | 100.0 | 94.3 | 4,939 | $8.44 |

Published (all 10 conversations): mem0 2026 92.5 (top-200, gpt-4o class), Zep 75.1, full-context ~73, mem0 2025 66.9.

Rows for the full 10-conversation run and the agent-ingest run are appended when they complete.
