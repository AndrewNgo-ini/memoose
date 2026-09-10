"""The CLI surface: the fact DSL, exit codes, rendering, spill, and the escape hatch."""

from __future__ import annotations

import json

import pytest

from memoose.cli import CliError, main, parse_fact


@pytest.fixture
def cli(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEMOOSE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("MEMOOSE_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv("MEMOOSE_EMBEDDER", "hash")  # never load an ONNX model in tests

    def run(*argv: str) -> tuple[int, str, str]:
        code = main(list(argv))
        out = capsys.readouterr()
        return code, out.out, out.err

    return run


# ----- the fact DSL -------------------------------------------------------------------
def test_parse_fact_types_both_endpoints():
    source, name, target, src_name, tgt_name = parse_fact("alice:Person --owns--> billing-service:System")
    assert (src_name, name, tgt_name) == ("alice", "owns", "billing-service")
    assert source.type == "Person" and target.type == "System"


def test_parse_fact_untyped_endpoint_is_not_declared():
    source, name, target, src_name, tgt_name = parse_fact("bob:Person --owns--> billing-service")
    assert target is None and tgt_name == "billing-service"
    assert source.name == "bob"


def test_parse_fact_rejects_prose():
    with pytest.raises(CliError, match="is not a fact"):
        parse_fact("alice owns billing")


def test_parse_fact_keeps_colons_that_are_not_types():
    _, _, _, src, tgt = parse_fact("repo:main --depends_on--> lib:v2")
    assert src == "repo:main" and tgt == "lib:v2"  # lowercase suffix is part of the name


# ----- round trip ---------------------------------------------------------------------
def test_remember_then_recall(cli):
    code, out, _ = cli("remember", "alice:Person --owns--> billing-service:System",
                       "--desc", "Alice owns billing.", "-e", "repo://src/auth.py#L40-L82")
    assert code == 0 and "stored 2 entities, 1 facts" in out

    code, out, _ = cli("recall", "who", "owns", "billing")
    assert code == 0
    assert "alice --owns--> billing-service" in out
    assert "repo://src/auth.py#L40-L82" in out  # evidence survives to the rendered line


def test_untyped_endpoint_must_already_exist(cli):
    code, _, err = cli("remember", "bob:Person --owns--> never-seen")
    assert code == 1 and "neither in `entities` nor already remembered" in err


def test_bad_fact_exits_one(cli):
    code, _, err = cli("remember", "alice owns billing")
    assert code == 1 and "is not a fact" in err


def test_json_flag_emits_the_tool_payload(cli):
    cli("remember", "alice:Person --owns--> billing:System", "--desc", "x")
    code, out, _ = cli("--json", "recall", "billing")
    assert code == 0
    payload = json.loads(out)
    assert payload["facts"][0]["fact"].startswith("alice --owns--> billing")
    assert payload["mode"] and payload["datasets"]


def test_output_longer_than_max_inline_spills_to_a_file(cli, tmp_path):
    cli("remember", "alice:Person --owns--> billing:System", "--desc", "A long enough description to push past the cap.")
    code, out, _ = cli("--max-inline", "80", "recall", "billing")
    assert code == 0 and "full output:" in out
    path = tmp_path / "data" / "out"
    spilled = list(path.glob("recall-*.txt"))
    assert spilled and "alice --owns--> billing" in spilled[0].read_text()


def test_history_shows_the_write(cli):
    cli("remember", "alice:Person --owns--> billing:System", "--desc", "Alice owns billing.")
    code, out, _ = cli("history", "billing")
    assert code == 0 and "assert" in out and "alice --owns--> billing" in out


# ----- supersession still works when driven from the shell ----------------------------
def test_functional_supersession_through_the_cli(cli, monkeypatch):
    monkeypatch.setattr("sys.stdin", _Stdin('{"names": ["owns"]}'))
    assert cli("tool", "declare_functional_relations", "--stdin")[0] == 0
    cli("remember", "alice:Person --owns--> billing:System", "--desc", "Alice owns billing.", "--valid-from", "2026-01-01")
    cli("remember", "alice --owns--> auth:System", "--desc", "Alice moved to auth.", "--valid-from", "2026-06-01")

    code, out, _ = cli("recall", "alice", "--superseded")
    assert code == 0 and "SUPERSEDED" in out

    code, out, _ = cli("recall", "alice")
    assert "auth" in out and "SUPERSEDED" not in out  # the current value only, by default


def test_unknown_tool_lists_what_exists(cli):
    code, _, err = cli("tool", "no_such_tool")
    assert code == 1 and "recall" in err


class _Stdin:
    def __init__(self, text: str) -> None:
        self._text = text

    def read(self) -> str:
        return self._text


# ----- the periodic pass --------------------------------------------------------------
def test_maintain_is_quiet_on_an_empty_store(cli):
    code, out, _ = cli("maintain")
    assert code == 0 and "nothing pending" in out


def test_maintain_lists_what_needs_judging(cli):
    cli("remember", "alice:Person --owns--> billing:System", "--desc", "Alice owns billing.")
    cli("remember", "alice --owns--> auth:System", "--desc", "Alice owns auth too.")
    code, out, _ = cli("maintain")
    assert code == 0
    assert "need judging" in out
    assert "hotspot: alice --owns" in out, "one subject with two values for one relation is the hotspot"
    assert "summary needed" in out  # buckets exist but have no summary yet


def test_maintain_decides_nothing_itself(cli):
    """The pass proposes; a model disposes. Running it must not change any fact."""
    cli("remember", "alice:Person --owns--> billing:System", "--desc", "Alice owns billing.")
    cli("remember", "alice --owns--> auth:System", "--desc", "Alice owns auth too.")
    before = cli("--json", "recall", "alice", "--superseded")[1]
    cli("maintain")
    assert cli("--json", "recall", "alice", "--superseded")[1] == before


def test_dataset_flag_works_after_the_subcommand(cli):
    """`memoose remember "..." --dataset user` is the order people write; both must work."""
    assert cli("remember", "alice:Person --owns--> billing:System", "--desc", "x",
               "--dataset", "user")[0] == 0
    assert "alice" in cli("recall", "alice", "--dataset", "user")[1]
    # the leading form still works, and is not clobbered by the trailing default
    assert "alice" in cli("--dataset", "user", "recall", "alice")[1]
    # and the fact went to `user`, not the project dataset
    assert "nothing matched" in cli("recall", "alice", "--no-user")[1]


def test_context_rows_render_as_text_not_json(cli):
    """A rules recall is read by a model; dumping the raw row wastes its context."""
    sid = json.loads(cli("--json", "session", "start")[1])["session_id"]
    cli("session", "context", sid, "--section", "rules", "--text", "Never force-push to main.")
    out = cli("recall", "what rules should I follow")[1]
    assert "[rules] Never force-push to main." in out
    assert '"section"' not in out and '"confidence"' not in out


def test_dismiss_from_the_shell_removes_the_candidate(cli):
    cli("remember", "alice:Person --owns--> billing:System", "--desc", "x")
    cli("remember", "alice --owns--> auth:System", "--desc", "y")
    code, out, _ = cli("--json", "maintain")
    key = json.loads(out)["hotspots"][0]["key"]
    assert cli("dismiss", key, "--reason", "owns is multi-valued")[0] == 0
    code, out, _ = cli("maintain")
    assert "· hotspot:" not in out and "1 earlier candidate(s) dismissed" in out
    with pytest.raises(SystemExit):  # argparse: the reason is required
        cli("dismiss", key)



def test_view_writes_a_self_contained_page_with_the_graph_inline(cli, tmp_path):
    cli("remember", "alice:Person --owns--> billing:System", "--desc", "Alice owns billing.", "-e", "repo://x.py#L1")
    cli("remember", "run tests:Procedure --leads_to--> commit:Procedure", "--desc", "When green: commit.")
    out_path = tmp_path / "g.html"
    code, out, _ = cli("view", "--out", str(out_path), "--no-open")
    assert code == 0 and "4 entities, 2 facts" in out and str(out_path) in out
    html = out_path.read_text()
    assert "<!doctype html>" in html.lower() and "vis-network" in html
    for needle in ("alice", "billing", "Alice owns billing.", "repo://x.py#L1", "run tests", "leads_to", '"Procedure"'):
        assert needle in html, needle
    assert "</script" not in html.split("const G = ", 1)[1].split(";\n", 1)[0], "inline JSON must not be able to close the script tag"


def test_view_hides_superseded_facts_unless_asked(cli, tmp_path):
    cli("remember", "alice:Person --owns--> billing:System", "--desc", "old", "--valid-from", "2025-01-01")
    cli("remember", "alice --owns--> auth:System", "--desc", "new", "--valid-from", "2026-01-01")
    _stdin = json.dumps({"names": ["owns"]})
    import sys as _sys
    class _S:
        def read(self_inner): return _stdin
    _sys.stdin = _S()
    cli("tool", "declare_functional_relations", "--stdin")
    cli("remember", "alice --owns--> auth", "--desc", "new again", "--valid-from", "2026-02-01")
    p = tmp_path / "a.html"
    cli("view", "--out", str(p), "--no-open")
    assert '"superseded": true' not in p.read_text()
    cli("view", "--out", str(p), "--no-open", "--superseded")
    assert '"superseded": true' in p.read_text()
