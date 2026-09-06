"""Sessions: cognee's fast cache of turns plus typed context entries, and the inputs for
session distillation.

cognee distills a finished session in three model steps: curate lessons per batch,
accept or reject each lesson against prior memory, persist accepted lessons through
cognify. Here `timeline` packs the batches and lists prior lessons, the skill
carries the curator and writer rules, and `publish_lessons` persists what the
Host Model accepted as Lesson entities linked into the graph.
"""

from __future__ import annotations

import uuid

from .store.sqlite_store import SqliteStore

SECTIONS = (
    "goals", "rules", "preferences", "lessons_learned",
    "tool_rules", "workflow_state", "success_patterns", "failure_lessons", "environment_facts",
    "feedback",
)


def validate_section(section: str) -> str:
    s = section.strip().casefold()
    if s not in SECTIONS:
        raise ValueError(f"Unknown section {section!r}. Use one of: {', '.join(SECTIONS)}.")
    return s


def timeline(store: SqliteStore, session_id: str, batch_chars: int = 6000) -> dict:
    """Pack a session's turns and context into batches of at most batch_chars (cognee's curator batches)."""
    if store.session(session_id) is None:
        raise ValueError(f"Unknown session {session_id!r}.")
    turns = store.turns(session_id)
    ctx = store.context(session_id=session_id)
    lines = [f"[{t['role']}] {t['text'].strip()}" for t in turns] + [f"[context/{c['section']}] {c['content'].strip()}" for c in ctx]
    batches: list[str] = []
    buf = ""
    for line in lines:
        if buf and len(buf) + 1 + len(line) > batch_chars:
            batches.append(buf)
            buf = line
        else:
            buf = f"{buf}\n{line}" if buf else line
    if buf:
        batches.append(buf)
    return {
        "session_id": session_id,
        "turns": len(turns),
        "context_entries": len(ctx),
        "batches": batches,
        "prior_lessons": [{"id": l["id"], "title": l["title"], "text": l["text"]} for l in store.lessons(50)],
        "curator_rules": CURATOR_RULES,
        "writer_rules": WRITER_RULES,
    }


CURATOR_RULES = (
    "For each batch, propose lessons that are (1) general beyond this one session, (2) actionable next time, "
    "(3) supported by what actually happened in the batch, and (4) not already in prior_lessons. "
    "Each lesson: a short title, one to three sentences, and the evidence (turn or context line) it rests on. "
    "Prefer fewer, sharper lessons. Never invent."
)
WRITER_RULES = (
    "For each proposed lesson, recall related prior lessons and facts. Reject it if a prior lesson already says it "
    "or if the evidence is thin. Otherwise write the final text so it stands alone without the session, name the "
    "entities it applies to (systems, technologies, people, conventions), and pass it to publish_lessons with those names."
)


def lesson_id(title: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"lesson:{title.strip().casefold()}"))
