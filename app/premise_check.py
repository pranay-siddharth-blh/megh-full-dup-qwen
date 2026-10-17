"""
backend/premise_check.py — catch a false numeric premise in a DATA question.

A question can *assert* a quantity as already-true and ask about it:

    "How is construction progressing on the 1.71 L sanctioned PMAY-G houses?"
    "Of the ₹500 Cr released, how much is unspent?"
    "What share of the 520999 job cards were used?"

The SQL layer answers the *question* ("construction progress", "unspent",
"share") and ignores the asserted number entirely, so the composer is free to
repeat "1.71 L sanctioned" as fact even when the data says 2057 houses were
sanctioned. On a government dashboard that reads as the assistant endorsing a
wrong figure.

This module extracts each asserted quantity, checks it against the query
result, and — when the data contradicts it — returns a note string. The notes
ride the same `notes` channel `entity_resolver` already uses; `compose_response`
is told to lead with the correction instead of answering as though the premise
held.

Deterministic, no model call. Precision over recall: it only fires on a clear
declarative quantity against a small (1-3 row) result, and stays silent when it
cannot be sure.
"""
from __future__ import annotations

import decimal
import logging
from dataclasses import dataclass, field

from app.text_match import Hit, Matcher, W

logger = logging.getLogger(__name__)

# ── scale words ────────────────────────────────────────────────────────────────
_SCALE = {
    "k": 1_000, "thousand": 1_000,
    "l": 100_000, "lac": 100_000, "lacs": 100_000, "lakh": 100_000, "lakhs": 100_000,
    "m": 1_000_000, "mn": 1_000_000, "million": 1_000_000, "millions": 1_000_000,
    "cr": 10_000_000, "crore": 10_000_000, "crores": 10_000_000,
    "bn": 1_000_000_000, "billion": 1_000_000_000, "billions": 1_000_000_000,
}

# ── character helpers (no regex: project rule D-047) ───────────────────────────

def _ps_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _ps_digits(text: str, i: int) -> int:
    """Length of the run of digits starting at text[i]."""
    j = i
    while j < len(text) and text[j].isdecimal():
        j += 1
    return j - i


def _ps_spaces(text: str, i: int) -> int:
    """Position after the run of whitespace starting at text[i]."""
    while i < len(text) and text[i].isspace():
        i += 1
    return i


def _ps_at(text: str, i: int, word: str) -> bool:
    """text[i:] starts with `word`, ignoring case."""
    return text[i:i + len(word)].lower() == word


def _ps_boundary(text: str, i: int) -> bool:
    """A word boundary at position i (a word character on exactly one side)."""
    left = i > 0 and _ps_word_char(text[i - 1])
    right = i < len(text) and _ps_word_char(text[i])
    return left != right


def _ps_is_year(s: str) -> bool:
    """Four digits starting 19 / 20 / 21."""
    return len(s) == 4 and s.isdecimal() and s[:2] in ("19", "20", "21")


def _ps_number_ends(text: str, i: int):
    """Where a number starting at text[i] can end, in preference order: a
    comma-grouped figure ("1,23,456": 1-3 digits, then ",dd" / ",ddd" groups),
    else digits with an optional decimal part ("1.71"), longest first."""
    run = _ps_digits(text, i)
    if not run:
        return
    if run <= 3:
        def groups(x, n):
            if text.startswith(",", x):
                g = _ps_digits(text, x + 1)
                for take in (3, 2):
                    if g >= take:
                        yield from groups(x + 1 + take, n + 1)
            if n:
                yield x
        yield from groups(i + run, 0)
    for k in range(run, 0, -1):
        e = i + k
        if k == run and text.startswith(".", e):
            for f in range(_ps_digits(text, e + 1), 0, -1):
                yield e + 1 + f
        yield e


# A number, then an optional scale word. Single-letter scales (k / l / m, either
# case) are only honoured as a standalone token right after the digits — "1.71 L",
# "500k" — so a stray letter mid-word can't be read as a multiplier.
_QTY_SCALES = ("lakhs", "lakh", "lacs", "lac", "crores", "crore", "thousand", "millions", "million",
               "billions", "billion", "mn", "bn", "cr")


