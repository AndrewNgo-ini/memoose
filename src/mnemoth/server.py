"""MCP server exposing the Engine as plain tools, plus the `mnemoth` CLI.

`mnemoth` / `mnemoth serve`  run the stdio MCP server (what hosts launch)
`mnemoth install <host>`     wire the server + skill into a host (see integrations.py)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import __version__
from .engine import Engine
from .models import EntityIn, RelationIn
from .ontology import OntologyError

INSTRUCTIONS = """mnemoth is persistent memory for this project. It stores a typed knowledge graph
(entities and relations with one-sentence facts) plus source text, and recalls by hybrid search.
It never calls a model: you do the extraction. Typical flow: `recall` at the start of a task and
whenever the user refers to something from the past; `describe_ontology` once per session;
`recall` related names before `remember` so you reuse existing entity names and notice
contradictions; `remember` facts as source --relation--> target with an evidence pointer.
Load the `mnemoth` skill for the extraction rules."""

SKILL_PATH = Path(__file__).resolve().parents[2] / "skills" / "mnemoth" / "SKILL.md"


def build_server(engine: Engine | None = None) -> MCPServer:
    engine = engine or Engine()
    server = MCPServer(name="mnemoth", instructions=INSTRUCTIONS, version=__version__)

    def _err(e: Exception) -> dict:
        return {"error": type(e).__name__, "message": str(e)}

    @server.tool(description="Entity types and relation-name rule for a dataset, plus store stats. Call once per session before remember.")
    def describe_ontology(dataset: str | None = None) -> dict:
        return engine.dataset(dataset).describe_ontology()

    @server.tool(description="Add an entity type when nothing in describe_ontology fits. Prefer basic types; put specifics in descriptions.")
    def add_entity_type(name: str, description: str, dataset: str | None = None) -> dict:
        try:
            return engine.dataset(dataset).add_entity_type(name, description)
        except OntologyError as e:
            return _err(e)

    @server.tool(
        description=(
            "Store memory as a typed graph: entities (name, type, description) and relations "
            "(source --name--> target, one-sentence description, evidence pointer). "
            "Optionally pass the source text and a summary so recall can find it lexically. "
            "Validates against the ontology and merges entities that already exist by name."
        )
    )
    def remember(
        entities: list[EntityIn],
        relations: list[RelationIn] = [],
        summary: str | None = None,
        source_text: str | None = None,
        source: str | None = None,
        dataset: str | None = None,
    ) -> dict:
        try:
            return engine.dataset(dataset).remember(entities, relations, summary=summary, source_text=source_text, source=source)
        except (OntologyError, ValueError) as e:
            return _err(e)

    @server.tool(
        description=(
            "Hybrid recall over entities, facts, and source chunks (lexical + local embeddings + one-hop graph). "
            "Returns ranked raw facts with evidence pointers; you synthesise the answer and re-verify evidence when it matters."
        )
    )
    def recall(query: str, limit: int = 10, dataset: str | None = None) -> dict:
        try:
            return engine.dataset(dataset).recall(query, limit=limit)
        except ValueError as e:
            return _err(e)

    @server.tool(description="Forget an entity (and its relations) by exact name, a relation by id, or a whole dataset. Confirm with the user first.")
    def forget(entity: str | None = None, relation_id: str | None = None, dataset: str | None = None, whole_dataset: bool = False) -> dict:
        if whole_dataset:
            name = dataset or engine.default_dataset_name()
            return {"dataset": name, "deleted": engine.forget_dataset(name)}
        ds = engine.dataset(dataset)
        if entity:
            return {"dataset": ds.name, "entities_deleted": ds.forget_entity(entity)}
        if relation_id:
            return {"dataset": ds.name, "relations_deleted": ds.forget_relation(relation_id)}
        return _err(ValueError("Pass entity, relation_id, or whole_dataset=true."))

    @server.tool(description="List datasets (memory scopes) on this machine and which one is the default for the current project.")
    def list_datasets() -> dict:
        return {"default": engine.default_dataset_name(), "datasets": engine.list_datasets(), "embedder": engine.embedder.name}

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mnemoth", description="Memory harness for coding agents.")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="Run the stdio MCP server (default).")
    p_install = sub.add_parser("install", help="Wire mnemoth into a host: claude, codex, opencode, cursor.")
    p_install.add_argument("host", choices=["claude", "codex", "opencode", "cursor"])
    p_install.add_argument("--project", nargs="?", const=".", default=None, help="Install into this project instead of the user scope.")
    p_install.add_argument("--command", default=None, help='MCP server command override, e.g. "uvx mnemoth serve".')
    p_un = sub.add_parser("uninstall", help="Remove mnemoth from a host.")
    p_un.add_argument("host", choices=["claude", "codex", "opencode", "cursor"])
    p_un.add_argument("--project", nargs="?", const=".", default=None)
    p_status = sub.add_parser("status", help="Show what is installed where.")
    p_status.add_argument("--project", nargs="?", const=".", default=None)
    args = parser.parse_args(argv)

    if args.cmd in (None, "serve"):
        build_server().run("stdio")
        return 0
    from . import integrations

    if args.cmd == "install":
        result = integrations.install(args.host, project=args.project, command=args.command.split() if args.command else None)
    elif args.cmd == "uninstall":
        result = integrations.uninstall(args.host, project=args.project)
    else:
        result = integrations.status(project=args.project)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
