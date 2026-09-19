#!/usr/bin/env python3
"""Background capture: store what this turn taught, without anyone asking.

Runs from the Stop and PreCompact hooks with `async: true`, so it never blocks the
conversation. It reads only the transcript slice it has not seen yet, applies a cheap
relevance gate before spending anything, and then hands the extraction to a **small model**
through the host's own CLI — the host's auth, the host's subscription, no API key.

The expensive model driving the conversation is never used for bookkeeping. The keeper writes
through the `memoose` command line rather than the MCP server: no server handshake per capture,
and no tool schemas in the keeper's context, which is most of what a capture prompt costs.
"""

from __future__ import annotations

import os
import shutil
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
    env,
    read_event,
    read_exchange,
    read_offset,
    state_dir,
    write_offset,
)

MODEL = env("CAPTURE_MODEL") or "haiku"
MIN_CHARS = int(env("CAPTURE_MIN_CHARS") or "400")
TIMEOUT_S = int(env("CAPTURE_TIMEOUT") or "300")
LOCK_STALE_S = 900

PROMPT = """You are memoose's memory keeper. Read the exchange below and store only what is worth
remembering weeks from now, using the `memoose` command line. Load the `memoose` skill's rules if
available. Run every command with Bash; there are no MCP tools in this session.

Store: decisions and their reasons, who or what owns which part, how systems relate, conventions and
constraints the user states, preferences the user expresses, dates things happened, problems found and
how they were solved, and durable facts about this project or environment.

Do NOT store: transient task state, what a file currently contains (that is in the code), the fact that
you ran a command, restatements of the user's request, or anything you are unsure of.

The command is `{memoose}`. Use it like this:

  {memoose} ontology                                    # entity types to use — run this once, first
  {memoose} recall "<names you are about to write>"     # reuse existing names; run before storing
  {memoose} remember "alice:Person --owns--> billing:System" \\
      --desc "One dry sentence using both names." -e "user said {today}" --valid-from 2026-01-31

Rules:
- A fact is `source[:Type] --snake_case_name--> target[:Type]`. The `:Type` declares an entity that
  is new; leave it off for a name that already exists. Every fact needs `--desc`, one self-contained
  sentence using the endpoint names.
- Put where each fact came from in `-e/--evidence`, e.g. "user said {today}" or a file path.
- Set `--valid-from` (YYYY-MM-DD) whenever the exchange says when a fact became true.
- When a fact CHANGED (a new owner, a new version, a new region, a new gateway), first run
  `echo '{{"names":["<relation>"]}}' | {memoose} tool declare_functional_relations --stdin`, then
  store BOTH values with the SAME relation name, oldest `--valid-from` first. Never invent a name for
  the old value such as `previously_owned_by` or `former_owner`. The store then marks the old value
  superseded and keeps it queryable as history, so "who owns it now" and "who owned it before" both
  have answers. Dropping the old value loses the history; renaming the relation hides the change.
- Add `--dataset {dataset}` on every command except facts about the user themselves, which take
  `--dataset user`.
- A command that fails prints what to fix on stderr — read it and correct the command rather than
  trying a different syntax.
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


def _plugin_root() -> str:
    """The plugin (or checkout) root: two levels above harness/hooks/."""
    return os.environ.get("CLAUDE_PLUGIN_ROOT") or str(Path(__file__).resolve().parents[2])


def _memoose_cmd() -> str:
    """How the keeper invokes the CLI: the installed binary if there is one, else uvx."""
    return shutil.which("memoose") or f'uvx --from "{_plugin_root()}" memoose'


def _child_env(cwd: str) -> dict:
    """The store the keeper must write to, passed down so its shell commands agree with ours."""
    child = {**os.environ, "MEMOOSE_PROJECT_DIR": cwd}
    for var in ("DATA_DIR", "EMBEDDER"):  # a legacy MNEMOTH_* value is passed on under the new name
        if value := env(var):
            child[f"MEMOOSE_{var}"] = value
    return child


def _no_mcp_config(tmp: Path) -> Path:
    """An empty server list: with --strict-mcp-config the keeper loads no MCP server at all."""
    cfg = tmp / "mcp.json"
    cfg.write_text('{"mcpServers":{}}')
    return cfg


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
        with tempfile.TemporaryDirectory(prefix="memoose-capture-") as td:
            tmp = Path(td)
            cfg = _no_mcp_config(tmp)
            prompt = PROMPT.format(
                exchange=exchange, today=time.strftime("%Y-%m-%d"),
                dataset=dataset_name(cwd), memoose=_memoose_cmd(),
            )
            cmd = [
                "claude", "-p", "--model", MODEL, "--max-turns", "24",
                "--mcp-config", str(cfg), "--strict-mcp-config",
                "--allowedTools", "Bash",
                "--dangerously-skip-permissions",
            ]
            plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
            if plugin_root:
                cmd += ["--plugin-dir", plugin_root]
            try:
                subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=td,
                               env=_child_env(cwd), timeout=TIMEOUT_S)
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
