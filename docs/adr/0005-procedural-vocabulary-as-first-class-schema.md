---
status: accepted
extends: ADR 0004 (keeps procedures in the same graph); supersedes ADR 0004 §2 (lexical localisation)
source: Lu, Chen, Wu, Arik. "Procedural Graphs: Self-Evolving Execution Structures for LLM Agents." arXiv:2609.09153, Google, 2026.
---

# The paper's procedural vocabulary becomes first-class schema and surface, and the agent declares its own Position

ADR 0004 adopted Procedural Graphs by convention: a `Procedure` type, transitions as ordinary
relations with `When <condition>: <guidance>. Avoid: <pitfall>.` packed into one description, and a
hook that guessed the agent's position by lexically matching its last shell command against
Procedure names. Eight days of use showed the convention was not enough. Nothing in the Engine
could answer "what comes next from here"; only the hook could, with its own sqlite queries. The
packed sentence could not be queried, revised one attribute at a time, or validated. The lexical
matcher fired on token overlap and steered the agent toward an unrelated procedure. Nothing recorded
where the agent was or how a session ended, so the contrastive distillation ADR 0004 left to a skill
rule had no trace to contrast. And the hotspot rule flagged every branching Procedure as a
conflict to judge.

## Decision

1. **One graph, still.** Transitions stay Facts between two Procedures. No second store or schema.
   Three nullable columns on `relations`, `condition`, `advice` and `pitfall`, hold the paper's
   edge attributes. They are null on every non-procedural relation. `remember` accepts them as
   `--when`, `--do`, `--avoid`; existing packed descriptions are parsed into them once on upgrade.
2. **Guidance is an Engine method, a tool and a command.** `guidance(procedure)` returns the
   outgoing Transitions two hops out, grouped by hop, superseded excluded, with their attributes.
   It ranks and chooses nothing. The host model reads it with the query and its history and decides.
   The hook cannot import the Engine (hooks are stdlib only), so it mirrors the same walk over the
   same tables, and a test asserts the two agree.
3. **The agent declares its Position; the lexical matcher is gone.** A Session turn may carry the
   Procedure the agent is at. Guidance is keyed on the latest declared Position of the open Session
   and on nothing else. No declared Position means no Guidance. Silence is preferred to a wrong
   steer, which is the paper's own choice: exact match or nothing.
4. **A Session ends with an Outcome**: succeeded, failed, or abandoned. The Session's Positions in
   order form its Trace. `session_end` returns the Trace and, when the Outcome was failed or
   succeeded after a failure, says a procedural distillation is owed, the way it already says a
   lesson distillation is owed. Each Transition's traversals accumulate per Outcome and are shown
   with Guidance and in `history` as evidence for the model that refines the chain.
5. **A branch is not a Hotspot.** The hotspot rule skips subjects whose several values are all
   Transitions from a Procedure.
6. **Dismissal widens** to cover a declined change to a Transition, so the refiner sees what was
   already tried and rejected. Same ledger, same tool.

## What we did not adopt

- **A validation gate**, still. The per-Outcome counts make a gate possible for the first time, and
  we show them as evidence rather than enforce them. The paper's gate needed twenty held-out
  episodes per decision; a project has one run at a time. Revisit as a warning on `supersede` once
  real counts exist.
- **A guidance model call.** ADR 0001 holds. The host model is the guidance model and the refiner.
- **Procedures written by the background keeper.** A wrong Transition steers future work; the
  small model that captures facts in the background does not author them. Foreground only, for now.
- **Named procedure graphs.** Procedures are flat per Dataset. Two-hop expansion bounds the wander;
  a grouping concept waits until a project holds more than one chain and the wander is observed.

## Consequences

The vocabulary in CONTEXT.md gains Transition, Condition, Advice, Pitfall, Start, Position, Trace
and Outcome, and the skills, the CLI help, the MCP tool descriptions and the viewer use those words
and no others. The hook loses its transcript parsing and its matcher; it reads one Position and walks from it. Guidance now
depends on the agent declaring its Position, which the skills must make routine; if they fail to,
the symptom is silence, not misdirection. Schema upgrades are additive and idempotent, as before.
