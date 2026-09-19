---
name: memoose-sessions
description: Track a working session in memoose and distill it into lessons at the end. Use at the start of a task (load standing rules and preferences), at each step of a multi-step task (declare your Position and read the guidance), whenever the user states a goal, rule, preference, or environment fact, and when a task or conversation ends (declare the outcome, distill lessons).
---

# Sessions in memoose

A session is one conversation's short-lived memory: turns plus typed context entries. At the
end it is distilled into a few durable lessons that join the permanent graph. memoose stores and
packs; you curate and write.

## At the start of work

1. `session_start(session_id?)`. Use a stable id per conversation if the host gives you one.
2. Read `standing_context` (goals, rules, preferences, lessons_learned, tool_rules,
   environment_facts) and `recent_lessons`. Follow the rules and preferences without being asked.
3. `recall` anything the task depends on.

## During work

Record, do not narrate. Use `session_set_context(session_id, section, content, confidence)`:

| section | put here |
| --- | --- |
| `goals` | what the user is trying to achieve in this session |
| `rules` | constraints the user states ("never force-push", "tests before commit") |
| `preferences` | style and tooling preferences ("uv not pip", "short answers") |
| `environment_facts` | facts about the machine, repo, services discovered while working |
| `workflow_state` | where a multi-step task stands, so a later session can resume |
| `tool_rules` | how a specific tool must be used here |
| `success_patterns` / `failure_lessons` | what worked or failed and why |
| `feedback` | `+Name` / `-Name` to raise or lower how strongly an entity is recalled |

Replace an outdated entry with `retire_entry_id` instead of adding a second one.
Add turns with `session_add_turn` only for exchanges worth distilling later: decisions,
discoveries, corrections. Not every message.

### Where you are

When the work is a multi-step task, declare your **Position** on the turn that reaches a step
memory knows: `session_add_turn(session_id, "assistant", "tests are green", position="run the test suite")`
(CLI: `memoose session turn <id> --text ... --at "run the test suite"`). The reply carries the
**Guidance** from there: the Transitions two hops out with their Condition, Advice, Pitfall and how
past runs ended. Read it, then decide; it is memory, not an instruction. Declaring is what builds
the session's **Trace**, and the Trace is the only thing a later distillation can learn a procedure
from. If the step is not a Procedure yet, the call says so; remember it first if the chain is worth
keeping, otherwise leave `position` off.

## At the end of work: distillation

1. `session_timeline(session_id)`. It returns batches, `prior_lessons`, and the rules below.
2. **Curate** (per batch): propose lessons that are general beyond this session, actionable next
   time, supported by what actually happened, and not already in `prior_lessons`. Short title,
   one to three sentences, the evidence line. Fewer and sharper beats many. Never invent.
3. **Write or reject** (per lesson): `recall` related lessons and facts. Reject if a prior lesson
   already says it or the evidence is thin. Otherwise write the text so it stands alone and list
   the entities it applies to (systems, technologies, people, conventions).
4. `publish_lessons(session_id, lessons)` with `applies_to` names and `entity_types` for any
   name not yet remembered.
5. `session_end(session_id, outcome)` with the **Outcome**: `succeeded`, `failed`, or `abandoned`
   (CLI: `memoose session end <id> --outcome failed`). Every Transition the Trace traversed counts
   it, and the reply returns the Trace and says what to distil from it.

### Lessons about *how*, from contrast

When a session held a failure followed by a success, or the user corrected a step, the lesson is
procedural and belongs in the graph as Procedures and Transitions, not as a sentence. Take the
Trace `session_end` returned and `guidance()` from its first Position, and compare: which
Transition did the failed run take that the successful one did not, or take too early, or skip?
Write the difference as Transitions with `condition`, `advice` and `pitfall` (CLI `--when`,
`--do`, `--avoid`). If a Transition memory already holds is what led astray, `supersede` it with
the corrected one rather than adding a second; the failed route stays queryable as history. If the
chain was right and the run failed for another reason, `dismiss("transition:<id>", reason)` so the
next pass does not re-judge it. A Transition with several `failed` and no `succeeded` counts is
the first place to look. This is how a procedure improves from experience without anyone editing
it by hand; the store counts, you judge.

Ask before distilling anything personal the user did not ask you to keep.
