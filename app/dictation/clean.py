"""What the speech model wrote -> what the officer would have typed (dictation, D-111). No regex (D-046).

    why_not(raw, prompt, voiced_s, seconds)  -> "" when a segment's words may be used, else the reason
    clean(raw)                               -> Cleaned(text, corrections)

clean(), in order:
  1. fillers off ("um", "uh", "er" ...), the sentence's capital kept;
  2. spoken numbers written as digits (app/dictation/numbers.py): "two thousand twenty-three twenty-four"
     -> 2023-24, "five lakh" -> 5 lakh, "rupees five lakh" -> ₹5 lakh. Before the table, so the table's
     "a year next" condition sees the year written;
  3. the mishearing table data/dictation_hearing.yaml ("see em elevate" -> CM Elevate, "person dies" ->
     person-days, "in reply" -> Ri Bhoi only where a place stands); then a block / constituency name heard by
     ear, only just before "block" / "constituency" and only a clear winner ("Amleerin block" -> Amlarem);
  4. app/spelling.normalise(), keeping ONLY its scheme / district / block corrections (the typed pipeline
     runs it again on the question; its word / village rewrites stay the pipeline's business).
Every change of words (not of case or number style) is returned in `corrections` so the page can say
"heard 'in reply' -> Ri Bhoi". Anything ambiguous is left as said.

The table is read only here: typed questions never see it.
"""
from __future__ import annotations

import contextvars
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app import asr_guard
from app.dictation import numbers
from app.dictation.words import Chunk, join, letters, match_case, split

logger = logging.getLogger(__name__)

TABLE_FILE = Path(__file__).resolve().parents[2] / "data" / "dictation_hearing.yaml"

