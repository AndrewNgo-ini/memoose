#!/usr/bin/env python3
"""The advisor: a second agent that watches the primary step by step and advises it.

A port of Oh My Pi's advisor (`advisor/runtime.ts`, MIT) onto Claude Code's hooks. On by default,
off with `MEMOOSE_ADVISOR=0`. It is the recommendation path's live half: the prompt hint surfaces
memory before the agent starts, the advisor surfaces it while the agent works.

- **Trigger.** An async PostToolUse and Stop hook, so the advisor sees every step, like OMP's
  per-step `onTurnEnd`, and never blocks the primary.
- **Delta.** A cursor into the primary's transcript. Each review sends only what is new since
  the cursor, with the tool calls and results (the advisor must see what the primary *did*), and
  drops the advisor's own Advisories echoed back into the transcript. A delta that ends mid-turn
  carries OMP's `[in progress — more steps follow]` marker.
- **Drain.** One review runs per session at a time. Whoever holds the lock keeps reviewing
  until the cursor reaches the end of the transcript, so steps that arrive during a review are
  batched into the next one instead of waiting for a later hook (OMP's `#drain`).
- **One advisor conversation.** The first review starts a `claude -p --session-id` session and
  later ones `--resume` it, so the advisor remembers what it already reviewed and flagged, and
  the prompt cache holds. It is restarted after `MEMOOSE_ADVISOR_RESET_AFTER` reviews.
- **Tools.** Read, Grep, Glob, `memoose recall`, and `advise.py`, which is its only output.
  Nothing else is allowed, and it gets no MCP server.
- **Policy.** OMP's advisor prompt, plus the project's standing memory, plus every WATCHDOG.md
  from the user's memoose directory down to this project (closest last). Only the advisor reads it.
- **Late blockers.** A blocker that lands after the primary finished its turn wakes the session:
  this hook is `asyncRewake`, so exit 2 puts stderr in front of the primary.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import complete_lines, connect, data_dir, dataset_name, dataset_path, env, read_event, read_offset, write_offset  # noqa: E402
from advise import _path, advisor_on, mark_delivered, pending, render, session_state  # noqa: E402
from capture import _lock, _memoose_cmd, _no_mcp_config  # noqa: E402

MODEL = env("ADVISOR_MODEL") or "haiku"
TIMEOUT_S = int(env("ADVISOR_TIMEOUT") or "300")
RESET_AFTER = int(env("ADVISOR_RESET_AFTER") or "40")  # ponytail: a review count, not a token estimate
MAX_FAILURES = 3  # consecutive failed reviews before the advisor halts for the session, as in OMP
RESULT_CHARS = 2000
DELTA_CHARS = 40000
WIP = "\n\n---\n\n[in progress — more steps follow]"
ADVISE = str(Path(__file__).resolve().parent / "advise.py")

SYSTEM = """User, code-quality, robustness advocate; peer-shadow main agent.
- Sharpen strategy, problem-solving, judgment; identify cleaner approach.
- Challenge premature "done", thin verification, skipped reasoning.
- Enforce user ask; flag drift immediately.
- Prevent rabbit holes, overthinking, baked-in edge cases.

Cover skipped angles; NEVER re-run reasoning agent already has. Advise before wrong-direction work.

<workflow>
Receive incremental agent transcript as `### Session update` messages, including tool calls and results.
The agent works in {project}; give Read, Grep and Glob absolute paths under it.
Verify suspicions with your read-only tools: Read, Grep, Glob, and project memory through
`{memoose} recall "<question>" --dataset {dataset}` (decisions, conventions, rules, and Pitfalls
from earlier sessions). Memory is where you see what the agent does not: when the agent is about to
contradict a stored decision, rule or Pitfall, say so and cite the stored fact.
Per advisory: 2–3 tool calls. Critical bugs MAY need deeper verification before a `blocker`.
Send advice ONLY by running: {advise} <nit|concern|blocker> "<one concrete, terse note>"
Use it sparingly; stay silent when nothing matters. Call it to avert likely-wrong or materially wasteful work.
After you advise or decide to stay silent, end your reply with one word: done.
</workflow>

<communication>
- Max {max_notes} non-blockers per update (`blocker` exempt). Silence preferred when agent on track.
- Address agent directly; offer alternatives, not lectures.
- NEVER restate information agent has, including seen errors: type errors, failed builds/tests, lint.
- NEVER repeat prior advice or send identical advice twice; allow action before revisiting its theme.
- `[in progress — more steps follow]` at the end of an update: agent mid-turn. Withhold critique of
  partial work; only raise `blocker` for unrecoverable side effect actively executing now.
- NEVER nitpick what user accepts. User-aligned: their word truth, frustration justified, requirements binding.
</communication>

