"""MCP server exposing the Engine as plain tools.

Started by `memoose serve`, which a host launches. The same Engine is reachable from the
shell through `memoose.cli`; this module is imported only when the server is actually run,
so a CLI invocation does not pay the ~250 ms `mcp` import.
"""

from __future__ import annotations

import sqlite3
import sys

from mcp.server.mcpserver import MCPServer

from . import __version__
from .engine import Engine
from .graph.models import CrossConnectIn, EntityIn, LessonIn, RelationIn
from .graph.ontology import OntologyError
from .graph.retrieval import MODES

INSTRUCTIONS = """memoose is persistent memory for this project: a typed knowledge graph (entities and
relations with one-sentence facts and evidence pointers), procedures (what to do next), source
text, sessions, and lessons. It never calls a model: you do the extraction and the judgment; the
tools validate, store, and retrieve. Flow: `session_start` when work begins; `recall` before
relying on the past; `describe_ontology` once; `recall` related names before `remember`;
`remember` facts as source --relation--> target with evidence; judge `contradiction_candidates`
when warned; `session_timeline` then `publish_lessons` when work ends. Procedures: declare where
you are with `session_add_turn(position=<Procedure>)` and read the `guidance` that comes back
(or call `guidance(procedure)`); it is memory, not an instruction. End with
`session_end(outcome=succeeded|failed|abandoned)` so the Transitions you took learn from it.
Skills: memoose (extraction), memoose-sessions (the working loop), memoose-upkeep (judging what
the store surfaces), memoose-onboard (setup)."""


