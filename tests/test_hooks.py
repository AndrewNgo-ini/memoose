"""The hooks must never break a session, and must agree with the library they read."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "hooks"
sys.path.insert(0, str(HOOKS))
import _common  # noqa: E402

from memoose.datasets import project_dataset_name  # noqa: E402
from memoose.embeddings import HashEmbedder  # noqa: E402
from memoose.engine import Engine  # noqa: E402
from memoose.models import EntityIn, LessonIn, RelationIn  # noqa: E402


def run_hook(script: str, event: dict, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(event), capture_output=True, text=True,
        env={**os.environ, **env}, timeout=60,
    )


def test_hook_dataset_naming_matches_library(tmp_path, monkeypatch):
    """_common duplicates the library's naming so hooks need no dependencies; keep them in step."""
    proj = tmp_path / "My Project"
    proj.mkdir()
    monkeypatch.setenv("MEMOOSE_PROJECT_DIR", str(proj))
    assert _common.dataset_name(str(proj)) == project_dataset_name()
    assert _common.dataset_name(None) == project_dataset_name()


def test_legacy_mnemoth_env_and_data_dir_still_resolve(tmp_path, monkeypatch):
    """Setups made before the rename keep working: old env names, and memory left in ~/.mnemoth."""
    from memoose import datasets

    monkeypatch.delenv("MEMOOSE_DATA_DIR", raising=False)
    monkeypatch.delenv("MEMOOSE_PROJECT_DIR", raising=False)
    monkeypatch.setenv("MNEMOTH_DATA_DIR", str(tmp_path / "old"))
    monkeypatch.setenv("MNEMOTH_PROJECT_DIR", str(tmp_path))
    assert datasets.data_dir() == _common.data_dir() == tmp_path / "old"
    assert datasets.project_dataset_name() == _common.dataset_name(None)

    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path / "new"))  # the new name wins when both are set
    assert datasets.data_dir() == _common.data_dir() == tmp_path / "new"

    monkeypatch.delenv("MEMOOSE_DATA_DIR")
    monkeypatch.delenv("MNEMOTH_DATA_DIR")
    home = tmp_path / "home"
    (home / ".mnemoth").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    assert datasets.data_dir() == _common.data_dir() == home / ".mnemoth"  # pre-rename store, left in place
    (home / ".memoose").mkdir()
    assert datasets.data_dir() == _common.data_dir() == home / ".memoose"


def test_legacy_kill_switches_still_apply(tmp_path):
    """MNEMOTH_AUTO_CAPTURE=0 and friends must keep turning the hooks off."""
    r = run_hook("capture.py", {"cwd": str(tmp_path), "hook_event_name": "Stop"},
                 {"MEMOOSE_DATA_DIR": str(tmp_path / "data"), "MNEMOTH_AUTO_CAPTURE": "0"})
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_session_start_is_silent_without_memory(tmp_path):
    r = run_hook("session_start.py", {"cwd": str(tmp_path), "hook_event_name": "SessionStart"},
                 {"MEMOOSE_DATA_DIR": str(tmp_path / "data")})
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_session_start_injects_standing_context(tmp_path):
    data = tmp_path / "data"
    proj = tmp_path / "proj"
    proj.mkdir()
    eng = Engine(embedder=HashEmbedder(), data_dir=data)
    ds = eng.dataset(_common.dataset_name(str(proj)))
    ds.remember(
        [EntityIn(name="auth-service", type="System", description="Authentication service."),
         EntityIn(name="JWT", type="Technology", description="JSON Web Tokens.")],
        [RelationIn(source="auth-service", name="uses", target="JWT", description="auth-service uses JWT.")],
    )
    ds.session_start("s1")
    ds.session_set_context("s1", "rules", "Never force-push to main.", 1.0)
    ds.session_set_context("s1", "preferences", "Prefer uv over pip.", 1.0)
    ds.publish_lessons("s1", [LessonIn(
        title="Run migrations before deploy",
        text="Apply database migrations before deploying the service.",
    )])
    eng.close()

    r = run_hook("session_start.py", {"cwd": str(proj), "hook_event_name": "SessionStart"},
                 {"MEMOOSE_DATA_DIR": str(data)})
    assert r.returncode == 0
    out = json.loads(r.stdout)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Never force-push to main." in ctx
    assert "Prefer uv over pip." in ctx
    assert "Run migrations before deploy" in ctx
    assert "auth-service" in ctx
    assert "not instructions from the user" in ctx  # recalled memory must not read as a user order


