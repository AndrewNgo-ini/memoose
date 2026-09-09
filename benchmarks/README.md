# Benchmarks

Two different questions, and it matters which one a number answers.

**Can you find a fact that was stated once?** That is retrieval, and it is what every published
memory benchmark scores — LoCoMo, LongMemEval, the mem0 and Zep suites. See [LoCoMo](#locomo) below.

**Does a body of facts stay trustworthy as it changes?** A fact was revised; two sources disagree;
where did this come from; we learned this before. That is what memoose claims and what makes memory
hard to keep for months, and no published benchmark asks it. So we built one:
**[`maintained/`](./maintained/README.md)**.

| suite | asks | model | wall time | cost |
| --- | --- | --- | --- | --- |
| [`maintained/`](./maintained/README.md) | does memory stay true as facts change | none | ~1 s | $0 |
| `locomo/retrieval_bench.py` | does the gold evidence come back (recall@k) | none | ~5 min | $0 |
| `locomo/run_locomo.py` | end-to-end judged answer accuracy | answerer + judge | ~1.5 h | ~$9 |

Only the first two can run in CI, and `maintained/` is wired into pytest for exactly that reason.

## Maintained memory

18 cases, 66 assertions, no model, about a second. It asserts on the payloads the MCP tools return —
is this fact flagged `superseded`, does `superseded_by` point at its replacement, is `contested` true
on *both* sides, did the `repo://` evidence pointer survive, does the second session's standing
context contain the first session's rule. Three cases are negative controls that fail if the system
over-reacts, so a system that flags everything cannot pass.

memoose scores **18/18** on both embedders. That is not evidence memoose is better than anything —
it is our own suite — and [`maintained/README.md`](./maintained/README.md) says so plainly, and
restates all 18 cases as API-neutral requirements so another system can be scored on them. The
evidence it did produce is a bug: on its first run it scored 14/18 and caught functional supersession
being decided by write order alone, so backfilling a 2024 fact after the 2025 value was known
silently made 2024 current again. LoCoMo could never have shown that, because LoCoMo has no notion
of a fact being revised.

## How the LoCoMo numbers are produced

memoose has no model of its own, so the LLM-judge path measures two things separately:

1. **Retrieval quality without any model** (`locomo/retrieval_bench.py`): ingest LoCoMo turns as
   chunks, ask `recall` every question, and check whether the gold evidence turns come back.
   Runs in seconds; used to tune ranking, chunking, and modes.
2. **End-to-end LLM-judge score** (`locomo/run_locomo.py`): the protocol from
   [mem0ai/memory-benchmarks](https://github.com/mem0ai/memory-benchmarks), with their answerer and
   judge prompts vendored verbatim (`locomo/mem0_prompts.py`), so the memory system is the only
   variable. The host model is Claude Code (`claude -p`), exactly how memoose ships.

## LoCoMo

10 multi-session conversations, 1,986 questions; categories 1–4 are scored (1,540 questions):
multi-hop, temporal, open-domain, single-hop. Category 5 (adversarial) is excluded by every
published result because its gold answers are missing. Score is the percentage the judge labels
CORRECT.

### Published numbers (LLM judge, categories 1–4)

| system | overall | notes |
| --- | --- | --- |
| mem0 (2026 algorithm, top-200) | 92.5 | mem0's own harness, gpt-4o class answerer |
| Zep | 75.1 | Zep's re-run of the mem0 study |
| full-context baseline | ~73 | whole conversation in the prompt |
| mem0 graph (2025) | ~68 | mem0 paper |
| mem0 (2025) | 66.9 | mem0 paper |

### memoose

Two ingest paths are reported. `chunks` stores conversation windows deterministically (no model:
it is the RAG-style floor of the system). `agent` is the real product path: a Claude Code run with
the memoose plugin reads each session and calls `remember` itself, so the graph, dates, and
evidence come from skill-driven extraction.

Full tables live in `locomo/RESULTS.md`. Headline findings:

- 91.9 on a 160-question stratified sample (95% CI 86.6–95.2) vs mem0's published 92.5, at 4,728
  prompt tokens vs their 6,956, with a much smaller answerer (Claude Haiku 4.5).
- The graph does not beat plain chunk retrieval here (paired McNemar p = 1.00) and costs 77% more
  tokens. LoCoMo does not test what the graph is for.
- Raising the retrieval budget lifts evidence recall but not the judged score (p = 1.00), so k=20 at
  4 turns per chunk is the default.

## Reproduce

See **[SETUP.md](./SETUP.md)** for a fresh machine (dependencies, headless Claude Code auth, dataset
fetch, and the operational traps). Short version:

```sh
uv sync --extra fastembed --group dev
uv run python benchmarks/maintained/run_maintained.py                            # ~1 s, no model, no key
uv run python benchmarks/locomo/retrieval_bench.py --k 20                       # model-free, all 10 conversations
uv run python benchmarks/locomo/run_locomo.py --conv 0 --ingest chunks --k 20    # LLM judge, one conversation
uv run python benchmarks/locomo/run_locomo.py --conv 0 --ingest agent --k 20     # real skill-driven ingest
```

Only the LoCoMo LLM-judge run needs credentials or patience; `maintained/` and `retrieval_bench.py`
need neither. LoCoMo runs resume: rerunning with the same `--tag` skips finished questions, and a
usage limit pauses the run rather than corrupting it. The LoCoMo dataset is downloaded on first use,
not committed.