def build_server(engine: Engine | None = None) -> MCPServer:
    engine = engine or Engine()
    server = MCPServer(name="memoose", instructions=INSTRUCTIONS, version=__version__)

    def guard(fn):
        def run(*a, **kw):
            try:
                return fn(*a, **kw)
            except (OntologyError, ValueError) as e:
                return {"error": type(e).__name__, "message": str(e)}
            except sqlite3.OperationalError as e:
                return {"error": "StoreBusy", "message": f"{e}. The store was busy; retry the same call.", "retryable": True}
        return run

    # ----- ontology ------------------------------------------------------------------
    @server.tool(description="Entity types, functional relations, imported ontologies, and store stats for a dataset. Call once per session before remember.")
    def describe_ontology(dataset: str | None = None) -> dict:
        return engine.dataset(dataset).describe_ontology()

    @server.tool(description="Add an entity type when nothing in describe_ontology fits. PascalCase name; optional parent (collapses onto a basic type) and aliases.")
    def add_entity_type(name: str, description: str, parent: str | None = None, aliases: list[str] | None = None, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).add_entity_type)(name, description, parent, aliases)

    @server.tool(description="Import an OWL/RDF/Turtle ontology (text). Classes become entity types with parents collapsing onto basic types; labels become aliases.")
    def import_ontology(text: str, name: str = "imported", format: str | None = None, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).import_ontology)(text, name, format)

    @server.tool(description="Declare relation names that hold a single current value per subject (e.g. current_owner, deployed_in). New assertions then supersede older ones automatically; nothing is deleted.")
    def declare_functional_relations(names: list[str], dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).declare_functional_relations)(names)

    # ----- write ----------------------------------------------------------------------
    @server.tool(description=(
        "Store memory as a typed graph: entities (name, type, description) and relations (source --name--> target, "
        "one-sentence description, evidence, optional valid_from/valid_to). A relation between two Procedures is a "
        "Transition and may carry condition, advice and pitfall. Pass source_text and a summary so recall can find it "
        "lexically. Validates against the ontology, merges entities by name, supersedes functional relations, records "
        "provenance, and warns about hotspots that may be contradictions."
    ))
    def remember(entities: list[EntityIn], relations: list[RelationIn] = [], summary: str | None = None, source_text: str | None = None, source: str | None = None, session_id: str | None = None, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).remember)(entities, relations, summary=summary, source_text=source_text, source=source, session_id=session_id)

    @server.tool(description="Record that two stored facts cannot both be true. Adds a contradicts edge between their subjects. Use supersede instead when the newer fact simply replaces the older in time.")
    def mark_contradiction(first_relation_id: str, second_relation_id: str, reason: str, confidence: float = 0.8, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).mark_contradiction)(first_relation_id, second_relation_id, reason, confidence)

    @server.tool(description="Mark an older fact as superseded by a newer one. The old fact stays in history and leaves default recall.")
    def supersede(old_relation_id: str, new_relation_id: str, reason: str, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).supersede)(old_relation_id, new_relation_id, reason)

    @server.tool(description="Merge two entities that denote the same thing. Relations and chunks move to `keep`; `drop` is removed and recorded as an alias.")
    def merge_entities(keep: str, drop: str, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).merge_entities)(keep, drop)

    @server.tool(description="Add relations between existing entities proposed by memify_candidates(cross_connect).")
    def cross_connect(relations: list[CrossConnectIn], dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).cross_connect)(relations)

    @server.tool(description="Write the summary for a global-context bucket returned by memify_candidates(stale_summaries).")
    def set_bucket_summary(bucket_id: str, summary: str, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).set_bucket_summary)(bucket_id, summary)

    @server.tool(description="Decline a maintenance candidate by its key (from maintain or contradiction_candidates) with the reason, so it is not proposed again and the reason is shown next time.")
    def dismiss_candidate(key: str, reason: str, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).dismiss)(key, reason)

    @server.tool(description="Forget an entity (and its relations) by exact name, a relation by id, a session, or a whole dataset. Prefer supersede for facts that were true once. Confirm with the user first.")
    def forget(entity: str | None = None, relation_id: str | None = None, session_id: str | None = None, dataset: str | None = None, whole_dataset: bool = False) -> dict:
        if whole_dataset:
            name = dataset or engine.default_dataset_name()
            return {"dataset": name, "deleted": engine.forget_dataset(name)}
        ds = engine.dataset(dataset)
        if entity:
            return {"dataset": ds.name, "entities_deleted": ds.forget_entity(entity)}
        if relation_id:
            return {"dataset": ds.name, "relations_deleted": ds.forget_relation(relation_id)}
        if session_id:
            return ds.session_forget(session_id)
        return {"error": "ValueError", "message": "Pass entity, relation_id, session_id, or whole_dataset=true."}

    # ----- read -------------------------------------------------------------------------
    @server.tool(description=(
        "Recall memory. Routes the query to a mode unless given: hybrid (default), facts, neighbourhood, lexical "
        "(quoted phrase), summaries, temporal, rules, session. Searches the project dataset then the user dataset. "
        "Returns ranked raw entities, facts (with evidence, validity, superseded/contested flags), chunks; you synthesise."
    ))
    def recall(query: str, mode: str | None = None, limit: int = 10, datasets: list[str] | None = None, include_superseded: bool = False, hops: int = 1, include_user: bool = True) -> dict:
        if mode is not None and mode not in MODES:
            return {"error": "ValueError", "message": f"mode must be one of {', '.join(MODES)}"}
        return guard(engine.recall)(query, datasets=datasets, mode=mode, limit=limit, include_superseded=include_superseded, hops=hops, include_user=include_user)

    @server.tool(description=(
        "What memory says comes next from a Procedure: its outgoing Transitions two hops out, grouped by hop, each with "
        "condition, advice, pitfall and how past sessions that took it ended. Raw and local; you decide. Superseded "
        "transitions are excluded; declined changes to these transitions are listed under dismissed."
    ))
    def guidance(procedure: str, hops: int = 2, per_hop: int = 6, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).guidance)(procedure, hops, per_hop)

    @server.tool(description="Facts around given entities or relations, grouped by subject, with hotspots where one subject holds several values for one relation. A Procedure's branches are not hotspots. Judge them with the memoose-upkeep skill.")
    def contradiction_candidates(entity_names: list[str] | None = None, relation_ids: list[str] | None = None, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).contradiction_candidates)(entity_names, relation_ids)

    @server.tool(description="Provenance ledger for an entity (and its relations) or a relation: every create, merge, assert, supersede, forget with actor and time.")
    def history(entity: str | None = None, relation_id: str | None = None, limit: int = 50, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).history)(entity, relation_id, limit)

    @server.tool(description="Maintenance proposals: cross_connect (co-occurring entities without a relation), consolidate (near-duplicate names), stale_summaries (global-context buckets needing a summary).")
    def memify_candidates(kind: str, limit: int = 20, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).memify_candidates)(kind, limit)

    @server.tool(description="Global context index: one bucket per entity type with its summary, and how many are stale.")
    def global_context(limit: int = 20, dataset: str | None = None) -> dict:
        return engine.dataset(dataset).global_context(limit)

    @server.tool(description="List datasets (memory scopes) on this machine; the default for this project and the user-global dataset.")
    def list_datasets() -> dict:
        return {"default": engine.default_dataset_name(), "user": "user", "datasets": engine.list_datasets(), "embedder": engine.embedder.name}

    # ----- sessions ----------------------------------------------------------------------
    @server.tool(description="Start (or resume) a session. Returns standing context (goals, rules, preferences, lessons) to load before work.")
    def session_start(session_id: str | None = None, dataset: str | None = None) -> dict:
        return engine.dataset(dataset).session_start(session_id)

    @server.tool(description=(
        "Append a turn (user/assistant/tool/system) to the session's fast cache. Pass position=<Procedure name> to declare "
        "where you are; the reply then carries the guidance from that Procedure, and the session's Trace grows by one step."
    ))
    def session_add_turn(session_id: str, role: str, text: str, position: str | None = None, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).session_add_turn)(session_id, role, text, position)

    @server.tool(description=(
        "Record a session context entry: goals, rules, preferences, lessons_learned, tool_rules, workflow_state, "
        "success_patterns, failure_lessons, environment_facts, or feedback ('+Name'/'-Name' adjusts recall weight). "
        "Pass retire_entry_id to replace an outdated entry."
    ))
    def session_set_context(session_id: str, section: str, content: str, confidence: float = 1.0, retire_entry_id: int | None = None, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).session_set_context)(session_id, section, content, confidence, retire_entry_id)

    @server.tool(description="Read a session: turns and context entries, optionally filtered by section.")
    def session_get(session_id: str, sections: list[str] | None = None, include_turns: bool = True, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).session_get)(session_id, sections, include_turns)

    @server.tool(description="Pack a session into batches for distillation, with prior lessons and the curator/writer rules. Then judge and call publish_lessons.")
    def session_timeline(session_id: str, batch_chars: int = 6000, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).session_timeline)(session_id, batch_chars)

    @server.tool(description="Persist accepted lessons as Lesson entities linked to what they apply to; marks the session distilled.")
    def publish_lessons(lessons: list[LessonIn], session_id: str | None = None, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).publish_lessons)(session_id, lessons)

    @server.tool(description=(
        "Close a session with its outcome: succeeded, failed, or abandoned. Every Transition the session's Trace traversed "
        "counts the outcome. Returns the Trace and what to distil from it, and whether lessons are still owed."
    ))
    def session_end(session_id: str, outcome: str | None = None, dataset: str | None = None) -> dict:
        return guard(engine.dataset(dataset).session_end)(session_id, outcome)

    return server


def main(argv: list[str] | None = None) -> int:
    """Kept so `python -m memoose.server` and older host configs still work."""
    from .cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