<critical>
Advise only on concrete technical risk or transcript-evident execution failure; generic uncertainty,
vague unease, user-intent ambiguity → SILENT.
NEVER second-guess decisions the agent understands and commits to unless certain.
NEVER advise on user intent or ceremony: never tell the agent to seek clarification, confirm scope,
summarize input or narrate workflow. Your lane: correctness, edge cases, design, execution strategy, verification.
NEVER police scope or ambition. Object ONLY when an explicit instruction is breached, ambient user work
is touched, or a bounded request gains unrequested features; cite evidence.
NEVER raise backwards compatibility unless the user or a standing project rule requires it.
Cite only transcript evidence or personally inspected tool output. A result containing an `elided`
marker is only an excerpt. Cite exact instruction, stored fact, or risk.
</critical>

<severity>
nit: non-urgent cleanup, simplification, missed opportunity. Delivered when the agent's turn ends.
concern: agent may head wrong or miss a material issue — wrong code path, missing constraint,
  guessing what source/docs/memory could tell it, churn without progress, a stored decision or Pitfall
  about to be repeated. Delivered at the agent's next tool step; the agent decides.
blocker: stop/reconsider. ONLY when continued progress clearly contradicts an explicit instruction
  (cite it), is fundamentally unsound, claims done on work never exercised against the user's ask,
  substitutes stubs or mocks for required work, or yields before an explicit convergence condition is
  met. Verify thoroughly before raising.
</severity>

MAY suggest approach/fix after enough exploration for confidence. Offer better designs, not only warning."""


def watchdog(cwd: str) -> str:
    """Every WATCHDOG.md from the user's memoose dir, then from the repo root down to `cwd`."""
    here = Path(cwd).resolve()
    chain = [here, *here.parents]
    root = next((p for p in chain if (p / ".git").exists()), None)
    dirs = chain[: chain.index(root) + 1] if root else [here]
    files = [data_dir() / "WATCHDOG.md", *(d / "WATCHDOG.md" for d in reversed(dirs))]
    blocks = [f.read_text(errors="replace").strip() for f in files if f.is_file()]
    return "\n".join(f"Especially pay attention to:\n<attention>\n{b}\n</attention>" for b in blocks if b)


def standing_memory(cwd: str) -> str:
    conn = connect(dataset_path(cwd))
    if conn is None:
        return ""
    try:
        from session_start import build_context
        return build_context(conn)
    except Exception:  # noqa: BLE001 - memory is context, not a requirement
        return ""
    finally:
        conn.close()


def project_context(cwd: str) -> str:
    """The primary's own instructions. The advisor runs outside the project, so nothing loads them for it."""
    files = [Path(cwd) / n for n in ("AGENTS.md", "CLAUDE.md")]
    return "\n\n".join(f.read_text(errors="replace").strip() for f in files if f.is_file())


def system_prompt(cwd: str) -> str:
    from advise import MAX_NOTES
    parts = [SYSTEM.format(memoose=_memoose_cmd(), dataset=dataset_name(cwd), project=cwd,
                           advise=f"python3 {shlex.quote(ADVISE)}", max_notes=MAX_NOTES)]
    if project := project_context(cwd):
        parts.append(f"<project-context>\n{project}\n</project-context>")
    if memory := standing_memory(cwd):
        parts.append(f"<memory-context>\n{memory}\n</memory-context>")
    if attention := watchdog(cwd):
        parts.append(attention)
    return "\n\n".join(parts)


# ----- the delta ---------------------------------------------------------------------------------
def _clip(text: str, limit: int = RESULT_CHARS) -> str:
    return text if len(text) <= limit else f"{text[:limit]}\n[… {len(text) - limit} chars elided …]"


def _render_block(b: dict) -> str:
    t = b.get("type")
    if t == "text":
        return b.get("text") or ""
    if t == "thinking":
        return f"(thinking) {b.get('thinking') or ''}".strip() if b.get("thinking") else ""
    if t == "tool_use":
        return f"Tool call {b.get('name')}: {_clip(json.dumps(b.get('input'), ensure_ascii=False))}"
    if t == "tool_result":
        c = b.get("content")
        if isinstance(c, list):
            c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
        return f"Tool result{' (error)' if b.get('is_error') else ''}: {_clip(str(c or ''))}"
    return ""


def read_delta(transcript_path: str | None, start: int) -> tuple[str, int, bool]:
    """(rendered delta, new cursor, primary mid-turn) for complete transcript lines from `start`.

    A last line the host is still writing is left for the next pass (`complete_lines`).
    """
    if not transcript_path or not Path(transcript_path).exists():
        return "", start, False
    lines = complete_lines(Path(transcript_path))
    out, mid_turn, size = [], False, 0
    for i in range(start, len(lines)):
        line = lines[i]
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if d.get("type") not in ("user", "assistant") or d.get("isMeta"):
            continue
        content = (d.get("message") or {}).get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
        parts = [s for s in (_render_block(b) for b in blocks if isinstance(b, dict)) if s.strip()]
        text = "\n".join(parts).strip()
        if not text or text.startswith("<system-reminder") or "<advisory " in text:
            continue  # injected text, and the advisor's own advice coming back
        entry = _clip(f"{'User' if d['type'] == 'user' else 'Agent'}: {text}", DELTA_CHARS)
        if out and size + len(entry) > DELTA_CHARS:
            return "\n\n".join(out), i, True  # the rest is the next batch; more follows, so mid-turn
        out.append(entry)
        size += len(entry) + 2
        # the turn is over once the agent's last message calls no tool
        mid_turn = d["type"] == "user" or any(isinstance(b, dict) and b.get("type") == "tool_use" for b in blocks)
    return "\n\n".join(out), len(lines), mid_turn


