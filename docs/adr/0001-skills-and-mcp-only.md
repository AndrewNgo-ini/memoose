---
status: accepted
---

# mnemoth reaches the Host only through skills and MCP tools; the library never calls or orchestrates a model

mnemoth ports cognee's memory-management logic, whose pipelines call an LLM several times per chunk (entity extraction, summarization, contradiction detection, distillation). No API key is allowed, and neither Claude Code nor Codex grants the MCP `sampling` capability (anthropics/claude-code#1785 is open). We do not replace those model calls with any mechanism of our own. The library holds only the deterministic parts of cognee's logic: graph store, ontology resolution, chunking, embeddings, lexical, vector, and graph retrieval, ranking, provenance, temporal supersession, datasets, sessions, forget. These are exposed as plain MCP tools. Everything cognee asked a model to do is described in skills, and the Host Model does that thinking itself while it calls the tools. Claude Code and Codex are harnessed only through the portable Agent Plugin surface: `skills/` and `mcp.json`.

## Considered Options

- **Engine-driven Completion Requests.** The server returns cognee's prompts and schemas and the agent answers them through a `submit` tool. Rejected: it makes the server orchestrate the Host Model, which the project explicitly does not want; the library must be a pure memory engine.
- **MCP sampling.** Rejected: no target Host grants it.
- **Optional BYO API key.** Rejected: violates the no-key principle.
- **Host-specific hooks extension.** Rejected: the harness surface is skills and MCP only, so session-start recall and session-end distillation are skill instructions, not hooks.

## Consequences

- Skills carry the intelligence. cognee's prompt templates are rewritten as skill instructions for extraction, contradiction checking, and distillation.
- Tool inputs are typed and validated against the Ontology, because tool errors are the only lever the library has over extraction quality.
- Nothing runs in the background: memory changes only when the Host Model calls a tool.
