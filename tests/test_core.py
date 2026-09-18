"""End-to-end coverage of the ported cognee memory core, driven the way the skills drive it."""

import pytest

from memoose.models import CrossConnectIn, EntityIn, LessonIn, RelationIn
from memoose.ontology import OntologyError
from memoose.retrieval import route

E = EntityIn
R = RelationIn


def seed(ds):
    ds.remember(
        entities=[E(name="Acme", type="Organization", description="The company."), E(name="Alice", type="Person", description="Engineer at Acme."), E(name="Bob", type="Person", description="Engineer at Acme."),
                  E(name="auth-service", type="System", description="Authentication service."), E(name="PostgreSQL", type="Technology", description="Relational database."), E(name="2026-03-01", type="Date", description="")],
        relations=[R(source="Alice", name="works_at", target="Acme", description="Alice works at Acme as a platform engineer.", evidence="hr://2026"),
                   R(source="Bob", name="works_at", target="Acme", description="Bob works at Acme."),
                   R(source="auth-service", name="uses", target="PostgreSQL", description="auth-service stores sessions in PostgreSQL.", evidence="repo://src/auth/db.py#L1-L20"),
                   R(source="auth-service", name="migrated_on", target="2026-03-01", description="auth-service migrated to PostgreSQL on 2026-03-01.", valid_from="2026-03-01")],
        summary="This chunk is about:\n- People: Alice, Bob\n- Systems: auth-service\nFacts:\n- Alice and Bob work at Acme.\n- auth-service uses PostgreSQL since 2026-03-01.",
        source_text="Alice and Bob work at Acme. The auth-service stores sessions in PostgreSQL since the migration on 2026-03-01.",
        source="test",
    )


# ----- functional supersession (resolve_temporal_contradictions) -----------------------------
def test_functional_relation_supersedes_older_value(ds):
    seed(ds)
    ds.declare_functional_relations(["owned_by"])
    first = ds.remember([], [R(source="auth-service", name="owned_by", target="Alice", description="Alice owns auth-service.", evidence="user 2026-01")])
    second = ds.remember([], [R(source="auth-service", name="owned_by", target="Bob", description="Bob owns auth-service.", evidence="user 2026-09")])
    assert second["superseded"] and second["superseded"][0]["relation_id"] == first["relations"][0]["id"]
    facts = ds.recall("who owns auth-service", mode="facts")["facts"]
    owners = [f for f in facts if f["relation"] == "owned_by"]
    assert [f["target"] for f in owners] == ["Bob"]
    hist = ds.recall("who owns auth-service", mode="facts", include_superseded=True)["facts"]
    assert {f["target"] for f in hist if f["relation"] == "owned_by"} == {"Alice", "Bob"}
    assert any(f["superseded"] and f["superseded_by"] == second["relations"][0]["id"] for f in hist)
    events = ds.history(relation_id=first["relations"][0]["id"])["events"]
    assert [e["action"] for e in events][:1] == ["supersede"] and events[-1]["action"] == "assert"


def test_non_functional_multi_value_becomes_hotspot_not_supersession(ds):
    seed(ds)
    out = ds.remember([E(name="Redis", type="Technology", description="Cache.")], [R(source="auth-service", name="uses", target="Redis", description="auth-service caches tokens in Redis.")])
    assert not out["superseded"]
    assert out["hotspots"] and out["hotspots"][0]["subject_relation"] == "auth-service --uses"
    assert any("contradiction_candidates" in w for w in out["warnings"])


