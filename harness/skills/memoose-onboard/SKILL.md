---
name: memoose-onboard
description: Set up memoose memory for this user and host, and give an existing project its first memory. Use when memoose was just installed, when a project has history but memoose ontology reports an empty store, when the user asks to enable, configure, or turn off automatic memory, hints, or background capture, or when memory is not being captured or recalled automatically and they want to know why.
---

# Onboarding memoose

memoose cannot see how this machine is configured, so this skill walks the setup with the user.
Work through it in order and report what you found rather than assuming.

## 1. Find out what is actually working

```
memoose status         # what is installed where: CLI, plugin, skills, hooks, agent, MCP
memoose datasets       # which dataset is this project? (no shell: the list_datasets tool)
memoose ontology       # how much is already remembered?
```

Then check which automatic parts are live on this host:

| capability | how to check | if missing |
| --- | --- | --- |
| Memory commands | `memoose datasets` answers (or `list_datasets` over MCP) | the CLI is not on PATH and no server is wired; see step 2 |
| Hints on each prompt | the user sees "memoose already holds memory…" before your answers | hooks not installed; step 3 |
| Standing context at session start | you received rules and preferences without asking | hooks not installed; step 3 |
| Background capture after each turn | new facts appear without anyone calling `remember` | hooks not installed; step 3 |

Everything still works without hooks: the tools and skills cover every capability. Hooks only
remove the need to ask.

Read the store stats too. If `memoose ontology` reports no entities while the directory has a git
history, a README, docs or ADRs, this is a **brownfield** project: it knows things memory does not.
Go to step 6 before anything else, because every later session benefits from the first fill.

## 2. If the commands are missing

`pip install memoose` (or `uv tool install memoose`) puts the CLI on PATH; that alone is enough for
an agent with a shell. Then `memoose install claude` (or `codex`, `opencode`, `cursor`) copies the
skills in and, on Claude Code, the hooks and the `memory-keeper` agent. Only if the agent has no
shell add `--mcp`, which registers `uvx memoose serve`. Restart the host afterwards. Ask the user to
run it; do not edit their host configuration behind their back.

## 3. Enabling the automatic parts

Hooks come from either the Claude Code plugin (wired through its manifest) or `memoose install
claude` (registered in `.claude/settings.json`); `memoose status` shows which. If they are not
firing, the likely causes are, in order:

1. The host has no hook surface memoose wires (Codex, OpenCode, Cursor). Fall back to the delegated
   path: the `memoose` skill tells you to hand memory work to the `memory-keeper` subagent, which
   needs no hooks.
2. The host was not restarted after installing.
3. The user turned them off. See the switches below.

**Never install hooks into the user's global configuration without asking.** Show them what it would
do and let them decide.

## 4. The switches

All are environment variables; all default to on. Set them where the host's MCP server and hooks get
their environment.

| variable | effect |
| --- | --- |
| `MEMOOSE_HINTS=0` | stop injecting relevant-memory hints before each prompt |
| `MEMOOSE_AUTO_RECALL=0` | stop injecting standing context at session start |
| `MEMOOSE_AUTO_CAPTURE=0` | stop background capture entirely |
| `MEMOOSE_AUTO_MAINTAIN=0` | stop the daily offer to run the upkeep pass (`MEMOOSE_MAINTAIN_EVERY_HOURS` re-paces it) |
| `MEMOOSE_CAPTURE_MODEL=haiku` | which small model does the background extraction |
| `MEMOOSE_CAPTURE_MIN_CHARS=400` | how substantial a turn must be before capture spends anything |
| `MEMOOSE_DATA_DIR` | where the SQLite files live |
| `MEMOOSE_EMBEDDER=hash\|fastembed\|auto` | local embeddings; `hash` needs no model download |

The project was called mnemoth before, so every `MNEMOTH_*` variable above is still read when the
`MEMOOSE_*` one is unset, and memory already written to `~/.mnemoth` keeps being used from there.
Nothing is moved or copied; point `MEMOOSE_DATA_DIR` at it to be explicit.

## 5. Tell the user what is being stored

Automatic capture means facts get written that nobody explicitly asked for, so be plain about it:

- Memory lives in a SQLite file on this machine (`list_datasets` shows where). Nothing is uploaded.
- Two scopes: this project, and a `user` dataset for facts that hold across projects.
- `recall` shows what is remembered; `history(entity=…)` shows who stored it and when.
- `forget` removes an entity, a fact, or a whole dataset.

Offer to run a `recall` over anything they are unsure about, and ask before enabling capture if the
project contains anything sensitive.

## 6. The first fill

A cold memory helps nobody, and on a project with history the material already exists.

**Ask once, then go.** Tell the user what you found (how many commits, which documents) and what you
propose to read, and ask one question: fill memory from these now, or skip. Default to yes. If the
user already told you to just go, or you are running where nobody can answer, go ahead under the
precision rule below and report what you wrote at the end. Never ask twice, and never ask per fact.

**Greenfield** (no history to read): ask what is worth knowing about this project and store it: the
stack, who owns what, conventions to follow, hard constraints. Use `session_set_context` for rules
and preferences so they come back automatically at the start of every future session.

**Brownfield** (history, no memory): read, in this order, what exists of

1. `README.md`, `CONTEXT.md` or any glossary, `CONTRIBUTING.md`, `docs/adr/*`
2. `CODEOWNERS`, the manifest (`pyproject.toml`, `package.json`, `go.mod`, ...) for the stack
3. CI workflows, `Makefile` or package scripts: the steps this project runs to test, build, release
4. `git log --oneline -50` and `git shortlog -sn` for what changed lately and who works here

and write three kinds of memory from it:

- **Facts** with evidence: decisions and their reasons (`decided_on`, `replaced_by`), ownership
  (`owned_by`), how systems relate (`depends_on`, `deployed_in`), the stack (`uses`), conventions and
  constraints. Evidence is the file range, `repo://docs/adr/0002-single-sqlite-store.md#L1-L12`, or
  the commit. Facts, not entities alone. On hosts with subagents, hand this part to `memory-keeper`
  with the list of files; it is bookkeeping and should not occupy the conversation.
- **Standing context**: rules and preferences the documents state ("tests before commit", "uv, not
  pip") go in `session_set_context` under `rules` or `preferences`, so they load at every start.
- **Procedures**: a documented multi-step workflow (release, deploy, review, the test-then-commit
  chain in CONTRIBUTING or the CI file) becomes Procedure entities joined by Transitions with
  `--when`, `--do`, `--avoid` taken from the text. Write these yourself, in the foreground; the
  keeper does not author procedures. Three to seven steps per chain; skip anything the documents do
  not actually spell out.

**Precision rule.** Store what the documents say, not what you infer from code. A wrong fact
learned on day one is recalled on every later day. When a document contradicts another, store both
with their evidence and let `memoose maintain` surface the hotspot for the user to judge. Skip
anything that looks personal or secret. Aim for tens of facts, not hundreds; `memoose maintain`
afterwards will show duplicates and stale buckets to tidy.

**Report** what was written: counts by kind, the standing rules now active, and the procedures
memory holds, with `memoose recall` lines the user can run to check.
