# memoose

A memory engine for coding agents, packaged as an Agent Plugin (skills plus an MCP server). It adapts the deterministic parts of cognee's memory-management logic and exposes them as MCP tools; the thinking cognee delegated to an LLM is described in skills and done by the Host Model as it calls the tools.

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
_Avoid_: Server, backend, cognee

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
A subject that holds several values for one relation. A candidate for a Contradiction or a Functional Relation, not yet judged.
_Avoid_: Duplicate, collision

**Lesson**:
A distilled, reusable learning from a Session, stored as an entity linked to what it applies to.
_Avoid_: Insight, takeaway, note, memory

**Bucket**:
A group of entities of one type with a written summary; together the Buckets form the global context of a Dataset.
_Avoid_: Cluster, community, index entry, topic

**Procedure**:
A step an agent takes, stored as an entity: a tool action, a check, or a state of the work. Its outgoing relations (leads_to, requires, triggers, converges_to) say what comes next and, in their descriptions, under which condition and with which pitfall. A Fact answers what is; a Procedure answers what to do next.
_Avoid_: Workflow, playbook, recipe, skill (a skill is the host's instruction file, not memory)

**Guidance**:
The transitions two hops out from the Procedure matching the agent's most recent action, put in front of the agent before it acts. Keyed on what the agent just did, where a Hint is keyed on what the user just said.
_Avoid_: Suggestion, plan, next steps

**Dismissal**:
A recorded judgment that a maintenance candidate (a Hotspot, a possible duplicate, a possible connection, an undistilled Session) was reviewed and declined, with the reason. It removes the candidate from later passes and changes nothing in the graph. Lives in Provenance.
_Avoid_: Rejection, ignore, mute, suppress

**Provenance**:
The append-only ledger of every change to memory: who did what to which entity or Fact, and when.
_Avoid_: Audit log, history table, changelog
