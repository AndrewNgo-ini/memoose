# mnemoth — end-to-end port plan

> Status: implemented in v0.2.0. Every row of §1 has a tool or skill section and a test (`tests/test_port.py`).

One pass, no milestone gates. The deliverable is the whole memory core of cognee, working,
exposed only through skills and MCP tools, with no model call anywhere in the library
(ADR 0001) and one SQLite file per Dataset (ADR 0002). Vocabulary: `CONTEXT.md`.

The rule for every cognee capability: **deterministic logic becomes a tool; model judgment
becomes a skill instruction; the Host Model does the judgment while calling the tools.**

## 1. Capability map

| cognee capability | where the model was | mnemoth |
| --- | --- | --- |
| `add` + `cognify` (classify, chunk, extract graph, summarize, persist) | extract + summarize | `remember` tool; extraction and summary rules in skill `mnemoth` |
| Ontology (OWL/RDF via rdflib, closest-match resolution) | none | `import_ontology`, `describe_ontology`, `add_entity_type`; hierarchy collapses to basic types |
| Deterministic ids (`Entity:<name>`) | none | `ids.py` (done) |
| `detect_contradictions` (candidate facts around touched nodes → LLM pairs → `contradicts` edge) | pairing | `contradiction_candidates` tool builds the candidate fact list; skill `mnemoth-contradictions` judges; `mark_contradiction` stores the edge with reason + confidence |
| `resolve_temporal_contradictions` (functional relationships, supersede older) | none | `declare_functional_relations` + automatic supersession inside `remember`; `supersede` tool for manual cases; nothing deleted |
| `record_provenance` ledger | none | `provenance` table written by every mutating tool; `history` tool |
| `recall` regex router → 20 search types | most types end in a completion | router ported; search types collapse to retrieval modes (§4); the completion step is the Host Model |
| Sessions: fast cache of Q&A turns + context entries (goals, rules, preferences, lessons) | context extraction | `session_*` tools; skill `mnemoth-sessions` says what to capture |
| Session distillation (curate batches → accept/reject lessons → persist) | curator + writer | `session_timeline` packs batches; skill carries curator + writer rules; `publish_lessons` persists accepted lessons into the graph |
| memify: `cross_connect_entities`, `consolidate_entities`, frequency/feedback weights, global context index | cross-connect, consolidate, summarize | `memify_candidates` (co-occurrence pairs, near-duplicate names) for the agent to judge; `merge_entities`; weights are deterministic tools; `global_context` buckets built deterministically, summaries written by the agent via `set_bucket_summary` |
| Datasets + permissions | none | project Dataset + user-global Dataset; `recall` searches project then user; single-user, no ACL |
| `forget` | none | `forget` (done) + soft `supersede` |
| coding-rule associations (agent rules) | LLM | `rules` section of session context + `recall(search_type="rules")` |
| user preferences + weights | LLM | `preferences` section + rank boost in recall |

Out of scope, permanently: eval framework, cloud/sync, UI, Slack, text-to-SQL, translation, DLT
sources, audio/image transcription, Cypher search, code-graph search, multi-user ACL.

## 2. Storage schema (v2, SQLite per Dataset)

Existing: `meta`, `entity_types`, `entities`, `relations`, `chunks`, `entity_chunks`, `fts`,
`embeddings`. Added:

- `relations` gains `superseded INTEGER`, `superseded_by TEXT`, `supersession_reason TEXT`,
  `weight REAL DEFAULT 1.0`, `valid_from TEXT`, `valid_to TEXT` (ISO dates, nullable).
- `functional_relations(name TEXT PRIMARY KEY)` — declared single-valued relation names.
- `contradictions(id, first_relation_id, second_relation_id, reason, confidence, created_at, resolved_by TEXT)`
  plus a `contradicts` edge between the two subjects, as cognee does.