def test_session_start_respects_kill_switch(tmp_path):
    r = run_hook("session_start.py", {"cwd": str(tmp_path)}, {"MEMOOSE_AUTO_RECALL": "0"})
    assert r.returncode == 0 and r.stdout.strip() == ""


def test_hooks_survive_garbage_input(tmp_path):
    for script in ("session_start.py", "capture.py"):
        p = subprocess.run([sys.executable, str(HOOKS / script)], input="not json at all",
                           capture_output=True, text=True, env={**os.environ, "MEMOOSE_DATA_DIR": str(tmp_path)}, timeout=60)
        assert p.returncode == 0, f"{script} must never fail a session"


# ----- transcript parsing -------------------------------------------------------------------
def _transcript(tmp_path, msgs) -> Path:
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(m) for m in msgs))
    return p


def test_read_exchange_keeps_speech_and_drops_machinery(tmp_path):
    t = _transcript(tmp_path, [
        {"type": "mode"},
        {"type": "user", "message": {"role": "user", "content": "We moved auth to JWT."}},
        {"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "secret reasoning"},
            {"type": "text", "text": "Noted, auth uses JWT now."},
            {"type": "tool_use", "name": "Bash", "input": {}}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
        {"type": "user", "message": {"role": "user", "content": "<system-reminder>ignore me</system-reminder>"}},
    ])
    text, n, tools = _common.read_exchange(str(t))
    assert "We moved auth to JWT." in text
    assert "Noted, auth uses JWT now." in text
    assert "secret reasoning" not in text  # thinking is never persisted
    assert "ignore me" not in text  # injected system text is not the user speaking
    assert "tool_result" not in text
    assert tools is True and n == 5


def test_read_exchange_resumes_from_offset(tmp_path):
    t = _transcript(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": "first thing"}},
        {"type": "user", "message": {"role": "user", "content": "second thing"}},
    ])
    text, n, _ = _common.read_exchange(str(t), start_line=1)
    assert "second thing" in text and "first thing" not in text and n == 2


def test_read_exchange_tolerates_missing_and_corrupt(tmp_path):
    assert _common.read_exchange(None) == ("", 0, False)
    assert _common.read_exchange(str(tmp_path / "nope.jsonl"), 3)[1] == 3
    bad = tmp_path / "bad.jsonl"
    bad.write_text("{not json\n" + json.dumps({"type": "user", "message": {"role": "user", "content": "kept"}}))
    assert "kept" in _common.read_exchange(str(bad))[0]


def test_offsets_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path))
    assert _common.read_offset("sess/1") == 0
    _common.write_offset("sess/1", 42)
    assert _common.read_offset("sess/1") == 42


# ----- capture gate and locking --------------------------------------------------------------
def test_capture_gate_skips_thin_turns_without_spending_a_model(tmp_path, monkeypatch):
    """A short turn must advance the offset and never invoke the model."""
    t = _transcript(tmp_path, [{"type": "user", "message": {"role": "user", "content": "ok thanks"}}])
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "claude-was-called"
    (fake_bin / "claude").write_text(f"#!/bin/sh\ntouch {marker}\n")
    (fake_bin / "claude").chmod(0o755)
    env = {"MEMOOSE_DATA_DIR": str(tmp_path / "data"), "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    r = run_hook("capture.py", {"session_id": "s1", "cwd": str(tmp_path), "transcript_path": str(t)}, env)
    assert r.returncode == 0
    assert not marker.exists(), "the relevance gate must not spend a model call on a trivial turn"
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path / "data"))
    assert _common.read_offset("s1") == 1  # still advanced, so the turn is not re-read


