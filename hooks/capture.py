#!/usr/bin/env python3
"""Background capture: store what this turn taught, without anyone asking.

Runs from the Stop and PreCompact hooks with `async: true`, so it never blocks the
conversation. It reads only the transcript slice it has not seen yet, applies a cheap
relevance gate before spending anything, and then hands the extraction to a **small model**
through the host's own CLI — the host's auth, the host's subscription, no API key.

The expensive model driving the conversation is never used for bookkeeping.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    dataset_name,
    dataset_path,
    enabled,
    read_event,
    read_exchange,
    read_offset,
    state_dir,
    write_offset,
)

MODEL = os.environ.get("MNEMOTH_CAPTURE_MODEL", "haiku")
MIN_CHARS = int(os.environ.get("MNEMOTH_CAPTURE_MIN_CHARS", "400"))
TIMEOUT_S = int(os.environ.get("MNEMOTH_CAPTURE_TIMEOUT", "300"))
LOCK_STALE_S = 900

PROMPT = """You are mnemoth's memory keeper. Read the exchange below and store only what is worth
remembering weeks from now, using the mnemoth tools. Load the `mnemoth` skill's rules if available.

Store: decisions and their reasons, who or what owns which part, how systems relate, conventions and
constraints the user states, preferences the user expresses, dates things happened, problems found and
how they were solved, and durable facts about this project or environment.

Do NOT store: transient task state, what a file currently contains (that is in the code), the fact that
you ran a command, restatements of the user's request, or anything you are unsure of.

Rules:
- Call `describe_ontology` once, then `remember` with entities (name, type, description) and relations
  (source --snake_case_name--> target) with a one-sentence description using the endpoint names.
- Put where each fact came from in `evidence`, e.g. "user said {today}" or a file path.
- Reuse existing names: call `recall` first when a name may already be known.
- Set `valid_from` (YYYY-MM-DD) whenever the exchange says when a fact became true.
- When a fact CHANGED (a new owner, a new version, a new region, a new gateway): call
  `declare_functional_relations` for that relation name, then store BOTH values with the SAME
  relation name, oldest `valid_from` first, and never invent a name for the old value such as
  `previously_owned_by` or `former_owner`. The store then marks the old value superseded and keeps
  it queryable as history, so "who owns it now" and "who owned it before" both have answers.
  Dropping the old value loses the history; renaming the relation hides the change.
- Pass dataset: "{dataset}" on every call except facts about the user themselves, which go to dataset "user".
- If nothing here is worth remembering, store nothing and reply exactly: NOTHING.

Reply with one short line naming what you stored, or NOTHING.

--- exchange ---
{exchange}
"""


def _lock(session_id: str) -> Path | None:
    """One capture per session at a time; a crashed run's lock goes stale rather than jamming."""
    lock = state_dir() / f"{session_id or 'unknown'}.lock"
    try:
        if lock.exists() and time.time() - lock.stat().st_mtime > LOCK_STALE_S:
            lock.unlink(missing_ok=True)
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return lock
    except FileExistsError:
        return None
    except OSError:
        return None


def _mcp_config(tmp: Path, cwd: str) -> Path:
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parents[1])
    env = {"MNEMOTH_PROJECT_DIR": cwd}
    for var in ("MNEMOTH_DATA_DIR", "MNEMOTH_EMBEDDER"):
        if os.environ.get(var):
            env[var] = os.environ[var]
    cfg = tmp / "mcp.json"
    cfg.write_text(
        '{"mcpServers":{"mnemoth":{"command":"uvx","args":["--from",%s,"mnemoth","serve"],"env":%s}}}'
        % (_json(plugin_root), _json(env))
    )
    return cfg


def _json(v) -> str:
    import json

    return json.dumps(v)


def main() -> int:
    if not enabled():
        return 0
    event = read_event()
    session_id = str(event.get("session_id") or "unknown")
    cwd = event.get("cwd") or os.getcwd()

    start = read_offset(session_id)
    exchange, new_offset, _ = read_exchange(event.get("transcript_path"), start)

    # Relevance gate: never spend a model call on a turn with nothing durable in it.
    if len(exchange) < MIN_CHARS:
        write_offset(session_id, new_offset)
        return 0

    lock = _lock(session_id)
    if lock is None:
        return 0  # a capture is already running; its offset will cover this turn too
    try:
        with tempfile.TemporaryDirectory(prefix="mnemoth-capture-") as td:
            tmp = Path(td)
            cfg = _mcp_config(tmp, cwd)
            prompt = PROMPT.format(exchange=exchange, today=time.strftime("%Y-%m-%d"), dataset=dataset_name(cwd))
            cmd = [
                "claude", "-p", "--model", MODEL, "--max-turns", "24",
                "--mcp-config", str(cfg), "--strict-mcp-config",
                "--dangerously-skip-permissions",
            ]
            plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
            if plugin_root:
                cmd += ["--plugin-dir", plugin_root]
            try:
                subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=td, timeout=TIMEOUT_S)
            except (OSError, subprocess.SubprocessError):
                return 0  # claude missing or failed: silent, memory is best-effort
        write_offset(session_id, new_offset)
    finally:
        lock.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - a hook must never break the session
        sys.exit(0)
