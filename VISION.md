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

memoose inverts the usual split. The library holds only what is deterministic — a typed graph store,
an ontology, chunking, ranking, supersession, a provenance ledger — and exposes it as plain MCP
tools. Everything that needs judgment (what is an entity, which facts contradict, what is worth
remembering, what a session taught) is written down as skills, and the model the host is *already
running* does that thinking while it calls the tools.

Memory work also never happens on the expensive model, and never on the user's clock. Extraction and
maintenance are delegated to a **small model** — Haiku, or whatever small model the host offers — running
as a **background job**, so the conversation is not paused to do bookkeeping.

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

The cost of the bet is honest: quality depends on the host model following a skill, and on the host
having something to delegate to.

## Three surfaces, in order

**Skills and MCP tools are the core** and are fully functional alone: every capability is reachable
through a tool call, on any host that speaks MCP ([ADR 0001](./docs/adr/0001-skills-and-mcp-only.md)).
On top of that, and never in place of it, memory also maintains *itself*
([ADR 0003](./docs/adr/0003-proactive-background-memory.md)):

| surface | what it does | needs |
| --- | --- | --- |
| **MCP tools** | the deterministic store: typed graph, ontology, ranking, supersession, provenance | any MCP host |
| **Skills** | teach the host model to extract, judge, and *delegate memory work to a cheap background subagent* | any host with skills |
| **Hooks** | capture and recall with nobody asking: hints before each prompt, standing context at session start, capture when a turn ends and before compaction | hosts with hooks |

Relying only on the agent choosing to call `remember` is how memory plugins fail: the agent is busy
with the user's real task, so bookkeeping is the first thing dropped. So the hooks run it
automatically where they exist, and everywhere else the skills tell the agent to hand it to a
background subagent. Explicit tool calls keep working; they are just no longer the only path.

### Recommendation as a memory

The same problem applies to *reading*. An agent only recalls when it thinks to, and it usually does
not think to. So memoose does not wait to be queried: it reads each incoming prompt, searches memory
locally, and when something genuinely matches it hands the agent a hint before the agent starts
thinking — what memory already holds, and the `recall` query that would fetch the rest.

The recommendation is deliberately dumb and therefore free: BM25 over the local index, a relevance
floor, a hard cap on how much it injects, and silence when nothing matches. No model, a few
milliseconds, so it can run on every prompt without anyone noticing. Memory raises its hand instead
of waiting to be asked, and the agent keeps full control over whether to follow the hint.

Because we cannot see how any given machine is configured, a `memoose-onboard` skill walks the user
through what is actually live on their host, what is being stored, and how to turn any of it off.

## What memoose is for

Memory for **long-lived project work**, where the hard part is not finding a fact once but keeping a
body of facts trustworthy for months: who owns what now, which decision replaced which, what
convention this team follows, what we learned last time and why.

That framing came out of benchmarking, not before it. On LoCoMo, the standard conversational-memory
benchmark, memoose scores at parity with mem0 using a third fewer tokens and a much smaller model —
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
them. Scoring ourselves on an eval of our own making would prove nothing, so we publish no number for
this: proposing an eval the field can run is the open problem, and it is on the roadmap.

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

**Done.** The LoCoMo headline sample at parity (91.9 vs mem0's 92.5, at a third fewer tokens on a
much smaller model).

**Now.** Propose an eval for maintained memory that other systems can run — a fact was revised, two
sources disagree, where did this come from — since no published benchmark asks it and a suite only we
run is not evidence. Alongside it, a token-cost methodology: accuracy is reported everywhere and cost
almost nowhere, though cost is what a memory system charges you every turn.

**Next.** Real-project soak: run memoose on its own development and report what it gets wrong. Live
runs have found real bugs, which is the argument for doing it continuously. One model-matched LoCoMo
run to retire the answerer confound, and then stop touching LoCoMo.

**Then.** An export a human can read.

**Not yet.** Other storage backends, other hosts beyond the four, a service.
