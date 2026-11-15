"""Two checks on what the live voice says. String methods only (no regex, D-046 / D-047).

1. Numbers. The voice is told to read the checked answer word for word. Every
   number in what it actually said (its own transcript: digits or English
   words, Indian or international grouping, lakh / crore) is compared with the
   numbers in the answers it was given this session. A number with no source
   is a deviation: logged and counted and, since 14 Nov 2026 (VOICE_BLOCK_UNSOURCED,
   on by default), BLOCKED: the relay stops that sentence's audio and caption
   and the line is replaced (guard_line). This is the voice's version of the
   composer's numeric-faithfulness rule.
2. Engine names. The voice never names the model or the company behind it;
   any such name in a caption is replaced before it reaches the screen.
"""
from __future__ import annotations

_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
           "million": 1_000_000, "crore": 10_000_000, "crores": 10_000_000, "billion": 1_000_000_000}
_SCALE_AFTER_DIGITS = (("crores", 10_000_000), ("crore", 10_000_000), ("lakhs", 100_000), ("lakh", 100_000),
                       ("lacs", 100_000), ("lac", 100_000), ("million", 1_000_000), ("thousand", 1_000))
_DIGIT_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
                "six": "6", "seven": "7", "eight": "8", "nine": "9"}

# Numbers that need no source: small counts and ordinals said in passing.
TRIVIAL = {float(x) for x in range(0, 13)}


_COMPOSE_SCALES = _SCALE_AFTER_DIGITS + (("hundred", 100),)
_GAP_OK = {"and", "s"}          # "2 crore and 55 lakh"; the "s" left over from "thousands"


def _digit_values(text: str, keep_parts: bool = False) -> list[tuple]:
    """Numbers written with digits, each as its possible readings: 54,89,616 -> (5489616,);
    37.49 crore -> (37.49, 374900000); 2023-24 -> (2023,), (24,).
    A descending run of number + scale groups is ONE figure, the way the live voice transcribes an Indian number:
    '2 crore 55 lakh 96 thousand 237' -> (25596237,) (2026-11-03: each piece used to be a separate, unsupported
    figure, so the page re-read a correct answer)."""
    raw = _digit_groups(text)
    out: list[tuple] = []
    low = (text or "").lower()
    i = 0
    while i < len(raw):
        start, end, v, word, mult = raw[i]
        total, j, last_mult, last_end = (v * mult if mult else 0.0), i + 1, mult, end
        # 2026-11-16: a written figure with decimals ("₹14.55 crore and 5,00,656 person-days") is never the head of a
        # spoken run: it was read as one figure 14.55 crore + 5,00,656, so a correct "5 lakh" was blocked
        while mult and float(v).is_integer() and j < len(raw):
            s2, e2, v2, w2, m2 = raw[j]
            gap = low[last_end:s2].replace(",", " ").split()
            if any(g not in _GAP_OK for g in gap):
                break
            if m2 is not None and m2 < last_mult and v2 * m2 < last_mult:
                total += v2 * m2
                last_mult, last_end = m2, e2
                j += 1
                continue
            if m2 is None and float(v2).is_integer() and v2 < last_mult and "," not in text[s2:e2]:
                total += v2
                last_end = e2
                j += 1
            break
        if j > i + 1:                                    # a composed run: one figure
            out.append((round(total, 2),))
            if keep_parts:
                # 2026-11-16: in an ANSWER, "₹14.55 crore and 5,00,656 person-days" are two figures as well as the run
                # a voice would say as one; both readings are facts (a spoken "about 5 lakh" was cut otherwise)
                for k in range(i, j):
                    _s, _e, pv, pw, pm = raw[k]
                    out.append((pv, round(pv * pm, 2)) if pm is not None and pw != "hundred" else (pv,))
            i = j
            continue
        if word == "hundred":
            out.append((v,))
        else:
            out.append((v, round(v * mult, 2)) if mult is not None else (v,))
        i += 1
    return out


def _digit_groups(text: str) -> list[tuple]:
    """(start, end, value, scale word or '', multiplier or None) for every digit number; `end` is past its scale word."""
    out: list[tuple] = []
    t = text or ""
    low = t.lower()
    i, n = 0, len(t)
    while i < n:
        if not t[i].isdigit():
            i += 1
            continue
        j, buf = i, ""
        while j < n:
            c = t[j]
            if c.isdigit():
                buf += c
                j += 1
            elif c == "," and j + 1 < n and t[j + 1].isdigit() and buf:
                j += 1                                   # a grouping comma (Indian or international)
            elif c == "." and j + 1 < n and t[j + 1].isdigit() and "." not in buf:
                buf += "."
                j += 1
            else:
                break
        try:
            v = float(buf)
        except ValueError:
            i = j
            continue
        chunk = low[j:j + 12]
        rest = chunk.lstrip()
        hit = next(((word, mult) for word, mult in _COMPOSE_SCALES if rest.startswith(word)), None)
        if hit:
            out.append((i, j + len(chunk) - len(rest) + len(hit[0]), v, hit[0], hit[1]))
        else:
            out.append((i, j, v, "", None))
        i = j
    return out


