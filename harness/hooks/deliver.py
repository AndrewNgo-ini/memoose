#!/usr/bin/env python3
"""Deliver the advisor's Advisories into the primary, each severity at its own safe point.

A sync hook on PostToolUse, UserPromptSubmit and Stop. It only reads the mailbox advise.py
fills, so it costs milliseconds. The routing follows Oh My Pi's `resolveAdvisorDeliveryChannel`:

| severity | primary mid-turn (PostToolUse)   | primary between turns                        |
|----------|----------------------------------|----------------------------------------------|
| nit      | held                             | aside at the next prompt                     |
| concern  | steer, unless in the immune window | aside at the next prompt                   |
| blocker  | steer                            | Stop `decision: block`; idle wake in advisor.py |

A steer opens an immune window of `MEMOOSE_ADVISOR_IMMUNE_TURNS` tool steps (default 3, as in
OMP) in which concerns wait for the next prompt instead of interrupting again. Blockers are exempt.
Unlike OMP, a concern steers mid-turn rather than waiting for the prompt to end (oh-my-pi#10600).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import env, read_event  # noqa: E402
from advise import advisor_on, mark_delivered, pending, render, session_state  # noqa: E402

IMMUNE_TURNS = int(env("ADVISOR_IMMUNE_TURNS") or "3")


def route(event: dict) -> dict | None:
    """The hook output for this event, or None. Updates delivery state as a side effect."""
    name = event.get("hook_event_name")
    with session_state(str(event.get("session_id") or "unknown")) as st:
        waiting = pending(st)
        if name == "UserPromptSubmit":
            st["prompt_id"] = event.get("prompt_id") or st.get("prompt_id")
            out = waiting
        elif name == "PostToolUse":
            st["step"] = st.get("step", 0) + 1
            immune = st["step"] <= st.get("immune_until", 0)
            out = [a for a in waiting if a["severity"] == "blocker" or (a["severity"] == "concern" and not immune)]
            if out:
                st["immune_until"] = st["step"] + IMMUNE_TURNS
        elif name == "Stop" and not event.get("stop_hook_active"):
            out = [a for a in waiting if a["severity"] == "blocker"]
        else:
            out = []
        mark_delivered(st, out)
    if not out:
        return None
    text = render(out)
    if name == "Stop":
        return {"decision": "block", "reason": text}
    return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": text}}


def main() -> int:
    if not advisor_on():
        return 0
    out = route(read_event())
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - a hook must never break the session
        sys.exit(0)