def test_capture_invokes_the_small_model_on_substantive_turns(tmp_path, monkeypatch):
    long_text = "We decided to move authentication to JWT because sessions did not scale. " * 12
    t = _transcript(tmp_path, [{"type": "user", "message": {"role": "user", "content": long_text}}])
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    argv, stdin = tmp_path / "argv", tmp_path / "stdin"
    (fake_bin / "claude").write_text(f'#!/bin/sh\necho "$@" > {argv}\ncat > {stdin}\n')
    (fake_bin / "claude").chmod(0o755)
    env = {"MEMOOSE_DATA_DIR": str(tmp_path / "data"), "PATH": f"{fake_bin}:{os.environ['PATH']}",
           "CLAUDE_PLUGIN_ROOT": str(Path(__file__).resolve().parents[1])}
    r = run_hook("capture.py", {"session_id": "s2", "cwd": str(tmp_path), "transcript_path": str(t)}, env)
    assert r.returncode == 0
    args = argv.read_text()
    assert "--model haiku" in args, "capture must run on the small model, not the conversation model"
    assert "--strict-mcp-config" in args and "--mcp-config" in args
    prompt = stdin.read_text()
    assert "JWT" in prompt and "NOTHING" in prompt
    assert "Do NOT store" in prompt  # the precision rules travel with the prompt
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path / "data"))
    assert _common.read_offset("s2") == 1


def test_capture_kill_switch_and_lock(tmp_path, monkeypatch):
    long_text = "A durable decision about the architecture that is definitely long enough. " * 12
    t = _transcript(tmp_path, [{"type": "user", "message": {"role": "user", "content": long_text}}])
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "called"
    (fake_bin / "claude").write_text(f"#!/bin/sh\ntouch {marker}\n")
    (fake_bin / "claude").chmod(0o755)
    base = {"MEMOOSE_DATA_DIR": str(tmp_path / "data"), "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    ev = {"session_id": "s3", "cwd": str(tmp_path), "transcript_path": str(t)}

    assert run_hook("capture.py", ev, {**base, "MEMOOSE_AUTO_CAPTURE": "0"}).returncode == 0
    assert not marker.exists()

    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path / "data"))
    lock = _common.state_dir() / "s3.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("999999")
    assert run_hook("capture.py", ev, base).returncode == 0
    assert not marker.exists(), "a held lock must prevent a second concurrent capture"
    lock.unlink()


def test_capture_survives_missing_claude_cli(tmp_path):
    long_text = "Something durable and long enough to pass the relevance gate for capture. " * 12
    t = _transcript(tmp_path, [{"type": "user", "message": {"role": "user", "content": long_text}}])
    empty = tmp_path / "emptybin"
    empty.mkdir()
    r = run_hook("capture.py", {"session_id": "s4", "cwd": str(tmp_path), "transcript_path": str(t)},
                 {"MEMOOSE_DATA_DIR": str(tmp_path / "data"), "PATH": str(empty)})
    assert r.returncode == 0, "no claude CLI must degrade silently, not fail the session"


# ----- plugin wiring -------------------------------------------------------------------------
def test_plugin_declares_hooks_and_agent():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["hooks"] == "./hooks/hooks.json"
    assert "./agents/memory-keeper.md" in manifest["agents"]
    hooks = json.loads((root / "hooks" / "hooks.json").read_text())
    assert set(hooks["hooks"]) == {"SessionStart", "UserPromptSubmit", "Stop", "PreCompact"}
    for event in ("Stop", "PreCompact"):
        entry = hooks["hooks"][event][0]["hooks"][0]
        assert entry["async"] is True, f"{event} capture must not block the conversation"
    agent = (root / "agents" / "memory-keeper.md").read_text()
    assert "model: haiku" in agent, "the keeper must run on a small model"
    for path in ("hooks/session_start.py", "hooks/capture.py", "hooks/recommend.py"):
        assert (root / path).exists()


