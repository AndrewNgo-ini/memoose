---
name: memoose-memify
description: Maintain and enrich memoose memory. Use when the user asks to clean up, consolidate, or improve memory, after a large batch of remembers, or periodically: cross-connect co-occurring entities, merge duplicate names, and refresh global-context summaries.
---

# memify in memoose (adapted from cognee)

memify is maintenance over an existing graph. memoose proposes; you judge; you write.

`memoose maintain` runs every pass below at once and prints one worklist, which is the cheapest way
to start: it gathers hotspots, duplicate names, unconnected pairs, stale summaries and undistilled
sessions in a single command, and changes nothing on its own. Use the individual
`memify_candidates` kinds when you want one pass at a time or have no shell.

## Passes

1. **Cross-connect**: `memify_candidates(kind="cross_connect")` lists entity pairs that share
   source chunks but have no relation, with the shared context. Add a relation only when the
   context states a real relationship. Use `cross_connect([...])` with a snake_case name, a
   one-sentence description using both names, and the chunk or file as evidence. Skip pairs that
   merely co-occur.
2. **Consolidate**: `memify_candidates(kind="consolidate")` lists near-duplicate names (same
   tokens, acronym and expansion, similar spelling, same type). Merge only when both names denote
   the same real thing. `merge_entities(keep, drop)` keeps the fuller, more-mentioned name and
   records the other as an alias. When unsure, ask the user; a wrong merge is hard to undo.
3. **Global context**: `memify_candidates(kind="stale_summaries")` returns buckets (one per
   entity type) whose members changed since their summary, with the facts to summarise. Write
   each summary from the listed facts only, in this shape, then `set_bucket_summary`:

   ```
   This bucket is about:
   - <Category>: <names>
   Facts:
   - <self-contained sentence>
   ```

   `global_context()` shows all buckets; `recall(..., mode="summaries")` returns them.

## Weights

Recall rank is multiplied by frequency (how often an entity is re-mentioned) and feedback
(`session_set_context(section="feedback", content="+Name -Other")`). Use feedback when the
user says a memory keeps surfacing wrongly or matters more than it ranks.

## When to run

After ingesting a document or a long session, when recall returns obvious duplicates, or when
the user asks for an overview and `global_context` reports stale buckets.
