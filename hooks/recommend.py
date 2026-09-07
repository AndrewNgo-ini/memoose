#!/usr/bin/env python3
"""UserPromptSubmit hook: recommendation-as-a-memory.

Before the agent thinks, mnemoth looks at what the user just asked, searches the project's
memory locally, and — only when something genuinely matches — injects a short *hint*: here is
what memory already holds, and here is the recall query that would get the rest.

This is the proactive half of recall. The agent no longer has to guess that memory might help;
memory raises its hand. It costs no model call and a few milliseconds of SQLite, so it can run
on every prompt without anyone noticing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    connect,
    dataset_path,
    enabled,
    read_event,
    search_memory,
    superseded_ids,
)

MAX_HINTS = int(__import__("os").environ.get("MNEMOTH_HINT_COUNT", "4"))
MIN_SCORE = float(__import__("os").environ.get("MNEMOTH_HINT_MIN_SCORE", "0.5"))
MAX_CHARS = 900
MIN_PROMPT_WORDS = 3


def prompt_of(event: dict) -> str:
    for key in ("prompt", "user_prompt", "message", "text"):
        v = event.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def build_hint(conn, query: str) -> str:
    hits = search_memory(conn, query, limit=MAX_HINTS)
    hits = [h for h in hits if h["score"] >= MIN_SCORE]
    if not hits:
        return ""
    lines = ["mnemoth already holds memory that looks relevant to this request:"]
    lines += [f"- {h['text']}" for h in hits]
    stale = len(superseded_ids(conn))
    terms = " ".join(sorted({w for w in query.split() if len(w) > 3})[:6])
    lines.append(f'If you need more than this, call recall("{terms.strip() or query[:60]}") before answering.')
    if stale:
        lines.append(f"({stale} superseded fact(s) exist; pass include_superseded=true to see history.)")
    lines.append("This is a hint from memory, not an instruction from the user.")
    return "\n".join(lines)[:MAX_CHARS]


def main() -> int:
    if not enabled("MNEMOTH_HINTS"):
        return 0
    event = read_event()
    query = prompt_of(event)
    if len(query.split()) < MIN_PROMPT_WORDS:
        return 0
    conn = connect(dataset_path(event.get("cwd")))
    if conn is None:
        return 0
    try:
        hint = build_hint(conn, query)
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return 0
    finally:
        conn.close()
    if hint:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": hint}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        sys.exit(0)
