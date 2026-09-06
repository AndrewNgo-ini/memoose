# mnemoth

Memory harness for coding agents. mnemoth adapts the deterministic parts of
[cognee](https://github.com/topoteretes/cognee)'s memory-management logic
(typed knowledge graph, ontology, chunking, hybrid retrieval) and exposes them
as plain MCP tools plus a skill, packaged as an
[Agent Plugin](https://agent-plugins.org/). The library never calls a model:
the host model (Claude Code, Codex, ...) does the thinking while it calls the tools.

No API key. One SQLite file per dataset. Install once, works in any host that speaks
skills + MCP.

See `CONTEXT.md` for the glossary and `docs/adr/` for the decisions.

## Install

From a source checkout (until the package is on PyPI):

```sh
uv run mnemoth install claude      # or: codex | opencode | cursor
uv run mnemoth install claude --project .   # project scope instead of user scope
uv run mnemoth status
```

`install` writes one MCP server entry into the host's own config and copies the
`mnemoth` skill into the host's skills directory. Nothing else is touched.

Or load it as a plugin directly in Claude Code:

```sh
claude --plugin-dir /path/to/mnemoth
```

## Tools

| tool | what it does |
| --- | --- |
| `describe_ontology` | entity types and the relation-name rule for a dataset |
| `add_entity_type` | extend the ontology with a basic PascalCase type |
| `remember` | store entities and `source --relation--> target` facts with evidence pointers; validates and merges |
| `recall` | hybrid recall (FTS5 + local embeddings + one-hop graph); returns ranked raw facts |
| `forget` | remove an entity, a relation, or a whole dataset |
| `list_datasets` | memory scopes on this machine |

Data lives in `~/.mnemoth/<dataset>.sqlite` (override with `MNEMOTH_DATA_DIR`). The default
dataset is derived from the directory the host launched the server in; pass `dataset`
explicitly to use another scope. Embeddings use `fastembed` when the extra is installed
(`uvx --from . --with fastembed mnemoth serve`) and a keyless hashed fallback otherwise
(`MNEMOTH_EMBEDDER=hash|fastembed|auto`).

## Develop

```sh
uv sync --group dev
uv run pytest
claude plugin validate .
```
