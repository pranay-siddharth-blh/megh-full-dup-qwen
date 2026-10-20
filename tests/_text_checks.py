"""Plain-string text checks shared by the harness scripts under tests/
(sheet_runs, nl2sql_eval, rag_eval, live_context_validation).

Project rule (D-047): text is checked with plain string code. These helpers do,
with string methods and character loops, the few text checks the harness
scripts need:

    find_phrase / has_phrase   a literal phrase, optionally case-insensitive and
                               a whole word (not inside a longer word). In a
                               phrase, '#' stands for one decimal digit and
                               '?' for any character but a newline.
    number_runs                a digit, then digits/commas, then optional '.digits'
    zero_lakh                  a standalone 0 (or 0.0 ...), optional spaces, 'lakh'
    no_near                    the word 'no', then within N characters (no '.') a
                               word starting with one of the alternatives
    first_of                   the leftmost of several literals
    word_chars_only            drop every character that is not a letter/digit/'_'
"""
from __future__ import annotations


def is_word_char(ch: str) -> bool:
    """A word character: a letter, a digit or '_'."""
    return ch.isalnum() or ch == "_"


def _boundary(text: str, p: int) -> bool:
    """A word edge at position p: a word character on exactly one side."""
    before = p > 0 and is_word_char(text[p - 1])
    after = p < len(text) and is_word_char(text[p])
    return before != after


def _char_ok(c: str, pc: str, case: bool) -> bool:
    if pc == "#":
        return c.isdecimal()
    if pc == "?":
        return c != "\n"
    return c == pc if case else c.lower() == pc


def _at(text: str, i: int, pat: str, case: bool) -> bool:
    if i + len(pat) > len(text):
        return False
    return all(_char_ok(text[i + k], pc, case) for k, pc in enumerate(pat))


def find_phrase(text: str | None, phrase: str, *, case: bool = False,
                bounded: bool = False, start: int = 0) -> int:
    """Index of the first occurrence of `phrase` in `text` at or after `start`
    (-1 if none). case=False compares case-insensitively; bounded=True needs a
    word edge on both sides (a whole word, not inside a longer word)."""
    text = text or ""
    pat = phrase if case else phrase.lower()
    for i in range(start, len(text) - len(pat) + 1):
        if not _at(text, i, pat, case):
            continue
        if bounded and not (_boundary(text, i) and _boundary(text, i + len(pat))):
            continue
        return i
    return -1


def has_phrase(text: str | None, *phrases: str, case: bool = False, bounded: bool = False) -> bool:
    """Does `text` contain any of `phrases`? (see find_phrase)"""
    return any(find_phrase(text, p, case=case, bounded=bounded) != -1 for p in phrases)


def number_runs(text: str | None, *, signed: bool = False, lookbehind: bool = False,
                commas_first: bool = False) -> list[tuple[int, int, str]]:
    """Numbers -> (start, end, text): a digit, then digits and commas, then
    optionally '.' and digits. signed=True allows a leading '-'; lookbehind=True
    skips a number that directly follows a digit or '.'; commas_first=True lets
    the run start with a comma instead of a digit."""
    text = text or ""
    out = []
    i, n = 0, len(text)

    def starts_run(k: int) -> bool:
        return k < n and (text[k].isdecimal() or (commas_first and text[k] == ","))

    while i < n:
        s = i
        if signed and text[i] == "-" and starts_run(i + 1):
            j = i + 1
        elif starts_run(i):
            j = i
        else:
            i += 1
            continue
        if lookbehind and s > 0 and (text[s - 1].isdecimal() or text[s - 1] == "."):
            i += 1
            continue
        j += 1
        while j < n and (text[j].isdecimal() or text[j] == ","):
            j += 1
        if j + 1 < n and text[j] == "." and text[j + 1].isdecimal():
            j += 2
            while j < n and text[j].isdecimal():
                j += 1
        out.append((s, j, text[s:j]))
        i = j
    return out


def zero_lakh(text: str | None, *, case: bool = True) -> bool:
    """A standalone 0 (or 0.0, 0.00 ...), optional spaces, then 'lakh'."""
    text = text or ""
    n = len(text)
    for i in range(n):
        if text[i] != "0" or not _boundary(text, i):
            continue
        ends = [i + 1]
        if text[i + 1:i + 2] == "." and text[i + 2:i + 3] == "0":
            j = i + 2
            while j < n and text[j] == "0":
                j += 1
            ends.insert(0, j)
        for j in ends:
            while j < n and text[j].isspace():
                j += 1
            if _at(text, j, "lakh", case):
                return True
    return False


def no_near(text: str | None, alts: tuple[str, ...], max_gap: int, *, case: bool = False) -> bool:
    """The whole word 'no', then within
    max_gap characters (no '.' among them) a word that starts with one of `alts`."""
    text = text or ""
    n = len(text)
    pats = [a if case else a.lower() for a in alts]
    i = find_phrase(text, "no", case=case, bounded=True)
    while i != -1:
        e = i + 2
        for p in range(e, min(e + max_gap, n) + 1):
            if _boundary(text, p) and any(_at(text, p, a, case) for a in pats):
                return True
            if p < n and text[p] == ".":
                break
        i = find_phrase(text, "no", case=case, bounded=True, start=i + 1)
    return False


def first_of(text: str | None, *alts: str) -> str | None:
    """The literal among `alts` that occurs first in `text` (case-sensitive)."""
    text = text or ""
    best, where = None, len(text) + 1
    for a in alts:
        k = text.find(a)
        if k != -1 and k < where:
            best, where = a, k
    return best


def word_chars_only(s: str | None) -> str:
    """`s` keeping only its letters, digits and '_'."""
    return "".join(ch for ch in (s or "") if is_word_char(ch))


def need_ok(text: str | None, need: str) -> bool:
    """A harness 'need' written 'alt|alt|...': true when any alternative occurs
    in `text`, case-insensitively. An alternative wrapped in [ ] must be a
    whole word or phrase; '#' in an alternative stands for one digit."""
    for alt in need.split("|"):
        bounded = alt.startswith("[") and alt.endswith("]") and len(alt) > 2
        if bounded:
            alt = alt[1:-1]
        if find_phrase(text, alt, bounded=bounded) != -1:
            return True
    return False
