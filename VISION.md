# Vision

## The problem

An agent that forgets is an agent you re-teach every morning. Every coding agent now ships some
answer to this, and none of them is portable: Claude Code has its memory, Codex has another, Cursor
a third. Move tools and your project's accumulated context stays behind.

The libraries that solve it properly solve it at a price. cognee, mem0, and Zep are good systems, but
each one wants an LLM API key of its own, and usually a service to run. That means a second inference
bill on top of the subscription you already pay, your project's memory leaving the machine, another
vendor in the loop, and a dependency footprint that does not belong in a developer tool — cognee's
core is 45 dependencies over three databases.

The protocol has an answer for this that nobody implements. MCP defines `sampling/createMessage`,
which lets a server borrow the host's model instead of bringing its own; cognee even has an adapter
for it. No host we target grants the capability
([anthropics/claude-code#1785](https://github.com/anthropics/claude-code/issues/1785) is open), so
in practice the server still needs its own key.

## The bet

**The agent already has a model. Memory should not bring a second one.**

mnemoth inverts the usual split. The library holds only what is deterministic — a typed graph store,
an ontology, chunking, ranking, supersession, a provenance ledger — and exposes it as plain MCP
tools. Everything that needs judgment (what is an entity, which facts contradict, what is worth
remembering, what a session taught) is written down as skills, and the model the host is *already
running* does that thinking while it calls the tools.

The consequences are the point:

- **No API key, ever.** Not optional, not a fallback path. There is no code path in the library that
  calls a model ([ADR 0001](./docs/adr/0001-skills-and-mcp-only.md)).
- **Nothing leaves the machine.** One SQLite file per scope
  ([ADR 0002](./docs/adr/0002-single-sqlite-store.md)). Inspect it, copy it, delete it, put it in a
  backup. Retrieval takes ~35 ms locally.
- **Portable by construction.** Skills plus an MCP server is the whole surface, so the same plugin
  works in Claude Code, Codex, OpenCode, and Cursor with no host-specific code outside the installer.
- **Intelligence improves for free.** When the host's model gets better, extraction and judgment get
  better without shipping anything.

The cost of the bet is honest: quality depends on the host model following a skill, and we cannot
run anything in the background, because memory only changes when the agent calls a tool.

## What mnemoth is for

Memory for **long-lived project work**, where the hard part is not finding a fact once but keeping a
body of facts trustworthy for months: who owns what now, which decision replaced which, what
convention this team follows, what we learned last time and why.

That framing came out of benchmarking, not before it. On LoCoMo, the standard conversational-memory
benchmark, mnemoth scores at parity with mem0 using a third fewer tokens and a much smaller model —
but a controlled paired test showed our knowledge graph does **not** beat plain chunk retrieval
there (McNemar p = 1.00), at 77% more tokens. That is not a defect; it is a statement about the
benchmark. LoCoMo asks needle questions over conversations that fit in a context window, so chunk
retrieval finds the needles and the answering model does the joining. It never asks the questions a
graph exists to answer:

- A fact changed. Does recall return the current one, and can it still show me the old one?
- Two sources disagree. Does the system say so, or silently pick one?
- Why do we believe this? Point me at the file range, the message, the date.
- We solved this before. What did we learn, and does it apply here?

Those are the questions that make memory worth maintaining, and no published memory benchmark tests
them. **Building that benchmark is on our roadmap**, because we would rather be measured on what we
claim than score well on what is convenient.

## Principles

1. **The library never calls a model.** If a feature needs judgment, it becomes a skill and a
   validated tool, not an inference call.
2. **The harness is skills and MCP.** No hooks, no host-specific code paths in the core. Portability
   beats convenience.
3. **Facts carry their evidence.** Every relation can point at where it came from, so a later run can
   re-verify rather than trust. Borrowed from OpenWiki's grounded claims.
4. **Nothing true is deleted.** Facts are superseded, not removed; history stays queryable.
5. **Errors teach.** A rejected write returns a message written for the model — which type to use,
   which relation name — because tool errors are the only lever we have on extraction quality.
6. **Boring storage.** One SQLite file. Add a backend when someone actually outgrows it, not before.
7. **Report what we measure.** No claimed benchmark win we cannot defend. State the confound.

## Non-goals

Being the best retrieval system over chat logs. Multi-user access control. A hosted service. A UI.
Ingesting audio and images. Replacing the host's own context management. Winning LoCoMo.

## How we would know it works

- A developer installs it once and it works in whichever agent they open tomorrow.
- After a month on a project, an agent answers "why is it built this way?" with the decision, the
  date, and the evidence — and flags the two places the codebase now disagrees with it.
- When a fact changes, nobody has to remember to clean up.
- The memory file is small enough to read, and a person can open it and understand what the agent
  believes about their project.

## Roadmap

**Now.** Finish the honest LoCoMo numbers, including a model-matched run, so parity is documented
rather than asserted.

**Next.** A benchmark for maintained memory: conflicting facts asserted over time, superseded
history, evidence that must be re-checked, lessons reused across sessions. Publish it whether or not
we win it.

**Then.** Real-project soak: run mnemoth on its own development for a month and report what it got
wrong. Consolidation that runs without being asked. An export a human can read.

**Not yet.** Other storage backends, other hosts beyond the four, a service.