- `provenance(id, at, actor, action, kind, ref_id, payload JSON)` — append-only ledger.
- `sessions(id, started_at, ended_at, distilled_at)`
- `session_turns(id, session_id, seq, role, text, created_at)` — the fast cache.
- `session_context(id, session_id, section, content, confidence, created_at, retired_at)` —
  sections: goals, rules, preferences, lessons_learned, tool_rules, workflow_state,
  success_patterns, failure_lessons, environment_facts (cognee's list).
- `lessons(id, session_id, title, text, evidence, accepted_at, relation_ids JSON)`.
- `entity_weights(entity_id PRIMARY KEY, frequency REAL, feedback REAL)`.
- `context_buckets(id, key, label, member_ids JSON, summary TEXT, summary_stale INTEGER)`.
- `ontology_sources(id, name, format, imported_at, class_count)` and `entity_types` gains
  `parent TEXT`, `source_id TEXT`, `aliases JSON`.
- Schema version in `meta`; forward-only migrations in `store/migrations.py`.

User-global Dataset: fixed name `user`, same schema, at `~/.mnemoth/user.sqlite`.

## 3. Tools (complete surface)

Ontology: `describe_ontology`, `add_entity_type`, `import_ontology(path|text, format)`,
`declare_functional_relations(names[])`.

Write: `remember` (extended: `valid_from`, `valid_to`, `session_id`; applies functional
supersession; writes provenance; recomputes frequency weights), `mark_contradiction`,
`supersede(old_relation_id, new_relation_id, reason)`, `merge_entities(keep, drop)`,
`set_bucket_summary(bucket_id, summary)`, `forget`.

Read: `recall(query, search_type?, datasets?, session_id?, limit, include_superseded=false)`,
`contradiction_candidates(relation_ids[] | entity_names[])`, `history(entity|relation)`,
`memify_candidates(kind: cross_connect|consolidate|stale_summaries, limit)`,
`global_context(limit)`, `list_datasets`.

Sessions: `session_start(session_id?)`, `session_add_turn(session_id, role, text)`,
`session_set_context(session_id, section, content, confidence)`,
`session_get(session_id, sections?)`, `session_timeline(session_id, batch_chars)`,
`publish_lessons(session_id, lessons[])`, `session_end(session_id)`, `session_forget`.

Every mutating tool returns what changed and appends to `provenance`.

## 4. Recall: router and retrieval modes

The regex router is ported verbatim (quoted phrase / "exact" → lexical; when/before/since/
year → temporal; why/explain/because → reasoning; connection/related → neighbourhood;
rules/convention → rules; default → hybrid). The completion step of every cognee search type
is the Host Model, so the 20 types collapse to retrieval modes the tool returns raw:

| mode | returns | cognee types covered |
| --- | --- | --- |
| `hybrid` (default) | entities + facts + chunks, RRF | HYBRID_COMPLETION, GRAPH_COMPLETION, RAG_COMPLETION, FEELING_LUCKY |
| `facts` | ranked relations only | TRIPLET_COMPLETION, GRAPH_COMPLETION_COT |
| `neighbourhood` | top entities expanded 2 hops | GRAPH_COMPLETION_CONTEXT_EXTENSION, GRAPH_COMPLETION_DECOMPOSITION |
| `lexical` | chunks by FTS5 only | CHUNKS_LEXICAL, CHUNKS |
| `summaries` | chunk summaries + bucket summaries | SUMMARIES, GRAPH_SUMMARY_COMPLETION, GRAPH_REPORT |
| `temporal` | facts filtered/sorted by `valid_from`/Date entities in the query | TEMPORAL |
| `rules` | session-context rules/preferences + lessons | CODING_RULES, SKILLS |
| `session` | fast-cache turns + context by keyword, falls through to `hybrid` | session-aware recall |

Ranking: RRF over lexical and vector hits, then multiply by relation `weight`
(frequency × feedback, cognee's memify weights), drop superseded unless asked, project Dataset
before user Dataset with a fixed reserve for user hits (cognee's `conversational_reserve`).

## 5. Skills (single-purpose, Agent Skills format)

- `mnemoth` — recall/remember discipline and extraction rules (done; extend with temporal
  fields, evidence, dataset choice, functional relations).
- `mnemoth-contradictions` — cognee's contradiction rules (only mutually exclusive facts;
  never paraphrases), how to use `contradiction_candidates` → `mark_contradiction` →
  `supersede`, and when to ask the user.
- `mnemoth-sessions` — what to capture into sections during work; at the end of a task or
  session run `session_timeline`, apply the curator rules (propose lessons that are general,
  actionable, non-duplicate), then the writer/rejecter rules (check prior lessons via recall,
  reject duplicates), then `publish_lessons`.
- `mnemoth-memify` — periodic maintenance: cross-connect co-occurring entities with a
  described relation, merge near-duplicate entities, write bucket summaries in the
  "This chunk is about / Facts" shape.
- `mnemoth-ontology` — importing an OWL/Turtle file, extending types, declaring functional
  relations such as `current_ceo`, `owned_by`, `deployed_in`.

## 6. Implementation order (one pass)

1. Schema v2 + migrations; provenance ledger; functional supersession inside `remember`.
2. Ontology import (rdflib optional extra; fallback parser for Turtle class declarations);
   parent → basic-type collapse; aliases in resolution.
3. Recall router + retrieval modes + weights + superseded filtering + temporal filter.
4. Contradictions: candidate builder (cognee's touched-node neighbourhood, structural
   relations excluded), `mark_contradiction`, `supersede`, `history`.
5. Sessions: fast cache, context sections, timeline batching, `publish_lessons` (lessons
   become `Lesson` entities linked to the entities they mention, chunk = lesson text).
6. memify: co-occurrence and near-duplicate candidates, `merge_entities` (re-point edges,
   union chunks, re-index), frequency weights on every write, feedback weights via
   `session_set_context(section="feedback")`, global context buckets by entity type.
7. User-global Dataset and cross-Dataset recall with reserve.
8. Skills 2–5; extend skill 1.
9. Tests for every tool over stdio; installer e2e for all four hosts; `claude plugin validate`.
10. README and docs; tag `v0.2.0`.

## 7. Done means

- Every row of §1 has a tool or a skill section and a test.
- A full session can be run with only the Host Model: remember with evidence, recall by every
  mode, detect and supersede a contradiction, capture session context, distill lessons,
  run memify maintenance, import an ontology, forget.
- `mnemoth install <host>` works for claude, codex, opencode, cursor; the plugin validates.
- No API key, no model call, no host-specific code outside `integrations.py`.
