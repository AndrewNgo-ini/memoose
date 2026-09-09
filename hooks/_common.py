"""Shared helpers for memoose's hooks.

Hooks run on the host's plain `python3` with no dependencies, so this module is stdlib only
and never imports memoose. `dataset_name` mirrors `memoose.datasets.project_dataset_name`
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
    """MEMOOSE_* is canonical; the MNEMOTH_* name is still read for setups made before the rename."""
    return os.environ.get(f"MEMOOSE_{name}") or os.environ.get(f"MNEMOTH_{name}")


def data_dir() -> Path:
    """Mirrors `memoose.datasets.data_dir`, including the pre-rename `~/.mnemoth` fallback."""
    override = env("DATA_DIR")
    if override:
        return Path(override).expanduser()
    new, old = Path.home() / ".memoose", Path.home() / ".mnemoth"
    return old if old.exists() and not new.exists() else new


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
    """`var` is the suffix: MEMOOSE_<var>, or the legacy MNEMOTH_<var>. On unless explicitly off."""
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


def read_exchange(transcript_path: str | None, start_line: int = 0, max_chars: int = 24000) -> tuple[str, int, bool]:
    """Plain-text transcript slice from `start_line`, the new line count, and whether tools ran.

    Thinking blocks, tool calls, tool results and injected system text are dropped: what is
    worth remembering is what the user and the assistant actually said.
    """
    if not transcript_path:
        return "", start_line, False
    p = Path(transcript_path)
    if not p.exists():
        return "", start_line, False
    lines = p.read_text(errors="replace").splitlines()
    out, tools = [], False
    for raw in lines[start_line:]:
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
        tools = tools or had_tools
        text = text.strip()
        if not text or text.startswith(_SKIP_PREFIXES):
            continue
        role = "User" if d["type"] == "user" else "Assistant"
        out.append(f"{role}: {text}")
    joined = "\n\n".join(out)
    if len(joined) > max_chars:  # keep the most recent, that is where new facts are
        joined = joined[-max_chars:]
    return joined, len(lines), tools


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