def _ps_quantities(text: str) -> list[Hit]:
    """Each number in `text` not glued to a word character or '.' before it, with
    the scale word after it: Hit groups "num" and "scale" ("1.71 L", "500k",
    "1,200"). The span runs past the spaces after the number."""
    out: list[Hit] = []
    i, n = 0, len(text)
    while i < n:
        if not text[i].isdecimal() or (i > 0 and (_ps_word_char(text[i - 1]) or text[i - 1] == ".")):
            i += 1
            continue
        e = next(_ps_number_ends(text, i))
        j = _ps_spaces(text, e)
        scale = next((w for w in _QTY_SCALES if _ps_at(text, j, w)), None)
        if scale is None and j < n and text[j].lower() in ("k", "l", "m") and _ps_boundary(text, j + 1):
            scale = text[j]
        named = {"num": (i, e)}
        end = j
        if scale is not None:
            named["scale"] = (j, j + len(scale))
            end = j + len(scale)
        out.append(Hit(text, i, end, [], named))
        i = end
    return out


# yyyy-mm-dd / yyyy/mm/dd and dd-mm-yyyy / dd/mm/yyyy (also with dots), and the
# written forms "15 December 2020" / "December 15, 2020" — the "15" of a written
# date was read as an assumed figure ("not the 15 the question assumes", PMAY-G
# use-case QA 2026-09-28, KI-094).
_MONTH_NAME = W("jan", "january", "feb", "february", "mar", "march", "apr", "april", "may", "jun", "june",
                "jul", "july", "aug", "august", "sep", "sept", "september", "oct", "october", "nov",
                "november", "dec", "december")
_PS_MONTHS = frozenset(_MONTH_NAME.options)
_PS_ORDINALS = ("st", "nd", "rd", "th")
_PS_DATE_SEPS = ("-", "/", ".")


def _ps_month_end(text: str, i: int) -> "int | None":
    """End of a month name starting at text[i] (the whole run of letters)."""
    j = i
    while j < len(text) and text[j].isalpha():
        j += 1
    return j if j > i and text[i:j].lower() in _PS_MONTHS else None


def _ps_year_end(text: str, i: int) -> "int | None":
    return i + 4 if _ps_digits(text, i) == 4 and _ps_is_year(text[i:i + 4]) else None


def _ps_ordinal(text: str, i: int) -> int:
    return i + 2 if any(_ps_at(text, i, o) for o in _PS_ORDINALS) else i


def _ps_sep_at(text: str, i: int) -> bool:
    return text[i:i + 1] in _PS_DATE_SEPS and i < len(text)


def _ps_date_at(text: str, i: int) -> "int | None":
    """End of a calendar date starting at text[i], or None."""
    if not (text[i].isdecimal() or text[i].isalpha()):
        return None
    run = _ps_digits(text, i)
    if run and (i == 0 or not text[i - 1].isdecimal()):
        # 2020-01-05 / 2020/1/5 / 2020.01.05
        if run == 4 and _ps_is_year(text[i:i + 4]) and _ps_sep_at(text, i + 4):
            a = i + 5
            ra = _ps_digits(text, a)
            if ra in (1, 2) and _ps_sep_at(text, a + ra):
                b = a + ra + 1
                rb = _ps_digits(text, b)
                if rb in (1, 2):
                    return b + rb
        if run in (1, 2):
            # 05-01-2020 / 5/1/2020
            if _ps_sep_at(text, i + run):
                a = i + run + 1
                ra = _ps_digits(text, a)
                if ra in (1, 2) and _ps_sep_at(text, a + ra):
                    y = _ps_year_end(text, a + ra + 1)
                    if y is not None:
                        return y
            # 15 December 2020 / 15th of Dec., 2020
            j = _ps_ordinal(text, i + run)
            k = _ps_spaces(text, j)
            if k > j:
                starts = [k]
                if _ps_at(text, k, "of") and _ps_spaces(text, k + 2) > k + 2:
                    starts.insert(0, _ps_spaces(text, k + 2))
                for m in starts:
                    me = _ps_month_end(text, m)
                    if me is None:
                        continue
                    me += text.startswith(".", me)
                    me += text.startswith(",", me)
                    ys = _ps_spaces(text, me)
                    if ys > me:
                        y = _ps_year_end(text, ys)
                        if y is not None:
                            return y
    # December 15, 2020 / Dec. 15th 2020
    if _ps_boundary(text, i):
        me = _ps_month_end(text, i)
        if me is not None:
            me += text.startswith(".", me)
            d = _ps_spaces(text, me)
            rd = _ps_digits(text, d)
            if d > me and rd in (1, 2):
                j = _ps_ordinal(text, d + rd)
                j += text.startswith(",", j)
                ys = _ps_spaces(text, j)
                if ys > j:
                    y = _ps_year_end(text, ys)
                    if y is not None:
                        return y
    return None


