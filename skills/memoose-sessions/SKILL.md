---
name: memoose-sessions
description: Track a working session in memoose and distill it into lessons at the end. Use at the start of a task (load standing rules and preferences), whenever the user states a goal, rule, preference, or environment fact, and when a task or conversation ends (distill lessons).
---

# Sessions in memoose (adapted from cognee)

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

## At the end of work: distillation

1. `session_timeline(session_id)`. It returns batches, `prior_lessons`, and the rules below.
2. **Curate** (per batch): propose lessons that are general beyond this session, actionable next
   time, supported by what actually happened, and not already in `prior_lessons`. Short title,
   one to three sentences, the evidence line. Fewer and sharper beats many. Never invent.
3. **Write or reject** (per lesson): `recall` related lessons and facts. Reject if a prior lesson
   already says it or the evidence is thin. Otherwise write the text so it stands alone and list
   the entities it applies to (systems, technologies, people, conventions).
4. `publish_lessons(session_id, lessons)` with `applies_to` names and `entity_types` for any
   name not yet remembered. Then `session_end(session_id)`.

Ask before distilling anything personal the user did not ask you to keep.
