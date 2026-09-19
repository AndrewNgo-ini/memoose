"""Chunk source text for lexical and vector recall."""

from __future__ import annotations

import re


class Chunker:
    """Packs paragraphs up to a character budget; oversize paragraphs split on sentence boundaries.

    Sizes are in characters so the library needs no tokenizer.
    """

    _PARAGRAPH = re.compile(r"\n\s*\n")
    _SENTENCE = re.compile(r"(?<=[.!?])\s+")

    def __init__(self, max_chars: int = 1200) -> None:
        self.max_chars = max_chars

    def split(self, text: str) -> list[str]:
        chunks: list[str] = []
        current = ""
        for paragraph in self._PARAGRAPH.split(text):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            pieces = [paragraph] if len(paragraph) <= self.max_chars else self._split_paragraph(paragraph)
            for piece in pieces:
                if not current:
                    current = piece
                elif len(current) + 2 + len(piece) <= self.max_chars:
                    current = f"{current}\n\n{piece}"
                else:
                    chunks.append(current)
                    current = piece
        if current:
            chunks.append(current)
        return chunks

    def _split_paragraph(self, paragraph: str) -> list[str]:
        pieces: list[str] = []
        current = ""
        for sentence in self._SENTENCE.split(paragraph):
            if len(sentence) > self.max_chars:
                if current:
                    pieces.append(current)
                    current = ""
                pieces.extend(sentence[i : i + self.max_chars] for i in range(0, len(sentence), self.max_chars))
            elif not current:
                current = sentence
            elif len(current) + 1 + len(sentence) <= self.max_chars:
                current = f"{current} {sentence}"
            else:
                pieces.append(current)
                current = sentence
        if current:
            pieces.append(current)
        return pieces
