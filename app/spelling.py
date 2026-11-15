"""
Misspelt and variant scheme / district names, read before routing (spelling-fix
brief, 2026-10-29, megh_chatbot_spelling_fix_prompt.md).

Officers type fast, on phones, by sound: "ribhoy" for Ri Bhoi, "fokus plus" and
"fokus+" for Focus Plus. The live chat before this module (tests/live_chat_spelling.py,
13/25): "womens share in mgnrega employmnt in ribhoy 2023-24" resolved no place, so
the chat's previous place was filled in and East Khasi Hills was answered (75.99%
instead of Ri Bhoi's 55.76%); "how many fokus plus benificiaries in 2022-23" named no
scheme and got a picker.

What this module does, and nothing more:

- normalise(): rewrites a misspelt SCHEME, DISTRICT or BLOCK name in the question to
  its canonical form, and a misspelt ordinary domain word from a closed list ("mony"
  -> money), so every later stage (routing, the resolver, SQL generation, retrieval,
  the scope banner) reads the canonical name; records each change for the "Showing
  results for Ri Bhoi (you typed 'ribhoy')." line. A name the existing matchers
  already read is left exactly as typed.
- unresolved_place(): a place the user named that matches nothing ("in zorbatown
  district"), with the closest real names. The chat's previous place is never filled
  in for it (c14 _same_scheme_context_year), and the data stage says it could not
  find it (c13) instead of answering for another place.

A village is rewritten only when the user wrote "village" after it and one village sounds
clearly closest (_village_at); otherwise entity_resolver.resolve_village reads the typo by
sound (village_matches) and a close race gets the "Choose a place" pick-list. A block
typo is never rewritten over a village name, or over a village that sounds as close.

Matching, best first: an exact alias -> the same sound ("ribhoy" = "ri bhoi": y/i,
k/c/q, w/u, ph/f, ee/i, oo/u, h after a consonant and doubled letters ignored) -> a
few edits on the sound (Damerau-Levenshtein, 1 for a name of 5 letters or fewer, 2 up
to 10, 3 above, same first letter, one clear winner). Acronyms (EKH, WGH) match only
exactly.

Sources, all read at run time: district names and aliases from the entity-resolver
catalogue (data/<scheme>/*_entity_resolver.yaml), the hand-kept table
data/spelling_aliases.yaml (an alias is added there, no code change).

No regex (D-046): a character scan plus rapidfuzz.
"""
from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rapidfuzz import fuzz
from rapidfuzz.distance import DamerauLevenshtein

logger = logging.getLogger(__name__)

_ALIAS_FILE = Path(__file__).resolve().parents[1] / "data" / "spelling_aliases.yaml"

# A multi-word alias word of 4+ letters may be misspelt this much (rapidfuzz ratio):
# "fokus" ~ "focus" 80, "legasy" ~ "legacy" 83, "elivate" ~ "elevate" 86.
_WORD_FUZZ = 80
# Forms this short are acronyms (EKH, WGH, SWKH): exact only. Their sound keys are
# two letters ("EGH" -> "eg") and would read "e.g." as East Garo Hills.
_ACRONYM_MAX = 4
# The shortest typed name the sound / edit stages try.
_FUZZY_MIN = 5
# A word just before a typed place, and the level words just after one.
PLACE_PREPS = frozenset(("in", "at", "from", "near", "inside", "within"))
LEVEL_WORDS = {"district": "district", "districts": "district", "block": "block", "blocks": "block",
               "village": "village", "villages": "village", "gp": "village", "panchayat": "village"}
# Never part of a place name: "in jayantia hills east" is "in" + the district.
_SPAN_STOP = PLACE_PREPS | frozenset(("of", "for", "the", "and", "to", "on", "by", "with", "under", "per", "a",
                                      "an", "or", "vs", "versus", "compare", "district", "districts", "block",
                                      "village",
                                      # "Dairy across South West Khasi Hills" read "across South West" as
                                      # South West Garo Hills (fuzzy 81) and the question became
                                      # "Dairy South West Garo Hills Khasi Hills" (CM Elevate UAT 2026-10-30)
                                      "across", "between", "among", "amongst", "over", "than"))
_DIRECTIONS = frozenset(("east", "west", "north", "south", "south west", "eastern west"))
_VOWELS = frozenset("aeiou")
_SOUND_MAP = str.maketrans({"y": "i", "c": "k", "q": "k", "w": "u"})


@dataclass(frozen=True)
class Tok:
    start: int
    end: int
    raw: str

    @property
    def low(self) -> str:
        return self.raw.lower()


@dataclass
class Correction:
    typed: str
    canonical: str
    kind: str              # "scheme" | "district" | "block" | "village" | "word" | "year" (2026-11-15: "2023 24")
    how: str               # "alias" | "sound" | "fuzzy"
    score: float = 100.0

    def to_dict(self) -> dict:
        return {"typed": self.typed, "canonical": self.canonical, "kind": self.kind, "how": self.how,
                "score": round(self.score, 1)}


@dataclass
class Normalised:
    text: str
    original: str
    corrections: list = field(default_factory=list)

    def note(self) -> "str | None":
        """"Showing results for **Ri Bhoi** (you typed 'ribhoy')." or None."""
        shown = [c for c in self.corrections if c.kind in ("scheme", "district", "block", "village")]
        if not shown:
            return None
        parts = [f"**{c.canonical}** (you typed '{c.typed}')" for c in shown]
        return "Showing results for " + " and ".join(parts) + "."


# ── tokens and keys ─────────────────────────────────────────────────────────

def tokens(text: str) -> list[Tok]:
    """Runs of letters / digits, and each "+" as a token of its own ("fokus+")."""
    out: list[Tok] = []
    i, n = 0, len(text or "")
    while i < n:
        ch = text[i]
        if ch.isalnum():
            j = i
            while j < n and text[j].isalnum():
                j += 1
            out.append(Tok(i, j, text[i:j]))
            i = j
        elif ch == "+":
            out.append(Tok(i, i + 1, "+"))
            i += 1
        else:
            i += 1
    return out


