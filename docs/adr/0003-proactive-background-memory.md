---
status: accepted
extends: ADR 0001 (adds a third surface; does not replace skills + MCP)
---

# Memory also maintains itself: hooks, plus skill-directed background jobs on a small model

Under ADR 0001 alone, memory is *available* to the agent but never *automatic*: nothing is stored
unless the agent chooses to call `remember`, and nothing is recalled unless it chooses to call
`recall`. In practice that is where memory plugins fail. The agent is busy doing the user's actual
task, so the bookkeeping is the first thing skipped, and when it does happen it interrupts the main
conversation to do it.

Skills plus MCP remain the core and stay fully functional on their own. We **add** two mechanisms on
top, neither of which is required for correctness:

1. **Hooks, where the host has them.** Host lifecycle events drive capture and recall without the
   agent deciding to: context injected at session start, facts extracted when a turn ends, memory
   rescued before compaction discards it. Claude Code command hooks take `async: true`, which runs
   in the background without blocking and without timeout enforcement, and `asyncRewake` to surface
   a failure later. They ship in a reverse-domain namespace, which the agent-plugins.org spec
   reserves for exactly this, so the portable core is untouched.
2. **Skill-directed background jobs.** The skills tell the host agent to *delegate* memory work to a
   background subagent on a small model rather than doing it inline. This needs no hooks at all, so
   it works on any host with subagents, and it is how the heavier maintenance runs: distilling a
   session into lessons, cross-connecting entities, consolidating duplicates, refreshing summaries.

Three properties define the result:

- **Fast.** Memory work never blocks the conversation. It runs in the background, in a hook or a
  delegated job, and the user waits for nothing.
- **Cheap.** Extraction and maintenance run on a small model — Haiku, or whatever small model the
  host offers — not the model driving the conversation. Plugin-shipped subagents pin one per agent
  through `model:` frontmatter, so the expensive model never spends tokens on bookkeeping.
- **Seamless.** The agent does not have to remember to remember. Explicit tool calls still work and
  are still the documented path; they are simply no longer the only one.

The no-API-key principle of ADR 0001 is untouched, and it is why this works at all: the small model
is the *host's*, on the host's existing auth. A `prompt` or `agent` hook hands work to the host's own
model natively, which is precisely the capability MCP `sampling/createMessage` was meant to provide
and that no host grants. Hooks and delegated subagents give us host-model delegation today, with no
key and no second vendor.

## Consequences

- Capability parity is a rule, not an aspiration: anything automation does must be reachable through
  a tool call, so a host without hooks or subagents loses convenience, never function.
- Automation must be conservative about what it stores. An agent asked to remember stores what the
  user meant; a background observer stores what it saw. Precision rules and a cheap relevance gate
  matter more here than in the pull model, or the graph fills with noise.
- Background capture writes to the same SQLite file as foreground calls, which is why embeddings are
  computed outside the write transaction and the store carries a 60 s busy timeout.
- Anything automation stores must stay visible and reversible: the provenance ledger records the
  actor, and the user must be able to see and delete what was captured without having to ask.
