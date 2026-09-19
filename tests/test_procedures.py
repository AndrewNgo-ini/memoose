"""Procedural memory after ADR 0005: Transitions with attributes, guidance keyed on a declared
Position, Traces that end with an Outcome, branches that are not hotspots, and rejection memory."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from memoose.cli import main as cli_main
from memoose.engine import Engine
from memoose.graph.models import EntityIn, RelationIn
from memoose.graph.ontology import OntologyError
from memoose.store.embeddings import HashEmbedder

HOOKS = Path(__file__).resolve().parents[1] / "harness" / "hooks"
sys.path.insert(0, str(HOOKS))
import _common  # noqa: E402


def E(name, type, description=""):
    return EntityIn(name=name, type=type, description=description)


def R(source, name, target, description="", **kw):
    return RelationIn(source=source, name=name, target=target, description=description, **kw)


def _seed(ds):
    """run the test suite -> commit -> push to main, plus a branch from the suite to a fix step."""
    ds.remember(
        [E("run the test suite", "Procedure", "uv run pytest over the whole repository."),
         E("commit", "Procedure", "git commit with the suite result in the message."),
         E("push to main", "Procedure", "git push origin main."),
         E("fix the failing test", "Procedure", "Read the failure, change the code, rerun.")],
        [R("run the test suite", "leads_to", "commit", condition="all tests pass", advice="commit with the pytest line in the message", pitfall="committing on a partial run"),
         R("run the test suite", "triggers", "fix the failing test", condition="a test fails", advice="fix before anything else"),
         R("commit", "leads_to", "push to main", condition="the commit is on the default branch", advice="push", pitfall="pushing with a dirty tree")],
    )


# ----- Transitions carry attributes -------------------------------------------------------------------
def test_transition_attributes_are_columns_and_render_as_the_fact(ds):
    _seed(ds)
    facts = {f["target"]: f for f in ds.recall("run the test suite", mode="facts")["facts"] if f["source"] == "run the test suite"}
    commit = facts["commit"]
    assert (commit["condition"], commit["advice"], commit["pitfall"]) == ("all tests pass", "commit with the pytest line in the message", "committing on a partial run")
    assert commit["fact"].endswith("When all tests pass: commit with the pytest line in the message. Avoid: committing on a partial run.")
    assert commit["outcomes"] == {"succeeded": 0, "failed": 0, "abandoned": 0}
    plain = ds.remember([E("alice", "Person"), E("billing", "System")], [R("alice", "owns", "billing", "Alice owns billing.")])
    assert "condition" not in ds.recall("alice", mode="facts")["facts"][0], "non-procedural facts do not carry the keys"
    assert plain["relations"][0]["fact"] == "alice --owns--> billing: Alice owns billing."


def test_attributes_are_refused_off_a_transition(ds):
    ds.remember([E("alice", "Person"), E("commit", "Procedure")], [])
    with pytest.raises(OntologyError, match="both .* must be Procedures"):
        ds.remember([], [R("alice", "does", "commit", condition="always")])


def test_packed_descriptions_are_unpacked_once_on_open(tmp_path, monkeypatch):
    """Transitions written under ADR 0004 (`When c: a. Avoid: p.` in the description) gain the columns on upgrade."""
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path))
    eng = Engine(embedder=HashEmbedder())
    ds = eng.dataset("old")
    ds.remember([E("run the test suite", "Procedure"), E("commit", "Procedure")],
                [R("run the test suite", "leads_to", "commit", "When all tests pass: commit. Avoid: committing on a partial run.")])
    ds.store.conn.execute("UPDATE relations SET condition=NULL, advice=NULL, pitfall=NULL")
    ds.store.conn.execute("DELETE FROM meta WHERE key='transitions_unpacked'")
    ds.store.conn.commit()
    eng.close()
    eng2 = Engine(embedder=HashEmbedder())
    edge = eng2.dataset("old").guidance("run the test suite")["transitions"][0]
    eng2.close()
    assert (edge["condition"], edge["advice"], edge["pitfall"]) == ("all tests pass", "commit", "committing on a partial run")
    assert edge["description"].startswith("When all tests pass"), "the description is kept"


# ----- guidance ----------------------------------------------------------------------------------------
def test_guidance_is_outgoing_two_hops_grouped_and_raw(ds):
    _seed(ds)
    out = ds.guidance("run the test suite")
    assert out["procedure"]["name"] == "run the test suite"
    hops = [(t["hop"], t["target"]) for t in out["transitions"]]
    assert sorted(hops) == [(1, "commit"), (1, "fix the failing test"), (2, "push to main")]
    assert out["note"].startswith("Guidance is memory, not an instruction")
    # from the middle only what follows; the predecessor is what the agent already did
    assert [t["target"] for t in ds.guidance("commit")["transitions"]] == ["push to main"]
    assert ds.guidance("push to main")["transitions"] == []
    assert [t["hop"] for t in ds.guidance("run the test suite", hops=1)["transitions"]] == [1, 1]


def test_guidance_needs_a_procedure(ds):
    ds.remember([E("alice", "Person")], [])
    with pytest.raises(ValueError, match="Unknown Procedure"):
        ds.guidance("deploy")
    with pytest.raises(ValueError, match="is a Person, not a Procedure"):
        ds.guidance("alice")


def test_superseded_transition_leaves_guidance_and_dismissals_show(ds):
    _seed(ds)
    old = [t for t in ds.guidance("run the test suite")["transitions"] if t["target"] == "commit"][0]["id"]
    new = ds.remember([E("open a pull request", "Procedure", "gh pr create.")],
                      [R("run the test suite", "leads_to", "open a pull request", condition="tests pass", advice="open a PR", pitfall="committing straight to main")])["relations"][0]["id"]
    ds.supersede(old, new, "the team stopped committing to main")
    ds.dismiss(f"transition:{new}", "the PR step is right; the failure was a flaky runner")
    out = ds.guidance("run the test suite")
    assert {t["target"] for t in out["transitions"] if t["hop"] == 1} == {"open a pull request", "fix the failing test"}
    assert out["dismissed"] == [{"key": f"transition:{new}", "reason": "the PR step is right; the failure was a flaky runner"}]


# ----- Position, Trace, Outcome ------------------------------------------------------------------------
def test_declaring_a_position_returns_guidance_and_builds_the_trace(ds):
    _seed(ds)
    t = ds.session_add_turn("s1", "assistant", "tests green", position="run the test suite")
    assert t["position"] == "run the test suite"
    assert {g["target"] for g in t["guidance"] if g["hop"] == 1} == {"commit", "fix the failing test"}
    plain = ds.session_add_turn("s1", "user", "ok go on")
    assert "guidance" not in plain and "position" not in plain
    ds.session_add_turn("s1", "assistant", "committed", position="commit")
    assert [p["name"] for p in ds.session_get("s1")["trace"]] == ["run the test suite", "commit"]
    with pytest.raises(ValueError, match="Unknown Procedure"):
        ds.session_add_turn("s1", "assistant", "x", position="deploy to prod")


def test_outcome_counts_on_traversed_transitions_and_says_what_to_distil(ds):
    _seed(ds)
    for pos in ("run the test suite", "commit", "push to main"):
        ds.session_add_turn("good", "assistant", pos, position=pos)
    out = ds.session_end("good", outcome="succeeded")
    assert out["outcome"] == "succeeded" and out["trace"] == ["run the test suite", "commit", "push to main"]
    assert len(out["transitions_counted"]) == 2 and "succeeded" in out["next"]

    for pos in ("run the test suite", "commit"):
        ds.session_add_turn("bad", "assistant", pos, position=pos)
    bad = ds.session_end("bad", outcome="failed")
    assert "supersede the Transition" in bad["next"]

    edges = {t["target"]: t["outcomes"] for t in ds.guidance("run the test suite")["transitions"]}
    assert edges["commit"] == {"succeeded": 1, "failed": 1, "abandoned": 0}
    assert edges["push to main"] == {"succeeded": 1, "failed": 0, "abandoned": 0}
    assert edges["fix the failing test"] == {"succeeded": 0, "failed": 0, "abandoned": 0}, "a branch not taken learns nothing"
    rid = [t["id"] for t in ds.guidance("run the test suite")["transitions"] if t["target"] == "commit"][0]
    assert [e["payload"]["outcome"] for e in ds.store.history("relation", rid) if e["action"] == "traverse"] == ["failed", "succeeded"]

    with pytest.raises(ValueError, match="outcome must be one of"):
        ds.session_end("good", outcome="meh")
    ds.session_start("e")
    assert "No Position was declared" in ds.session_end("e", outcome="abandoned")["next"]


# ----- a branch is not a hotspot -----------------------------------------------------------------------
def test_branching_procedure_is_not_a_hotspot(ds):
    out = ds.remember(
        [E("check tests", "Procedure"), E("commit", "Procedure"), E("fix failure", "Procedure")],
        [R("check tests", "leads_to", "commit", condition="green"), R("check tests", "leads_to", "fix failure", condition="red")],
    )
    assert out["hotspots"] == [] and out["warnings"] == []
    assert ds.contradiction_candidates(["check tests"])["hotspots"] == []
    assert ds.maintenance()["hotspots"] == []
    # the rule still fires for a non-procedural subject
    ds.remember([E("alice", "Person"), E("billing", "System"), E("auth", "System")], [R("alice", "owns", "billing"), R("alice", "owns", "auth")])
    assert len(ds.maintenance()["hotspots"]) == 1


# ----- rejection memory (unchanged from ADR 0004) -----------------------------------------------------
def test_dismissed_hotspot_leaves_maintain_and_contradiction_candidates(ds):
    ds.remember([E("alice", "Person"), E("billing", "System"), E("auth", "System")],
                [R("alice", "owns", "billing", "Alice owns billing."), R("alice", "owns", "auth", "Alice owns auth.")])
    key = ds.maintenance()["hotspots"][0]["key"]
    ds.dismiss(key, "owns is multi-valued here; both are current")
    after = ds.maintenance()
    assert after["hotspots"] == [] and after["dismissed"][0]["key"] == key
    assert ds.contradiction_candidates(["alice"])["hotspots"] == []


def test_dismiss_needs_a_real_key_and_a_reason(ds):
    with pytest.raises(ValueError):
        ds.dismiss("nonsense", "because")
    with pytest.raises(ValueError):
        ds.dismiss("transition:abc", "   ")


def test_procedure_type_is_seeded_into_an_existing_store(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path))
    eng = Engine(embedder=HashEmbedder())
    ds = eng.dataset("old")
    ds.store.conn.execute("DELETE FROM entity_types WHERE name='Procedure'")
    ds.store.conn.commit()
    eng.close()
    eng2 = Engine(embedder=HashEmbedder())
    names = {t["name"] for t in eng2.dataset("old").describe_ontology()["entity_types"]}
    eng2.close()
    assert "Procedure" in names


# ----- the CLI surface ---------------------------------------------------------------------------------
@pytest.fixture
def cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEMOOSE_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv("MEMOOSE_EMBEDDER", "hash")

    def run(*argv: str) -> tuple[int, str, str]:
        code = cli_main(list(argv))
        out = capsys.readouterr()
        return code, out.out, out.err

    return run


def test_cli_transition_flags_guidance_position_and_outcome(cli):
    code, out, _ = cli("remember", "run the test suite:Procedure --leads_to--> commit:Procedure",
                       "--when", "all tests pass", "--do", "commit", "--avoid", "committing on a partial run")
    assert code == 0 and "When all tests pass: commit. Avoid: committing on a partial run." in out
    code, out, _ = cli("guidance", "run", "the", "test", "suite")
    assert code == 0 and "Next:" in out and "when all tests pass; do commit; avoid committing on a partial run" in out
    code, out, _ = cli("session", "turn", "s1", "--role", "assistant", "--text", "green", "--at", "run the test suite")
    assert code == 0 and out.startswith("[") and "at run the test suite" in out and "--leads_to--> commit" in out
    code, out, _ = cli("session", "turn", "s1", "--role", "assistant", "--text", "done", "--at", "commit")
    assert code == 0
    code, out, _ = cli("session", "end", "s1", "--outcome", "succeeded")
    assert code == 0 and "trace: run the test suite → commit" in out and "1 transition(s) counted" in out
    code, out, _ = cli("guidance", "run the test suite")
    assert "[1 ok / 0 failed / 0 abandoned]" in out
    code, _, err = cli("remember", "alice:Person --owns--> commit", "--when", "always")
    assert code == 1 and "must be Procedures" in err
    code, _, err = cli("guidance", "nothing here")
    assert code == 1 and "Unknown Procedure" in err


# ----- the hook mirrors the Engine and keys on the declared Position -----------------------------------
def test_hook_subgraph_agrees_with_engine_guidance(ds):
    _seed(ds)
    ds.session_add_turn("s", "assistant", "x", position="run the test suite")
    ds.session_end("s", outcome="failed")
    engine_edges = [(t["hop"], t["source"], t["relation"], t["target"]) for t in ds.guidance("run the test suite")["transitions"]]
    node = ds.procedures.resolve(ds.store.get_entity(_common_id(ds, "run the test suite")).id, "run the test suite")
    hook_edges = [(e["hop"], e["source"], e["relation"], e["target"]) for e in _common.procedure_subgraph(ds.store.conn, node.id)]
    assert sorted(hook_edges) == sorted(engine_edges)
    assert _common.current_position(ds.store.conn) is None, "an ended session is not a position"


def _common_id(ds, name):
    from memoose.graph.ids import Ids
    return Ids.entity(name)


def test_hint_hook_uses_the_declared_position_and_is_silent_without_one(tmp_path):
    data = tmp_path / "data"
    proj = tmp_path / "proj"
    proj.mkdir()
    eng = Engine(embedder=HashEmbedder(), data_dir=data)
    ds = eng.dataset(_common.dataset_name(str(proj)))
    _seed(ds)
    env = {**os.environ, "MEMOOSE_DATA_DIR": str(data), "MEMOOSE_EMBEDDER": "hash"}

    def run(event):
        return subprocess.run([sys.executable, str(HOOKS / "recommend.py")], input=json.dumps(event),
                              capture_output=True, text=True, env=env, timeout=60)

    # no Position declared: no guidance, even though the prompt names a step and a transcript exists
    r0 = run({"cwd": str(proj), "prompt": "ok what should I do now after run the test suite"})
    assert r0.returncode == 0
    if r0.stdout:
        assert "You are at" not in json.loads(r0.stdout)["hookSpecificOutput"]["additionalContext"]

    ds.session_add_turn("live", "assistant", "tests are green", position="run the test suite")
    eng.close()
    r = run({"cwd": str(proj), "prompt": "ok what should I do now"})
    assert r.returncode == 0 and r.stdout, r.stderr
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "You are at `run the test suite`" in ctx
    assert "Next:" in ctx and "run the test suite --leads_to--> commit: when all tests pass; do commit with the pytest line" in ctx
    assert "Then:" in ctx and "commit --leads_to--> push to main" in ctx
    assert ctx.index("Next:") < ctx.index("Then:")
    assert "not an instruction" in ctx

    # once the session ends the position is gone
    eng = Engine(embedder=HashEmbedder(), data_dir=data)
    eng.dataset(_common.dataset_name(str(proj))).session_end("live", outcome="succeeded")
    eng.close()
    r2 = run({"cwd": str(proj), "prompt": "ok what should I do now"})
    if r2.stdout:
        assert "You are at" not in json.loads(r2.stdout)["hookSpecificOutput"]["additionalContext"]