# ----- one review ----------------------------------------------------------------------------------
def review(session_id: str, cwd: str, delta: str, mid_turn: bool) -> bool:
    """Send one delta to the advisor. True when the advisor ran."""
    with session_state(session_id) as st:
        adv = st.setdefault("advisor", {})
        if not adv.get("id") or adv.get("reviews", 0) >= RESET_AFTER:
            adv.update(id=str(uuid.uuid4()), reviews=0, started=False)
        adv["update"] = adv.get("update", 0) + 1
        advisor_id, resume, update = adv["id"], adv["started"], adv["update"]
    memoose = _memoose_cmd()
    # A fixed directory per session: `--resume` finds a session only from the cwd that made it, and
    # running outside the project keeps the advisor's transcripts out of the user's session list.
    home = _path(session_id, "d")
    home.mkdir(exist_ok=True)
    cmd = ["claude", "-p", "--model", MODEL,
           *(["--resume", advisor_id] if resume else ["--session-id", advisor_id]),
           "--append-system-prompt", system_prompt(cwd), "--add-dir", cwd,
           "--mcp-config", str(_no_mcp_config(home)), "--strict-mcp-config",
           "--allowedTools", "Read", "Grep", "Glob",
           f"Bash({memoose} recall:*)", f"Bash(python3 {shlex.quote(ADVISE)}:*)"]
    child = {**os.environ, "MEMOOSE_PROJECT_DIR": cwd, "MEMOOSE_ADVISOR_SESSION": session_id,
             "MEMOOSE_ADVISOR_UPDATE": str(update),
             # the advisor's own session must not advise, capture, or hint itself
             "MEMOOSE_ADVISOR": "0", "MEMOOSE_AUTO_CAPTURE": "0", "MEMOOSE_HINTS": "0",
             "MEMOOSE_AUTO_RECALL": "0"}
    try:
        r = subprocess.run(cmd, input=f"### Session update\n\n{delta}{WIP if mid_turn else ''}",
                           capture_output=True, text=True, cwd=home, env=child, timeout=TIMEOUT_S)
        ok = r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    with session_state(session_id) as st:
        adv = st.setdefault("advisor", {})
        if ok:
            adv.update(started=True, reviews=adv.get("reviews", 0) + 1, failures=0)
        else:
            adv["failures"] = adv.get("failures", 0) + 1
    return ok


def halted(session_id: str) -> bool:
    with session_state(session_id) as st:
        return st.get("advisor", {}).get("failures", 0) >= MAX_FAILURES


def drain(session_id: str, cwd: str, transcript: str | None) -> bool:
    """Review until the cursor reaches the transcript's end. Returns whether the primary is mid-turn."""
    key, mid_turn = f"advisor-{session_id}", True
    while not halted(session_id):
        start = read_offset(key)
        delta, end, mid_turn = read_delta(transcript, start)
        if end <= start:
            break
        if delta:
            review(session_id, cwd, delta, mid_turn)
        write_offset(key, end)  # a failed review drops its batch, as OMP does after its retries
    return mid_turn


def main() -> int:
    if not advisor_on():
        return 0
    event = read_event()
    session_id = str(event.get("session_id") or "unknown")
    cwd = event.get("cwd") or os.getcwd()
    transcript = event.get("transcript_path")
    key = f"advisor-{session_id}"
    while True:
        lock = _lock(key)
        if lock is None:
            return 0  # the holder drains everything, this step included
        try:
            mid_turn = drain(session_id, cwd, transcript)
        finally:
            lock.unlink(missing_ok=True)
        if halted(session_id):
            return 0
        # a step that arrived between the last check and the unlock found the lock held; take it
        if read_delta(transcript, read_offset(key))[1] <= read_offset(key):
            break
    if mid_turn:
        return 0  # the next PostToolUse or Stop delivers
    time.sleep(1)  # let a Stop hook that is still running take its blockers first
    with session_state(session_id) as st:
        late = [a for a in pending(st) if a["severity"] == "blocker"]
        mark_delivered(st, late)
    if late:
        print(render(late), file=sys.stderr)
        return 2  # asyncRewake: wakes the idle primary with the blocker
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001 - a hook must never break the session
        sys.exit(0)