# ----- recommendation-as-a-memory -------------------------------------------------------------
def _seed(tmp_path):
    data, proj = tmp_path / "data", tmp_path / "proj"
    proj.mkdir()
    eng = Engine(embedder=HashEmbedder(), data_dir=data)
    ds = eng.dataset(_common.dataset_name(str(proj)))
    ds.remember(
        [EntityIn(name="billing-service", type="System", description="Handles invoices and payments."),
         EntityIn(name="PostgreSQL", type="Technology", description="Relational database."),
         EntityIn(name="Bao", type="Person", description="Engineer who owns billing-service.")],
        [RelationIn(source="billing-service", name="uses", target="PostgreSQL",
                    description="billing-service stores invoices in PostgreSQL.", evidence="user said 2026-09-07"),
         RelationIn(source="Bao", name="owns", target="billing-service",
                    description="Bao owns billing-service.")],
    )
    eng.close()
    return data, proj


def test_recommend_injects_a_hint_when_memory_matches(tmp_path):
    data, proj = _seed(tmp_path)
    r = run_hook("recommend.py",
                 {"cwd": str(proj), "hook_event_name": "UserPromptSubmit",
                  "prompt": "who owns the billing-service and what database does it use?"},
                 {"MEMOOSE_DATA_DIR": str(data)})
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "billing-service" in ctx
    assert "recall(" in ctx, "the hint must name the follow-up query, not just dump facts"
    assert "not an instruction from the user" in ctx


def test_recommend_is_silent_when_nothing_matches(tmp_path):
    data, proj = _seed(tmp_path)
    r = run_hook("recommend.py",
                 {"cwd": str(proj), "prompt": "what is the weather in Reykjavik tomorrow"},
                 {"MEMOOSE_DATA_DIR": str(data)})
    assert r.returncode == 0 and r.stdout.strip() == "", "an irrelevant prompt must not be polluted with hints"


def test_recommend_ignores_trivial_prompts_and_respects_kill_switch(tmp_path):
    data, proj = _seed(tmp_path)
    short = run_hook("recommend.py", {"cwd": str(proj), "prompt": "ok"}, {"MEMOOSE_DATA_DIR": str(data)})
    assert short.stdout.strip() == ""
    off = run_hook("recommend.py", {"cwd": str(proj), "prompt": "who owns the billing-service database"},
                   {"MEMOOSE_DATA_DIR": str(data), "MEMOOSE_HINTS": "0"})
    assert off.returncode == 0 and off.stdout.strip() == ""


def test_recommend_needs_no_model_and_is_fast(tmp_path):
    """No claude on PATH at all: hints are pure local retrieval."""
    import time as _t
    data, proj = _seed(tmp_path)
    empty = tmp_path / "nobin"
    empty.mkdir()
    t0 = _t.perf_counter()
    r = run_hook("recommend.py", {"cwd": str(proj), "prompt": "which database does billing-service use"},
                 {"MEMOOSE_DATA_DIR": str(data), "PATH": str(empty)})
    assert r.returncode == 0 and "PostgreSQL" in r.stdout
    assert _t.perf_counter() - t0 < 5


def test_recommend_reaches_the_user_dataset(tmp_path):
    """`recall` searches project then user; the hint must too, or standing rules never surface.

    The capture hook deliberately files facts about the person — their hard rules and
    preferences — under the user Dataset, so a hint that only reads the project Dataset drops
    exactly the memory that applies to every prompt.
    """
    data, proj = _seed(tmp_path)
    eng = Engine(embedder=HashEmbedder(), data_dir=data)
    eng.dataset("user").remember(
        [EntityIn(name="Approve new dependencies first", type="Requirement",
                  description="A hard rule that no new dependency may be added without explicit approval.")],
        [],
    )
    eng.close()
    r = run_hook("recommend.py",
                 {"cwd": str(proj), "prompt": "can I add the requests library as a dependency?"},
                 {"MEMOOSE_DATA_DIR": str(data)})
    assert r.returncode == 0 and r.stdout.strip(), "the user's standing rule must reach the hint"
    assert "dependency" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]