def _letters(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", text or "").lower() if c.isascii() and c.isalpha())


def sound_key(text: str) -> str:
    """The same key for names that sound the same in Khasi / Garo spellings:
    "Ri Bhoi" / "ribhoy" / "ri boi" -> "riboi", "Khasi" / "kasi" -> "kasi"."""
    s = _letters(text).replace("ph", "f").translate(_SOUND_MAP).replace("ee", "i").replace("oo", "u")
    out: list[str] = []
    for ch in s:
        if ch == "h" and out and out[-1] not in _VOWELS:
            continue
        if out and out[-1] == ch:
            continue
        out.append(ch)
    return "".join(out)


def max_edits(n: int) -> int:
    """How many edits a name of n letters may carry (brief §3.2)."""
    return 1 if n <= 5 else 2 if n <= 10 else 3


def _title(name: str) -> str:
    return " ".join(w if w.isupper() and len(w) <= 4 and w not in ("EAST", "WEST") else w.capitalize()
                    for w in str(name).replace("-", " ").split()) if str(name).isupper() else str(name)


# ── the alias table ─────────────────────────────────────────────────────────

_ALIASES: dict = {}


def reload() -> dict:
    """(Re)read data/spelling_aliases.yaml. A broken file leaves the module working
    on the catalogue alone (logged), never stops a turn."""
    global _ALIASES
    try:
        with open(_ALIAS_FILE, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("spelling aliases not loaded (%s): %s", _ALIAS_FILE, e)
        data = {}
    schemes = {}
    for canon, aliases in (data.get("schemes") or {}).items():
        schemes[str(canon)] = [[t.low if t.raw != "+" else "plus" for t in tokens(str(a))] for a in aliases or []]
    _ALIASES = {
        "schemes": schemes,
        "rename": frozenset(" ".join(t.low for t in tokens(str(a))) for a in data.get("rename") or []),
        "bare_focus": frozenset(str(w).lower() for w in data.get("bare_focus") or []),
        "words": tuple(dict.fromkeys(str(w).lower() for w in data.get("words") or [])),
        "not_typos": frozenset(str(w).lower() for w in data.get("not_typos") or []),
        "districts": {str(k): str(v) for k, v in (data.get("districts") or {}).items()},
    }
    _FORMS.clear()
    _PLACE_CACHE.clear()
    return _ALIASES


def _aliases() -> dict:
    return _ALIASES or reload()


def warm() -> None:
    """Build the gazetteer and the suggestion pool (app startup, after the catalogue
    and the village index load), so the first user turn does not pay for it. A later
    reload of either rebuilds them on the next call."""
    try:
        reload()
        for level in ("district", "block", "assembly_constituency"):
            _forms(level)
            _spellings(level)
        _suggestion_pool()
        _village_sound_index()
        normalise("warm up in ribhoy")
    except Exception:  # noqa: BLE001 — never stops startup
        logger.warning("spelling warm-up failed (non-fatal)", exc_info=True)


# ── the place gazetteer (from the resolver catalogue) ───────────────────────

_FORMS: dict = {}


_GEN: dict = {"n": 0, "cat": None, "vn": None}


def _catalog_id() -> int:
    """A number that changes when the catalogue or the village index object is
    replaced (a reload, a test stub). Every cache here is cleared then. The objects are
    held, so an id() of a freed one can never be reused to serve stale names."""
    from app import entity_resolver as er
    if er._catalog is not _GEN["cat"] or er._village_names is not _GEN["vn"]:
        _GEN.update(n=_GEN["n"] + 1, cat=er._catalog, vn=er._village_names)
        _FORMS.clear()
        _KNOWN_CACHE.clear()
        _PLACE_CACHE.clear()
    return _GEN["n"]


def _forms(level: str) -> list[tuple[str, str, str]]:
    """[(squashed form, sound key, canonical name)] for "district" or "block", from
    every scheme's catalogue (+ the alias table's districts). Rebuilt when the
    catalogue object changes (a reload)."""
    from app import entity_resolver as er
    cat = er._catalog
    if _FORMS.get((level, "id")) == _catalog_id() and _FORMS.get(level):
        return _FORMS[level]
    forms: set = set()
    canon_by_fold: dict = {}
    for dims in cat.values():
        for v in dims.get(level) or []:
            canon = _title(v.get("canonical") or "")
            if not canon:
                continue
            canon_by_fold[_letters(canon)] = canon
            for f in [v.get("canonical") or "", *(v.get("aliases") or [])]:
                sq = _letters(str(f))
                if len(sq) >= 3:
                    forms.add((sq, sound_key(str(f)), canon))
    if level == "district":
        for typed, canon in _aliases()["districts"].items():
            forms.add((_letters(typed), sound_key(typed), canon_by_fold.get(_letters(canon), canon)))
    out = sorted(forms)
    if out:
        _FORMS[level], _FORMS[(level, "id")] = out, _catalog_id()
    return out


def _district_forms() -> list[tuple[str, str, str]]:
    return _forms("district")


def _spaced(text: str) -> str:
    """Lower-case words of letters / digits, one space apart ("Ri-Bhoi" -> "ri bhoi")."""
    return " ".join(t.low for t in tokens(unicodedata.normalize("NFKC", text or "")) if t.raw != "+")


def _spellings(level: str) -> frozenset:
    """Every catalogue name / alias of the level, _spaced."""
    from app import entity_resolver as er
    key = (level, "spell")
    if _FORMS.get((key, "id")) == _catalog_id() and _FORMS.get(key):
        return _FORMS[key]
    out = frozenset(_spaced(str(f)) for dims in er._catalog.values() for v in dims.get(level) or []
                    for f in [v.get("canonical") or "", *(v.get("aliases") or [])]) - {""}
    if out:
        _FORMS[key], _FORMS[(key, "id")] = out, _catalog_id()
    return out


def _resolver_reads(typed: str, canon: str, level: str) -> bool:
    """Is `typed` a catalogue spelling the resolver already reads as `canon`? Then it
    is left exactly as typed ("EKH", "Ri-Bhoi", "West Garo"). A catalogue form the
    scan does not read ("EastGaroHills" typed as one word) is still rewritten."""
    if _spaced(typed) not in _spellings(level):
        return False
    if level != "district":
        return True           # an exact block name / alias: the resolver's first stage
    from app import entity_resolver as er
    try:
        scheme = next(iter(er._catalog))
        return [d.upper() for d in er.scan_districts(typed, scheme)] == [canon.upper()]
    except Exception:  # noqa: BLE001
        return False


def districts() -> list[str]:
    return sorted({c for _sq, _k, c in _district_forms()})


# ── matching ────────────────────────────────────────────────────────────────

def _pipeline():
    from app import pipeline
    return pipeline


_KNOWN_CACHE: dict = {}


def _known_word(word: str) -> bool:
    """An ordinary vocabulary word (never rewritten into a place). Cached per catalogue."""
    key = (word.lower(), _catalog_id())
    if key in _KNOWN_CACHE:
        return _KNOWN_CACHE[key]
    try:
        p = _pipeline()
        # The few-shot term map knows the data's own spellings: the stored Focus Plus
        # tranche_label is "Tranch 1". Without it the rephrased "in Tranch 1" was a
        # place "Tranch" that matched nothing -> "I couldn't find a place called
        # “Tranch”" (sheet FOCUS-007 / 018 / 028, 2026-10-30).
        from app.annotations import _FEWSHOT_SYNONYMS
        out = bool((p._is_known_word(word) or word.lower() in _FEWSHOT_SYNONYMS)
                   and word.lower() not in p._place_words())
    except Exception:  # noqa: BLE001 — pipeline not importable: treat as unknown
        return False
    if len(_KNOWN_CACHE) > 20000:
        _KNOWN_CACHE.clear()
    _KNOWN_CACHE[key] = out
    return out


def _named_by_existing_matcher(scheme: str, text: str) -> bool:
    try:
        return bool(_pipeline()._SCHEME_NAME_MATCHER[scheme].search(text))
    except Exception:  # noqa: BLE001
        return False


def _word_match(typed: str, want: str) -> "float | None":
    """How well one typed word matches one alias word (None = no match)."""
    if typed == want:
        return 100.0
    if len(want) < 4 or len(typed) < 4 or typed[0] != want[0]:
        return None
    r = fuzz.ratio(typed, want)
    return r if r >= _WORD_FUZZ else None


def _scheme_at(toks: list[Tok], i: int) -> "tuple[int, str, float] | None":
    """(end token index, scheme, score) of the longest scheme alias starting at
    token i, or None."""
    best = None
    for canon, phrases in _aliases()["schemes"].items():
        for words in phrases:
            k = len(words)
            if not words or i + k > len(toks):
                continue
            scores = []
            for t, w in zip(toks[i:i + k], words):
                low = "plus" if t.raw == "+" else t.low
                s = _word_match(low, w)
                if s is None:
                    break
                scores.append(s)
            else:
                score = sum(scores) / len(scores)
                if k == 1 and score < 100 and fuzz.ratio(toks[i].low, words[0]) < 85:
                    continue
                cand = (i + k, canon, score)
                if best is None or (cand[0], cand[2]) > (best[0], best[2]):
                    best = cand
    return best


def _place_at(toks: list[Tok], i: int, level: str, *, cue: bool) -> "tuple[int, str, str, float] | None":
    """(end token index, name, how, score) of the best `level` ("district" / "block")
    name starting at token i, or None. `cue`: a place word ("in", "district") sits
    next to it."""
    forms = _forms(level)
    found = []
    for j in range(i + 1, min(i + (5 if level == "district" else 3), len(toks)) + 1):
        span = toks[i:j]
        if not all(t.raw.isalpha() and t.low not in _SPAN_STOP for t in span):
            break
        words = [t.low for t in span]
        orders = [words]
        # "khasi hills east", "garo west": the direction written last
        for k in (2, 1):
            if level == "district" and len(words) > k and " ".join(words[-k:]) in _DIRECTIONS:
                orders.append(words[-k:] + words[:-k])
        for ws in orders:
            sq = "".join(ws)
            key = sound_key(sq)
            for fsq, fkey, canon in forms:
                if sq == fsq:
                    found.append((0, -(j - i), 0, 0, canon, j, "alias"))
                    continue
                if len(fsq) <= _ACRONYM_MAX or len(sq) < _FUZZY_MIN or not key or not fkey:
                    continue
                if key == fkey:
                    found.append((0, -(j - i), 1, 0, canon, j, "sound"))
                    continue
                lim = max_edits(len(fkey))
                if key[0] != fkey[0] or abs(len(key) - len(fkey)) > lim:
                    continue
                d = DamerauLevenshtein.distance(key, fkey, score_cutoff=lim)
                if d <= lim:
                    found.append((1, d, 2, -(j - i), canon, j, "fuzzy"))
    if not found:
        return None
    # An exact or same-sound reading first, the longest such span ("south west khasi
    # hils" is the whole district, not the alias "South West Khasi" plus a stray
    # "hils"); otherwise the fewest edits, then the longest span.
    found.sort()
    best = found[0]
    canon, end, how = best[4], best[5], best[6]
    tier, d = (2, best[1]) if best[0] == 1 else (best[2], 0)
    rivals = {f[4] for f in found if f[:2] == best[:2] and f[4] != canon}
    if rivals:
        return None                       # two places equally close: not a clear winner
    if tier >= 1 and end - i == 1:
        if _known_word(toks[i].raw):
            return None
        if tier == 2 and not cue:
            return None
    # "that's wrong, I asked for completed houses" became "that'Shillong, …" (fuzzy 66.7 on
    # the span "s wrong"), so the complaint was no longer read as one and its apology was
    # lost (harness META_correction_keeps_scope, live 2026-10-29). A sound / fuzzy reading
    # never starts on a one-letter piece of a contraction, nor covers only ordinary words.
    # Nor does it start on an ordinary word: "applications across South West Garo Hills"
    # read "across South West" as South West Garo Hills (fuzzy 81.2) and wrote "…
    # South West Garo Hills Garo Hills and …", which then asked "which district is
    # 'garo hills'?" (CM Elevate Legacy sheet TC-35, 2026-10-30). The exact reading one
    # word later is the place.
    if tier >= 1 and end - i > 1:
        span = toks[i:end]
        if len(span[0].raw) == 1 or _known_word(span[0].raw) or all(_known_word(t.raw) for t in span):
            return None
    score = 100.0 if tier < 2 else round(100.0 * (1 - d / max(1, len(sound_key(canon)))), 1)
    return end, canon, how, score


def _inside_village_name(toks: list[Tok], i: int, end: int) -> bool:
    """The span toks[i:end] is part of a LONGER phrase in the text that is exactly a
    village name. MGNREGA UAT 2026-10-30 (KI-640): "households … in RONGARE ADING" —
    "RONGARE" alone sounds like the Rongara block, the village index knows only the
    two-word name, so the block guard below did not fire, the text became "Rongara
    ADING" and the officer was asked block / constituency / village with the real
    village not offered. A village is never rewritten in the text (D-093)."""
    from app import entity_resolver as er
    for a in range(max(0, i - 3), i + 1):
        for b in range(end, min(len(toks), end + 3) + 1):
            if b - a <= end - i:
                continue
            span = toks[a:b]
            if not all(t.raw.isalpha() or t.raw in "()-." for t in span):
                continue
            if er.is_village_name(" ".join(t.raw for t in span)):
                return True
    return False


def _district_at(toks: list[Tok], i: int, *, cue: bool) -> "tuple[int, str, str, float] | None":
    hit = _place_at(toks, i, "district", cue=cue)
    if hit is not None and hit[2] != "alias" and _inside_village_name(toks, i, hit[0]):
        return None
    return hit


def _block_at(toks: list[Tok], i: int, *, cue: bool) -> "tuple[int, str, str, float] | None":
    """A block name typed close to the catalogue's ("mawsinram" -> Mawsynram,
    "umlyng" -> Umling): never over a village name or a village spelt closer."""
    hit = _place_at(toks, i, "block", cue=cue)
    if hit is None or hit[2] == "alias":
        return hit
    if _inside_village_name(toks, i, hit[0]):
        return None
    # A few edits away, of any length, only beside a place word: "we are a self help
    # group" read "self help" as the block Selsella (2 edits, no cue).
    after = toks[hit[0]].low if hit[0] < len(toks) else ""
    if hit[2] == "fuzzy" and not (cue or after in LEVEL_WORDS):
        return None
    from app import entity_resolver as er
    typed = " ".join(t.raw for t in toks[i:hit[0]])
    if er.is_village_name(typed):
        return None
    try:
        v = er.village_fuzzy(typed)
    except Exception:  # noqa: BLE001
        v = None
    if v is not None and _letters(v[0]) != _letters(hit[1]):
        return None
    # ... nor over a village that SOUNDS at least as close ("darongre" is one edit
    # from the village DARONGGRE, more from the block Dadenggiri).
    near = village_matches(typed, limit=1)
    if near and _letters(near[0][0]) != _letters(hit[1]) \
            and near[0][1] <= DamerauLevenshtein.distance(sound_key(typed), sound_key(hit[1])):
        return None
    return hit


def scheme_scores(question: str) -> dict:
    """{scheme: 0-100}: how close the question's words come to each scheme's aliases
    (the best alias, its words matched in order anywhere in the question). Orders the
    "which scheme?" picker, best guess first (brief §3.4)."""
    toks = [("plus" if t.raw == "+" else t.low) for t in tokens(question or "")]
    out: dict = {}
    for canon, phrases in _aliases()["schemes"].items():
        best = 0.0
        for words in phrases:
            for i in range(len(toks) - len(words) + 1):
                s = [fuzz.ratio(toks[i + k], w) for k, w in enumerate(words)]
                if len(words) == 1 and s[0] < 85:
                    continue              # one short word: "many" is 75 from "pmay"
                best = max(best, sum(s) / len(s))
        out[canon] = round(best, 1)
    return out


# Real English words one edit from a vocabulary word, never typos of it: "bank account numbers"
# became "bank amount numbers" and slipped past the personal-data guardrail; "Kenches Trace"
# became "Kenches tranche" (CM Elevate UAT 2026-10-30, N1 / N3).
_NOT_A_TYPO = frozenset("account accounts trace traces".split())


def _domain_word(word: str) -> "str | None":
    """The closed-vocabulary word a typo stands for ("mony" -> "money"), or None.
    Never a known word, a place or a village name."""
    w = word.lower()
    vocab = _aliases()["words"]
    if (len(w) < 3 or not word.isalpha() or w in vocab or w in _NOT_A_TYPO
            or w in _aliases().get("not_typos", ())):
        return None
    hits = []
    for v in vocab:
        lim = 1 if len(v) <= 5 else max_edits(len(v))
        if v[0] != w[0] or abs(len(v) - len(w)) > lim:
            continue
        if (v.startswith(w) or w.startswith(v)) and not (v == w + "e" and len(w) >= 6):
            # "loans", "employ": another form, not a typo. 2026-11-15: a long word missing only its final "e"
            # ("expenditur") is a typo; no English word is formed by dropping a final "e" (gold bank W2-PF-MGX)
            return None
        d = DamerauLevenshtein.distance(w, v, score_cutoff=lim)
        if d <= lim:
            hits.append((d, v))
    if not hits:
        return None
    hits.sort()
    if len(hits) > 1 and hits[1][0] == hits[0][0]:
        return None                      # two words equally close: leave it
    if _is_place(word) or _inflection(w, hits[0][1]):
        return None                      # "employs" is not a typo of "employed"
    # A word the pipeline only "knows" because a measure family reads it by its start ("disbursd" is money:
    # "disburs…") is still a typo one edit from a vocabulary word: left as typed, the metric catalogue
    # refused it as a word it does not know ("focus pluss totel amount disbursd", no-model bank 2026-11-14).
    # A real word, or another form of the vocabulary word ("sanctions" / "sanctioned"), stays as typed.
    if _known_word(word) and not (hits[0][0] == 1 and not _plain_word(w) and not _inflection(w, hits[0][1])):
        return None
    return hits[0][1]


# Endings that make another form of the same word, not a typo of it ("sanctions" / "sanctioned").
_FORM_ENDINGS = frozenset(("", "s", "es", "ed", "ing", "ment", "ments", "er", "ers", "ion", "ions", "al", "ly"))


def _inflection(a: str, b: str) -> bool:
    """Are `a` and `b` two forms of one stem (each ending, after their common start, in a word ending)?"""
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n >= 4 and a[n:] in _FORM_ENDINGS and b[n:] in _FORM_ENDINGS


def _plain_word(w: str) -> bool:
    """In one of the pipeline's word lists outright (not read by a measure family's prefix or a fuzzy match)."""
    try:
        p = _pipeline()
        from app.annotations import _FEWSHOT_SYNONYMS
        return (w in p._REPHRASE_VOCAB or w in p._COMMON_WORDS or w in p._HINGLISH_GLOSS
                or w in _FEWSHOT_SYNONYMS or w in p._place_words())
    except Exception:  # noqa: BLE001 — pipeline not importable: treat it as a word (never correct it)
        return True


def _span_text(text: str, toks: list[Tok], i: int, j: int) -> str:
    return text[toks[i].start:toks[j - 1].end]


def _same_name(a: str, b: str) -> bool:
    return _letters(a) == _letters(b)


def normalise(question: str) -> Normalised:
    """The question with misspelt scheme / district names written canonically, and
    what changed. Never raises: any failure returns the question unchanged."""
    try:
        return _normalise(question or "")
    except Exception:  # noqa: BLE001 — spelling help must never break a turn
        logger.warning("spelling normalise failed (non-fatal)", exc_info=True)
        return Normalised(question or "", question or "")


def _place_hit(toks: list[Tok], i: int, prev: str) -> "tuple[str, tuple] | None":
    """("district" | "block", hit) for a place name starting at token i. The level
    word written after it rules ("Mawryngkneng block", "jakrm village": no district
    / block rewrite over a village)."""
    def level_after(end: int) -> str:
        if end >= len(toks):
            return ""
        # "William Nagar constituency" is the assembly constituency's own spelling; it
        # was rewritten to the block "Williamnagar" and then asked "block or
        # constituency?" (CM Elevate Legacy sheet TC-31, 2026-10-30).
        if toks[end].low in ("constituency", "constituencies"):
            return "assembly_constituency"
        return LEVEL_WORDS.get(toks[end].low, "")

    nxt = toks[i + 1].low if i + 1 < len(toks) else ""
    cue = prev in PLACE_PREPS or nxt in LEVEL_WORDS
    ac = _place_at(toks, i, "assembly_constituency", cue=True)
    if ac is not None and level_after(ac[0]) == "assembly_constituency":
        return "assembly_constituency", ac
    # The catalogue also holds "<name> constituency" forms, so the reading may swallow
    # the level word: "Rambrai jyrngam constituency" was not taken at "Rambrai", and the
    # next word alone read "jyrngam" -> Jirang (fuzzy), answering Jirang's 417 for
    # Rambrai Jyrngam's 694 (all-constituencies run 2026-10-30). The span then ends
    # before the level word, which stays in the text.
    if ac is not None and ac[0] - i > 1 and level_after(ac[0] - 1) == "assembly_constituency":
        return "assembly_constituency", (ac[0] - 1, *ac[1:])
    d = _district_at(toks, i, cue=cue)
    if d is not None and level_after(d[0]) in ("", "district") and not _starts_a_village(toks, i, d[0]) \
            and not _starts_a_block(toks, i, d[0]):
        return "district", d
    b = _block_at(toks, i, cue=cue or bool(level_after(i + 1)))
    if b is not None and level_after(b[0]) in ("", "block") and not _starts_a_village(toks, i, b[0]) \
            and not _starts_a_block(toks, i, b[0]):
        return "block", b
    return None


def _starts_a_block(toks: list[Tok], i: int, end: int) -> bool:
    """The tokens from i begin a LONGER span that is exactly a block name of some
    scheme's catalogue: "William Nagar-Municipal Board block" (the LGD block, CM
    Elevate 149 applications) was rewritten to Focus Plus's spelling "Williamnagar"
    on its first two words and every scheme then answered 0 for the block
    (Cross Scheme sheet re-run 2026-10-30, CROSS-9). An exact block name is never
    rewritten, like an exact village name (_starts_a_village)."""
    spell = _spellings("block")
    for k in range(end + 1, min(len(toks), i + 6) + 1):
        if not all(t.raw.replace("-", "").replace("'", "").isalnum() for t in toks[i:k]):
            break
        if _spaced(" ".join(t.raw for t in toks[i:k])) in spell:
            return True
    return False


def _starts_a_village(toks: list[Tok], i: int, end: int) -> bool:
    """The tokens from i up to `end` (the place hit) begin a longer span that is EXACTLY a
    village name: "RONGARE ADING" (village 274191) was rewritten to the block "Rongara ADING"
    (fuzzy 85.7 on its first word) and asked Rongara block / constituency / village instead
    of answering the village (PMAY-G all-villages run 2026-10-30). _block_at checks only the
    matched tokens themselves; a multi-word village is checked here."""
    return _village_span_end(toks, i, end) is not None


def _village_span_end(toks: list[Tok], i: int, end: int) -> "int | None":
    """The end (exclusive token index) of the LONGEST span starting at i, longer than `end`,
    that is exactly a village name; None when there is none. The whole span is what the
    normaliser must step over: "hawai bhoi" (279381) kept its first word but the loop moved
    one token, and "bhoi" alone was then read as the district alias of Ri Bhoi ("Showing
    results for Ri Bhoi (you typed 'bhoi')", all-villages run 2026-10-30, KI-631)."""
    found = None
    # ward villages are "William Nagar (Mb) - Ward No.1", "Mendipathar - Ward No.10":
    # digits and the stripped punctuation are part of the name (cross-scheme village
    # run 2026-10-30, KI-646), so the span is compared on its letters and digits
    for k in range(end + 1, min(len(toks), i + 8) + 1):
        if not all(t.raw.isalnum() for t in toks[i:k]):
            break
        if _exact_village(" ".join(t.raw for t in toks[i:k])):
            found = k
    return found


_FULL_NAMES: dict = {}


def _fold_name(text: str) -> str:
    return "".join(ch for ch in str(text).upper() if ch.isalnum())


def _exact_village(text: str) -> bool:
    """`text` is exactly a village name: by the folded index, or by the full stored name.
    The index folds the word VILLAGE away and leaves out one-word generic names, so
    "CENTRE VILLAGE" (folded "CENTRE", a denied solo word) is not in it; the code -> name
    map holds every stored name as written. A name with punctuation ("William Nagar
    (Mb) - Ward No.1") is matched on its letters and digits."""
    from app import entity_resolver as er
    if er.is_village_name(text):
        return True
    gen = _catalog_id()
    if _FULL_NAMES.get("gen") != gen:
        names = [str(n) for n in (getattr(er, "_village_code_names", None) or {}).values()]
        _FULL_NAMES.update(gen=gen, names=frozenset(" ".join(n.upper().split()) for n in names),
                           folded=frozenset(_fold_name(n) for n in names) - {""})
    return " ".join(str(text).upper().split()) in _FULL_NAMES["names"] or _fold_name(text) in _FULL_NAMES["folded"]


def _village_at(toks: list[Tok], i: int) -> "tuple[int, str, int] | None":
    """(end token index, village name, edits) for a misspelt village the user marked
    with the word "village" ("mawryngkning village"), when ONE village sounds clearly
    closest. The text then carries the real name, as for a district: the resolver
    read the typo by sound, but the SQL model, given "lgd_village_name =
    'mawryngkning'", filtered a view that has no village_code after the guard's
    rewrite, and three repairs later the turn fell back to the documents (live T9,
    2026-10-29). Several close names: left as typed, for the resolver's pick-list."""
    from app import entity_resolver as er
    for k in (3, 2, 1):
        j = i + k
        if j >= len(toks) or toks[j].low not in ("village", "villages"):
            continue
        span = toks[i:j]
        if not all(t.raw.isalpha() and t.low not in _SPAN_STOP for t in span):
            return None
        name = " ".join(t.raw for t in span)
        if er.is_village_name(name) or (k == 1 and _known_word(name)):
            return None
        # a stored name that itself ends in "village" ("CENTRE VILLAGE", Jirang 277685, was corrected
        # to Kentra by sound: UAT 2026-10-30 N4, and the PMAY-G all-villages run, KI-631): written
        # exactly, left alone — the full-name index (Main) and the stored-name check (UAT) both apply
        if _exact_village(name + " " + toks[j].raw) or er.is_stored_village_name(name):
            return None
        near = village_matches(name, limit=2)
        if near and (len(near) == 1 or near[1][1] > near[0][1]):
            return j, _title(near[0][0]), near[0][1]
        return None
    return None


def _exact_village_end(question: str, toks: list[Tok], i: int, place_end: int) -> "int | None":
    """The end token of an exact village name or alias that starts at token i and runs past
    `place_end` (the district / block reading's end), else None."""
    from app import entity_resolver as er
    best = None
    for j in range(place_end + 1, min(i + 9, len(toks)) + 1):
        if er.is_village_name(question[toks[i].start:toks[j - 1].end]):
            best = j
    return best


def _spaced_fy(question: str, toks: list[Tok], i: int) -> "str | None":
    """"2023-24" for the tokens "2023" "24" (or "2023" "2024") at i, written with only spaces between them and
    naming consecutive years; else None."""
    if i + 1 >= len(toks):
        return None
    a, b = toks[i].raw, toks[i + 1].raw
    if not (len(a) == 4 and a.isdecimal() and a.startswith("20")):
        return None
    if not ((len(b) == 2 or (len(b) == 4 and b.startswith("20"))) and b.isdecimal()):
        return None
    gap = question[toks[i].end:toks[i + 1].start]
    if not gap or gap.strip() or int(b[-2:]) != (int(a[-2:]) + 1) % 100:
        return None
    if len(b) == 4 and int(b) != int(a) + 1:
        return None
    return f"{a}-{b[-2:]}"


# 2026-11-16 (voice audit): "MGNREGA person-days in East and West Khasi Hills" was answered for West Khasi Hills
# alone, typed and spoken alike (the scan read the one full name; "East" was dropped without a word). Two or more
# directions that share one district stem name EACH of those districts: "East and West Khasi Hills" = East Khasi Hills
# and West Khasi Hills, "South West, West and East Garo Hills" likewise. Written out in full (and shown in the
# "Showing results for …" line) only when every one is a real district; otherwise the words stay as typed.
_ELIDED_DIRS = (("south", "west"), ("eastern", "west"), ("east",), ("west",), ("north",), ("south",))
_ELIDED_STEMS = ("khasi", "garo", "jaintia")


def _elided_dir_at(toks: list[Tok], i: int) -> "tuple[str, int] | None":
    for words in _ELIDED_DIRS:
        if i + len(words) <= len(toks) and tuple(t.low for t in toks[i:i + len(words)]) == words:
            return " ".join(w.title() for w in words), i + len(words)
    return None


def _is_district_name(name: str) -> bool:
    try:
        from app.entity_resolver import named_places
        return named_places(name).get(name.upper()) == "district"
    except Exception:  # noqa: BLE001 — no catalogue: not expanded
        return False


def _elided_districts(question: str, toks: list[Tok], i: int) -> "tuple[int, str] | None":
    """(the token index after the phrase, the districts written out) for "East and West Khasi Hills" at token i."""
    dirs: list[str] = []
    j = i
    while True:
        hit = _elided_dir_at(toks, j)
        if hit is None:
            return None
        dirs.append(hit[0])
        j = hit[1]
        if j >= len(toks):
            return None
        if toks[j].low in _ELIDED_STEMS:
            break
        gap = question[toks[j - 1].end:toks[j].start]
        if toks[j].low == "and":
            gap2 = question[toks[j].end:toks[j + 1].start] if j + 1 < len(toks) else "x"
            if (gap.strip() not in ("", ",")) or gap2.strip():
                return None
            j += 1
        elif gap.strip() == "," and _elided_dir_at(toks, j) is not None:
            pass                                            # "East, West and …"
        else:
            return None
    if len(dirs) < 2:
        return None
    stem = toks[j].low
    end = j + 1
    if end < len(toks) and toks[end].low in ("hills", "hill"):
        end += 1
    names = [f"{d} {stem.title()} Hills" for d in dirs]
    if len(set(names)) != len(names) or not all(_is_district_name(n) for n in names):
        return None
    return end, ", ".join(names[:-1]) + " and " + names[-1]


def _normalise(question: str) -> Normalised:
    toks = tokens(question)
    out: list[str] = []
    corrections: list[Correction] = []
    last = 0
    i = 0
    aliases = _aliases()
    while i < len(toks):
        t = toks[i]
        prev = toks[i - 1].low if i > 0 else ""
        el = _elided_districts(question, toks, i) if t.low in ("east", "west", "north", "south", "eastern") else None
        if el is not None:
            end, written = el
            out += [question[last:t.start], written]
            last = toks[end - 1].end
            corrections.append(Correction(_span_text(question, toks, i, end), written, "district", "elided"))
            i = end
            continue
        fy = _spaced_fy(question, toks, i)
        if fy is not None:
            # 2026-11-15: "2023 24" (the dash dropped, gold bank PF-MG-misspelt) is FY 2023-24 when the two numbers
            # are consecutive years; written with its dash so every year reader reads it
            out += [question[last:t.start], fy]
            last = toks[i + 1].end
            corrections.append(Correction(_span_text(question, toks, i, i + 2), fy, "year", "spaced"))
            i += 2
            continue
        hit = _scheme_at(toks, i)
        if hit is not None:
            end, canon, score = hit
            typed = _span_text(question, toks, i, end)
            renamed = " ".join(tk.low for tk in toks[i:end]) in aliases["rename"]
            if (renamed or not _named_by_existing_matcher(canon, typed)) and not _same_name(typed, canon):
                out += [question[last:t.start], canon]
                last = toks[end - 1].end
                corrections.append(Correction(typed, canon, "scheme", "alias" if score == 100 else "fuzzy", score))
            i = end
            continue
        if t.raw.isalpha():
            wend = _exact_village_end(question, toks, i, i + 1)
            if wend is not None and any(not tk.raw.isalpha() for tk in toks[i:wend]):
                # an exact ward / village name with a number in it is left whole: "Kenches Trace - Ward
                # No.23" became "Kenches tranche - Ward No.23" (CM Elevate UAT 2026-10-30, N1)
                i = wend
                continue
            phit = _place_hit(toks, i, prev)
            vend = None
            if phit is not None:
                # an exact village / ward name that starts here OR up to 6 tokens earlier and covers
                # this span: "Ladthalaboh East - Ward No.1" was read as East Garo Hills (UAT 2026-10-30, N1)
                for j0 in range(max(0, i - 6), i + 1):
                    # a name that began earlier may END on the corrected word itself:
                    # "POMLAKRAI RNGI SHYLLONG" (village 278328) lost its last word to Shillong
                    vend = _exact_village_end(question, toks, j0, phit[1][0] - (1 if j0 < i else 0))
                    if vend is not None:
                        break
            if vend is not None:
                # "William Nagar (MB) - Ward No.8" is a village written exactly; the block alias
                # "William Nagar (MB" was rewritten to "Williamnagar) - Ward No.8" and the ward was
                # lost (CM Elevate UAT 2026-10-30, OFF-003 wards). Left whole.
                i = vend
                continue
            if phit is not None:
                level, (end, canon, how, score) = phit
                typed = _span_text(question, toks, i, end)
                # What the resolver already reads as written ("EKH", "Ri-Bhoi",
                # "West Garo", "Mawkyrwat") is left as typed. Anything else that reads
                # as a district / block (a sound / edit match, "westgaro hills",
                # "eastgarohills", "mawsinram", a table alias) is written canonically.
                if not _resolver_reads(typed, canon, level):
                    out += [question[last:t.start], canon]
                    last = toks[end - 1].end
                    corrections.append(Correction(typed, canon, level, how, score))
                i = end
                continue
            vhit = _village_at(toks, i)
            if vhit is not None:
                end, canon, d = vhit
                typed = _span_text(question, toks, i, end)
                out += [question[last:t.start], canon]
                last = toks[end - 1].end
                corrections.append(Correction(typed, canon, "village", "sound" if d == 0 else "fuzzy"))
                i = end
                continue
            vend = _village_span_end(toks, i, i + 1)
            if vend is not None:
                # no word of an exact multi-word village name is a typo of a scheme, domain
                # word, district or block: "Pyndeng Shallang" (276876) became "pending Shallang"
                # and was answered as the Shallang block; "hawai bhoi" (279381) lost its second
                # word to the Ri Bhoi alias (all-villages run 2026-10-30, KI-631)
                i = vend
                continue
            if t.low in aliases["bare_focus"] or (
                    t.low != "focus" and len(t.low) >= 5 and t.low[0] == "f" and fuzz.ratio(t.low, "focus") >= 80
                    and not _known_word(t.raw)):
                out += [question[last:t.start], "Focus"]
                last = t.end
                corrections.append(Correction(t.raw, "Focus", "word", "fuzzy", fuzz.ratio(t.low, "focus")))
            elif (fixed := _domain_word(t.raw)) is not None:
                out += [question[last:t.start], fixed]
                last = t.end
                corrections.append(Correction(t.raw, fixed, "word", "fuzzy"))
        i += 1
    out.append(question[last:])
    text = "".join(out)
    if corrections:
        logger.info("spelling: %r -> %r %s", question, text, [c.to_dict() for c in corrections])
    return Normalised(text, question, corrections)


# ── a place named that matches nothing ──────────────────────────────────────

_PLACE_CACHE: dict = {}


def _is_place(name: str) -> bool:
    """Does any catalogue, the village index or this module's reading know `name`?
    (Then the resolver reads it; it is not an unresolved place.) Cached per catalogue
    and village index."""
    key = (name.lower(), _catalog_id())
    if key not in _PLACE_CACHE:
        if len(_PLACE_CACHE) > 20000:
            _PLACE_CACHE.clear()
        _PLACE_CACHE[key] = _is_place_uncached(name)
    return _PLACE_CACHE[key]


def _is_place_uncached(name: str) -> bool:
    from app import entity_resolver as er
    try:
        if er.named_places(name):
            return True
    except Exception:  # noqa: BLE001
        pass
    if er.is_village_name(name):
        return True
    try:
        if er.village_fuzzy(name):
            return True
    except Exception:  # noqa: BLE001
        pass
    # This module's own reading of every catalogue level (exact, same sound, a few
    # edits). Not entity_resolver.resolve_dimension: it folds the whole catalogue on
    # every call (~130 ms), twelve calls per name blew the 150 ms budget (brief §4 H).
    toks = tokens(name)
    return bool(toks) and any(_place_at(toks, 0, level, cue=True) is not None
                              for level in ("district", "block", "assembly_constituency"))


def _out_of_area(name: str) -> bool:
    try:
        from app import edge
        low = name.lower()
        return bool(edge._OUT_OF_AREA.search(low) or edge._FOREIGN_PLACE.search(low))
    except Exception:  # noqa: BLE001
        return False


def suggestions(name: str, level: "str | None" = None, limit: int = 3) -> list[dict]:
    """The closest real places to a typed name, best first:
    [{"name", "level", "parent", "score"}]. `level` narrows the search when the user
    wrote "district" / "block" / "village"."""
    from app import entity_resolver as er
    from rapidfuzz import process
    key = sound_key(name)
    if len(key) < 3:
        return []
    pool: dict = {}
    for lvl, entries in _suggestion_pool().items():
        if level not in (None, lvl):
            continue
        for _k, s, idx in process.extract(key, [e[3] for e in entries], scorer=fuzz.ratio,
                                          limit=limit, processor=None):
            n, parent = entries[idx][1], entries[idx][2]
            pool[(n.upper(), lvl)] = ({"name": n, "level": lvl, "parent": parent}, s)
    ranked = sorted(pool.values(), key=lambda x: -x[1])[:limit]
    return [{**d, "score": round(float(s), 1)} for d, s in ranked]


def _suggestion_pool() -> dict:
    """{level: [(level, display name, parent, sound key)]} for every district, block
    and village, built once per catalogue / village index."""
    from app import entity_resolver as er
    cid = _catalog_id()
    if _FORMS.get(("pool", "id")) == cid:
        return _FORMS["pool"]
    pool: dict = {"district": [(  "district", d, "", sound_key(d)) for d in districts()]}
    seen: set = set()
    blocks = []
    for dims in er._catalog.values():
        for v in dims.get("block") or []:
            c = v.get("canonical") or ""
            if c and c.upper() not in seen:
                seen.add(c.upper())
                parent = v.get("district") or v.get("parent_district") or ""
                blocks.append(("block", _title(c), _title(parent) if parent else "", sound_key(c)))
    pool["block"] = blocks
    if er.village_index_loaded():
        villages = []
        for real in er._village_keys():
            places = er.village_places(real)
            parent = f"{_title(places[0][1])} block, {_title(places[0][2])}" if places else ""
            villages.append(("village", _title(real), parent, sound_key(real)))
        pool["village"] = villages
    _FORMS["pool"], _FORMS[("pool", "id")] = pool, cid
    return pool


def _village_sound_index() -> list:
    """[(sound key, folded village name)] for the village index, built once per index."""
    from app import entity_resolver as er
    cid = _catalog_id()
    if _FORMS.get(("vsound", "id")) == cid:
        return _FORMS["vsound"]
    out = [(sound_key(k), k) for k in er._village_keys()] if er.village_index_loaded() else []
    _FORMS["vsound"], _FORMS[("vsound", "id")] = out, cid
    return out


def village_matches(text: str, limit: int = 5) -> list[tuple[str, int]]:
    """[(folded village name, edits)] of the villages whose name SOUNDS closest to a
    typed one (sound key, Damerau-Levenshtein, 1 / 2 / 3 edits by length, same first
    letter), best first. entity_resolver.resolve_village reads it before its trigram
    search, which missed transposed letters and Khasi / Garo sound swaps: "darongre"
    never listed DARONGGRE, "darangigttim" resolved to another village (live
    2026-10-29, 77/126 typos read)."""
    key = sound_key(text)
    if len(key) < _FUZZY_MIN:
        return []
    hits = []
    for vkey, name in _village_sound_index():
        if not vkey or vkey[0] != key[0]:
            continue
        lim = max_edits(len(vkey))
        if abs(len(vkey) - len(key)) > lim:
            continue
        d = DamerauLevenshtein.distance(key, vkey, score_cutoff=lim)
        if d <= lim:
            hits.append((d, name))
    # Equal sound distance: the closer plain spelling first ("darnggre" is one sound
    # edit from several villages; DARONGGRE is the one spelt nearest), never A-Z.
    typed = _letters(text)
    # A short typed name (up to 6 letters) is read by sound only when its PLAIN spelling is
    # one edit from the village: "asgard" (an invented place) sounded like ASKAPARA, two
    # letters away, and was answered 0 for that village (CM Elevate UAT 2026-10-30, C14-INV-14).
    if len(typed) <= 6:
        hits = [h for h in hits if DamerauLevenshtein.distance(typed, _letters(h[1]), score_cutoff=1) <= 1]
    hits.sort(key=lambda h: (h[0], -fuzz.ratio(typed, _letters(h[1])), h[1]))
    return [(n, d) for d, n in hits[:limit]]


# Words that follow "in" / "at" / "from" and are not places, which the rephraser's
# vocabulary may lack ("in detail", "in hindi", "in rupees", "in january").
_NOT_A_PLACE = frozenset("""
detail details brief short general particular words word english hindi khasi garo bengali assamese
rupees rupee lakh lakhs crore crores percentage percentages percent numbers figures figure digits
numerals table tables tabular chart charts graph graphs summary order terms future past comparison
addition case progress kind cash time favour favor respect line rural urban hilly process advance
aggregate full list points bullet bullets simple plain format writing paragraph sentence sentences
total totals sum overall depth short brief points tranche tranches installment instalment batch
batches phase phases stage stages round rounds part parts cycle cycles quarter quarters
level levels hold
january february march april may june july august september october november december
jan feb mar apr jun jul aug sep sept oct nov dec
""".split())


def unresolved_place(question: str) -> "dict | None":
    """{"typed", "level", "suggestions"} for a place the question names that matches
    nothing ("in zorbatown district", "in zorbaville", "in ribhoy" when no district
    reads it), else None.

    A name is a run of up to three words after in / at / from that are neither
    vocabulary ("in total", "in 2023-24", "in mgnrega") nor an ordinary non-place
    word (_NOT_A_PLACE: "in detail", "in hindi"). A place outside Meghalaya
    ("Guwahati") is the edge layer's, not this. `suggestions` are the closest real
    places, best first."""
    try:
        return _unresolved_place(question or "")
    except Exception:  # noqa: BLE001
        logger.warning("spelling unresolved_place failed (non-fatal)", exc_info=True)
        return None


def _unresolved_place(question: str) -> "dict | None":
    toks = tokens(question)
    for i, t in enumerate(toks):
        if t.low not in PLACE_PREPS:
            continue
        j = i + 1
        while j < len(toks) and j - i <= 3 and toks[j].raw.isalpha() and len(toks[j].raw) >= 3 \
                and toks[j].low not in LEVEL_WORDS and toks[j].low not in PLACE_PREPS \
                and toks[j].low not in _NOT_A_PLACE and not _known_word(toks[j].raw):
            j += 1
        if j == i + 1:
            continue
        name = _span_text(question, toks, i + 1, j)
        if _exact_village_end(question, toks, i + 1, i + 1) is not None:
            continue                      # the start of an exact village / ward name ("Kenches Trace - Ward No.23", N1)
        level = LEVEL_WORDS.get(toks[j].low) if j < len(toks) else None
        if level == "village":
            from app import entity_resolver as er
            if er.is_stored_village_name(name):
                continue                  # "CENTRE VILLAGE": a stored one-word name the index leaves out (N4)
        if _is_place(name) or _out_of_area(name):
            continue
        if level is None and len(_letters(name)) < 4:
            continue
        return {"typed": name, "level": level, "suggestions": suggestions(name, level)}
    return None


def candidate_alias(typed: str, chosen: str) -> None:
    """A "Did you mean" pick: logged for a person to review (brief §3.7). Never
    added automatically."""
    logger.info("spelling: candidate alias %r -> %r (review, then add to %s)", typed, chosen, _ALIAS_FILE.name)
