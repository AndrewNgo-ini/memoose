---
name: memoose-upkeep
description: Judge what memoose's store surfaces for maintenance. Use when remember returns hotspots or a superseded warning, when recall shows a fact flagged contested or several values for one relation, when the user says a stored fact is wrong or outdated, when the user asks to clean up or consolidate memory, after a large batch of remembers, or when a session start says upkeep is due.
---

# Upkeep in memoose

memoose never decides what conflicts, what is a duplicate, or what deserves a connection. It
surfaces candidates; you judge; you record the judgment. Nothing is deleted: superseded facts stay
in history and leave default recall, and a declined candidate is remembered so it is not asked again.

`memoose maintain` prints every candidate in one worklist: hotspots, open contradictions, duplicate
names, unconnected pairs, stale summaries, sessions that ended without lessons, and the reasons
behind earlier dismissals. It changes nothing on its own. Without a shell, the tools behind it are
`contradiction_candidates` and `memify_candidates(kind)`.

## Hotspots and contradictions

A hotspot is one subject holding several values for one relation. For each, decide:

- **Superseded in time**: the newer fact replaced the older one (a new owner, a new database, a
  moved team). `supersede(old_relation_id, new_relation_id, reason)`. Prefer this whenever
  `valid_from`, `updated_at` or the evidence shows an order.
- **Genuine contradiction**: both claim to be current and cannot both be true.
  `mark_contradiction(first, second, reason, confidence)`, then tell the user which two facts
  conflict, cite their `evidence`, and ask which is right. When they answer, `supersede` the wrong
  one with their answer as the reason.
- **Compatible**: dismiss it (below). Many-valued relations (`uses`, `knows`, `depends_on`)
  legitimately hold several objects.

If a relation is single-valued by nature (`owned_by`, `current_version`, `deployed_in`,
`reports_to`), `declare_functional_relations([...])` once. New assertions then supersede old ones
automatically and you will not be asked again. Never declare a many-valued relation functional.

Two facts contradict only when they cannot both be true at the same time about the same subject:
mutually exclusive values, direct negations, logically incompatible statements. Do not mark facts
that are different but compatible, a more and a less specific version of one fact, or paraphrases.
Confidence: 0.9+ when the relation is obviously single-valued and both facts are explicit; 0.6 to
0.8 when it depends on interpretation; below 0.6, do not mark, ask the user.

A Procedure with several Transitions (`leads_to`, `triggers`, ...) is a branch, not a hotspot. The
store does not list those, and you should not mark them.

## Duplicates, connections, summaries

1. **Consolidate**: near-duplicate names (same tokens, acronym and expansion, similar spelling, same
   type). Merge only when both names denote the same real thing: `merge_entities(keep, drop)` keeps
   the fuller, more-mentioned name and records the other as an alias. When unsure, ask the user; a
   wrong merge is hard to undo.
2. **Cross-connect**: entity pairs that share source chunks but have no relation, with the shared
   context. Add a relation only when the context states a real relationship, with `cross_connect`:
   a snake_case name, a one-sentence description using both names, and the chunk or file as
   evidence. Skip pairs that merely co-occur.
3. **Global context**: buckets (one per entity type) whose members changed since their summary, with
   the facts to summarise. Write each from the listed facts only, then `set_bucket_summary`:

   ```
   This bucket is about:
   - <Category>: <names>
   Facts:
   - <self-contained sentence>
   ```

   `global_context()` shows all buckets; `recall(..., mode="summaries")` returns them.

4. **Undistilled sessions**: `session_timeline` then `publish_lessons`, per the sessions skill.

## Declining a candidate

Judging a candidate and doing nothing means it comes back next time. When two names are *not* the
same thing, a pair has *no* real relationship, a hotspot's values coexist, or a Transition was right
and the run that failed on it was not: `memoose dismiss <key> --reason "..."` (tool:
`dismiss_candidate(key, reason)`), with the key printed next to the item (`transition:<relation_id>`
for a Transition). The candidate is filtered from later passes and the reason is shown under
`dismissed`. Nothing about the graph changes.

## Weights

Recall rank is multiplied by frequency (how often an entity is re-mentioned) and feedback
(`session_set_context(section="feedback", content="+Name -Other")`). Use feedback when the user says
a memory keeps surfacing wrongly or matters more than it ranks.

## Reading recall output

`contested: true` means an open contradiction touches the fact. `superseded: true` appears only with
`include_superseded=true`; use that for "what did we used to..." questions. `history(relation_id=...)`
shows every assert, supersede and traverse with time and evidence.

## When to run

When `remember` warns, when recall returns obvious duplicates, after ingesting a document or a long
session, when the user asks for an overview and `global_context` reports stale buckets, or when the
session-start context says upkeep is due. On hosts with subagents, hand the pass to `memory-keeper`
so it does not occupy the main conversation.
