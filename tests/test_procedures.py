"""What the Procedural Graphs paper contributed: rejection memory, a Procedure type, and guidance
localised on the agent's last action instead of on the user's prompt."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from memoose.embeddings import HashEmbedder
from memoose.engine import Engine
from memoose.models import EntityIn, RelationIn

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
sys.path.insert(0, str(HOOKS))
import _common  # noqa: E402


def E(name, type, description=""):
    return EntityIn(name=name, type=type, description=description)


def R(source, name, target, description="", **kw):
    return RelationIn(source=source, name=name, target=target, description=description, **kw)


# ----- rejection memory ------------------------------------------------------------------------------
def test_dismissed_hotspot_leaves_maintain_and_contradiction_candidates(ds):
    ds.remember([E("alice", "Person"), E("billing", "System"), E("auth", "System")],
                [R("alice", "owns", "billing", "Alice owns billing."), R("alice", "owns", "auth", "Alice owns auth.")])
    hot = ds.maintenance()["hotspots"]
    assert len(hot) == 1 and hot[0]["key"].startswith("hotspot:")
    key = hot[0]["key"]

    out = ds.dismiss(key, "owns is multi-valued here; both are current")
    assert out["dismissed"] == key

    after = ds.maintenance()
    assert after["hotspots"] == [], "a judged candidate must not come back"
    assert after["dismissed"][0] == {"key": key, "reason": "owns is multi-valued here; both are current"}
    assert ds.contradiction_candidates(["alice"])["hotspots"] == [], "the same judgment applies to the direct query"


def test_dismiss_changes_no_fact_and_is_in_the_ledger(ds):
    ds.remember([E("alice", "Person"), E("billing", "System"), E("auth", "System")],
                [R("alice", "owns", "billing"), R("alice", "owns", "auth")])
    before = ds.recall("alice", include_superseded=True)["facts"]
    key = ds.maintenance()["hotspots"][0]["key"]
    ds.dismiss(key, "fine")
    assert ds.recall("alice", include_superseded=True)["facts"] == before
    assert any(e["action"] == "dismiss" and e["ref_id"] == key for e in ds.store.history("candidate", key))


def test_dismiss_needs_a_real_key_and_a_reason(ds):
    with pytest.raises(ValueError):
        ds.dismiss("nonsense", "because")
    with pytest.raises(ValueError):
        ds.dismiss("consolidate:a:b", "   ")


def test_maintain_cross_connect_needs_two_shared_chunks_but_memify_does_not(ds):
    """One chunk makes every pair co-occur; the periodic pass must not list all of them."""
    ds.remember([E("alice", "Person"), E("bob", "Person"), E("carol", "Person")], [],
                summary="alice bob carol met once", source_text="alice, bob and carol met in one meeting.")
    assert ds.memify_candidates("cross_connect")["candidates"], "an explicit request still sees single-chunk pairs"
    assert ds.maintenance()["cross_connect"] == [], "the pass wants at least two shared chunks"
    ds.remember([E("alice", "Person"), E("bob", "Person")], [],
                summary="alice and bob again", source_text="alice and bob paired on the migration.")
    pairs = {(c["a"]["name"], c["b"]["name"]) for c in ds.maintenance()["cross_connect"]}
    assert pairs == {("alice", "bob")} or pairs == {("bob", "alice")}


# ----- the Procedure type ----------------------------------------------------------------------------
def test_procedure_type_is_seeded_into_an_existing_store(tmp_path, monkeypatch):
    """A store created before the type existed gains it on open; builtins seed additively."""
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


# ----- guidance localised on the last action ---------------------------------------------------------
def _seed_procedure(ds):
    ds.remember(
        [E("run the test suite", "Procedure", "uv run pytest over the whole repository."),
         E("commit", "Procedure", "git commit with the suite result in the message."),
         E("push to main", "Procedure", "git push origin main.")],
        [R("run the test suite", "leads_to", "commit", "When all tests pass: commit. Avoid: committing on a partial run."),
         R("commit", "leads_to", "push to main", "When the commit is on the default branch: push. Avoid: pushing with a dirty tree.")],
    )


def _transcript(tmp_path, tool_name, tool_input) -> Path:
    t = tmp_path / "t.jsonl"
    t.write_text("\n".join(json.dumps(m) for m in [
        {"type": "user", "message": {"role": "user", "content": "please run the tests"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "Running."}, {"type": "tool_use", "name": tool_name, "input": tool_input}]}},
    ]))
    return t


def test_last_tool_uses_reads_name_and_arguments(tmp_path):
    t = _transcript(tmp_path, "Bash", {"command": "uv run pytest -q", "description": "Run the test suite"})
    assert _common.last_tool_uses(str(t)) == ["Bash uv run pytest -q Run the test suite"]
    assert _common.last_tool_uses(None) == [] and _common.last_tool_uses(str(tmp_path / "nope")) == []


def test_locate_and_expand_outgoing_only(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path))
    eng = Engine(embedder=HashEmbedder())
    ds = eng.dataset("p")
    _seed_procedure(ds)
    conn = ds.store.conn
    node = _common.locate_procedure(conn, "Bash uv run pytest -q Run the test suite")
    assert node and node["name"] == "run the test suite"
    edges = _common.procedure_subgraph(conn, node["id"])
    assert [(e["hop"], e["target"]) for e in edges] == [(1, "commit"), (2, "push to main")]
    # from the middle of the chain only what follows is guidance; the predecessor is not
    mid = _common.locate_procedure(conn, "Bash git commit -m 'tests pass'")
    assert mid and mid["name"] == "commit"
    assert [e["target"] for e in _common.procedure_subgraph(conn, mid["id"])] == ["push to main"]
    eng.close()


def test_superseded_transition_is_not_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path))
    eng = Engine(embedder=HashEmbedder())
    ds = eng.dataset("p")
    _seed_procedure(ds)
    old = [f for f in ds.recall("run the test suite", mode="facts")["facts"] if f["target"] == "commit"][0]["id"]
    new = ds.remember([E("open a pull request", "Procedure", "gh pr create.")],
                      [R("run the test suite", "leads_to", "open a pull request", "When tests pass: open a PR. Avoid: committing straight to main.")])["relations"][0]["id"]
    ds.supersede(old, new, "the team stopped committing to main")
    node = _common.locate_procedure(ds.store.conn, "Bash uv run pytest")
    targets = [e["target"] for e in _common.procedure_subgraph(ds.store.conn, node["id"]) if e["hop"] == 1]
    assert targets == ["open a pull request"]
    eng.close()


def test_locate_refuses_a_thin_match(tmp_path, monkeypatch):
    """A wrong procedure would steer the agent; one shared token is not enough to match."""
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path))
    eng = Engine(embedder=HashEmbedder())
    ds = eng.dataset("p")
    _seed_procedure(ds)
    assert _common.locate_procedure(ds.store.conn, "Read the README") is None
    assert _common.locate_procedure(ds.store.conn, "Bash ls -la") is None
    eng.close()


def test_hint_hook_injects_localised_guidance_then_falls_back(tmp_path):
    data = tmp_path / "data"
    proj = tmp_path / "proj"
    proj.mkdir()
    eng = Engine(embedder=HashEmbedder(), data_dir=data)
    _seed_procedure(eng.dataset(_common.dataset_name(str(proj))))
    eng.close()
    env = {**os.environ, "MEMOOSE_DATA_DIR": str(data), "MEMOOSE_EMBEDDER": "hash"}

    def run(event):
        return subprocess.run([sys.executable, str(HOOKS / "recommend.py")], input=json.dumps(event),
                              capture_output=True, text=True, env=env, timeout=60)

    t = _transcript(tmp_path, "Bash", {"command": "uv run pytest -q"})
    r = run({"cwd": str(proj), "prompt": "ok what should I do now", "transcript_path": str(t)})
    assert r.returncode == 0 and r.stdout, r.stderr
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "You just ran `Bash uv run pytest -q`" in ctx
    assert "Next:" in ctx and "run the test suite --leads_to--> commit" in ctx
    assert "Then:" in ctx and "commit --leads_to--> push to main" in ctx
    assert ctx.index("Next:") < ctx.index("Then:"), "grouped by hop, nearest first"
    assert "not an instruction" in ctx

    # no matching step: the hook still works, keyed on the prompt as before
    t2 = _transcript(tmp_path, "Read", {"file_path": "/etc/hosts"})
    r2 = run({"cwd": str(proj), "prompt": "who owns the test suite around here", "transcript_path": str(t2)})
    assert r2.returncode == 0
    if r2.stdout:
        assert "You just ran" not in json.loads(r2.stdout)["hookSpecificOutput"]["additionalContext"]

    # no transcript at all is not an error
    assert run({"cwd": str(proj), "prompt": "what next for the tests"}).returncode == 0
