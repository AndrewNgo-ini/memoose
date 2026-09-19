# LongMemEval results

Protocol: mem0's [memory-benchmarks](https://github.com/mem0ai/memory-benchmarks) LongMemEval harness
(`longmemeval_s_cleaned`, user+assistant pair chunks, their answerer and judge prompts vendored in
`mem0_prompts.py`). Host model is Claude Code; ingest is deterministic chunks, no extraction.

## pilot30-k20-haiku (2026-09-16)

30 questions, 5 per type, seed 42 (mem0's default pilot). Haiku answerer and judge, k=20, fastembed.
This is a vibe check, not a score: the 95% CI is 66–93.

| type | score | n |
| --- | --- | --- |
| knowledge-update | 60.0 | 5 |
| multi-session | 40.0 | 5 |
| single-session-assistant | 100.0 | 5 |
| single-session-preference | 100.0 | 5 |
| single-session-user | 100.0 | 5 |
| temporal-reasoning | 100.0 | 5 |
| **overall** | **83.3** (CI 66.4–92.7) | 30 |

Mean prompt 14.3K tokens (mem0 reports 6.8K), retrieval p50 19 ms, $2.80 total. Answer-session hit
100%, gold-turn recall 0.947: every miss had the evidence in the prompt and Haiku miscounted or
picked the wrong candidate (aggregation questions: "how many", "which the most").

Reference: mem0 reports 67.8 (2025) and 94.4 (2026 algorithm, gpt-5 answerer) on all 500.

```sh
uv run python benchmarks/longmemeval/run_longmemeval.py --per-type 5 --k 20 --answerer haiku --judge haiku
uv run python benchmarks/longmemeval/run_longmemeval.py --per-type 5 --k 20 --retrieval-only   # no model
```

### Same 30 questions, mem0's published per-question results (platform, gpt-5, top-200)

| type | memoose (Haiku, k=20) | mem0 (gpt-5, k=200) |
| --- | --- | --- |
| knowledge-update | 3/5 | 5/5 |
| multi-session | 2/5 | 4/5 |
| single-session-assistant | 5/5 | 5/5 |
| single-session-preference | 5/5 | 5/5 |
| single-session-user | 5/5 | 5/5 |
| temporal-reasoning | 5/5 | 5/5 |
| **overall** | **25/30 (83.3)** | **29/30 (96.7)** |

mem0's full-500 file scores 93.4 (their README says 94.4). The gap is entirely in the two
aggregation types; the 20 single-session and temporal questions tie. Different answerer (Haiku vs
gpt-5) and retrieval budget (20 chunks vs 200 facts), so this is a floor for memoose, not a
head-to-head.

### multisession-k20-sonnet: same 5 multi-session questions, Sonnet answerer, Haiku judge

Sonnet 4/5 (Haiku 2/5, mem0 gpt-5 4/5). Both Haiku misses that had the evidence in the prompt
(4 properties, Thrive Market) flip to correct. The remaining miss ("how many doctors", gold 3) is a
retrieval miss: 1 of 5 gold turns came back at k=20, so both answerers count 2. $1.01.