def _words(text: str) -> list[str]:
    low = (text or "").lower().replace("-", " ")
    return "".join(ch if (ch.isalpha() or ch.isspace()) else " " for ch in low).split()


def _word_values(text: str) -> list[tuple]:
    """Numbers said in English words: 'fifty four lakh eighty nine thousand six hundred and sixteen' -> 5489616.
    'twenty twenty-three' is two numbers (20, 23), not 43."""
    toks = _words(text)
    out: list[tuple] = []
    i = 0
    while i < len(toks):
        if toks[i] not in _UNITS and toks[i] not in _TENS:
            i += 1
            continue
        total, cur, last, j = 0, 0, "", i
        while j < len(toks):
            x = toks[j]
            if x in _TENS:
                if last in ("tens", "units"):
                    break
                cur += _TENS[x]
                last = "tens"
            elif x in _UNITS:
                if last == "units" or (last == "tens" and _UNITS[x] >= 10):
                    break
                cur += _UNITS[x]
                last = "units"
            elif x == "hundred" and last:
                cur = (cur or 1) * 100
                last = "scale"
            elif x in _SCALES and last:
                total += (cur or 1) * _SCALES[x]
                cur = 0
                last = "scale"
            elif x == "and" and last and j + 1 < len(toks) and (toks[j + 1] in _UNITS or toks[j + 1] in _TENS):
                last = "scale"
            else:
                break
            j += 1
        val = float(total + cur)
        if j < len(toks) and toks[j] == "point" and j + 1 < len(toks) and toks[j + 1] in _DIGIT_WORDS:
            dec, k = "", j + 1
            while k < len(toks) and toks[k] in _DIGIT_WORDS:
                dec += _DIGIT_WORDS[toks[k]]
                k += 1
            val = float(f"{int(val)}.{dec}")
            j = k
        out.append((val,))
        i = max(j, i + 1)
    return out


def spoken_values(text: str) -> list[tuple]:
    """Every number in a transcript, each as a tuple of the values it may stand for."""
    return _digit_values(text) + _word_values(text)


def _item_counts(text: str) -> set:
    """How many items an answer lists (its lines, its ';'-separated parts): a voice saying "these 15 blocks" of a
    15-line answer names a count the screen shows, not a figure from memory."""
    t = text or ""
    out = set()
    lines = [ln for ln in t.splitlines() if any(ch.isalpha() for ch in ln)]
    for n in (len(lines), len(lines) - 1, len([p for p in t.split(";") if p.strip()])):
        if n >= 2:
            out.add(float(n))
    return out


