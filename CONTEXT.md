# memoose

A dual-path memory system for proactive agents, packaged as an Agent Plugin (skills plus an MCP server). The deterministic parts of memory management are MCP tools; the judgment that other memory libraries delegate to an LLM is described in skills and done by the Host Model as it calls the tools.

## Language

### Actors

**Host**:
The agent client that installs the plugin and runs the conversation, such as Claude Code or Codex.
_Avoid_: Provider, client, harness, IDE

**Host Model**:
The LLM the Host is already running the conversation with. The only model memoose ever uses.
_Avoid_: LLM, provider model, API model, sampling

**Engine**:
The MCP server part of the plugin. It stores, indexes, and retrieves memory. It never calls, prompts, or orchestrates a model.
_Avoid_: Server, backend

### Memory

**Dataset**:
A named scope that memory belongs to and recall is restricted to. A project directory and a user's global memory are each a Dataset.
_Avoid_: Namespace, collection, workspace

**Ontology**:
The declared entity types and relation types that extracted facts are resolved against.
_Avoid_: Schema, taxonomy, graph model

**Session**:
One conversation's short-lived memory: turns plus typed context entries, distilled into Lessons when the conversation ends.
_Avoid_: Thread, chat, conversation log

**Fact**:
One relation between two entities with a one-sentence description and an evidence pointer. The unit recall returns.
_Avoid_: Triple, edge, triplet, claim

**Evidence**:
Where a Fact comes from, as a pointer a later run can re-check: a file range, URL, issue id, or "user said <date>".
_Avoid_: Source, citation, reference

**Functional Relation**:
A relation name that holds one current value per subject, such as owned_by. A newer Fact supersedes the older one automatically.
_Avoid_: Single-valued, cardinality-one, unique relation

**Superseded**:
The state of a Fact that a newer Fact replaced. It leaves default recall but stays in history.
_Avoid_: Deleted, archived, stale, outdated

**Contradiction**:
Two Facts that cannot both be true of the same subject at the same time, recorded with a reason and a confidence until one supersedes the other.
_Avoid_: Conflict, inconsistency, clash

**Hotspot**:
A subject that holds several values for one relation. A candidate for a Contradiction or a Functional Relation, not yet judged. A Procedure with several Transitions is a branch, never a Hotspot.
_Avoid_: Duplicate, collision

**Lesson**:
A distilled, reusable learning from a Session, stored as an entity linked to what it applies to.
_Avoid_: Insight, takeaway, note, memory

**Bucket**:
A group of entities of one type with a written summary; together the Buckets form the global context of a Dataset.
_Avoid_: Cluster, community, index entry, topic

**Procedure**:
A step an agent takes, stored as an entity: a tool action, a check, or a state of the work. A Fact answers what is; a Procedure and its Transitions answer what to do next.
_Avoid_: Workflow, playbook, recipe, step, skill (a skill is the host's instruction file, not memory)

**Transition**:
A Fact whose source and target are both Procedures. It says the target is admissible after the source, and carries a Condition, an Advice and a Pitfall.
_Avoid_: Edge, next step, arrow, link

**Condition**:
The circumstance under which a Transition applies.
_Avoid_: Precondition, trigger, when-clause

**Advice**:
How to carry out the target Procedure once a Transition is taken.
_Avoid_: Guidance (that is the assembled neighbourhood), instruction, how-to, tip

**Pitfall**:
What went wrong on a Transition before and must be avoided when it is taken again.
_Avoid_: Warning, anti-pattern, gotcha, failure

**Start**:
A Procedure that marks the entry of a chain, so the first Position of a task can be localised and a chain can be built from nothing.
_Avoid_: Root, entry point, begin

**Position**:
The Procedure the agent is at now, declared on a Session turn. The only signal Guidance is keyed on.
_Avoid_: Active node, current step, state, location

**Trace**:
The ordered Positions of one Session, closed by its Outcome. What a later distillation contrasts a failed run against a successful one with.
_Avoid_: Trajectory, history, log, path

**Outcome**:
How a Session ended: succeeded, failed, or abandoned. Declared by the agent when the Session ends.
_Avoid_: Score, result, status, verdict

**Guidance**:
The Transitions two hops out from the agent's Position, put in front of the agent before it acts. The agent decides; Guidance is memory, not an instruction.
_Avoid_: Suggestion, plan, next steps, recommendation

**Dismissal**:
A recorded judgment that a candidate was reviewed and declined, with the reason: a maintenance candidate (a Hotspot, a possible duplicate, a possible connection, an undistilled Session) or a proposed change to a Transition. It removes the candidate from later passes and changes nothing in the graph. Lives in Provenance.
_Avoid_: Rejection, ignore, mute, suppress

**Provenance**:
The append-only ledger of every change to memory: who did what to which entity or Fact, and when.
_Avoid_: Audit log, history table, changelog

## Code layout

`src/memoose/` is three layers plus two entry points. Nothing imports upward.

`harness/` beside it holds what reaches the Host without code: `skills/`, `hooks/`, `agents/`. The plugin manifest and `memoose install` both read from there.

| Package | Holds | Imports from |
|---|---|---|
| `store/` | `sqlite_store`, `schema`, `embeddings`, `datasets` (where a Dataset's file lives) | nothing internal |
| `graph/` | `models`, `ids`, `ontology`, `chunking`, `retrieval`, `contradictions`, `memify`, `sessions`, `procedures` | `store/` |
| `engine.py` | the `Engine` facade every surface calls | `graph/`, `store/` |
| `server.py` | MCP tools over `Engine` | `engine`, `graph/` |
| `cli/` | `main` (the `memoose` command), `integrations` (host installers), `graph_html` (the viewer) | `engine`, `graph/`, `store/` |

Library users import from the top: `from memoose import Engine, EntityIn, RelationIn, OntologyError`.