def test_recommend_relevance_floor_is_corpus_aware(tmp_path):
    """A fixed bm25 floor silences memory exactly when it is new.

    bm25's IDF term is zero for a token present in every indexed row, so in a store with a
    handful of rows even a perfect keyword match scores ~0.0. With a fixed floor of 0.5 the
    hint hook stayed silent for the first sessions on a project, and permanently for the
    user Dataset, which never grows large.
    """
    data, proj = tmp_path / "data", tmp_path / "proj"
    proj.mkdir()
    eng = Engine(embedder=HashEmbedder(), data_dir=data)
    eng.dataset(_common.dataset_name(str(proj))).remember(
        [EntityIn(name="Never force-push to main", type="Requirement", description="Force-pushing to main is forbidden on this project.")],
        [],
    )
    eng.close()
    r = run_hook("recommend.py", {"cwd": str(proj), "prompt": "can I force-push this branch to main?"},
                 {"MEMOOSE_DATA_DIR": str(data)})
    assert r.returncode == 0 and r.stdout.strip(), "a one-fact store must still be able to raise its hand"
    assert "force-push" in json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    quiet = run_hook("recommend.py", {"cwd": str(proj), "prompt": "what is the capital of France?"},
                     {"MEMOOSE_DATA_DIR": str(data)})
    assert quiet.stdout.strip() == "", "dropping the floor must not make a tiny store chatty"


def test_capture_prompt_pins_the_dataset(tmp_path):
    """A capture running in a temp cwd must not invent a dataset named after that temp dir."""
    long_text = "We chose PostgreSQL for billing because MySQL could not handle the reporting joins. " * 8
    t = _transcript(tmp_path, [{"type": "user", "message": {"role": "user", "content": long_text}}])
    proj = tmp_path / "proj"
    proj.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    stdin = tmp_path / "stdin"
    (fake_bin / "claude").write_text(f'#!/bin/sh\ncat > {stdin}\n')
    (fake_bin / "claude").chmod(0o755)
    r = run_hook("capture.py", {"session_id": "sd", "cwd": str(proj), "transcript_path": str(t)},
                 {"MEMOOSE_DATA_DIR": str(tmp_path / "data"), "PATH": f"{fake_bin}:{os.environ['PATH']}"})
    assert r.returncode == 0
    assert f'dataset: "{_common.dataset_name(str(proj))}"' in stdin.read_text()


def test_recommend_never_hints_a_superseded_fact(tmp_path):
    """`recall` drops superseded facts by default; the hint must too.

    Supersession only flips a column — the fts row survives — so a hint built straight off
    the index will hand the agent the fact that was *replaced*, before it has thought about
    anything, which is worse than a stale `recall` the agent chose to make.
    """
    data, proj = tmp_path / "data", tmp_path / "proj"
    proj.mkdir()
    eng = Engine(embedder=HashEmbedder(), data_dir=data)
    ds = eng.dataset(_common.dataset_name(str(proj)))
    old = ds.remember(
        [EntityIn(name="billing-service", type="System", description="Handles invoices."),
         EntityIn(name="eu-west-1", type="Place", description="An AWS region."),
         EntityIn(name="eu-central-1", type="Place", description="An AWS region.")],
        [RelationIn(source="billing-service", name="deployed_in", target="eu-west-1",
                    description="billing-service is deployed in eu-west-1.", evidence="terraform 2024-03")],
    )["relations"][0]["id"]
    new = ds.remember([], [RelationIn(source="billing-service", name="deployed_in", target="eu-central-1",
                                      description="billing-service is deployed in eu-central-1 after the migration.",
                                      evidence="terraform 2025-01")])["relations"][0]["id"]
    assert ds.supersede(old, new, "migrated in January 2025")["superseded"] is True
    eng.close()

    r = run_hook("recommend.py", {"cwd": str(proj), "prompt": "where is the billing-service deployed right now?"},
                 {"MEMOOSE_DATA_DIR": str(data)})
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "eu-central-1" in ctx, "the current fact must still be hinted"
    assert "eu-west-1" not in ctx, "a superseded fact must never be injected as if it were current"
