"""Chunk source text for lexical and vector recall.

A simplification of cognee's TextChunker: pack paragraphs up to a size budget,
split oversize paragraphs on sentence boundaries. Sizes are in characters so the
library needs no tokenizer.
"""

from __future__ import annotations

import re

_PARA = re.compile(r"\n\s*\n")
_SENT = re.compile(r"(?<=[.!?])\s+")


def chunk_text(text: str, max_chars: int = 1200) -> list[str]:
    chunks: list[str] = []
    buf = ""
    for para in (p.strip() for p in _PARA.split(text) if p.strip()):
        pieces = [para] if len(para) <= max_chars else _split_long(para, max_chars)
        for piece in pieces:
            if not buf:
                buf = piece
            elif len(buf) + 2 + len(piece) <= max_chars:
                buf = f"{buf}\n\n{piece}"
            else:
                chunks.append(buf)
                buf = piece
    if buf:
        chunks.append(buf)
    return chunks


def _split_long(para: str, max_chars: int) -> list[str]:
    out: list[str] = []
    buf = ""
    for sent in _SENT.split(para):
        if len(sent) > max_chars:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(sent[i : i + max_chars] for i in range(0, len(sent), max_chars))
            continue
        if not buf:
            buf = sent
        elif len(buf) + 1 + len(sent) <= max_chars:
            buf = f"{buf} {sent}"
        else:
            out.append(buf)
            buf = sent
    if buf:
        out.append(buf)
    return out
