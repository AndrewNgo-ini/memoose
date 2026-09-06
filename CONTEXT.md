# mnemoth

A memory engine for coding agents, packaged as an Agent Plugin (skills plus an MCP server). It adapts the deterministic parts of cognee's memory-management logic and exposes them as MCP tools; the thinking cognee delegated to an LLM is described in skills and done by the Host Model as it calls the tools.

## Language

### Actors

**Host**:
The agent client that installs the plugin and runs the conversation, such as Claude Code or Codex.
_Avoid_: Provider, client, harness, IDE

**Host Model**:
The LLM the Host is already running the conversation with. The only model mnemoth ever uses.
_Avoid_: LLM, provider model, API model, sampling

**Engine**:
The MCP server part of the plugin. It stores, indexes, and retrieves memory. It never calls, prompts, or orchestrates a model.
_Avoid_: Server, backend, cognee

### Memory

**Dataset**:
A named scope that memory belongs to and recall is restricted to. A project directory and a user's global memory are each a Dataset.
_Avoid_: Namespace, collection, workspace

**Ontology**:
The declared entity types and relation types that extracted facts are resolved against.
_Avoid_: Schema, taxonomy, graph model

**Session**:
One conversation's short-lived memory, kept in a fast cache and distilled into permanent memory when the conversation ends.
_Avoid_: Thread, context, chat
