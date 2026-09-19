from memoose.graph.models import EntityIn, RelationIn
from memoose.graph.ontology import OntologyError

TEXT = "We moved auth to JWT last week. Bao owns auth-service now, Linh moved to billing."


def _remember_auth(ds):
    return ds.remember(
        entities=[
            EntityIn(name="auth-service", type="System", description="Authentication service of this project."),
            EntityIn(name="JWT", type="Technology", description="JSON Web Tokens used for auth."),
            EntityIn(name="Bao", type="Person", description="Engineer, owns auth-service."),
            EntityIn(name="Linh", type="Person", description="Engineer, moved to billing."),
            EntityIn(name="billing", type="Component", description="Billing area."),
        ],
        relations=[
            RelationIn(source="auth-service", name="uses", target="JWT", description="auth-service authenticates with JWT.", evidence="user said 2026-09-06"),
            RelationIn(source="Bao", name="owns", target="auth-service", description="Bao owns auth-service."),
            RelationIn(source="Linh", name="works_on", target="billing", description="Linh moved to billing."),
        ],
        summary="This chunk is about:\n- People: Bao, Linh\nFacts:\n- auth-service uses JWT.",
        source_text=TEXT,
        source="chat",
    )


def test_remember_and_recall_roundtrip(ds):
    out = _remember_auth(ds)
    assert len(out["entities"]) == 5 and all(not e["merged"] for e in out["entities"])
    assert len(out["relations"]) == 3 and all(r["new"] for r in out["relations"])
    assert out["chunks_stored"] == 1

    res = ds.recall("who owns auth-service?")
    names = [e["name"] for e in res["entities"]]
    assert "auth-service" in names
    facts = [f["fact"] for f in res["facts"]]
    assert any("Bao --owns--> auth-service" in f for f in facts)
    owning = next(f for f in res["facts"] if f["relation"] == "uses")
    assert owning["evidence"] == "user said 2026-09-06"
    assert res["chunks"] and TEXT in res["chunks"][0]["text"]


def test_entities_merge_by_name_case_insensitive(ds):
    _remember_auth(ds)
    out = ds.remember(
        entities=[EntityIn(name="bao", type="Person", description="Bao Nguyen, senior engineer who owns auth-service.")],
        relations=[RelationIn(source="bao", name="reports_to", target="Linh", description="Bao reports to Linh.")],
    )
    e = out["entities"][0]
    assert e["merged"] and e["name"] == "Bao" and e["mentions"] == 2
    assert "senior engineer" in e["description"]  # longer description wins
    assert ds.store.stats()["entities"] == 5


def test_unknown_type_is_a_teaching_error(ds):
    try:
        ds.remember(entities=[EntityIn(name="Bao", type="Mathematician", description="")], relations=[])
    except OntologyError as e:
        msg = str(e)
        assert "Mathematician" in msg and "Person" in msg and "add_entity_type" in msg
    else:
        raise AssertionError("expected OntologyError")
    assert ds.store.stats()["entities"] == 0  # nothing written on validation failure


def test_bad_relation_name_and_dangling_endpoint(ds):
    for rel in (
        RelationIn(source="Bao", name="Owns", target="auth-service"),
        RelationIn(source="Bao", name="owns", target="ghost-service"),
    ):
        try:
            ds.remember(entities=[EntityIn(name="Bao", type="Person"), EntityIn(name="auth-service", type="System")], relations=[rel])
        except OntologyError:
            pass
        else:
            raise AssertionError(f"expected OntologyError for {rel}")


def test_add_entity_type_then_use_it(ds):
    ds.add_entity_type("ApiEndpoint", "An HTTP route exposed by a service.")
    out = ds.remember(entities=[EntityIn(name="POST /login", type="apiendpoint", description="Login route.")], relations=[])
    assert out["entities"][0]["type"] == "ApiEndpoint"
    assert any(t["name"] == "ApiEndpoint" for t in ds.describe_ontology()["entity_types"])


def test_forget_entity_cascades(ds):
    _remember_auth(ds)
    assert ds.forget_entity("Bao") == 1
    assert ds.store.stats()["relations"] == 2
    res = ds.recall("Bao owns")
    assert all(e["name"] != "Bao" for e in res["entities"])


def test_persistence_across_engine_instances(engine):
    _remember_auth(engine.dataset("persist"))
    engine.close()
    from memoose.store.embeddings import HashEmbedder
    from memoose.engine import Engine

    again = Engine(embedder=HashEmbedder())
    try:
        assert again.dataset("persist").store.stats()["entities"] == 5
        assert "persist" in again.list_datasets()
    finally:
        again.close()


def test_default_dataset_is_project_scoped(engine):
    name = engine.default_dataset_name()
    assert name.startswith("proj-") and len(name) == len("proj-") + 8