# ----- contradictions (detect_contradictions) ---------------------------------------------------
def test_contradiction_candidates_mark_and_supersede(ds):
    seed(ds)
    out = ds.remember([E(name="Globex", type="Organization", description="Rival.")], [R(source="Alice", name="works_at", target="Globex", description="Alice works at Globex since 2026-08.", valid_from="2026-08-01")])
    cands = ds.contradiction_candidates(entity_names=["Alice"])
    hot = [h for h in cands["hotspots"] if h["subject_relation"] == "Alice --works_at"]
    assert hot and {f["object"] for f in hot[0]["facts"]} == {"Acme", "Globex"}
    ids = {f["object"]: f["relation_id"] for f in hot[0]["facts"]}
    marked = ds.mark_contradiction(ids["Acme"], ids["Globex"], "A person has one employer at a time.", 0.9)
    assert marked["contradiction_id"]
    assert marked["contradicts_edge"] is None  # same subject: no contradicts edge between subjects
    facts = ds.recall("Alice employer", mode="facts")["facts"]
    assert all(f["contested"] for f in facts if f["relation"] == "works_at" and f["source"] == "Alice")
    assert ds.store.stats()["open_contradictions"] == 1
    ds.supersede(ids["Acme"], ids["Globex"], "Alice moved to Globex in 2026-08.")
    assert ds.store.stats()["open_contradictions"] == 0
    current = ds.recall("Alice employer", mode="facts")["facts"]
    assert {f["target"] for f in current if f["relation"] == "works_at" and f["source"] == "Alice"} == {"Globex"}


def test_contradicts_edge_between_different_subjects(ds):
    seed(ds)
    a = ds.remember([E(name="Report A", type="Concept", description="")], [R(source="Report A", name="states", target="PostgreSQL", description="Report A states auth uses PostgreSQL.")])
    b = ds.remember([E(name="Report B", type="Concept", description=""), E(name="MySQL", type="Technology", description="")], [R(source="Report B", name="states", target="MySQL", description="Report B states auth uses MySQL.")])
    m = ds.mark_contradiction(a["relations"][0]["id"], b["relations"][0]["id"], "Auth cannot use both.", 0.7)
    assert m["contradicts_edge"] and ds.store.get_relation(m["contradicts_edge"]).name == "contradicts"


# ----- recall router and modes ------------------------------------------------------------------
@pytest.mark.parametrize("q,mode", [
    ('"stores sessions in PostgreSQL"', "lexical"),
    ("give me the exact wording about sessions", "lexical"),
    ("what rules do we follow for migrations", "rules"),
    ("summarize this project", "summaries"),
    ("why did auth move to PostgreSQL", "facts"),
    ("what is related to auth-service", "neighbourhood"),
    ("when did auth migrate", "temporal"),
    ("what happened in 2026", "temporal"),
    ("who works at Acme", "hybrid"),
])
def test_router(q, mode):
    assert route(q).mode == mode


def test_modes_return_expected_shapes(ds):
    seed(ds)
    lex = ds.recall('"stores sessions in PostgreSQL"')
    assert lex["mode"] == "lexical" and lex["chunks"] and "PostgreSQL" in lex["chunks"][0]["text"]
    assert ds.recall('"no such phrase anywhere"')["chunks"] == []
    nb = ds.recall("auth-service", mode="neighbourhood", hops=2)
    assert {f["target"] for f in nb["facts"]} >= {"PostgreSQL", "2026-03-01"}
    tmp = ds.recall("when did auth-service migrate")
    assert tmp["mode"] == "temporal" and tmp["facts"][0]["when"] == "2026-03-01"
    assert ds.recall("what happened in 2019", mode="temporal")["facts"] == []
    summ = ds.recall("summarize the project")
    assert summ["mode"] == "summaries" and summ["summaries"] and "Alice" in summ["summaries"][0]["summary"]
    facts = ds.recall("why does auth-service use PostgreSQL", mode="facts")
    assert facts["facts"][0]["evidence"] == "repo://src/auth/db.py#L1-L20"


def test_feedback_weights_change_ranking(ds):
    seed(ds)
    sid = ds.session_start("s1")["session_id"]
    before = ds.recall("engineer at Acme", mode="hybrid")["entities"]
    ds.session_set_context(sid, "feedback", "+Bob -Alice")
    after = ds.recall("engineer at Acme", mode="hybrid")["entities"]
    names_before = [e["name"] for e in before if e["name"] in ("Alice", "Bob")]
    names_after = [e["name"] for e in after if e["name"] in ("Alice", "Bob")]
    assert names_before[0] != names_after[0] or names_after[0] == "Bob"


