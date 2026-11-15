"""The text pieces dictation's cleaning reads (no regex, D-046).

A transcript is split on whitespace into Chunks. Each chunk keeps the
punctuation around its word (`lead`, `trail`), so a span of chunks can be
replaced by new words while the commas, full stops and question marks the
speech model wrote stay where they were. `key` is the word as compared:
lower case, letters and digits only ("C.M.L." -> "cml", "person-days" ->
"persondays").
"""
from __future__ import annotations

from dataclasses import dataclass

SENTENCE_END = ".?!"


@dataclass
class Chunk:
    lead: str
    core: str
    trail: str

    @property
    def key(self) -> str:
        return "".join(ch for ch in self.core.lower() if ch.isalnum())

    @property
    def text(self) -> str:
        return self.lead + self.core + self.trail

    def ends_sentence(self) -> bool:
        return any(ch in SENTENCE_END for ch in self.trail)


def _is_core_start(ch: str) -> bool:
    return ch.isalnum() or ch == "₹"


def _is_core_end(ch: str) -> bool:
    return ch.isalnum() or ch == "%"


def chunk(word: str) -> Chunk:
    i, j = 0, len(word)
    while i < j and not _is_core_start(word[i]):
        i += 1
    while j > i and not _is_core_end(word[j - 1]):
        j -= 1
    return Chunk(word[:i], word[i:j], word[j:])


def split(text: str) -> list[Chunk]:
    return [chunk(w) for w in (text or "").split()]


def join(chunks: list[Chunk]) -> str:
    return " ".join(c.text for c in chunks if c.text)


def replace(chunks: list[Chunk], i: int, j: int, new_core: str) -> list[Chunk]:
    """chunks[i:j] become one chunk `new_core`, keeping chunk i's leading and
    chunk j-1's trailing punctuation."""
    merged = Chunk(chunks[i].lead, new_core, chunks[j - 1].trail)
    return chunks[:i] + [merged] + chunks[j:]


def letters(text: str) -> str:
    return "".join(ch for ch in (text or "").lower() if ch.isalnum())


def match_case(original: str, new: str) -> str:
    """`new` starts with a capital when the words it replaces did and it does not."""
    if original[:1].isupper() and new[:1].islower():
        return new[:1].upper() + new[1:]
    return new
