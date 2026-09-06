"""Local, keyless embeddings.

`FastembedEmbedder` runs an ONNX sentence-transformer on the machine (install the
`fastembed` extra). `HashEmbedder` is a deterministic hashed bag-of-words fallback
that needs nothing: weaker semantics, but recall still has FTS5 for exact terms.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Protocol

_TOKEN = re.compile(r"[A-Za-z0-9_]+")


class Embedder(Protocol):
    name: str
    dimensions: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    name = "hash"

    def __init__(self, dimensions: int = 256) -> None:
        self.dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        toks = [t.casefold() for t in _TOKEN.findall(text)]
        grams = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]
        for g in grams:
            h = hashlib.blake2b(g.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dimensions
            sign = 1.0 if h[4] & 1 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


class FastembedEmbedder:
    name = "fastembed"

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding  # type: ignore[import-not-found]

        self._model = TextEmbedding(model_name=model)
        self.dimensions = len(next(iter(self._model.embed(["probe"]))))

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for v in self._model.embed(texts):
            vec = list(map(float, v))
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            out.append([x / norm for x in vec])
        return out


def default_embedder() -> Embedder:
    choice = os.environ.get("MNEMOTH_EMBEDDER", "auto").casefold()
    if choice in ("auto", "fastembed"):
        try:
            return FastembedEmbedder()
        except Exception:  # noqa: BLE001 - missing extra or model download failure
            if choice == "fastembed":
                raise
    return HashEmbedder()


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # vectors are unit-normalised
