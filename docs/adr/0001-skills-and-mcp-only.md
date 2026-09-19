---
status: accepted
---

# memoose reaches the Host only through skills and MCP tools; the library never calls or orchestrates a model

Memory libraries of this kind run pipelines that call an LLM several times per chunk (entity extraction, summarization, contradiction detection, distillation). No API key is allowed, and neither Claude Code nor Codex grants the MCP `sampling` capability (anthropics/claude-code#1785 is open). We do not replace those model calls with any mechanism of our own. The library holds only the deterministic parts: graph store, ontology resolution, chunking, embeddings, lexical, vector, and graph retrieval, ranking, provenance, temporal supersession, datasets, sessions, forget. These are exposed as plain MCP tools. Everything that needs model judgment is described in skills, and the Host Model does that thinking itself while it calls the tools. Claude Code and Codex are harnessed only through the portable Agent Plugin surface: `skills/` and `mcp.json`.

## Considered Options

- **Engine-driven Completion Requests.** The server returns extraction prompts and schemas and the agent answers them through a `submit` tool. Rejected: it makes the server orchestrate the Host Model, which the project explicitly does not want; the library must be a pure memory engine.
- **MCP sampling.** Rejected: no target Host grants it.
- **Optional BYO API key.** Rejected: violates the no-key principle.
- **Host-specific hooks extension.** Rejected as a *replacement* for the portable surface, and that
  still holds: skills plus MCP remain the core and every capability is reachable through them alone.
  [ADR 0003](./0003-proactive-background-memory.md) later **adds** hooks as an optional third surface
  on top, for hosts that support them, so memory can also maintain itself without waiting to be
  called. Nothing in this ADR changes: the library still never calls, prompts, or orchestrates a
  model, and no API key is ever required.

## Consequences

- Skills carry the intelligence: instructions for extraction, contradiction checking, and distillation.
- Tool inputs are typed and validated against the Ontology, because tool errors are the only lever the library has over extraction quality.
- Nothing runs in the background: memory changes only when the Host Model calls a tool.