FILLERS = frozenset({"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "ahh", "hmm", "hm", "mm", "mmm"})
# relisten guards (Full Duplex fdx/relisten.py, 4-12 Nov): a lone word like these for a long stretch of voice
# is the model guessing, not the officer speaking
LONE = frozenset({"okay", "ok", "oh", "uh", "um", "hmm", "mm", "yes", "no", "thank you", "thanks", "bye"})
LONE_MAX_VOICE_S = 1.5
MAX_LETTERS_PER_S = 25          # more letters than anyone can say in that time
SPELLING_KINDS = ("scheme", "district", "block")
END_PUNCT = ",.?!;"


# ── guards ──────────────────────────────────────────────────────────────────

def why_not(raw: str, prompt: str, voiced_s: float, seconds: float) -> str:
    """'' when the segment's words may be used, else why not (no words in the reason: it may be logged)."""
    text = (raw or "").strip()
    if not letters(text):
        return "empty"
    if asr_guard.is_no_speech(text):
        if voiced_s <= LONE_MAX_VOICE_S and " ".join(asr_guard._normalise(text).split()) in ("yes", "no"):
            return ""
        return "no speech"
    if asr_guard.is_prompt_echo(text, prompt):
        return "prompt echo"
    norm = asr_guard._normalise(text)
    if norm in LONE and voiced_s > LONE_MAX_VOICE_S:
        return "a lone word for a long stretch of voice"
    if len(letters(text)) / max(seconds, 0.05) > MAX_LETTERS_PER_S:
        return "too many letters for the voice heard"
    return ""


# ── the table ───────────────────────────────────────────────────────────────

@dataclass
class _Fix:
    to: str
    kind: str
    heard: list            # [(words, joined)]
    slots: list            # [[set_of_words or "" ...]]
    when: list             # [{"prev": set, "next": set}]


_TABLE: dict = {"mtime": None, "fixes": []}


def _load() -> list:
    try:
        mtime = os.path.getmtime(TABLE_FILE)
    except OSError:
        return []
    if _TABLE["mtime"] == mtime:
        return _TABLE["fixes"]
    data = yaml.safe_load(TABLE_FILE.read_text(encoding="utf-8")) or {}
    fixes = []
    for f in data.get("fixes") or []:
        heard = []
        for h in f.get("heard") or []:
            ws = [letters(w) for w in str(h).split() if letters(w)]
            if ws:
                heard.append((ws, "".join(ws)))
        slots = [[{letters(str(w)) for w in slot} for slot in seq] for seq in (f.get("slots") or [])]
        when = [{"prev": {str(w).lower() for w in (c.get("prev") or [])},
                 "next": {str(w).lower() for w in (c.get("next") or [])}} for c in (f.get("when") or [])]
        fixes.append(_Fix(str(f["to"]), str(f.get("kind") or "term"), heard, slots, when))
    _TABLE.update(mtime=mtime, fixes=fixes)
    return fixes


def _match_heard(keys: list, i: int, joined: str) -> int:
    """Chunks used when the letters of chunks i.. spell `joined` exactly (0 = no match)."""
    acc = ""
    j = i
    while j < len(keys) and len(acc) < len(joined):
        if not keys[j]:
            return 0
        acc += keys[j]
        j += 1
        if not joined.startswith(acc):
            return 0
    return j - i if acc == joined else 0


def _match_slots(keys: list, i: int, seq: list) -> int:
    """Chunks used when chunks i.. say one word of each slot in order, each word a chunk of its own or several
    run together ("Peep EMAYG" = peep + e + m + a + y + g); 0 = no match. The longest match wins."""
    best, acc, j = 0, "", i
    while j < len(keys) and keys[j] and len(acc) < 40:
        acc += keys[j]
        j += 1
        if _parses(acc, seq):
            best = j - i
    return best


def _parses(s: str, seq: list) -> bool:
    if not seq:
        return s == ""
    slot = seq[0]
    if "" in slot and _parses(s, seq[1:]):
        return True
    return any(w and s.startswith(w) and _parses(s[len(w):], seq[1:]) for w in slot)


def _is_yearish(core: str) -> bool:
    c = core.lower()
    if c.startswith("fy"):
        c = c[2:]
    return len(c) >= 4 and c[:2] == "20" and c[:4].isdigit()


def _context_ok(fix: _Fix, chunks: list, i: int, j: int) -> bool:
    if not fix.when:
        return True
    prev = chunks[i - 1].key if i > 0 and not chunks[i - 1].ends_sentence() else ""
    at_end = j >= len(chunks) or any(ch in END_PUNCT for ch in chunks[j - 1].trail)
    nxt = chunks[j].key if j < len(chunks) and not at_end else ""
    nxt2 = chunks[j + 1].core if j + 1 < len(chunks) else ""
    for c in fix.when:
        if c["prev"] and prev not in c["prev"]:
            continue
        if c["next"]:
            ok = nxt in c["next"]
            if "<end>" in c["next"] and at_end:
                ok = True
            if "<year>" in c["next"] and nxt and (_is_yearish(chunks[j].core) or (
                    nxt in ("in", "for", "during") and (_is_yearish(nxt2) or nxt2.lower() == "fy"))):
                ok = True
            if not ok:
                continue
        return True
    return False


def apply_table(chunks: list) -> "tuple[list, list]":
    fixes = _load()
    out_corr = []
    i = 0
    while i < len(chunks):
        keys = [c.key for c in chunks]
        best = (0, None)
        for fix in fixes:
            for _, joined in fix.heard:
                n = _match_heard(keys, i, joined)
                if n > best[0] and _context_ok(fix, chunks, i, i + n):
                    best = (n, fix)
            for seq in fix.slots:
                n = _match_slots(keys, i, seq)
                if n > best[0] and _context_ok(fix, chunks, i, i + n):
                    best = (n, fix)
        n, fix = best
        if not fix:
            i += 1
            continue
        heard = " ".join(c.core for c in chunks[i:i + n])
        new = match_case(heard, fix.to) if i == 0 or chunks[i - 1].ends_sentence() else fix.to
        if heard != new:
            # punctuation the model put INSIDE the words ("Pep, M A Y G") goes with them
            chunks = chunks[:i] + [Chunk(chunks[i].lead, new, chunks[i + n - 1].trail)] + chunks[i + n:]
            if letters(heard) != letters(fix.to):
                out_corr.append({"heard": heard, "wrote": fix.to, "kind": fix.kind})
        i += 1
    return chunks, out_corr


# ── fillers ─────────────────────────────────────────────────────────────────

def drop_fillers(chunks: list) -> list:
    out: list = []
    cap_next = False
    for k, c in enumerate(chunks):
        if c.key in FILLERS and c.core.isalpha():
            sentence_start = not out or out[-1].ends_sentence()
            if any(ch in ".?!" for ch in c.trail) and out:
                out[-1] = Chunk(out[-1].lead, out[-1].core, out[-1].trail.rstrip(",;") + c.trail.strip(",; "))
            cap_next = cap_next or sentence_start
            continue
        if cap_next and c.core[:1].islower():
            c = Chunk(c.lead, c.core[:1].upper() + c.core[1:], c.trail)
        cap_next = False
        out.append(c)
    return out


# ── spelling (scheme / district / block only) ───────────────────────────────

_QUIET = contextvars.ContextVar("dictation_quiet", default=False)


class _QuietFilter(logging.Filter):
    """The spelling module logs the question it corrected; a dictated sentence is never logged (D-111)."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not _QUIET.get()


_FILTER = _QuietFilter()
logging.getLogger("app.spelling").addFilter(_FILTER)


def spelling_pass(text: str) -> "tuple[str, list]":
    from app import spelling
    token = _QUIET.set(True)
    try:
        n = spelling.normalise(text)
    finally:
        _QUIET.reset(token)
    keep = [c for c in n.corrections if c.kind in SPELLING_KINDS and letters(c.typed) != letters(c.canonical)]
    if all(c.kind in SPELLING_KINDS for c in n.corrections):
        out = n.text
    else:
        out = text
        for c in keep:
            at = out.find(c.typed)
            if at >= 0:
                out = out[:at] + c.canonical + out[at + len(c.typed):]
    corr = [{"heard": c.typed, "wrote": c.canonical, "kind": "scheme" if c.kind == "scheme" else "place"}
            for c in keep]
    return out, corr


# ── names in their own case ─────────────────────────────────────────────────

def _names() -> list:
    """[(words as letters, canonical)] for every district and scheme, longest first."""
    from app import scheme_registry, spelling
    names = list(scheme_registry.NAMES) + list(spelling.districts())
    out = []
    for n in names:
        ws = [letters(w) for w in n.replace("-", " ").split() if letters(w)]
        out.append((ws, "".join(ws), n))
    return sorted(out, key=lambda x: -len(x[1]))


def name_case(chunks: list) -> list:
    """'west khasi hills' -> 'West Khasi Hills', 'pmay-g' -> 'PMAY-G': the same letters, written as Megh
    writes the name. Never a different word."""
    names = _names()
    i = 0
    while i < len(chunks):
        keys = [c.key for c in chunks]
        for ws, joined, canon in names:
            n = _match_heard(keys, i, joined)
            said = sum(len([w for w in c.core.replace("-", " ").split() if letters(w)]) for c in chunks[i:i + n])
            if n and said == len(ws):       # word for word only: 'Home stay' is not 'Homestay'
                heard = " ".join(c.core for c in chunks[i:i + n])
                if heard != canon and not any(c.trail.strip() for c in chunks[i:i + n - 1]):
                    chunks = chunks[:i] + [Chunk(chunks[i].lead, canon, chunks[i + n - 1].trail)] + chunks[i + n:]
                break
        i += 1
    return chunks


# ── a block / constituency name heard wrongly, where a block or constituency is said ──
# The ASR prompt is kept short on purpose (listing the 70 blocks made it snap to wrong ones, config.ASR_PROMPT),
# so a block name comes back spelt by ear: "Amlarem" as "Amleerin", "Am Laren", "Om Larem", "Amrlerum";
# "Nongstoin" as "non-stone" (the 240-clip bank, 15 Nov). Only the word(s) just before "block" / "constituency"
# are read, and only a clear winner is written: a coarse sound key (vowels after the first letter dropped, r = l,
# m = n, h dropped, k = c) next to the letters and the spelling module's own sound key.

LEVEL_AFTER = frozenset({"block", "blocks", "constituency", "constituencies"})
NOT_A_NAME = frozenset("""the a an any all each every which what whose this that these those same other another per
my our their its his her your top bottom by of in for at from to and or highest lowest biggest smallest largest most
least best worst first last next previous community development rural urban whole entire one two three four five
six seven eight nine ten its district state new old given said""".split())
PLACE_MIN_SCORE = 85
PLACE_MARGIN = 10
_PLACE_INDEX: dict = {}


def coarse_key(word: str) -> str:
    out = ""
    for i, ch in enumerate(letters(word)):
        if ch in "aeiouy":
            ch = "a" if i == 0 else ""
        elif ch == "r":
            ch = "l"
        elif ch == "m":
            ch = "n"
        elif ch == "h":
            ch = ""
        elif ch in "ck":
            ch = "k"
        if ch and not out.endswith(ch):
            out += ch
    return out


def _place_index() -> dict:
    """{letters of a block / constituency form: canonical name as Megh writes it}."""
    from app import entity_resolver as er
    from app import spelling
    key = id(er._catalog)
    if _PLACE_INDEX.get("id") == key and _PLACE_INDEX.get("forms"):
        return _PLACE_INDEX["forms"]
    forms: dict = {}
    for dims in er._catalog.values():
        for level in ("block", "constituency"):
            for v in dims.get(level) or []:
                canon = spelling._title(str(v.get("canonical") or ""))
                for f in [canon, *(v.get("aliases") or [])]:
                    if len(letters(str(f))) >= 4:
                        forms.setdefault(letters(str(f)), canon)
    _PLACE_INDEX.update(id=key, forms=forms)
    return forms


def _best_place(heard: str) -> "tuple[str, float, float] | None":
    from rapidfuzz import fuzz

    from app import spelling
    w = letters(heard)
    if len(w) < 4 or w.isdigit():
        return None
    by_name: dict = {}
    sk, ck = spelling.sound_key(w), coarse_key(w)
    for form, canon in _place_index().items():
        s = max(fuzz.ratio(w, form), fuzz.ratio(sk, spelling.sound_key(form)), 0.97 * fuzz.ratio(ck, coarse_key(form)))
        k = letters(canon)
        if s > by_name.get(k, (0, ""))[0]:
            by_name[k] = (s, canon)
    ranked = sorted(by_name.values(), reverse=True)
    if not ranked:
        return None
    best = ranked[0]
    second = ranked[1][0] if len(ranked) > 1 else 0.0
    return best[1], best[0], second


def place_by_sound(chunks: list) -> "tuple[list, list]":
    corr = []
    i = 1
    while i < len(chunks):
        if chunks[i].key not in LEVEL_AFTER or chunks[i - 1].ends_sentence():
            i += 1
            continue
        options = []
        for n in (1, 2):
            span = chunks[i - n:i]
            if len(span) < n or any(c.key in NOT_A_NAME or not c.core.replace("-", "").isalpha() for c in span):
                continue
            if any(c.trail.strip() for c in span[:-1]):
                continue
            heard = " ".join(c.core for c in span)
            if letters(heard) in _place_index():
                options = []                    # already a name Megh knows: as said
                break
            best = _best_place(heard)
            if best and best[1] >= PLACE_MIN_SCORE and best[1] - best[2] >= PLACE_MARGIN:
                options.append((best[1], n, heard, best[0]))
        if options:
            _, n, heard, canon = max(options)
            start = i - n
            chunks = chunks[:start] + [Chunk(chunks[start].lead, canon, chunks[i - 1].trail)] + chunks[i:]
            corr.append({"heard": heard, "wrote": canon, "kind": "place"})
            i = start + 2
            continue
        i += 1
    return chunks, corr


def ensure_catalogue() -> None:
    """The scheme catalogues the spelling pass reads (loaded at app start; tools and tests load them here)."""
    from app import entity_resolver as er
    if not er._catalog:
        er.load_all()


# ── clean ───────────────────────────────────────────────────────────────────

@dataclass
class Cleaned:
    text: str
    corrections: list = field(default_factory=list)


def clean(raw: str, *, spelling: bool = True) -> Cleaned:
    """The words as the officer would have typed them, and what was changed (never raises)."""
    try:
        chunks = drop_fillers(split(raw))
        chunks = numbers.spoken(chunks)
        chunks, corr = apply_table(chunks)
        if spelling:
            ensure_catalogue()
            chunks, more = place_by_sound(chunks)
            corr += more
            chunks = name_case(chunks)
        text = join(chunks)
        if spelling and text:
            text, more = spelling_pass(text)
            corr += more
        return Cleaned(text, corr)
    except Exception:  # noqa: BLE001 — cleaning must never lose the words
        logger.warning("dictation clean failed (non-fatal; words kept as heard)", exc_info=False)
        return Cleaned(" ".join((raw or "").split()), [])