# ----- sessions and distillation ------------------------------------------------------------------
def test_session_lifecycle_and_lessons(ds):
    seed(ds)
    s = ds.session_start("sess-1")
    assert s["new"] and s["standing_context"] == []
    ds.session_add_turn("sess-1", "user", "Please migrate auth to Postgres 16.")
    ds.session_add_turn("sess-1", "assistant", "Done. The pgvector extension needed CREATE EXTENSION before the migration ran.")
    ds.session_set_context("sess-1", "rules", "Run CREATE EXTENSION before migrations that need it.", 0.9)
    with pytest.raises(ValueError):
        ds.session_set_context("sess-1", "vibes", "x")
    got = ds.session_get("sess-1", sections=["rules"])
    assert len(got["turns"]) == 2 and got["context"][0]["section"] == "rules"
    tl = ds.session_timeline("sess-1", batch_chars=80)
    assert tl["turns"] == 2 and len(tl["batches"]) >= 2 and tl["prior_lessons"] == [] and "curator_rules" in tl
    pub = ds.publish_lessons("sess-1", [LessonIn(title="Enable extensions before migrating", text="Create required PostgreSQL extensions before running migrations that depend on them.", evidence="sess-1 turn 2", applies_to=["PostgreSQL", "Alembic"], entity_types={"Alembic": "Technology"})])
    assert pub["published"][0]["applies_to"] == ["PostgreSQL", "Alembic"]
    end = ds.session_end("sess-1")
    assert end["distilled"] is True
    rules = ds.recall("what rules apply to migrations", mode="rules")
    assert rules["rules"][0]["content"].startswith("Run CREATE EXTENSION") and rules["lessons"][0]["title"] == "Enable extensions before migrating"
    hy = ds.recall("PostgreSQL extensions migration lesson", mode="facts")["facts"]
    assert any(f["relation"] == "applies_to" and f["target"] == "PostgreSQL" for f in hy)
    s2 = ds.session_start("sess-2")
    assert s2["standing_context"][0]["content"].startswith("Run CREATE EXTENSION") and s2["recent_lessons"]
    sess_mode = ds.recall("pgvector extension", mode="session")
    assert sess_mode["session_turns"] and "pgvector" in sess_mode["session_turns"][0]["text"]
    with pytest.raises(OntologyError):
        ds.publish_lessons("sess-2", [LessonIn(title="x", text="y", applies_to=["Nobody"])])


# ----- memify ---------------------------------------------------------------------------------------------
def test_memify_cross_connect_consolidate_and_buckets(ds):
    seed(ds)
    cc = ds.memify_candidates("cross_connect")
    pairs = {(c["a"]["name"], c["b"]["name"]) for c in cc["candidates"]}
    assert any({"Alice", "Bob"} == set(p) for p in pairs)  # co-occur in the chunk, no relation
    ds.cross_connect([CrossConnectIn(source="Alice", name="works_with", target="Bob", description="Alice and Bob are colleagues at Acme.", evidence="test chunk")])
    assert not any({"Alice", "Bob"} == set((c["a"]["name"], c["b"]["name"])) for c in ds.memify_candidates("cross_connect")["candidates"])

    ds.remember([E(name="Postgres", type="Technology", description="Same database, short name.")], [R(source="auth-service", name="backed_by", target="Postgres", description="auth-service is backed by Postgres.")])
    cons = ds.memify_candidates("consolidate")["candidates"]
    assert any({c["keep"]["name"], c["drop"]["name"]} == {"PostgreSQL", "Postgres"} for c in cons)
    merged = ds.merge_entities("PostgreSQL", "Postgres")
    assert merged["relations_repointed"] == 1
    assert ds.store.get_entity(merged["dropped"]) is None
    facts = ds.recall("auth-service database", mode="facts")["facts"]
    assert {f["relation"] for f in facts if f["target"] == "PostgreSQL"} >= {"uses", "backed_by"}
    assert "Also known as Postgres" in ds.store.get_entity(merged["kept"]).description

    gc = ds.global_context()
    assert gc["stale_count"] == len(gc["buckets"]) > 0
    stale = ds.memify_candidates("stale_summaries", limit=1)["candidates"][0]
    assert stale["entities"] and "summary_shape" in stale
    ds.set_bucket_summary(stale["bucket_id"], "This bucket is about:\n- Things\nFacts:\n- something")
    assert ds.global_context()["stale_count"] == len(gc["buckets"]) - 1
    summ = ds.recall("overview of the project", mode="summaries")
    assert summ["global_context"] and summ["global_context"][0]["summary"].startswith("This bucket")


