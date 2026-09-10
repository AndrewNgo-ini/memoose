#!/usr/bin/env python3
"""UserPromptSubmit hook: recommendation-as-a-memory.

Before the agent thinks, memoose looks at what the user just asked, searches the project's
memory and the user's own memory locally, and — only when something genuinely matches —
injects a short *hint*: here is what memory already holds, and here is the recall query that
would get the rest.

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
    env,
    indexed_rows,
    last_tool_uses,
    locate_procedure,
    procedure_subgraph,
    read_event,
    search_memory,
    superseded_ids,
    user_dataset_path,
)

MAX_HINTS = int(env("HINT_COUNT") or "4")
MIN_SCORE = float(env("HINT_MIN_SCORE") or "0.5")
MAX_CHARS = 900
GUIDANCE_CHARS = 900  # the procedural block has its own budget; it is the more specific of the two
MIN_PROMPT_WORDS = 3
RECENT_ACTIONS = 3  # how far back to look for a step memory knows; the paper's trajectory window
USER_RESERVE = 1  # the user's standing rules must not be crowded out by project facts
MIN_DISCRIMINATING_ROWS = 8  # a round number with margin: bm25 starts discriminating around 5 rows


def score_floor(conn, configured: float = MIN_SCORE) -> float:
    """The relevance floor, which has to know how big the corpus is.

    bm25 is corpus-relative: its IDF term is zero for a token that appears in every indexed
    row, which is what happens in a small store, so a *perfect* keyword match there scores
    ~0.0 and a fixed floor rejects it. A fixed floor therefore silences memory exactly when
    it is new — the first sessions on a project, and permanently for the user Dataset, which
    by design holds only a handful of standing rules. Below `MIN_DISCRIMINATING_ROWS` the
    floor is dropped and the FTS match itself is the gate; it is already a real one, since
    `search_memory` matches only non-stopword tokens longer than two characters.
    """
    return configured if indexed_rows(conn) >= MIN_DISCRIMINATING_ROWS else 0.0


def prompt_of(event: dict) -> str:
    for key in ("prompt", "user_prompt", "message", "text"):
        v = event.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def build_hint(project, user, query: str) -> str:
    """Project memory first, then the user's own, keeping `USER_RESERVE` slots for the latter.

    `recall` searches the project Dataset and then the user Dataset with a reserve, and the
    hint has to do the same or it silently drops the standing rules and preferences that the
    capture hook deliberately files under the user Dataset — the memory most likely to apply
    to *any* prompt.
    """
    def relevant(conn) -> list[dict]:
        if conn is None:
            return []
        floor = score_floor(conn)
        return [h for h in search_memory(conn, query, limit=MAX_HINTS) if h["score"] >= floor]

    project_hits, user_hits = relevant(project), relevant(user)
    keep_user = user_hits[:USER_RESERVE] if user_hits else []
    hits, seen = [], set()
    for h in project_hits[: max(0, MAX_HINTS - len(keep_user))] + keep_user + project_hits[max(0, MAX_HINTS - len(keep_user)):] + user_hits[USER_RESERVE:]:
        if h["text"] in seen:
            continue
        seen.add(h["text"])
        hits.append(h)
        if len(hits) >= MAX_HINTS:
            break
    if not hits:
        return ""
    lines = ["memoose already holds memory that looks relevant to this request:"]
    lines += [f"- {h['text']}" for h in hits]
    stale = len(superseded_ids(project)) if project is not None else 0
    terms = " ".join(sorted({w for w in query.split() if len(w) > 3})[:6])
    lines.append(f'If you need more than this, call recall("{terms.strip() or query[:60]}") before answering.')
    if stale:
        lines.append(f"({stale} superseded fact(s) exist; pass include_superseded=true to see history.)")
    lines.append("This is a hint from memory, not an instruction from the user.")
    return "\n".join(lines)[:MAX_CHARS]


def build_guidance(project, user, transcript_path: str | None) -> str:
    """What memory says comes next, keyed on what the agent just did rather than on the prompt.

    A recall keyed on the user's words finds facts *about* things. A step the agent is in the
    middle of is a different question: given what it just ran, what does memory say to do next,
    under which condition, and what went wrong here before? That is answered by localising the
    most recent action on a Procedure entity and reading its outgoing transitions two hops out,
    grouped by hop, the way Procedural Graphs (Lu et al. 2026) serialise a local subgraph. Their
    ablation is why this is a *local* subgraph and not the whole store: injecting everything
    lowered task success on the embodied benchmark; the two-hop neighbourhood raised it.
    """
    actions = last_tool_uses(transcript_path, RECENT_ACTIONS)
    if not actions:
        return ""
    for conn in (project, user):
        if conn is None:
            continue
        for action in actions:
            node = locate_procedure(conn, action)
            if node is None:
                continue
            edges = procedure_subgraph(conn, node["id"])
            if not edges:
                continue
            lines = [f"You just ran `{action[:80]}`. Memory holds a procedure from here ({node['name']}):"]
            for hop, label in ((1, "Next"), (2, "Then")):
                rows = [e for e in edges if e["hop"] == hop]
                if rows:
                    lines.append(f"{label}:")
                    lines += [f"- {e['source']} --{e['relation']}--> {e['target']}" + (f": {e['description']}" if e["description"] else "") for e in rows]
            lines.append("Guidance from memory, not an instruction; deviate when the situation calls for it.")
            return "\n".join(lines)[:GUIDANCE_CHARS]
    return ""


def main() -> int:
    if not enabled("HINTS"):
        return 0
    event = read_event()
    query = prompt_of(event)
    if len(query.split()) < MIN_PROMPT_WORDS:
        return 0
    project = connect(dataset_path(event.get("cwd")))
    user = connect(user_dataset_path())
    if project is None and user is None:
        return 0
    try:
        guidance = build_guidance(project, user, event.get("transcript_path"))
        hint = build_hint(project, user, query)
        hint = "\n\n".join(part for part in (guidance, hint) if part)
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return 0
    finally:
        for conn in (project, user):
            if conn is not None:
                conn.close()
    if hint:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": hint}}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        sys.exit(0)