def _ps_blank_spans(text: str, hits: list) -> str:
    """`text` with each hit's span replaced by spaces (length-preserving)."""
    for h in hits:
        text = text[:h.start()] + " " * (h.end() - h.start()) + text[h.end():]
    return text


def _ps_blank_dates(text: str) -> str:
    """Every calendar date in `text` replaced by spaces (length-preserving)."""
    out, i, last = [], 0, 0
    while i < len(text):
        e = _ps_date_at(text, i)
        if e is None:
            i += 1
            continue
        out.append(text[last:i] + " " * (e - i))
        i = last = e
    out.append(text[last:])
    return "".join(out)

# Words right before the number that mean it is NOT an asserted stock but a
# ranking cut, a comparison threshold, or a relative-time span.
_PRECEDING_STOPWORDS = {
    "top", "bottom", "first", "last", "past", "next", "latest", "recent", "previous",
    "over", "under", "above", "below", "least", "most", "than", "least",
    "up",  # "up to N"
}
_PRECEDING_STOP_PHRASES = ("more than", "less than", "at least", "at most", "up to",
                           "fewer than", "greater than", "no more than", "as many as")
# Words right after the number that mark it as a ranking length, not a stock.
# "batch"/"cohort" are here for a different reason: in this schema "12.5K" and
# "93K" are literal batch_label VALUES (proper names for the two Focus Plus
# cohorts, see schema_context.py rule 4) — "the 12.5K batch" names which rows
# to read, it doesn't assert a count of anything. Without this, has_scale in
# _is_asserted_quantity below treats every "<number><scale>" as a stock
# regardless of context, so "status breakdown for the 12.5K batch" (whose
# breakdown sums to 12,527, not exactly 12,500) got flagged as contradicting
# an "assumed figure" it never asserted. Confirmed live 2026-09-12.
_FOLLOWING_STOPWORDS = {
    "highest", "lowest", "largest", "smallest", "biggest", "top", "best", "worst",
    "leading", "years", "year", "months", "month", "days", "day", "weeks", "quarters",
    "batch", "batches", "cohort", "cohorts",
}

# Determiners that flag the number as a *given* the question builds on.
_GIVEN_DETERMINERS = {"the", "those", "these", "that", "this", "all", "its", "their",
                      "of", "on", "among", "amongst", "from", "out", "these"}

# Metric vocabulary — only used to decide whether a small, scale-less number
# reads as an asserted stock ("the 900 houses sanctioned") rather than noise.
# NOT used to pick a column: a generated result often labels a column ambiguously
# (e.g. "House Sanctioned" is a *construction stage* in this schema, not the
# total sanctioned count), so matching a premise to a column by keyword produces
# confident but wrong "corrections". The check below compares against every
# value instead.
_ALL_KW = {
    "sanctioned", "sanction", "sanctions", "released", "release", "disbursed",
    "completed", "complete", "completions", "pending", "incomplete", "unspent",
    "approved", "allotted", "allocated", "proposed", "registered", "geotagged",
    "expenditure", "spent", "utilised", "utilized", "persondays",
    "houses", "house", "housing", "dwelling", "dwellings", "units",
    "beneficiaries", "households", "persons", "people",
    "amount", "rupees", "crore", "crores", "lakh", "lakhs", "money", "funds",
    "jobcards", "cards", "works", "assets", "villages", "workers",
}

# Multi-word metric phrases, normalised to the single tokens above so window
# scanning catches them.
def _ps_job_cards(text: str, i: int) -> "int | None":
    """End of "job card(s)" at text[i] ("jobcard", "Job  Cards")."""
    if not _ps_at(text, i, "job"):
        return None
    j = _ps_spaces(text, i + 3)
    if not _ps_at(text, j, "card"):
        return None
    return j + 4 + _ps_at(text, j + 4, "s")