# ----- ontology import -------------------------------------------------------------------------------
TTL = """
@prefix : <http://example.org/onto#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
:Employee a owl:Class ; rdfs:subClassOf :Person ; rdfs:label "Staff member" ; rdfs:comment "Someone employed by the company." .
:Person a owl:Class .
:Microservice a owl:Class ; rdfs:subClassOf :Service .
:Service a owl:Class ; rdfs:comment "A running software service." .
:Sprint a owl:Class ; rdfs:label "Sprint" .
"""


def test_import_turtle_ontology_collapses_to_basic_types(ds):
    res = ds.import_ontology(TTL, name="acme-onto")
    added = {t["name"]: t for t in res["types_added"]}
    assert res["classes_found"] == 5
    assert added["Employee"]["parent"] == "Person" and added["Employee"]["basic_type"] == "Person" and added["Employee"]["aliases"] == ["Staff member"]
    assert added["Service"]["basic_type"] == "System"
    assert added["Microservice"]["parent"] == "Service" and added["Microservice"]["basic_type"] == "System"
    assert added["Sprint"]["basic_type"] == "Concept"
    out = ds.remember([E(name="Carol", type="staff member", description="")], [])
    assert out["entities"][0]["type"] == "Employee"
    onto = ds.describe_ontology()
    assert onto["ontology_sources"][0]["name"] == "acme-onto"
    with pytest.raises(OntologyError):
        ds.remember([E(name="x", type="Mathematician", description="")], [])


XML = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:owl="http://www.w3.org/2002/07/owl#" xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Class rdf:about="http://x.org/o#DataCenter"><rdfs:subClassOf rdf:resource="http://x.org/o#Location"/><rdfs:comment>A physical location hosting servers.</rdfs:comment></owl:Class>
  <owl:Class rdf:about="http://x.org/o#Location"/>
</rdf:RDF>"""


def test_import_rdf_xml_fallback(ds):
    res = ds.import_ontology(XML, name="dc")
    added = {t["name"]: t for t in res["types_added"]}
    assert added["Location"]["basic_type"] == "Place" and added["DataCenter"]["basic_type"] == "Place"


def test_type_suggestion_on_typo(ds):
    with pytest.raises(OntologyError) as ei:
        ds.remember([E(name="x", type="Persn", description="")], [])
    assert "Did you mean Person" in str(ei.value)


# ----- cross-dataset recall ------------------------------------------------------------------------
def test_project_then_user_dataset_with_reserve(engine):
    proj = engine.dataset(engine.default_dataset_name())
    user = engine.user()
    seed(proj)
    user.remember([E(name="Hieu", type="Person", description="The user."), E(name="tabs", type="Requirement", description="Indentation preference.")],
                  [R(source="Hieu", name="prefers", target="tabs", description="Hieu prefers tabs over spaces in all projects.", evidence="user said")])
    out = engine.recall("what does Hieu prefer for indentation")
    assert out["datasets"] == [engine.default_dataset_name(), "user"]
    assert any(f["fact"].startswith("Hieu --prefers--> tabs") and f["dataset"] == "user" for f in out["facts"])
    only = engine.recall("Hieu indentation", datasets=[engine.default_dataset_name()])
    assert not any(f["dataset"] == "user" for f in only["facts"])


def test_history_for_entity_aggregates_relations(ds):
    seed(ds)
    h = ds.history(entity="auth-service")
    actions = {e["action"] for e in h["events"]}
    assert {"create", "assert"} <= actions


def test_merge_by_name_keeps_stats_and_schema_version(ds):
    seed(ds)
    st = ds.store.stats()
    assert st["schema_version"] == 3 and st["entities"] == 6 and st["relations"] == 4
