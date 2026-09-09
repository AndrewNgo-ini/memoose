# Inspirations

What memoose borrows from each project, and what it deliberately does not.

## cognee — https://github.com/topoteretes/cognee

**Borrowed**: the memory philosophy. Typed knowledge graph (Entity, EntityType, edges with one-sentence fact descriptions), ontology-constrained extraction, deterministic ids from identity fields, chunk + summary for retrieval, hybrid retrieval over chunk, entity, and fact channels merged by rank, datasets as scope, sessions distilled into permanent memory, contradiction and temporal supersession as first-class concepts. The extraction, summary, and contradiction guidance in the skill is adapted from cognee's prompt templates (Apache 2.0, see NOTICE.md).

**Not borrowed**: any model call. cognee's pipelines call an LLM; memoose's library never does (ADR 0001). Also not borrowed: the three-store stack (ADR 0002), document loaders, eval framework, cloud mode.

## OpenWiki — https://github.com/langchain-ai/openwiki

**Borrowed**: grounded claims. Every material fact carries a versioned evidence pointer (for example `repo://src/server.ts#L40-L82`) so a later run can check whether the evidence still holds instead of trusting the model again. In memoose every relation may carry an `evidence` pointer, and recall returns it, so the Host Model can re-verify before acting on a remembered fact. Also borrowed: the integration layer. `openwiki integrations install codex|claude|opencode|cursor` writes one MCP entry and one skill copy into each host's own config, user-scoped by default so one install works from every repository. memoose mirrors it as `memoose install <host>`, using the same per-host paths (`~/.codex/config.toml` + `~/.agents/skills/`, `~/.claude.json` + `~/.claude/skills/`, `~/.config/opencode/opencode.jsonc`, `~/.cursor/mcp.json`). Also borrowed: the attitude that memory is *maintained*, not written once, and that the agent embeds in the host it already runs in rather than bringing its own model.

**Not borrowed**: the wiki-page output format and the server-driven page-job loop; memoose stores facts, not pages, and never drives the model.

## obsidian-skills — https://github.com/kepano/obsidian-skills

**Borrowed**: the skill packaging discipline. Single-purpose skills in the Agent Skills format under `skills/<name>/SKILL.md`, portable across Claude Code, Codex, and OpenCode without host-specific code, with format-specific expertise written as concrete rules rather than vague guidance.

**Not borrowed**: Obsidian as a storage target. A future skill could export a Dataset to an Obsidian vault, but the store stays SQLite.
