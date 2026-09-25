#!/usr/bin/env python3
"""The advisor's one output: `advise.py <nit|concern|blocker> "<note>"`.

The advisor (advisor.py) runs as a separate small-model session beside the primary. It never
talks into the conversation; it calls this script, which runs the emission guard and appends the
accepted Advisory to the session's mailbox. deliver.py drains the mailbox into the primary at the
next safe point for its severity.

The guard is a port of Oh My Pi's `advisor/emission-guard.ts` (MIT): notes are normalised
(case, NFKC, punctuation folded), content-free filler is dropped, a note repeats only at a
higher severity, and each update gets a budget of non-blockers. OMP leaves blockers unbounded
(oh-my-pi#11888, a runaway advisor); here a blocker past the per-prompt cap becomes a concern.

The mailbox, the guard's memory, and the primary's delivery state live in `hook-state/`, all
behind one flock so the advisor and the primary's hooks can write concurrently.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import time
import unicodedata
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import _SAFE, enabled, env, state_dir  # noqa: E402

try:
    import fcntl
except ImportError:  # ponytail: no flock on Windows, so concurrent writers may race there
    fcntl = None

RANK = {"nit": 1, "concern": 2, "blocker": 3}
MAX_NOTES = max(1, min(32, int(env("ADVISOR_MAX_NOTES") or "4")))
MAX_BLOCKERS = int(env("ADVISOR_MAX_BLOCKERS") or "2")
HISTORY = 4096

NOISE = frozenset("""stop|stop here|stop now|halt|abort|done|task done|task complete|complete|finished|ok|
okay|ok done|no issue|no issues|no issue continue|no concerns|no concern|nothing to add|nothing to flag|
nothing to report|no notes|no further input|no further input needed|no further input required|
no further watcher input|no further watcher input needed|no further advice|no further advice needed|
lgtm|looks good|all good|agent is on track|agent on track|on track|continue|carry on""".replace("\n", "").split("|"))


def advisor_on() -> bool:
    """On unless MEMOOSE_ADVISOR=0, like every other memoose switch."""
    return enabled("ADVISOR")


def normalize(note: str) -> str:
    return re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", note.lower())).strip()


def _path(session_id: str, kind: str) -> Path:
    return state_dir() / f"advisor-{_SAFE.sub('-', (session_id or 'unknown').casefold())}.{kind}"


@contextlib.contextmanager
def session_state(session_id: str):
    """The session's advisor state as a dict, read and written back under an exclusive lock."""
    path = _path(session_id, "json")
    with open(_path(session_id, "flock"), "a") as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            state = {}
        yield state
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        tmp.replace(path)


def pending(state: dict) -> list[dict]:
    delivered = set(state.get("delivered", []))
    return [a for a in state.get("mail", []) if a["id"] not in delivered]


def mark_delivered(state: dict, advisories: list[dict]) -> None:
    state["delivered"] = state.get("delivered", []) + [a["id"] for a in advisories]


def render(advisories: list[dict]) -> str:
    return "\n".join(
        f'<advisory severity="{a["severity"]}" guidance="weigh, don\'t blindly obey">\n{a["note"]}\n</advisory>'
        for a in advisories
    )


def emit(session_id: str, update: str, severity: str, note: str) -> str:
    """Run the guard and append the Advisory if it passes. Returns the acknowledgement."""
    if severity not in RANK:
        return f"Rejected: severity must be one of {', '.join(RANK)}."
    key = normalize(note)
    if not key or key in NOISE:
        return "Suppressed: no concrete content. Stay silent when there is nothing to flag."
    with session_state(session_id) as st:
        if severity == "blocker":
            blockers = st.setdefault("blockers", {})
            prompt = st.get("prompt_id") or "-"
            if blockers.get(prompt, 0) >= MAX_BLOCKERS:
                severity = "concern"
            else:
                blockers[prompt] = blockers.get(prompt, 0) + 1
        seen = st.setdefault("seen", {})
        if seen.get(key, 0) >= RANK[severity]:
            return "Suppressed: already sent. Do not repeat advice."
        if severity != "blocker":
            budget = st.setdefault("budget", {})
            if budget.get(update, 0) >= MAX_NOTES:
                return f"Suppressed: {MAX_NOTES} non-blocker notes already sent this update."
            budget[update] = budget.get(update, 0) + 1
        seen[key] = RANK[severity]
        if len(seen) > HISTORY:
            del seen[next(iter(seen))]
        st.setdefault("mail", []).append(
            {"id": uuid.uuid4().hex[:12], "severity": severity, "note": note.strip(), "update": update,
             "at": int(time.time())})
    return f"Accepted as {severity}."


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: advise.py <nit|concern|blocker> <note>", file=sys.stderr)
        return 1
    session_id = os.environ.get("MEMOOSE_ADVISOR_SESSION") or "unknown"
    update = os.environ.get("MEMOOSE_ADVISOR_UPDATE") or "0"
    print(emit(session_id, update, argv[0].strip().lower(), " ".join(argv[1:])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
