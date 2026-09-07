# The maintained-memory benchmark

**18 cases, 66 assertions, ~1 second, no model, no API key, no network.**

Every published memory benchmark scores one question: *can you find a fact that was stated
once?* LoCoMo, LongMemEval, and the mem0 and Zep suites are all shaped that way. That is
retrieval, and retrieval is the easy half. It says nothing about what makes memory hard to
keep for months:

| the question | why it is hard | claim |
| --- | --- | --- |
| A fact changed. Does recall return the current one? | the old fact is still in the store, still matches the query, and often still ranks higher | `currency` |
| Can it still show me the old one, and why it changed? | systems that overwrite cannot; systems that keep everything cannot tell you which is current | `history` |
| Two sources disagree. Does the system say so, or silently pick one? | silently picking is indistinguishable from being right, until it isn't | `conflict` |
| Why do we believe this? Point at the evidence. | evidence has to survive ingestion, ranking, and merging to be worth anything | `provenance` |
| We solved this before. Does the lesson come back? | it has to arrive in a *later* session, unprompted | `reuse` |

mnemoth claims all five ([VISION.md](../../VISION.md)) and, until this suite existed, had
evidence for none of them. Our LoCoMo work showed the knowledge graph does not beat plain
chunk retrieval there (McNemar p = 1.00, at 77% more tokens) — which is a fact about
LoCoMo, not a defect, because LoCoMo never asks any of the five questions above. This
suite asks them.

## Why it needs no model

Each case builds a small history through the real MCP-facing API, then asserts on the
payload the tools return: is this fact's `superseded` flag set, does `superseded_by` point
at its replacement, is `contested` true on both sides, does `evidence` still hold the
`repo://` pointer it was written with, does the second session's `standing_context` contain
the first session's rule. All of that is decidable by reading a dict. No judge, no
sampling, no variance.

The consequence is the point: **it runs on every commit.** It is wired into pytest
(`tests/test_maintained.py`), so a change that quietly breaks supersession fails CI in one
second. An LLM-judged suite cannot do that — which is why nobody runs the existing ones
regularly, and why regressions in exactly these features would go unnoticed.

## Scoring, and why it is not gameable

A case passes only when **every** one of its checks passes. Alongside the positive cases
are three **negative controls**, which fail if the system over-reacts:

- `currency/non-functional-is-not-silently-picked` — a relation that legitimately holds
  many values (`depends_on`) must **not** be superseded. A system that overwrites blindly
  scores well on `currency` and fails here.
- `conflict/compatible-facts-are-not-flagged` — three facts that merely differ must **not**
  be reported as a clash. A system that flags everything passes `conflict/hotspot-surfaced`
  and fails here.
- `provenance/evidence-is-not-invented` — a fact stored without a source must come back
  with an empty one, not a plausible-looking pointer.

Without those, the suite would reward a system that says yes to everything.

## Results

Run with `--embedder hash` (deterministic, no download) and `--embedder fastembed` (what
ships by default). Both score identically, as they should: these are questions about
semantics, not ranking.

| embedder | cases | checks | negative controls | wall time | model calls | cost |
| --- | --- | --- | --- | --- | --- | --- |
| hash | **18/18** | 66/66 | 3/3 | 1.05 s | 0 | $0 |
| fastembed bge-small | **18/18** | 66/66 | 3/3 | 0.96 s | 0 | $0 |

**Read this honestly.** A suite written for our own system, which our own system passes, is
*not* evidence that mnemoth is better than anything. It is evidence that the claims are now
checked instead of asserted, and that they stay checked. The number that would mean
something is what *another* system scores, and the cases are written against behaviour any
memory system could implement, not against our API shape — porting them is a day's work.
We would rather publish a benchmark that someone beats us on than keep claiming things
nothing measures.

### What the first run found

The suite is worth its keep because of what happened the first time it ran, before any of
it was tuned: **14/18**. Three failures were bugs in the cases themselves. The fourth was
real, and is now fixed:

> `currency/late-arriving-old-fact` — for a functional relation, supersession was decided by
> *write* order alone. Backfilling a fact that was true in 2024, after the 2025 value was
> already known, silently made the 2024 value current again. Learning the past overwrote the
> present.
>
> Fixed in `src/mnemoth/contradictions.py` (`states_later_value`): when both facts carry
> `valid_from`, that decides which is current, and the arriving fact is stored as superseded
> history when it predates what is already known. Write order still decides when a date is
> missing, and an undated arrival is presumed current, so the ordinary path is unchanged.

That bug would never have shown up on LoCoMo, which has no notion of a fact being revised,
and it is exactly the failure a developer would hit in month two of using memory on a real
project.

## Running it

```sh
uv run python benchmarks/maintained/run_maintained.py                  # ~1 s
uv run python benchmarks/maintained/run_maintained.py --embedder fastembed
uv run python benchmarks/maintained/run_maintained.py -v               # show passing checks
uv run python benchmarks/maintained/run_maintained.py --claim conflict --claim currency
uv run python benchmarks/maintained/run_maintained.py --case currency/late-arriving-old-fact -v
uv run python benchmarks/maintained/run_maintained.py --json out.json  # full machine-readable result
uv run pytest tests/test_maintained.py -q                              # as CI runs it
```

Exit code is 0 only when every case passes. Stored results are in `results/`;
`baseline-prefix-hash.json` is the pre-fix 14/18 run, kept as the record of what the suite
caught.

## Adding a case

Cases live in `cases.py`, one function per case, registered with `@case(claim, id, asks)`:

```python
@case("currency", "my-case", "The plain-English question this case asks.")
def _(ds) -> list[Check]:
    ds.remember(entities=[...], relations=[...])
    res = ds.recall("...", mode="facts", limit=20)
    return [Check("what must be true", condition, "detail shown only when it fails")]
```

`ds` is a real `Dataset` on a throwaway SQLite file, one per case, so cases cannot
contaminate each other. Pass `negative=True` when the case asserts the system does *not*
do something. Keep every check decidable without a model — if a check needs judgment, it
belongs in a different suite.

## What this suite does not cover

- Whether the host model *acts* on a lesson it was handed, or *notices* a contradiction it
  was shown. That needs a judge, and is a separate tier we have not built.
- Retrieval quality over conversation logs. That is LoCoMo's job; see
  [`../locomo/RESULTS.md`](../locomo/RESULTS.md).
- The hook layer. Like the LoCoMo harness, this suite calls the tools directly, so it
  measures the store and not the automation on top of it.
