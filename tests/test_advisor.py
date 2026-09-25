"""The advisor: guard, delivery routing, delta cursor, and the runner's advisor session."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "harness" / "hooks"
sys.path.insert(0, str(HOOKS))


def _hook(script: str, event: dict, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HOOKS / script)], input=json.dumps(event),
                          capture_output=True, text=True, env={**os.environ, **env}, timeout=60)


def _on(monkeypatch, tmp_path):
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEMOOSE_ADVISOR", "1")
    import advise
    import deliver
    return advise, deliver


def test_guard_normalises_dedupes_budgets_and_caps_blockers(tmp_path, monkeypatch):
    advise, _ = _on(monkeypatch, tmp_path)
    assert advise.normalize("  *STOP!* ") == "stop"
    assert advise.emit("s", "1", "concern", "Stop.").startswith("Suppressed"), "content-free filler"
    assert advise.emit("s", "1", "nit", "Reuse parseConfig() here.").startswith("Accepted")
    assert advise.emit("s", "1", "nit", "reuse parseConfig here").startswith("Suppressed"), "same note, same rank"
    assert advise.emit("s", "1", "concern", "Reuse parseConfig() here!").startswith("Accepted"), "escalation passes"
    assert advise.emit("s", "1", "nit", "a").startswith("Accepted")
    assert advise.emit("s", "1", "nit", "b").startswith("Accepted")
    assert "already sent this update" in advise.emit("s", "1", "nit", "c"), "4 non-blockers per update"
    assert advise.emit("s", "2", "nit", "c").startswith("Accepted"), "the budget resets per update"
    assert advise.emit("s", "2", "blocker", "x1") == "Accepted as blocker."
    assert advise.emit("s", "2", "blocker", "x2") == "Accepted as blocker."
    assert advise.emit("s", "2", "blocker", "x3") == "Accepted as concern.", "blockers past the cap downgrade"
    assert advise.emit("s", "2", "maybe", "x4").startswith("Rejected")


def test_delivery_routes_each_severity_to_its_safe_point(tmp_path, monkeypatch):
    advise, deliver = _on(monkeypatch, tmp_path)
    ev = lambda name, **kw: {"session_id": "s", "hook_event_name": name, **kw}  # noqa: E731
    advise.emit("s", "1", "nit", "Consider reusing the helper.")
    advise.emit("s", "1", "concern", "This migration drops a column that prod still reads.")
    out = deliver.route(ev("PostToolUse"))
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert 'severity="concern"' in ctx and "nit" not in ctx, "a concern steers mid-turn, a nit waits"

    advise.emit("s", "2", "concern", "The retry loop never backs off.")
    assert deliver.route(ev("PostToolUse")) is None, "the immune window holds a second concern"
    advise.emit("s", "2", "blocker", "rm -rf is running against the real data dir.")
    assert 'severity="blocker"' in deliver.route(ev("PostToolUse"))["hookSpecificOutput"]["additionalContext"], \
        "blockers are exempt from the immune window"

    ctx = deliver.route(ev("UserPromptSubmit", prompt_id="p2"))["hookSpecificOutput"]["additionalContext"]
    assert "helper" in ctx and "backs off" in ctx, "held notes arrive at the next prompt"
    assert deliver.route(ev("UserPromptSubmit", prompt_id="p2")) is None, "each advisory is delivered once"

    advise.emit("s", "3", "blocker", "Tests were never run; the task said green CI.")
    assert deliver.route(ev("Stop", stop_hook_active=True)) is None, "no block inside a block"
    out = deliver.route(ev("Stop"))
    assert out["decision"] == "block" and "green CI" in out["reason"]


def test_delta_includes_tool_activity_drops_own_advice_and_waits_for_whole_lines(tmp_path):
    import advisor
    t = tmp_path / "t.jsonl"
    rows = [
        {"type": "user", "message": {"content": "Add tenant scoping to the query."}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Editing it."},
            {"type": "tool_use", "name": "Edit", "input": {"file_path": "db.py"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
        {"type": "user", "message": {"content": 'Stop hook feedback:\n<advisory severity="blocker">x</advisory>'}},
    ]
    t.write_text("".join(json.dumps(r) + "\n" for r in rows) + '{"type": "assistant", "mess')
    delta, end, mid_turn = advisor.read_delta(str(t), 0)
    assert end == 4, "the half-written last line is left for the next pass"
    assert "Tool call Edit" in delta and "Tool result: ok" in delta
    assert "advisory" not in delta, "the advisor never reviews its own advice"
    assert mid_turn
    with t.open("a") as f:
        f.write('age": {"content": [{"type": "text", "text": "Done."}]}}\n')
    delta, end, mid_turn = advisor.read_delta(str(t), 4)
    assert end == 5 and delta == "Agent: Done." and not mid_turn


def test_runner_starts_then_resumes_one_advisor_session(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "argv"
    (fake_bin / "claude").write_text(f'#!/bin/sh\necho "$@" >> {log}\necho ==CALL== >> {log}\ncat > /dev/null\n')
    (fake_bin / "claude").chmod(0o755)
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "WATCHDOG.md").write_text("Watch for queries without tenant_id.")
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "user", "message": {"content": "Refactor the billing query."}}) + "\n")
    env = {"MEMOOSE_DATA_DIR": str(tmp_path / "data"), "PATH": f"{fake_bin}:{os.environ['PATH']}"}
    ev = {"session_id": "s", "cwd": str(proj), "transcript_path": str(t), "hook_event_name": "PostToolUse"}

    assert _hook("advisor.py", ev, env).returncode == 0
    assert not log.exists(), "off by default"
    env["MEMOOSE_ADVISOR"] = "1"
    assert _hook("advisor.py", ev, env).returncode == 0
    assert _hook("advisor.py", ev, env).returncode == 0
    calls = lambda: log.read_text().split("==CALL==\n")[:-1]  # noqa: E731
    assert len(calls()) == 1, "nothing new since the cursor, no second review"
    with t.open("a") as f:
        f.write(json.dumps({"type": "assistant", "message": {"content": "Done."}}) + "\n")
    assert _hook("advisor.py", ev, env).returncode == 0
    first, second = calls()
    assert "--session-id" in first and "--resume" in second
    assert first.split("--session-id ")[1].split()[0] == second.split("--resume ")[1].split()[0]
    assert "tenant_id" in first, "WATCHDOG.md reaches the advisor"
    assert "--dangerously-skip-permissions" not in first, "the advisor's tools are an allowlist"
    assert "--model haiku" in first


def test_late_blocker_wakes_an_idle_primary(tmp_path, monkeypatch):
    advise, _ = _on(monkeypatch, tmp_path)
    t = tmp_path / "t.jsonl"
    t.write_text(json.dumps({"type": "assistant", "message": {"content": "All done."}}) + "\n")
    import _common
    _common.write_offset("advisor-s", 1)  # already reviewed; only the pending blocker is left
    advise.emit("s", "1", "blocker", "The deploy script was edited but never run.")
    r = _hook("advisor.py", {"session_id": "s", "cwd": str(tmp_path), "transcript_path": str(t),
                             "hook_event_name": "Stop"},
              {"MEMOOSE_DATA_DIR": str(tmp_path / "data"), "MEMOOSE_ADVISOR": "1"})
    assert r.returncode == 2 and "never run" in r.stderr, "asyncRewake delivers it"
    with advise.session_state("s") as st:
        assert advise.pending(st) == []


def test_a_failing_advisor_halts_instead_of_looping(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "calls"
    (fake_bin / "claude").write_text(f"#!/bin/sh\ncat > /dev/null\necho x >> {log}\nexit 1\n")
    (fake_bin / "claude").chmod(0o755)
    t = tmp_path / "t.jsonl"
    env = {"MEMOOSE_DATA_DIR": str(tmp_path / "data"), "PATH": f"{fake_bin}:{os.environ['PATH']}",
           "MEMOOSE_ADVISOR": "1"}
    for i in range(5):
        with t.open("a") as f:
            f.write(json.dumps({"type": "user", "message": {"content": f"step {i}"}}) + "\n")
        ev = {"session_id": "s", "cwd": str(tmp_path), "transcript_path": str(t), "hook_event_name": "PostToolUse"}
        assert _hook("advisor.py", ev, env).returncode == 0
    assert len(log.read_text().splitlines()) == 3, "three failed reviews halt the advisor for the session"
