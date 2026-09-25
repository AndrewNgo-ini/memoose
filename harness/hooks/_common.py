"""Shared helpers for memoose's hooks.

Hooks run on the host's plain `python3` with no dependencies, so this module is stdlib only
and never imports memoose. `dataset_name` mirrors `memoose.store.datasets.project_dataset_name`
exactly; `tests/test_hooks.py` asserts the two stay in agreement.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

_SAFE = re.compile(r"[^a-z0-9._-]+")


def read_event() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        return {}


def env(name: str) -> str | None:
    return os.environ.get(f"MEMOOSE_{name}")


def data_dir() -> Path:
    """Mirrors `memoose.store.datasets.data_dir`."""
    override = env("DATA_DIR")
    return Path(override).expanduser() if override else Path.home() / ".memoose"


def dataset_name(cwd: str | os.PathLike | None) -> str:
    path = Path(cwd or env("PROJECT_DIR") or os.getcwd()).resolve()
    digest = hashlib.sha1(str(path).encode()).hexdigest()[:8]
    base = _SAFE.sub("-", path.name.casefold()).strip("-") or "project"
    return f"{base}-{digest}"


def dataset_path(cwd: str | os.PathLike | None) -> Path:
    return data_dir() / f"{dataset_name(cwd)}.sqlite"


USER_DATASET = "user"


def user_dataset_path() -> Path:
    """The user-global Dataset, which holds standing rules and preferences about the person."""
    return data_dir() / f"{USER_DATASET}.sqlite"


def connect(path: Path) -> sqlite3.Connection | None:
    """Read-only connection, or None when there is no memory yet."""
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error:
        return None


def state_dir() -> Path:
    d = data_dir() / "hook-state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def enabled(var: str = "AUTO_CAPTURE") -> bool:
    """`var` is the suffix of MEMOOSE_<var>. On unless explicitly off."""
    return (env(var) or "1").strip().lower() not in ("0", "false", "off", "no")


# ----- transcript ---------------------------------------------------------------------
_SKIP_PREFIXES = ("<system-reminder", "<local-command", "<command-name", "Caveat:")


def _blocks_text(content) -> tuple[str, bool]:
    """Return (visible text, had_tool_activity) for one message's content."""
    if isinstance(content, str):
        return content, False
    if not isinstance(content, list):
        return "", False
    parts, tools = [], False
    for b in content:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text" and isinstance(b.get("text"), str):
            parts.append(b["text"])
        elif t in ("tool_use", "tool_result"):
            tools = True
    return "\n".join(parts), tools


def complete_lines(path: Path) -> list[str]:
    """The transcript's lines, minus a last line the host is still writing.

    A line without its newline is complete only if it parses; otherwise a reader that advanced
    its cursor past it would never see that message.
    """
    raw = path.read_text(errors="replace")
    lines = raw.split("\n")
    tail = lines.pop()
    if tail.strip():
        try:
            json.loads(tail)
            lines.append(tail)
        except json.JSONDecodeError:
            pass
    return lines


def read_exchange(transcript_path: str | None, start_line: int = 0, max_chars: int = 24000) -> tuple[str, int, bool]:
    """Plain-text transcript slice from `start_line`, the line to resume from, and whether tools ran.

    Thinking blocks, tool calls, tool results and injected system text are dropped: what is
    worth remembering is what the user and the assistant actually said. A slice is at most
    `max_chars`: it stops before the message that would overflow and returns that line as the
    resume point, so a long turn is read in pieces rather than cut. A single message longer than
    the budget is clipped.
    """
    if not transcript_path:
        return "", start_line, False
    p = Path(transcript_path)
    if not p.exists():
        return "", start_line, False
    lines = complete_lines(p)
    out, tools, size = [], False, 0
    for i in range(start_line, len(lines)):
        raw = lines[i]
        if not raw.strip():
            continue
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if d.get("type") not in ("user", "assistant"):
            continue
        msg = d.get("message") or {}
        text, had_tools = _blocks_text(msg.get("content"))
        text = text.strip()
        if not text or text.startswith(_SKIP_PREFIXES):
            tools = tools or had_tools
            continue
        role = "User" if d["type"] == "user" else "Assistant"
        entry = f"{role}: {text}"[:max_chars]
        if out and size + len(entry) + 2 > max_chars:
            return "\n\n".join(out), i, tools
        tools = tools or had_tools
        out.append(entry)
        size += len(entry) + 2
    return "\n\n".join(out), len(lines), tools


def offset_file(session_id: str) -> Path:
    safe = _SAFE.sub("-", (session_id or "unknown").casefold())
    return state_dir() / f"{safe}.offset"


def read_offset(session_id: str) -> int:
    try:
        return int(offset_file(session_id).read_text().strip())
    except (OSError, ValueError):
        return 0


def write_offset(session_id: str, value: int) -> None:
    try:
        offset_file(session_id).write_text(str(value))
    except OSError:
        pass


# ----- lightweight local search (no model, no MCP) -------------------------------------
_STOP = frozenset("""a an the and or but if then else of to in on at by for from with without about as into
like through after before over under again further is are was were be been being am do does did doing have
has had having will would shall should can could may might must i me my we us our you your he him his she
her it its they them their what which who whom this that these those there here where when why how all any
both each few more most other some such no nor not only own same so than too very just now up down out off
once during please need want make made get got let use using
""".split())
_WORD = re.compile(r"[A-Za-z0-9_]+")


