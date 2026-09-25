---
status: accepted
extends: ADR 0003 (another background job on the host's small model); source: Oh My Pi's advisor (can1357/oh-my-pi, MIT, docs/advisor-watchdog.md)
---

# An Advisor watches the primary step by step and feeds Advisories back into the running turn

ADR 0003 made memory maintain itself, but every background job only writes to the store. The
capture keeper runs once a turn has ended, and nothing it learns reaches the agent until a later
prompt happens to match. Memory could see that the agent was about to repeat a Pitfall or break a
stored rule, and had no way to say so while it still mattered.

Oh My Pi solves the general form of this with an advisor: a second agent with its own context and
read-only tools that receives the primary's transcript incrementally and calls one `advise` tool.
The severity of each note decides when the orchestrator delivers it. We port that mechanism onto
Claude Code's hooks. Under this ADR the Advisor is the only background job that talks back to the
primary.

## Decision

1. **Trigger and cursor.** An async `PostToolUse` and `Stop` hook (`advisor.py`) keeps a cursor
   into the primary's transcript. Each review sends only the complete lines added since the
   cursor, including tool calls and results. It drops the Advisor's own Advisories when they echo
   back, and ends a mid-turn delta with `[in progress — more steps follow]`.
2. **Drain, no daemon.** One review runs per session at a time, behind a lock. The holder keeps
   reviewing until the cursor reaches the transcript's end, so steps that arrive during a review
   are batched into the next one.
3. **One Advisor conversation per session.** `claude -p --session-id` starts it, `--resume`
   continues it, and it restarts after a fixed number of reviews. It runs outside the project
   directory (reaching the project through `--add-dir`) so its transcripts stay out of the user's
   session list. Its tools are an allowlist: Read, Grep, Glob, `memoose recall`, and `advise.py`.
4. **Policy.** It gets OMP's advisor prompt, the project's `AGENTS.md`/`CLAUDE.md`, the standing
   memory, and every `WATCHDOG.md` from the user's memoose directory down to the project. Only
   the Advisor reads `WATCHDOG.md`.
5. **Guard.** `advise.py` ports OMP's emission guard: NFKC normalisation, the content-free phrase
   list, dedupe by severity rank, and a budget of 4 non-blockers per update. It adds a cap of 2
   blockers per prompt, after which a blocker becomes a concern, because OMP's unbounded blockers
   let a runaway advisor send hundreds of them (oh-my-pi#11888).
6. **Delivery** (`deliver.py`, a sync hook that reads the mailbox):
   - A **nit** waits for the next prompt.
   - A **concern** steers at the next tool step. OMP holds concerns until the prompt ends, and
     oh-my-pi#10600 reports that they arrive stale that way.
   - A **blocker** steers at the next tool step. If the primary is finishing, it blocks `Stop`. If
     the primary is already idle, it wakes it through `asyncRewake`.
   - A steer opens an immune window of 3 tool steps, during which concerns wait.
   - Every Advisory is marked delivered once, because `asyncRewake` was observed delivering twice.
7. **On by default**, unlike OMP; `MEMOOSE_ADVISOR=0` turns it off. Memoose's premise is that
   memory is found two ways, by search and by recommendation, and recommendation that has to be
   switched on is not recommendation. The prompt hint recommends before a turn; the Advisor
   recommends during it. The cost is one small-model review per batch of steps, on the host's
   own auth, the same trade ADR 0003 made for capture. Claude Code only; other hosts keep ADR 0003's jobs. OMP's `syncBacklog` (making the primary
   wait for the Advisor) is not ported.

## Consequences

- An Advisory arrives after the step it is about. The Advisor reviews what happened, so it can
  steer what comes next but cannot veto a tool call before it runs.
- The Advisor never writes memory. Capture stays the only background writer, and an Advisor
  that misjudges costs one note, not a wrong fact.
- The guard only catches repeats with the same wording. A reworded repeat gets through; the
  prompt's "never repeat prior advice" and the Advisor's own conversation are what hold it back.
- Every tool call now runs two small hooks. The sync one only reads a mailbox; the async one
  returns at once when a review is already running.
