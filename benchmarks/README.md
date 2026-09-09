# Benchmarks

Everything here runs against LoCoMo, the standard conversational-memory benchmark, in two tiers.

| suite | asks | model | wall time | cost | run when |
| --- | --- | --- | --- | --- | --- |
| `locomo/retrieval_bench.py` | does the gold evidence come back (recall@k) | none | ~5 min | $0 | every change |
| `locomo/run_locomo.py` | end-to-end judged answer accuracy | answerer + judge | hours | ~$85 full, ~$9 sampled | rarely |

**The judged score is the full 1,540 questions** — `full-haiku-k20`, September 2026, 90.4 at 4,699
mean prompt tokens, $88.55. It is not re-run on every change: the model-free retrieval benchmark is
what catches a retrieval regression between commits, at $0 and five minutes.

The consequence for reading these numbers: **every published memory-system score is LLM-as-judge**,
so recall@k lines up against nobody and exists only to catch our regressions. The judged score is
comparable in kind, but ours is sampled and uses a smaller answerer than the systems it sits beside,
and the 2026 LoCoMo leaderboard is mostly self-reported claims on differing model stacks — ZeroMemory
96.1 and Zep 94.7 are both above us and both unverified, and third-party testing put Zep at 75.1 on
the same benchmark. Neither of our numbers is a claim to have won anything.

LoCoMo asks *can you find a fact that was stated once*. It does not ask whether a body of facts stays
trustworthy as it changes — a fact was revised, two sources disagree, where did this come from — which
is what memoose is built for. Designing an eval for that which other systems can run is an open
problem and a roadmap item, not a result we have.

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
| ZeroMemory | 96.1 | self-reported, unverified |
| Zep (vendor claim) | 94.7 | self-reported |
| mem0 (2026 algorithm, top-200) | 92.5 | mem0's own harness, gpt-4o class answerer |
| ByteRover | 92.2 / 96.1 | vendor published conflicting figures |
| Dakera | 88.2 | self-reported, no LLM reranking |
| Zep (third-party) | 75.1 | independently tested on the same benchmark |
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
uv run python benchmarks/locomo/retrieval_bench.py --k 20                       # model-free, all 10 conversations
uv run python benchmarks/locomo/run_locomo.py --conv 0 --ingest chunks --k 20    # LLM judge, one conversation
uv run python benchmarks/locomo/run_locomo.py --conv 0 --ingest agent --k 20     # real skill-driven ingest
```

Only the LoCoMo LLM-judge run needs credentials or patience; `retrieval_bench.py` needs neither. LoCoMo runs resume: rerunning with the same `--tag` skips finished questions, and a
usage limit pauses the run rather than corrupting it. The LoCoMo dataset is downloaded on first use,
not committed.
