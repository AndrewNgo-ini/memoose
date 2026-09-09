---
name: memoose-onboard
description: Set up memoose memory for this user and host. Use when memoose was just installed, when the user asks to enable, configure, or turn off automatic memory, hints, or background capture, or when memory is not being captured or recalled automatically and they want to know why.
---

# Onboarding memoose

memoose cannot see how this machine is configured, so this skill walks the setup with the user.
Work through it in order and report what you found rather than assuming.

## 1. Find out what is actually working

```
list_datasets          # is the MCP server reachable, and which dataset is this project?
describe_ontology      # how much is already remembered?
```

Then check which automatic parts are live on this host:

| capability | how to check | if missing |
| --- | --- | --- |
| Memory tools | `list_datasets` returns | the MCP server is not connected; see step 2 |
| Hints on each prompt | the user sees "memoose already holds memory…" before your answers | hooks not installed; step 3 |
| Standing context at session start | you received rules and preferences without asking | hooks not installed; step 3 |
| Background capture after each turn | new facts appear without anyone calling `remember` | hooks not installed; step 3 |

Everything still works without hooks: the tools and skills cover every capability. Hooks only
remove the need to ask.

## 2. If the tools are missing

The plugin ships its own MCP server. If `list_datasets` fails, the plugin is not installed for this
host. From a checkout: `memoose install claude` (or `codex`, `opencode`, `cursor`), then restart the
host. Ask the user to run it; do not edit their host configuration behind their back.

## 3. Enabling the automatic parts

Hooks ship with the plugin and are wired through its manifest, so on a host that supports plugin
hooks they are already active once the plugin is installed. If they are not firing, the likely causes
are, in order:

1. The host does not run plugin hooks. Fall back to the delegated path: the `memoose` skill tells you
   to hand memory work to the `memory-keeper` subagent, which needs no hooks.
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

## 6. Seed the first memories

A cold memory helps nobody. Ask what is worth knowing about this project and store it: the stack,
who owns what, conventions to follow, and any hard constraints. Use `session_set_context` for rules
and preferences so they come back automatically at the start of every future session.