def search_memory(conn: sqlite3.Connection, query: str, limit: int = 5) -> list[dict]:
    """Top *current* memory rows matching `query`, ranked by bm25. Milliseconds, no model.

    Superseded relations are excluded, because `supersede` only flips a column and leaves the
    fts row in place: without this filter a replaced fact still matches, often above the fact
    that replaced it, and gets pushed at the agent as current before it has thought about
    anything. `recall` drops them by default (`retrieval.py`) and so must every hook.

    The exclusion is applied in Python rather than in the SQL, because hooks open the store
    read-only and therefore never migrate it: on a store written before the `superseded`
    column existed, a WHERE clause naming it would throw and silence memory completely.
    `superseded_ids` already degrades to an empty set there.
    """
    toks = [t for t in _WORD.findall(query) if len(t) > 2 and t.casefold() not in _STOP]
    if not toks:
        return []
    match = " OR ".join(f'"{t}"' for t in list(dict.fromkeys(toks))[:24])
    try:
        rows = conn.execute(
            "SELECT kind, ref_id, text, bm25(fts) AS rank FROM fts WHERE fts MATCH ?"
            " AND kind IN ('entity','relation') ORDER BY rank LIMIT ?",
            (match, limit * 3),
        ).fetchall()
    except sqlite3.Error:
        return []
    stale = superseded_ids(conn)
    out, seen = [], set()
    for r in rows:
        text = " ".join((r["text"] or "").split())
        if not text or text in seen or r["ref_id"] in stale:
            continue
        seen.add(text)
        out.append({"kind": r["kind"], "text": text, "score": -float(r["rank"])})
        if len(out) >= limit:
            break
    return out


def indexed_rows(conn: sqlite3.Connection) -> int:
    try:
        return int(conn.execute("SELECT count(*) FROM fts").fetchone()[0])
    except sqlite3.Error:
        return 0


def superseded_ids(conn: sqlite3.Connection) -> set[str]:
    try:
        return {r[0] for r in conn.execute("SELECT id FROM relations WHERE superseded=1")}
    except sqlite3.Error:
        return set()


# ----- procedural guidance (after Procedural Graphs, Lu et al. 2026; ADR 0005) ---------------------
def current_position(conn: sqlite3.Connection) -> dict | None:
    """The Procedure the agent last declared it was at, on a Session that has not ended, or None.

    ADR 0004 guessed the position by matching the last shell command lexically against Procedure
    names; the guess fired on token overlap and steered the agent toward an unrelated procedure.
    ADR 0005 keys guidance on the Position the agent declares (`session turn --at`) and on nothing
    else: silence is preferred to a wrong steer. A store older than the column yields None.
    """
    try:
        r = conn.execute(
            "SELECT e.id, e.name, e.description FROM session_turns t JOIN sessions s ON s.id=t.session_id"
            " JOIN entities e ON e.id=t.position WHERE s.ended_at IS NULL AND t.position IS NOT NULL ORDER BY t.id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return None
    return {"id": r["id"], "name": r["name"], "description": r["description"] or ""} if r else None


def procedure_subgraph(conn: sqlite3.Connection, entity_id: str, hops: int = 2, per_hop: int = 6) -> list[dict]:
    """Outgoing Transitions from a Procedure, grouped by hop: what comes next, then what comes after.

    Directed and outgoing only. A procedure's *predecessors* are what the agent has already done;
    its successors are the guidance. Superseded transitions are history, not advice, and stay out.
    Hooks cannot import memoose, so this mirrors `Procedures.guidance`; `tests/test_procedures.py`
    asserts the two agree.
    """
    frontier, seen, out = [entity_id], {entity_id}, []
    for hop in range(1, hops + 1):
        nxt: list[str] = []
        for eid in frontier:
            try:
                rows = conn.execute(
                    "SELECT r.id, r.name, r.description, r.condition, r.advice, r.pitfall, r.succeeded, r.failed, r.abandoned,"
                    " r.target_id, s.name AS src, t.name AS dst"
                    " FROM relations r JOIN entities s ON s.id=r.source_id JOIN entities t ON t.id=r.target_id"
                    " WHERE r.source_id=? AND r.superseded=0 AND r.name<>'contradicts' AND t.type='Procedure'"
                    " ORDER BY r.updated_at DESC LIMIT ?",
                    (eid, per_hop),
                ).fetchall()
            except sqlite3.Error:
                return out
            for r in rows:
                attrs = "; ".join(p for p in (
                    f"when {r['condition']}" if r["condition"] else "", f"do {r['advice']}" if r["advice"] else "",
                    f"avoid {r['pitfall']}" if r["pitfall"] else "") if p)
                runs = f" [{r['succeeded']} ok / {r['failed']} failed / {r['abandoned']} abandoned]" if (r["succeeded"] or r["failed"] or r["abandoned"]) else ""
                out.append({"hop": hop, "source": r["src"], "relation": r["name"], "target": r["dst"],
                            "description": (attrs or r["description"] or "") + runs})
                if r["target_id"] not in seen:
                    seen.add(r["target_id"])
                    nxt.append(r["target_id"])
        frontier = nxt
        if not frontier:
            break
    return out
