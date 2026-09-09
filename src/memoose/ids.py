"""Deterministic identifiers, after cognee's identity_fields idea.

An entity's id is derived from its normalised name, so the same name always maps
to the same node and re-remembering a fact merges instead of duplicating.
"""

from __future__ import annotations

import re
import uuid

_NAMESPACE = uuid.UUID("6f1c2a2e-1b8b-4d2c-9c1e-0a0a0a0a0001")
_WS = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    return _WS.sub(" ", name.strip()).casefold()


def entity_id(name: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"Entity:{normalize_name(name)}"))


def relation_id(source_id: str, name: str, target_id: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"Relation:{source_id}:{name.strip().casefold()}:{target_id}"))


def chunk_id(text: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"Chunk:{text.strip()}"))