def facts_from(text: str, acc: set | None = None) -> set:
    """The numbers in an answer, plus the forms a voice may say them in (rounded, in lakh or crore, a year in halves),
    plus how many items it lists."""
    acc = acc if acc is not None else set()
    acc |= _item_counts(text)
    for alts in _digit_values(text, keep_parts=True) + _word_values(text):
        for v in alts:
            for x in (v, round(v), round(v, 1), round(v, 2), round(v / 1e5, 1), round(v / 1e5, 2),
                      round(v / 1e7, 1), round(v / 1e7, 2), round(v / 1e3), round(v / 1e6, 1), round(v / 1e6, 2)):
                acc.add(float(x))
            if float(v).is_integer() and 1900 <= v <= 2100:     # "twenty twenty-three"
                acc.add(float(int(v) // 100))
                acc.add(float(int(v) % 100))
    return acc


# An honest spoken rounding (2026-11-15, the natural spoken form): "about thirty-five thousand" for 35,039, "nearly
# 890 crore" for 886.29 crore. Accepted only when the sentence says it is approximate, and only within 3 % of a figure
# an answer holds; a number no answer supports is still blocked.
APPROX_WORDS = frozenset({"about", "nearly", "almost", "roughly", "around", "approximately", "just"})
APPROX_TOL = 0.03


def _supported(v: float, facts: set, approx: bool = False) -> bool:
    if v in TRIVIAL or v in facts or round(v, 1) in facts or round(v) in facts:
        return True
    tol = APPROX_TOL if approx else 0.006
    return any(abs(v - f) <= max(0.051, abs(f) * tol) for f in facts if f)


def _is_year(v: float) -> bool:
    return float(v).is_integer() and 1990 <= v <= 2035


_MONTHS = frozenset(("january february march april may june july august september october november december "
                     "jan feb mar apr jun jul aug sep sept oct nov dec").split())
_RANK_WORDS = frozenset(("top", "bottom", "first", "last"))
_ORDINAL_ENDS = ("st", "nd", "rd", "th")
_EDGE_PUNCT = ".,;:!?()[]\"'"


def _is_number_word(w: str) -> bool:
    return w in _UNITS or w in _TENS


def _drop_allowed(said: str) -> str:
    """The transcript without the numbers that are not figures (14 Nov 2026, the guard now BLOCKS, so a false alarm
    cuts a correct answer):
      * ordinals written with digits: "ranks 13th", "the 21st-ranked district" (words such as "thirteenth" are never
        read as numbers);
      * the size of a ranking: "top 15", "bottom five", "first 20", "last three";
      * a day of a date: "31 March 2024", "March 31".
    Each dropped token becomes a placeholder word, so the numbers either side of it are never joined into one."""
    toks = (said or "").split()
    low = [t.lower().strip(_EDGE_PUNCT) for t in toks]
    keep = list(toks)
    for i, w in enumerate(low):
        head = w.split("-", 1)[0]
        k = 0
        while k < len(head) and head[k].isdigit():
            k += 1
        if 0 < k < len(head) and head[k:] in _ORDINAL_ENDS:
            keep[i] = "_"
            continue
        if w.isdigit() and 1 <= int(w) <= 31 and (
                (i + 1 < len(low) and low[i + 1] in _MONTHS) or (i > 0 and low[i - 1] in _MONTHS)):
            keep[i] = "_"
            continue
        if i > 0 and low[i - 1] in _RANK_WORDS:
            if w.isdigit():
                keep[i] = "_"
            elif all(_is_number_word(p) for p in w.split("-") if p):
                keep[i] = "_"
                j = i + 1
                while j < len(low) and all(_is_number_word(p) for p in low[j].split("-") if p) and low[j]:
                    keep[j] = "_"
                    j += 1
    return " ".join(keep)


def deviations(said: str, facts: set) -> list[str]:
    """Numbers in what the voice said that no answer of this session supports. Years are never a deviation: a voice
    naming the year it was asked about ("in 2024-25", "twenty twenty-four") is not a figure from memory (a spurious
    "To be exact" re-read came from this on the real voice, 2026-11-02). Ordinals, the size of a ranking ("top 15")
    and the day of a date are not figures either (_drop_allowed)."""
    bad: list[str] = []
    approx = any(w in APPROX_WORDS for w in _words(said))
    vals = spoken_values(_drop_allowed(said))
    yearish = [False] * len(vals)
    for i, alts in enumerate(vals):
        v = alts[-1]
        if any(_is_year(x) for x in alts):
            yearish[i] = True
            nxt = vals[i + 1][-1] if i + 1 < len(vals) else None
            if nxt is not None and nxt == (v + 1) % 100:          # 2023-24: the second half
                yearish[i + 1] = True
        elif v in (19.0, 20.0) and i + 1 < len(vals):             # "twenty twenty-four" said in words
            nxt = vals[i + 1][-1]
            if float(nxt).is_integer() and 0 <= nxt <= 99:
                yearish[i] = yearish[i + 1] = True
    for i, alts in enumerate(vals):
        if yearish[i]:
            continue
        if any(_supported(v, facts, approx) for v in alts):
            continue
        v = alts[-1]
        s = str(int(v)) if float(v).is_integer() else str(v)
        if s not in bad:
            bad.append(s)
    return bad


ON_SCREEN_LINE = "That figure is on your screen."
SAFE_LINE = "The exact figures are on your screen."


def sentences(text: str) -> list[str]:
    """The sentences of a spoken line (text_match.split_sentences: a full stop inside a number never splits)."""
    from app.text_match import split_sentences
    return [s.strip() for s in split_sentences(text or "") if s.strip()]


def guard_line(text: str, facts: set) -> tuple[str, list[str]]:
    """(the line as it may be spoken / shown, the unsourced numbers). Every sentence holding a number no answer
    supports is replaced by ON_SCREEN_LINE (a run of them by one); a line left with no sentence of its own becomes
    SAFE_LINE, so a reply is never emptied. A line with no unsourced number comes back unchanged."""
    if not (text or "").strip():
        return text or "", []
    parts = sentences(text)
    out: list[str] = []
    bad_all: list[str] = []
    kept = 0
    for s in parts:
        bad = deviations(s, facts)
        if not bad:
            out.append(s)
            kept += 1
            continue
        bad_all += [b for b in bad if b not in bad_all]
        if not out or out[-1] != ON_SCREEN_LINE:
            out.append(ON_SCREEN_LINE)
    if not bad_all:
        return text, []
    if not kept:
        return SAFE_LINE, bad_all
    return " ".join(out), bad_all


_ENGINE_NAMES = ("google deepmind", "deepmind", "gemini", "google", "openai", "chatgpt", "anthropic", "claude",
                 "qwen", "llama", "mistral", "vllm")
_SELF = "Megh One AI"


def scrub(text: str) -> str:
    """Engine and vendor names out of anything shown or spoken."""
    if not text:
        return text or ""
    out = text
    for name in _ENGINE_NAMES:
        k = out.lower().find(name)
        while k >= 0:
            out = out[:k] + _SELF + out[k + len(name):]
            k = out.lower().find(name, k + len(_SELF))
    while f"{_SELF} {_SELF}" in out:
        out = out.replace(f"{_SELF} {_SELF}", _SELF)
    return out
