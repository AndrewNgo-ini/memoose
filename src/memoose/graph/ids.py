"""Deterministic identifiers.

The same name always maps to the same id, so re-remembering a fact merges into
the existing node instead of duplicating it.
"""

from __future__ import annotations

import re
import uuid


class Ids:
    NAMESPACE = uuid.UUID("6f1c2a2e-1b8b-4d2c-9c1e-0a0a0a0a0001")
    _WHITESPACE = re.compile(r"\s+")

    @classmethod
    def normalize(cls, name: str) -> str:
        return cls._WHITESPACE.sub(" ", name.strip()).casefold()

    @classmethod
    def entity(cls, name: str) -> str:
        return cls._uuid(f"Entity:{cls.normalize(name)}")

    @classmethod
    def relation(cls, source_id: str, name: str, target_id: str) -> str:
        return cls._uuid(f"Relation:{source_id}:{name.strip().casefold()}:{target_id}")

    @classmethod
    def chunk(cls, text: str) -> str:
        return cls._uuid(f"Chunk:{text.strip()}")

    @classmethod
    def _uuid(cls, key: str) -> str:
        return str(uuid.uuid5(cls.NAMESPACE, key))
