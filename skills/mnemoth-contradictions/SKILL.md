---
name: mnemoth-contradictions
description: Judge and resolve conflicting memories in mnemoth. Use when remember returns hotspots or a warning about contradiction_candidates, when recall shows facts flagged contested or several values for one relation, or when the user says a stored fact is wrong or outdated.
---

# Contradictions in mnemoth (adapted from cognee)

mnemoth never decides what conflicts. It gives you the candidate facts; you judge; you record
the judgment with `mark_contradiction` or `supersede`. Nothing is deleted: superseded facts stay
in history and leave default recall.

## Procedure

1. Call `contradiction_candidates` with the entity names involved (or the relation ids from
   `remember`). Read `hotspots` first: one subject holding several objects for the same relation.
2. For each pair decide:
   - **Superseded in time**: the newer fact replaced the older one (a new owner, a new database,
     a moved team). Call `supersede(old_relation_id, new_relation_id, reason)`. Prefer this
     whenever `valid_from`, `updated_at`, or the evidence shows an order.
   - **Genuine contradiction**: both claim to be current and cannot both be true. Call
     `mark_contradiction(first, second, reason, confidence)`, then tell the user which two facts
     conflict, cite their `evidence`, and ask which is right. When they answer, `supersede` the
     wrong one with their answer as the reason.
   - **Compatible**: do nothing. Many-valued relations (`uses`, `knows`, `depends_on`) legitimately
     hold several objects.
3. If a relation is single-valued by nature (`owned_by`, `current_version`, `deployed_in`,
   `reports_to`), call `declare_functional_relations([...])` once. From then on new assertions
   supersede old ones automatically and you will not be asked again.

## Rules for judging (cognee's contradiction rules)

Two facts contradict only when they cannot both be true at the same time about the same
subject: mutually exclusive values, direct negations, logically incompatible statements.

Do not report:
- facts that are different but compatible (additional, unrelated information),
- a more specific and a less specific version of the same fact,
- duplicates or paraphrases.

Confidence: 0.9+ when the relation is obviously single-valued and both facts are explicit;
0.6–0.8 when it depends on interpretation; below 0.6, do not mark, ask the user instead.

## Reading recall output

`contested: true` means an open contradiction touches the fact. `superseded: true` appears only
when you pass `include_superseded=true`; use that for "what did we used to..." questions.
`history(relation_id=...)` shows every assert and supersede with time and evidence.
