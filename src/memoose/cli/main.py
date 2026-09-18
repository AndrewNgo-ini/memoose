"""`memoose` on the command line: the same Engine the MCP server exposes, driven from a shell.

Why both surfaces exist: an MCP server puts ~21 tool schemas in the model's context on every
turn whether or not memory is touched. A CLI costs nothing until it is called, and a coding
agent already knows how to run a command and read its output. The MCP server stays for hosts
where the shell is restricted or a tool UI is wanted; `memoose serve` still starts it, and the
`mcp` package is imported only on that path.

Output is compact text for a reader (human or model). `--json` gives the exact payload the MCP
tool would return. Anything longer than `--max-inline` is written to a file and replaced by its
path, so a large recall does not flood a transcript.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from .datasets import data_dir
from .engine import Engine
from .models import EntityIn, LessonIn, RelationIn
from .ontology import OntologyError
from .retrieval import MODES

HOSTS = ["claude", "codex", "opencode", "cursor"]
SECTIONS_HINT = "goals, rules, preferences, lessons_learned, tool_rules, workflow_state, success_patterns, failure_lessons, environment_facts, feedback"

# alice:Person --owns--> billing-service:System
FACT = re.compile(r"^\s*(?P<source>.+?)\s*--\s*(?P<name>[A-Za-z0-9_]+)\s*-->\s*(?P<target>.+?)\s*$")
TYPE_SUFFIX = re.compile(r"^(?P<name>.+):(?P<type>[A-Z][A-Za-z0-9]*)$")


class CliError(Exception):
    """A message for the caller. Printed to stderr; exits 1."""


# ----- fact DSL ---------------------------------------------------------------------
def parse_fact(text: str) -> tuple[EntityIn | None, str, EntityIn | None, str, str]:
    """`name[:Type] --relation--> name[:Type]` into typed endpoints plus bare names.

    A `:Type` suffix declares the entity; without one the endpoint must already be
    remembered, and the engine says so if it is not.
    """
    m = FACT.match(text)
    if not m:
        raise CliError(f"{text!r} is not a fact. Write it as 'source:Type --relation_name--> target:Type' (the :Type is needed only for entities memoose has not seen).")
    source, target = _endpoint(m["source"]), _endpoint(m["target"])
    return source[1], m["name"], target[1], source[0], target[0]


def _endpoint(text: str) -> tuple[str, EntityIn | None]:
    m = TYPE_SUFFIX.match(text.strip())
    if not m:
        return text.strip(), None
    return m["name"].strip(), EntityIn(name=m["name"].strip(), type=m["type"])


# ----- rendering --------------------------------------------------------------------
def _fact_line(f: dict) -> str:
    bits = [f"· {f['fact']}"]
    if f.get("evidence"):
        bits.append(f"[{f['evidence']}]")
    if f.get("valid_from"):
        bits.append(f"(from {f['valid_from']})")
    if f.get("superseded"):
        bits.append("SUPERSEDED")
    if f.get("contested"):
        bits.append("CONTESTED")
    return " ".join(bits)


def _label(key: str, row) -> str:
    """A context row knows its own section (rules, preferences, goals); prefer that."""
    return row.get("section", key) if isinstance(row, dict) else key


def _row_text(row) -> str:
    """The readable field of a recall row, rather than the whole dict."""
    if isinstance(row, str):
        return row
    if not isinstance(row, dict):
        return str(row)
    for field in ("content", "fact", "text", "summary", "title"):
        if value := row.get(field):
            title = row.get("title")
            return f"{title}: {value}" if title and field != "title" else str(value)
    return json.dumps(row, ensure_ascii=False)[:300]


def render(cmd: str, payload: dict) -> str:
    """Compact text for the shapes the hot path returns; JSON for everything else."""
    if "error" in payload:
        return f"{payload['error']}: {payload.get('message', '')}"
    out: list[str] = []
    if cmd == "recall":
        scope = ", ".join(payload.get("datasets") or [payload.get("dataset") or "?"])
        out.append(f"[{scope}] mode={payload.get('mode')} query={payload.get('query')!r}")
        for f in payload.get("facts", []):
            out.append(_fact_line(f))
        for e in payload.get("entities", []):
            out.append(f"· {e['name']} ({e['type']}) {e.get('description', '')}".rstrip())
        for c in payload.get("chunks", []):
            text = (c.get("summary") or c.get("text") or "").strip().replace("\n", " ")
            out.append(f"· {text[:300]}{'…' if len(text) > 300 else ''}")
        for key in ("rules", "lessons", "context", "turns", "summaries"):
            for row in payload.get(key, []) or []:
                out.append(f"· [{_label(key, row)}] {_row_text(row)}")
        if len(out) == 1:
            out.append("nothing matched")
    elif cmd == "remember":
        ents = payload.get("entities", [])
        rels = payload.get("relations", [])
        out.append(f"[{payload.get('dataset')}] stored {len(ents)} entities, {len(rels)} facts")
        out += [f"· {r['fact']}" + (f" [{r['evidence']}]" if r.get("evidence") else "") for r in rels]
        out += [f"· superseded {s.get('fact', s.get('relation_id'))}" for s in payload.get("superseded", [])]
        out += [f"! {w}" for w in payload.get("warnings", [])]
    elif cmd == "history":
        out.append(f"[{payload.get('dataset')}] {payload.get('kind')} {payload.get('ref_id')}")
        for e in payload.get("events", []):
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(e["at"]))
            p = e.get("payload") or {}
            what = p.get("fact") or p.get("name") or p.get("superseded_by") or p.get("reason") or ""
            out.append(f"· {when} {e['action']:<12} {e['actor']:<10} {what}")
    elif cmd == "contradictions":
        for h in payload.get("hotspots", []):
            out.append(f"! {h.get('source')} --{h.get('relation')}--> {len(h.get('facts', []))} values")
            out += [f"    {_fact_line(f)}" for f in h.get("facts", [])]
        for c in payload.get("open_contradictions", []):
            out.append(f"! open: {c.get('first_relation_id')} vs {c.get('second_relation_id')} — {c.get('reason')}")
        if not out:
            out.append("no hotspots, no open contradictions")
    elif cmd == "ontology":
        types = payload.get("entity_types", [])
        out.append(f"[{payload.get('dataset')}] {len(types)} entity types, embedder={payload.get('embedder')}")
        out.append("types: " + ", ".join(t["name"] for t in types))
        if payload.get("functional_relations"):
            out.append("functional: " + ", ".join(payload["functional_relations"]))
        stats = payload.get("stats") or {}
        out.append("stats: " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    elif cmd == "maintain":
        if not payload.get("pending"):
            return f"[{payload.get('dataset')}] nothing pending"
        out.append(f"[{payload.get('dataset')}] {payload['pending']} items need judging")
        for h in payload.get("hotspots", []):
            out.append(f"· hotspot: {h['subject_relation']} holds {len(h['facts'])} values   [{h['key']}]")
            out += [f"    {f['text']}" for f in h["facts"]]
        for c in payload.get("open_contradictions", []):
            out.append(f"· contradiction: {c.get('reason')}")
        for c in payload.get("consolidate", []):
            out.append(f"· consolidate: {c.get('keep', {}).get('name', c)} / {c.get('drop', {}).get('name', '')} ({c.get('why', '')})   [{c.get('key', '')}]")
        for c in payload.get("cross_connect", []):
            out.append(f"· cross-connect: {c.get('a', {}).get('name', '?')} + {c.get('b', {}).get('name', '?')}, {c.get('shared_chunks', '?')} shared chunks   [{c.get('key', '')}]")
        for b in payload.get("stale_summaries", []):
            out.append(f"· summary needed: {b.get('label', '?')} bucket ({len(b.get('entities', []))} entities) {b.get('bucket_id', '')}")
        for sess in payload.get("undistilled_sessions", []):
            out.append(f"· session {sess['id']} ended without lessons   [{sess.get('key', '')}]")
        if payload.get("dismissed"):
            out.append(f"({len(payload['dismissed'])} earlier candidate(s) dismissed with reasons; `memoose dismiss <key> --reason ...` records a new one)")
        out.append(f"\n{payload.get('guidance', '')}")
    elif cmd == "view":
        out.append(f"[{payload.get('dataset')}] {payload.get('nodes')} entities, {payload.get('edges')} facts, {len(payload.get('types', []))} types")
        out.append(f"wrote {payload.get('path')}" + ("" if payload.get("opened", True) else " (not opened; open it in a browser)")
                   + ("" if payload.get("self_contained", True) else "; the drawing library could not be cached, so this page needs network to draw"))
    elif cmd == "session-start":
        out.append(f"[{payload.get('dataset')}] session {payload.get('session_id')} ({'new' if payload.get('new') else 'resumed'})")
        out += [f"· [{c['section']}] {c['content']}" for c in payload.get("standing_context", [])]
        out += [f"· [lesson] {le.get('title')}: {le.get('text')}" for le in payload.get("recent_lessons", [])]
    else:
        return json.dumps(payload, indent=2, ensure_ascii=False)
    return "\n".join(out)


def emit(cmd: str, payload: dict, args: argparse.Namespace) -> int:
    text = json.dumps(payload, indent=2, ensure_ascii=False) if args.json else render(cmd, payload)
    # `--json` is asked for by something that will parse it, so it is never cut or spilled.
    if args.max_inline and not args.json and len(text) > args.max_inline:
        path = _spill(cmd, text, "json" if args.json else "txt")
        head = text[: args.max_inline].rsplit("\n", 1)[0]
        print(f"{head}\n… {len(text)} chars total; full output: {path}")
    else:
        print(text)
    return 1 if "error" in payload else 0


def _spill(cmd: str, text: str, ext: str) -> Path:
    out = data_dir() / "out"
    out.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - 86400
    for old in out.glob("*.*"):  # yesterday's spills; no daemon, no cron
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    path = out / f"{cmd}-{time.strftime('%Y%m%d-%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.{ext}"
    path.write_text(text, encoding="utf-8")
    return path


def _stdin_json() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        raise CliError("--json - expects a JSON object on stdin.")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise CliError(f"stdin is not valid JSON: {e}") from e
    if not isinstance(payload, dict):
        raise CliError("stdin must be a JSON object, not a list or scalar.")
    return payload


# ----- commands ---------------------------------------------------------------------
def cmd_recall(engine: Engine, args: argparse.Namespace) -> dict:
    if args.mode and args.mode not in MODES:
        raise CliError(f"mode must be one of {', '.join(MODES)}")
    return engine.recall(
        " ".join(args.query), datasets=[args.dataset] if args.dataset else None, mode=args.mode,
        limit=args.limit, include_superseded=args.superseded, hops=args.hops, include_user=not args.no_user,
    )


def cmd_remember(engine: Engine, args: argparse.Namespace) -> dict:
    ds = engine.dataset(args.dataset)
    if args.stdin:
        payload = _stdin_json()
        return ds.remember(
            [EntityIn(**e) for e in payload.get("entities", [])],
            [RelationIn(**r) for r in payload.get("relations", [])],
            summary=payload.get("summary"), source_text=payload.get("source_text"),
            source=payload.get("source"), session_id=payload.get("session_id"),
        )
    entities: dict[str, EntityIn] = {}
    relations: list[RelationIn] = []
    for text in args.fact:
        src_ent, name, tgt_ent, src, tgt = parse_fact(text)
        for e in (src_ent, tgt_ent):
            if e is not None:
                entities[e.name] = e
        relations.append(RelationIn(
            source=src, name=name, target=tgt, description=args.desc or "",
            evidence=args.evidence, valid_from=args.valid_from, valid_to=args.valid_to,
        ))
    return ds.remember(list(entities.values()), relations, summary=args.summary, source=args.source, session_id=args.session)


def cmd_forget(engine: Engine, args: argparse.Namespace) -> dict:
    if args.all:
        name = args.dataset or engine.default_dataset_name()
        return {"dataset": name, "deleted": engine.forget_dataset(name)}
    ds = engine.dataset(args.dataset)
    if args.entity:
        return {"dataset": ds.name, "entities_deleted": ds.forget_entity(args.entity)}
    if args.relation_id:
        return {"dataset": ds.name, "relations_deleted": ds.forget_relation(args.relation_id)}
    if args.session:
        return ds.session_forget(args.session)
    raise CliError("Pass --entity, --relation-id, --session, or --all.")


def cmd_session(engine: Engine, args: argparse.Namespace) -> tuple[str, dict]:
    ds = engine.dataset(args.dataset)
    if args.action == "start":
        return "session-start", ds.session_start(args.session_id)
    if not args.session_id:
        raise CliError(f"session {args.action} needs a session id.")
    if args.action == "turn":
        if not args.text:
            raise CliError("session turn needs --text.")
        return "session", ds.session_add_turn(args.session_id, args.role, args.text)
    if args.action == "context":
        if not (args.section and args.text):
            raise CliError(f"session context needs --section ({SECTIONS_HINT}) and --text.")
        return "session", ds.session_set_context(args.session_id, args.section, args.text, args.confidence, args.retire)
    if args.action == "get":
        return "session", ds.session_get(args.session_id, args.sections, not args.no_turns)
    if args.action == "timeline":
        return "session", ds.session_timeline(args.session_id)
    if args.action == "lessons":
        payload = _stdin_json()
        return "session", ds.publish_lessons(args.session_id, [LessonIn(**le) for le in payload.get("lessons", [])])
    return "session", ds.session_end(args.session_id)


def cmd_view(engine: Engine, args: argparse.Namespace) -> dict:
    from .graph_html import write_graph  # only this command pays for the template

    ds = engine.dataset(args.dataset)
    out = Path(args.out).expanduser() if args.out else data_dir() / "out" / f"view-{ds.name}.html"
    result = write_graph(ds.store, ds.name, out, include_superseded=args.superseded)
    if not args.no_open:
        import webbrowser

        result["opened"] = webbrowser.open(out.as_uri())
    return result


def cmd_tool(engine: Engine, args: argparse.Namespace) -> dict:
    """Escape hatch: reach any Dataset or Engine method the hot path does not wrap."""
    kwargs = _stdin_json() if args.stdin else {}
    dataset = kwargs.pop("dataset", args.dataset)
    target: Any = engine if args.name in ("recall", "list_datasets", "forget_dataset") else engine.dataset(dataset)
    fn = getattr(target, args.name, None)
    if fn is None or args.name.startswith("_") or not callable(fn):
        names = sorted(n for n in dir(engine.dataset(dataset)) if not n.startswith("_") and callable(getattr(engine.dataset(dataset), n)))
        raise CliError(f"No tool named {args.name!r}. Available: {', '.join(names)}")
    for key, model in (("entities", EntityIn), ("relations", RelationIn), ("lessons", LessonIn)):
        if key in kwargs and isinstance(kwargs[key], list):
            kwargs[key] = [model(**v) if isinstance(v, dict) else v for v in kwargs[key]]
    result = fn(**kwargs)
    return result if isinstance(result, dict) else {"result": result}


# ----- parser -----------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="memoose", description="Memory for coding agents. Facts in one local SQLite file.")
    p.add_argument("--json", action="store_true", help="Print the raw payload instead of compact text.")
    p.add_argument("--max-inline", type=int, default=2000, help="Spill text output longer than this to a file and print the path (0 disables; --json is never spilled).")
    p.add_argument("-d", "--dataset", default=None, help="Dataset to act on (default: this project).")
    sub = p.add_subparsers(dest="cmd")

    def command(name: str, **kw) -> argparse.ArgumentParser:
        """A subcommand that also takes --dataset after it.

        argparse only accepts a global flag before the subcommand, but `memoose remember "..."
        --dataset user` is the order anyone actually writes. Accept both, into a separate dest so
        the trailing one does not overwrite a leading one with None.
        """
        sp = sub.add_parser(name, **kw)
        sp.add_argument("-d", "--dataset", dest="dataset_after", default=None, help=argparse.SUPPRESS)
        return sp

    r = command("recall", help="Search memory: facts, entities, chunks.")
    r.add_argument("query", nargs="+")
    r.add_argument("-m", "--mode", default=None, help=f"One of: {', '.join(MODES)} (default: routed from the query).")
    r.add_argument("-n", "--limit", type=int, default=10)
    r.add_argument("--hops", type=int, default=1)
    r.add_argument("--superseded", action="store_true", help="Include facts a newer one replaced.")
    r.add_argument("--no-user", action="store_true", help="Project dataset only; skip user-global memory.")

    m = command("remember", help="Store facts: 'alice:Person --owns--> billing-service:System'.")
    m.add_argument("fact", nargs="*", help="source[:Type] --relation_name--> target[:Type]")
    m.add_argument("--desc", default=None, help="One-sentence description, applied to each fact given.")
    m.add_argument("-e", "--evidence", default=None, help="repo://path#L1-L2, a URL, an issue id, or 'user said <date>'.")
    m.add_argument("--valid-from", default=None, help="ISO date this became true.")
    m.add_argument("--valid-to", default=None)
    m.add_argument("--summary", default=None, help="Text stored alongside so recall can find this lexically.")
    m.add_argument("--source", default=None)
    m.add_argument("--session", default=None)
    m.add_argument("--stdin", action="store_true", help="Read the full remember payload as JSON on stdin instead.")

    h = command("history", help="Provenance: every change to an entity or a fact.")
    h.add_argument("entity", nargs="?", default=None)
    h.add_argument("--relation-id", default=None)
    h.add_argument("-n", "--limit", type=int, default=50)

    c = command("contradictions", help="Hotspots and open contradictions to judge.")
    c.add_argument("entity", nargs="*", help="Entity names to inspect (default: open contradictions only).")

    mt = command("maintain", help="The periodic pass: everything that needs judging, in one worklist.")
    mt.add_argument("-n", "--limit", type=int, default=10, help="Items per category.")

    command("ontology", help="Entity types, functional relations, store stats.")
    command("datasets", help="Memory scopes on this machine.")
    command("context", help="Global context: one bucket per entity type.")

    vw = command("view", help="Open the knowledge graph in your browser: one self-contained HTML file, nothing uploaded.")
    vw.add_argument("--out", default=None, help="Where to write the file (default: ~/.memoose/out/view-<dataset>.html).")
    vw.add_argument("--superseded", action="store_true", help="Include superseded facts, drawn dashed.")
    vw.add_argument("--no-open", action="store_true", help="Write the file without opening a browser.")

    dm = command("dismiss", help="Decline a maintain candidate by key, with the reason, so it is not proposed again.")
    dm.add_argument("key", help="A candidate key printed by maintain, e.g. consolidate:<id>:<id>")
    dm.add_argument("--reason", required=True, help="Why it was declined; shown next time so the judgment is not redone.")

    f = command("forget", help="Delete an entity, a fact, a session, or a whole dataset.")
    f.add_argument("--entity", default=None)
    f.add_argument("--relation-id", default=None)
    f.add_argument("--session", default=None)
    f.add_argument("--all", action="store_true", help="Delete the whole dataset.")

    s = command("session", help="Session lifecycle: start, turn, context, get, timeline, lessons, end.")
    s.add_argument("action", choices=["start", "turn", "context", "get", "timeline", "lessons", "end"])
    s.add_argument("session_id", nargs="?", default=None)
    s.add_argument("--role", default="user", choices=["user", "assistant", "tool", "system"])
    s.add_argument("--text", default=None)
    s.add_argument("--section", default=None, help=SECTIONS_HINT)
    s.add_argument("--confidence", type=float, default=1.0)
    s.add_argument("--retire", type=int, default=None, help="Context entry id this replaces.")
    s.add_argument("--sections", nargs="*", default=None)
    s.add_argument("--no-turns", action="store_true")

    t = command("tool", help="Call any engine method by name with JSON arguments on stdin.")
    t.add_argument("name")
    t.add_argument("--stdin", action="store_true", help="Read keyword arguments as a JSON object on stdin.")

    sub.add_parser("serve", help="Run the stdio MCP server (what a host launches).")
    pi = sub.add_parser("install", help="Wire the MCP server and skills into a host.")
    pi.add_argument("host", choices=HOSTS)
    pi.add_argument("--project", nargs="?", const=".", default=None)
    pi.add_argument("--command", default=None, help='Server command override, e.g. "uvx memoose serve".')
    pu = sub.add_parser("uninstall", help="Remove memoose from a host.")
    pu.add_argument("host", choices=HOSTS)
    pu.add_argument("--project", nargs="?", const=".", default=None)
    ps = sub.add_parser("status", help="Show what is installed where.")
    ps.add_argument("--project", nargs="?", const=".", default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "dataset_after", None):
        args.dataset = args.dataset_after

    if args.cmd in (None, "serve"):
        from .server import build_server  # imports the mcp package; keep it off every other path

        build_server().run("stdio")
        return 0

    if args.cmd in ("install", "uninstall", "status"):
        from . import integrations

        if args.cmd == "install":
            result = integrations.install(args.host, project=args.project, command=args.command.split() if args.command else None)
        elif args.cmd == "uninstall":
            result = integrations.uninstall(args.host, project=args.project)
        else:
            result = integrations.status(project=args.project)
        print(json.dumps(result, indent=2))
        return 0

    engine = Engine()
    name = args.cmd
    try:
        if args.cmd == "recall":
            payload = cmd_recall(engine, args)
        elif args.cmd == "remember":
            payload = cmd_remember(engine, args)
        elif args.cmd == "history":
            payload = engine.dataset(args.dataset).history(args.entity, args.relation_id, args.limit)
        elif args.cmd == "contradictions":
            payload = engine.dataset(args.dataset).contradiction_candidates(args.entity or None)
        elif args.cmd == "maintain":
            payload = engine.dataset(args.dataset).maintenance(args.limit)
        elif args.cmd == "ontology":
            payload = engine.dataset(args.dataset).describe_ontology()
        elif args.cmd == "datasets":
            payload = {"default": engine.default_dataset_name(), "user": "user", "datasets": engine.list_datasets(), "embedder": engine.embedder.name}
        elif args.cmd == "context":
            payload = engine.dataset(args.dataset).global_context()
        elif args.cmd == "view":
            payload = cmd_view(engine, args)
        elif args.cmd == "dismiss":
            payload = engine.dataset(args.dataset).dismiss(args.key, args.reason)
        elif args.cmd == "forget":
            payload = cmd_forget(engine, args)
        elif args.cmd == "session":
            name, payload = cmd_session(engine, args)
        else:
            payload = cmd_tool(engine, args)
    except (CliError, OntologyError, ValueError) as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        engine.close()
    return emit(name, payload, args)


if __name__ == "__main__":
    sys.exit(main())