def _ps_person_days(text: str, i: int) -> "int | None":
    """End of "person day(s)" at text[i] ("person-days", "person days", "persondays")."""
    if not _ps_at(text, i, "person"):
        return None
    j = i + 6
    if j < len(text) and (text[j].isspace() or text[j] == "-") and _ps_at(text, j + 1, "day"):
        j += 1
    if not _ps_at(text, j, "day"):
        return None
    return j + 3 + _ps_at(text, j + 3, "s")


_PHRASE_NORMALISE = [
    (_ps_job_cards, "jobcards"),
    (_ps_person_days, "persondays"),
]

_PS_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _ps_words(text: str) -> list[str]:
    """Words for the window scan: an ASCII letter, then letters and hyphens."""
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] in _PS_LETTERS:
            j = i + 1
            while j < n and (text[j] in _PS_LETTERS or text[j] == "-"):
                j += 1
            out.append(text[i:j])
            i = j
        else:
            i += 1
    return out


@dataclass
class Premise:
    value: float          # the asserted quantity, scale expanded
    text: str             # the span as the user wrote it, e.g. "1.71 L"
    keywords: list[str] = field(default_factory=list)   # metric words around it


def _normalise_phrases(text: str) -> str:
    for phrase_end, repl in _PHRASE_NORMALISE:
        out, i, last = [], 0, 0
        while i < len(text):
            e = phrase_end(text, i)
            if e is None:
                i += 1
                continue
            out.append(text[last:i] + repl)
            i = last = e
        out.append(text[last:])
        text = "".join(out)
    return text


