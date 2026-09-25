---
name: memoose-onboard
description: Get memoose working on this host and give this project its memory. Use when memoose was just installed, when the user asks to set up, enable, configure or turn off memory, hints or background capture, when a project has no memory yet or memory that looks stale, or when memory is not being captured or recalled automatically and they want to know why.
---

# Onboarding memoose

Three jobs, in order: find out what works here, install what is missing, then fill this project's
memory so the next session starts with context. memoose cannot see the machine; you can. Report what
you found rather than assuming, and ask the user at most one question per job.

## 1. Check what works

```
memoose status         # CLI, plugin, skills, hooks, agent, MCP: what is installed where
memoose datasets       # which dataset is this project? (no shell: the list_datasets tool)
memoose ontology       # entity types and store stats: how much is remembered
```

| capability | how to tell | if missing |
| --- | --- | --- |
| Memory commands | `memoose datasets` answers (or `list_datasets` over MCP) | step 2 |
| Skills | this skill loaded, so at least one did; `status` lists the rest | step 2 |
| Hints on each prompt | the user sees "memoose already holds memory…" before your answers | step 2, or step 4 |
| Standing context at session start | you received rules and preferences without asking | step 2, or step 4 |
| Background capture | new facts appear without anyone calling `remember` | step 2, or step 4 |

Everything works without hooks; they only remove the need to ask. Note the store stats: no entities
means step 3 is a first fill, some entities means step 3 is a top-up.

## 2. Install what is missing

Say what is missing and what you will run, ask once, then run it:

- CLI not on PATH: `pip install memoose` (or `uv tool install memoose`).
- Skills, hooks or agent missing: `memoose install claude` (or `codex`, `opencode`, `cursor`).
  On Claude Code, the plugin is the alternative that keeps one copy of everything:
  `/plugin marketplace add AndrewNgo-ini/memoose` then `/plugin install memoose@memoose`.
- Agent has no shell: add `--mcp`, which registers `uvx memoose serve`.

Tell the user the host must restart before hooks and the server load, and carry on with step 3,
which needs only the CLI. Do not edit host configuration by hand; `install` and `uninstall` are the
only writes, and `status` shows what they did.

## 3. Fill this project's memory

Every project is brownfield: it has a README, a history, a stack, people, conventions, even when
memory is empty. A cold memory helps nobody, so this step runs whether memory is empty or not.

Open a session for it, so the fill is on record and can be distilled:
`memoose session start onboard-<date>`, then `session turn` for what you read and decided, and
`session end --outcome succeeded|abandoned` when done.

**Ask once, then go.** Tell the user what you found (commits, documents, what memory already holds)
and what you propose to read, and ask one question: fill from these now, or skip. Default to yes. If
the user already said to go, or nobody can answer, go ahead under the precision rule and report at
the end. Never ask per fact.

**Read**, in this order, what exists of:

1. `README.md`, `CONTEXT.md` or any glossary, `CONTRIBUTING.md`, architecture or decision docs
2. `CODEOWNERS` and the manifest (`pyproject.toml`, `package.json`, `go.mod`, ...) for the stack
3. CI workflows, `Makefile` or package scripts: how this project tests, builds, releases
4. `git log --oneline -50` and `git shortlog -sn`: what changed lately, who works here

When memory already has entities, first `memoose recall` the project name and `memoose context` to
see what it holds, then store only what is new or changed since. Where a document disagrees with a
stored fact, remember the new one with its evidence and let `memoose maintain` surface the hotspot.

**Write** three kinds of memory:

- **Facts** with evidence: decisions and their reasons (`decided_on`, `replaced_by`), ownership
  (`owned_by`), how systems relate (`depends_on`, `deployed_in`), the stack (`uses`), conventions
  and constraints. Evidence is a file range (`repo://docs/adr/0002.md#L1-L12`) or a commit. Facts,
  never bare entities. On hosts with subagents, hand this part to `memory-keeper` with the file
  list; it is bookkeeping and should not occupy the conversation.
- **Standing context**: rules and preferences the documents state ("tests before commit", "uv, not
  pip") go in `session context --section rules|preferences`, so they load at every future start.
- **Procedures**: a documented multi-step workflow (release, deploy, review, test-then-commit)
  becomes Procedure entities joined by Transitions with `--when`, `--do`, `--avoid` taken from the
  text. Write these yourself; the keeper does not author procedures. Three to seven steps per
  chain, and only what the documents spell out.

If there is nothing to read (a new, empty repository), ask the user the four things worth knowing:
the stack, who owns what, conventions to follow, hard constraints. Store them the same way.

**Precision rule.** Store what the documents say, not what you infer from code. A wrong fact learned
on day one is recalled every later day. Skip anything personal or secret. Aim for tens of facts, not
hundreds; `memoose maintain` afterwards shows duplicates and stale summaries to tidy.

**Report**: counts by kind, the standing rules now active, the procedures memory holds, and two or
three `memoose recall` lines the user can run to check.

## 4. If the automatic parts do not fire

Hooks come from the Claude Code plugin or from `memoose install claude`; `status` shows which. In
order of likelihood:

1. The host has no hook surface memoose wires (Codex, OpenCode, Cursor). Use the delegated path: the
   `memoose` skill hands memory work to the `memory-keeper` subagent, which needs no hooks.
2. The host was not restarted after installing.
3. The user turned them off; see the switches.

## 5. The switches

Environment variables, all on by default, set where the host's hooks and server get their
environment:

| variable | effect |
| --- | --- |
| `MEMOOSE_HINTS=0` | no relevant-memory hints before each prompt |
| `MEMOOSE_AUTO_RECALL=0` | no standing context at session start |
| `MEMOOSE_AUTO_CAPTURE=0` | no background capture |
| `MEMOOSE_AUTO_MAINTAIN=0` | no daily offer to run upkeep (`MEMOOSE_MAINTAIN_EVERY_HOURS` re-paces it) |
| `MEMOOSE_CAPTURE_MODEL=haiku` | which small model does background extraction |
| `MEMOOSE_CAPTURE_MIN_CHARS=400` | how substantial a turn must be before capture runs |
| `MEMOOSE_ADVISOR=1` | **off by default.** A second small-model session reviews every step of the primary, with memory and `WATCHDOG.md`, and injects Advisories (ADR 0006). Costs a review per step. `MEMOOSE_ADVISOR_MODEL` picks the model |
| `MEMOOSE_DATA_DIR` | where the memory files live |
| `MEMOOSE_EMBEDDER=hash\|fastembed\|auto` | local embeddings; `hash` needs no model download |

## 6. Tell the user what is stored

Background capture writes facts nobody explicitly asked for, so be plain:

- Memory lives on this machine (`memoose datasets` shows where). Nothing is uploaded.
- Two scopes: this project, and a `user` dataset for facts that hold across projects.
- `memoose recall` shows what is remembered; `memoose history <entity>` shows who stored it and when.
- `memoose forget` removes an entity, a fact, a session, or a whole dataset.

Offer a `recall` over anything they are unsure about, and ask before enabling capture if the project
holds anything sensitive.
