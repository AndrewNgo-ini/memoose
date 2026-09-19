"""Sessions: a fast cache of turns plus typed context entries, and the inputs for distillation.

A finished session is distilled in three model steps: curate lessons per batch, accept or
reject each against prior memory, persist the accepted ones. `timeline` packs the batches
and lists prior lessons; the memoose-sessions skill carries the curator and writer rules;
the engine's `publish_lessons` persists what the Host Model accepted.
"""

from __future__ import annotations

import uuid

from ..store.sqlite_store import SqliteStore


class Sessions:
    SECTIONS = (
        "goals", "rules", "preferences", "lessons_learned",
        "tool_rules", "workflow_state", "success_patterns", "failure_lessons", "environment_facts",
        "feedback",
    )
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

    def __init__(self, store: SqliteStore) -> None:
        self.store = store

    @classmethod
    def validate_section(cls, section: str) -> str:
        clean = section.strip().casefold()
        if clean not in cls.SECTIONS:
            raise ValueError(f"Unknown section {section!r}. Use one of: {', '.join(cls.SECTIONS)}.")
        return clean

    @staticmethod
    def lesson_id(title: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"lesson:{title.strip().casefold()}"))

    def timeline(self, session_id: str, batch_chars: int = 6000) -> dict:
        """The session's turns and context packed into batches of at most batch_chars, plus prior lessons."""
        if self.store.session(session_id) is None:
            raise ValueError(f"Unknown session {session_id!r}.")
        turns = self.store.turns(session_id)
        context = self.store.context(session_id=session_id)
        lines = [f"[{t['role']}] {t['text'].strip()}" for t in turns]
        lines += [f"[context/{c['section']}] {c['content'].strip()}" for c in context]
        return {
            "session_id": session_id,
            "turns": len(turns),
            "context_entries": len(context),
            "batches": self._batches(lines, batch_chars),
            "prior_lessons": [{"id": l["id"], "title": l["title"], "text": l["text"]} for l in self.store.lessons(50)],
            "curator_rules": self.CURATOR_RULES,
            "writer_rules": self.WRITER_RULES,
        }

    @staticmethod
    def _batches(lines: list[str], batch_chars: int) -> list[str]:
        batches: list[str] = []
        current = ""
        for line in lines:
            if current and len(current) + 1 + len(line) > batch_chars:
                batches.append(current)
                current = line
            else:
                current = f"{current}\n{line}" if current else line
        if current:
            batches.append(current)
        return batches