def _to_number(value: object) -> "int | float | None":
    """Coerce a result cell to a real number, or None. Local copy so this module
    has no import edge back into pipeline.py."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else value
    if isinstance(value, decimal.Decimal):
        f = float(value)
        return int(f) if f.is_integer() else f
    if isinstance(value, str):
        s = value.strip().replace(",", "")
        parts = (s[1:] if s.startswith("-") else s).split(".")
        if len(parts) <= 2 and all(p.isdecimal() for p in parts):
            return int(s) if "." not in s else float(s)
    return None


def _window_keywords(text: str, start: int, end: int, *, before: int = 4, after: int = 4) -> list[str]:
    """Metric words within `before` tokens left and `after` tokens right of the
    number span [start, end)."""
    left_words = _ps_words(text[:start].lower())[-before:]
    right_words = _ps_words(text[end:].lower())[:after]
    found: list[str] = []
    for w in (*left_words, *right_words):
        if w in _ALL_KW and w not in found:
            found.append(w)
    return found


def _is_asserted_quantity(text: str, m: Hit, value: float, has_scale: bool) -> bool:
    """True when the matched number reads as a stock the question takes as given,
    not a ranking length / threshold / time span / year."""
    raw = m.group("num").replace(",", "")
    if _ps_is_year(raw) and not has_scale:
        return False
    # a percentage is a rate, handled elsewhere
    tail = text[m.end():m.end() + 8].lstrip()
    if tail.startswith("%") or tail[:7].lower().startswith("percent"):
        return False

    left = text[:m.start()].lower()
    left_words = _ps_words(left)
    prev1 = left_words[-1] if left_words else ""
    prev2 = " ".join(left_words[-2:]) if len(left_words) >= 2 else ""
    if prev1 in _PRECEDING_STOPWORDS or prev2 in _PRECEDING_STOP_PHRASES:
        return False

    right_words = _ps_words(text[m.end():].lower())
    nxt = right_words[0] if right_words else ""
    if nxt in _FOLLOWING_STOPWORDS:
        return False

    has_separator = "," in m.group("num")
    kw = _window_keywords(text, m.start(), m.end())
    given_ctx = prev1 in _GIVEN_DETERMINERS or (len(left_words) >= 2 and left_words[-2] in _GIVEN_DETERMINERS)

    # Accept when the magnitude alone says "stock" (a scale word, a thousands
    # separator, or >= 1000), or when a metric word sits next to it AND it is
    # introduced as a given ("the 900 houses sanctioned").
    if has_scale or has_separator or value >= 1000:
        return bool(kw) or has_scale or has_separator or value >= 10_000
    return bool(kw) and given_ctx


# ── Stated amount filters ──────────────────────────────────────────────────
# "What is the total disbursement for Focus Plus for a loan of five thousand
# across all financial years?" (reported 2026-09-29) ran
#   SELECT SUM(amount_disbursed) FROM curated.v_focus_plus
# — the "five thousand" silently gone. In Focus Plus it is not noise: a payment
# is either ₹5,000 (Tranch 1, FY 2022-23) or ₹2,500 (every later tranche), so
# the dropped filter changed the answer about 2.5x. An amount stated as the
# SIZE of each payment / loan / instalment is a FILTER, never an asserted
# stock: stated_amount_filters() reads it, and extract_premises() leaves it out.
_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * (i + 2) for i, w in enumerate(
    "twenty thirty forty fifty sixty seventy eighty ninety".split())}
_MULT = {"hundred": 100, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000,
         "lacs": 100_000, "crore": 10_000_000, "crores": 10_000_000}
_NUMBER_WORDS = frozenset([*_UNITS, *_TENS, *_MULT])

# What a payment is called: "loan(s)", "payment(s)", "instal(l)ment(s)",
# "tranch / tranche(s)", "grant(s)", "benefit(s)", "subsidy / subsidies",
# "disbursement(s)", "transfer(s)" — each (stem, endings in preference order).
_AMOUNT_NOUNS = (
    ("loan", ("s", "")), ("payment", ("s", "")), ("instal", None), ("tranch", ("e", "es", "")),
    ("grant", ("s", "")), ("benefit", ("s", "")), ("subsid", ("y", "ies")),
    ("disbursement", ("s", "")), ("transfer", ("s", "")),
)
_PS_NOUN_FIRST = frozenset(stem[0] for stem, _ in _AMOUNT_NOUNS)
_AMOUNT_PREFIXES = ("₹", "rs.", "rs", "inr")
_AMOUNT_SUFFIXES = ("rupees", "rupee", "rs.", "rs", "/-")
_AMOUNT_SCALES = ("k", "thousand", "lakhs", "lakh", "lacs", "lac", "crores", "crore")


def _ps_noun_ends(text: str, i: int):
    """(end, noun) for a payment noun starting at text[i], in preference order."""
    if text[i:i + 1].lower() not in _PS_NOUN_FIRST:
        return
    for stem, endings in _AMOUNT_NOUNS:
        if not _ps_at(text, i, stem):
            continue
        j = i + len(stem)
        if endings is None:            # instal+ments?
            while _ps_at(text, j, "l"):
                j += 1
            if not _ps_at(text, j, "ment"):
                return
            j += 4
            endings_at = [j + 1] if _ps_at(text, j, "s") else []
            for e in (*endings_at, j):
                yield e, text[i:e]
            return
        for end in endings:
            if _ps_at(text, j, end):
                yield j + len(end), text[i:j + len(end)]
        return


def _ps_spaced_word_end(text: str, i: int, word: str) -> "int | None":
    """End of `word` at text[i] when followed by at least one whitespace."""
    if _ps_at(text, i, word) and _ps_spaces(text, i + len(word)) > i + len(word):
        return i + len(word)
    return None


def _ps_number_words_ends(text: str, i: int):
    """Ends of a run of number words starting at text[i] ("five thousand",
    "one lakh and fifty thousand", "two-thousand"), longest first. A number
    word is a whole word; words are joined by spaces / hyphens, with an
    optional "and" between two of them."""
    if not _ps_boundary(text, i):
        return

    def word_end(x):
        j = x
        while j < len(text) and _ps_word_char(text[j]):
            j += 1
        return j if j > x and text[x:j].lower() in _NUMBER_WORDS else None

    def sep_end(x):
        j = x
        while j < len(text) and (text[j].isspace() or text[j] == "-"):
            j += 1
        return j if j > x else None

    ends = []
    e = word_end(i)
    while e is not None:
        ends.append(e)
        s = sep_end(e)
        if s is None:
            break
        nxt = word_end(s)
        if nxt is None and _ps_at(text, s, "and") and not _ps_word_char(text[s + 3:s + 4] or " "):
            s2 = sep_end(s + 3)
            nxt = word_end(s2) if s2 is not None else None
        e = nxt
    yield from reversed(ends)


def _ps_amount_ends(text: str, i: int):
    """(end, groups) for each way an amount can be read at text[i], in
    preference order: optional "₹" / "Rs." / "INR", then digits with an
    optional scale ("5,000", "5 thousand", "2.5k") or number words ("five
    thousand"), then optional "rupees" / "Rs" / "/-". groups holds "digits",
    "dscale" or "words" spans."""
    starts = []
    for p in _AMOUNT_PREFIXES:
        if _ps_at(text, i, p):
            starts.append(_ps_spaces(text, i + len(p)))
    starts.append(i)
    for a in starts:
        for body_end, groups in _ps_amount_body(text, a):
            k = _ps_spaces(text, body_end)
            for sfx in _AMOUNT_SUFFIXES:
                if _ps_at(text, k, sfx):
                    yield k + len(sfx), groups
            yield body_end, groups


def _ps_amount_body(text: str, a: int):
    for e in _ps_number_ends(text, a):
        if text[e:e + 1] in ("-", "/") and text[e + 1:e + 2].isdecimal():
            continue                     # "2022-23", "1/2": not an amount
        w = _ps_spaces(text, e)
        for s in range(w, e - 1, -1):
            for sc in _AMOUNT_SCALES:
                if _ps_at(text, s, sc) and _ps_boundary(text, s + len(sc)):
                    yield s + len(sc), {"digits": (a, e), "dscale": (s, s + len(sc))}
            if _ps_boundary(text, s):
                yield s, {"digits": (a, e)}
    for e in _ps_number_words_ends(text, a):
        yield e, {"words": (a, e)}


def _ps_stated_amount_at(text: str, p: int) -> "Hit | None":
    """A stated payment size starting at text[p]: "loan of five thousand",
    "payments amount of ₹2,500", "₹5,000 instalments"."""
    c = text[p].lower()
    if not (c in _PS_STATED_FIRST or c.isdecimal()):
        return None
    # <noun> [amount] of|worth|for|= <amount>
    for n_end, noun in _ps_noun_ends(text, p):
        k = _ps_spaces(text, n_end)
        if k == n_end:
            continue
        ks = [k]
        am = _ps_spaced_word_end(text, k, "amount")
        if am is not None:
            ks.insert(0, _ps_spaces(text, am))
        for k2 in ks:
            for kw in ("of", "worth", "for", "="):
                if _ps_at(text, k2, kw):
                    a = _ps_spaces(text, k2 + len(kw))
                    if a == k2 + len(kw):
                        continue
                    for end, groups in _ps_amount_ends(text, a):
                        return Hit(text, p, end, [], {**groups, "noun": (p, n_end)})
    # <amount> <noun>
    for end, groups in _ps_amount_ends(text, p):
        k = _ps_spaces(text, end)
        for n_end, noun in _ps_noun_ends(text, k):
            return Hit(text, p, n_end, [], {**groups, "noun": (k, n_end)})
    return None


# what a stated amount can start with: a payment noun, "₹" / "rs" / "inr", a
# number word, or a digit
_PS_STATED_FIRST = frozenset([*_PS_NOUN_FIRST, *(x[0] for x in _AMOUNT_PREFIXES), *(w[0] for w in _NUMBER_WORDS)])


def _ps_stated_amounts(text: str) -> list[Hit]:
    """Each stated payment size in `text`, left to right, non-overlapping."""
    out, i = [], 0
    while i < len(text):
        h = _ps_stated_amount_at(text, i)
        if h is None or h.end() == i:
            i += 1
            continue
        out.append(h)
        i = h.end()
    return out


def words_to_number(text: str) -> "float | None":
    """"five thousand" -> 5000, "two thousand five hundred" -> 2500,
    "one lakh fifty thousand" -> 150000. None when a word is not a number word
    or nothing numeric is present."""
    total, current, seen = 0, 0, False
    for w in (text or "").lower().replace("-", " ").split():
        if not w or w in ("and", "a"):
            continue
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = (current or 1) * 100
        elif w in _MULT:
            total += (current or 1) * _MULT[w]
            current = 0
        else:
            return None
        seen = True
    return float(total + current) if seen else None


@dataclass
class StatedAmount:
    value: float    # rupees, scale expanded
    text: str       # the whole phrase as typed, e.g. "loan of five thousand"
    noun: str       # "loan", "payment", ...
    span: tuple     # (start, end) in the question


_PS_RUPEE_WORD = Matcher(W("rs", "inr"))


def stated_amount_filters(question: str) -> list[StatedAmount]:
    """Each amount the question states as the size of a payment / loan /
    instalment ("a loan of five thousand", "payments of ₹2,500", "₹5,000
    instalments"). Amounts under ₹100 are ignored ("tranche of 4" is not money)."""
    out: list[StatedAmount] = []
    for m in _ps_stated_amounts(question or ""):
        g = m.groupdict()
        digits, dscale, words = g.get("digits"), g.get("dscale"), g.get("words")
        noun = (g.get("noun") or "").lower()
        phrase = m.group(0)
        if digits and not dscale and _ps_is_year(digits) \
                and not ("₹" in phrase or "rupee" in phrase.lower() or _PS_RUPEE_WORD.search(phrase)):
            continue   # "a loan for 2024" names a year, not an amount
        if digits:
            value = float(digits.replace(",", "")) * _SCALE.get((dscale or "").lower(), 1)
        else:
            value = words_to_number(words or "")
        if value is None or value < 100:
            continue
        out.append(StatedAmount(value=value, text=m.group(0).strip(), noun=noun.rstrip("s"),
                                span=(m.start(), m.end())))
    return out


def extract_premises(question: str) -> list[Premise]:
    q = _normalise_phrases(question or "")
    # A calendar date is a filter, not an asserted stock: "sanctioned on
    # 2017-11-28" yielded premises 11 and 28, and the composer answered "504
    # houses, not the 11 or 28 figures assumed" (2026-09-27 screenshot). Blank
    # dates out, length-preserving so spans still index into `question`.
    q = _ps_blank_dates(q)
    # A stated payment size ("payments of ₹5,000") is a filter too.
    q = _ps_blank_spans(q, _ps_stated_amounts(q))
    out: list[Premise] = []
    for m in _ps_quantities(q):
        try:
            base = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        scale_tok = (m.group("scale") or "").lower().strip()
        has_scale = bool(scale_tok)
        value = base * _SCALE.get(scale_tok, 1) if has_scale else base
        if value <= 0:
            continue
        if not _is_asserted_quantity(q, m, value, has_scale):
            continue
        span = question[m.start():m.end()].strip() if len(question) >= m.end() else m.group(0).strip()
        out.append(Premise(value=value, text=span or m.group(0).strip(),
                           keywords=_window_keywords(q, m.start(), m.end())))
    return out


def _pretty_col(col: str) -> str:
    return col.replace("_", " ").strip().title()


def _fmt(v: "int | float") -> str:
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.2f}"
    return f"{int(v):,}"


def _close(a: float, b: float) -> bool:
    """Within 2% of the larger magnitude, or half a unit — tolerant of the
    rounding baked into '1.71 L' but not of an order-of-magnitude gap."""
    hi = max(abs(a), abs(b), 1.0)
    return abs(a - b) <= max(0.02 * hi, 0.5)


def check_premises(question: str, rows: list[dict]) -> list[str]:
    """Notes for any asserted quantity in `question` the result contradicts.
    Empty list when there is no premise, the result is too large to reason about
    cell-by-cell, or every premise is consistent with the data."""
    premises = extract_premises(question)
    if not premises:
        return []
    if not rows or len(rows) > 3:
        return []

    cells: list[tuple[str, "int | float"]] = []
    seen: set[tuple[str, float]] = set()
    for row in rows:
        for col, val in row.items():
            n = _to_number(val)
            if n is None:
                continue
            key = (col, float(n))
            if key in seen:
                continue
            seen.add(key)
            cells.append((col, n))
    if not cells:
        return []

    notes: list[str] = []
    for p in premises:
        # Consistent as long as SOME figure in the result is close to the asserted
        # number — deliberately lenient. A column whose label seems to disagree
        # (e.g. a "House Sanctioned" *stage* count vs. the total sanctioned house
        # count) is not evidence the premise is wrong.
        if any(_close(n, p.value) for _c, n in cells):
            continue

        near_c, near_n = min(cells, key=lambda cn: abs(cn[1] - p.value))
        notes.append(
            f'The question treats "{p.text}" (~{_fmt(p.value)}) as an established figure, but '
            f'no value in this result is close to it (nearest: {_pretty_col(near_c)} = '
            f'{_fmt(near_n)}). Do not restate "{p.text}" as fact; answer from the figures the '
            f'query actually returned and note that the assumed number is not supported here.'
        )
    return notes
