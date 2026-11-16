"""The checked answer, said the way a person would say it.

10 Nov 2026 (the user: "it sounds like a cascading agent, very robotic; Gemini feels like a human explaining the answer
to me") and 12 Nov 2026 (the user: "some questions come out in very nice natural language, but some still sound like a
cascading agent. Every question, in every permutation, must be answered in a warm tone, proper natural language, a good
amount of emotion").

Megh's page hands the voice a CHECKED answer (`speak`, at most ~320 characters, every figure from SQL) and its `kind`.
Every kind is now said warmly, by one of three paths, and none of them can change a figure or the meaning:

  1. SLOTS (data answers with figures, clarifications): every figure of the checked answer (with its rupee sign and
     its unit) and every year / financial year is cut out deterministically and replaced by a tag ([N1], [Y1]). The
     on-prem LLM (qwen4-deploy on the team gateway; nothing leaves the network) writes the spoken sentences AROUND the
     tags; it never sees a digit and may not write one. Code then puts each figure back exactly as it was written, and
     the deterministic guard of round 2 still runs on the filled text: every figure said, none added, every figure
     still beside its own district / scheme / year (`pairing_broken`), every name a name of the answer, caveats kept,
     the screen mentioned only if the answer does, every option of a clarification kept. One retry with the reason.
  2. FRAME (refusals, access messages, edge answers, notes, knowledge passages, data answers without a figure): no
     model. A warm human frame chosen by kind ("I'm sorry, sir." / "Sure, sir." ...) around the checked words, kept
     verbatim apart from the speech tidy below. Meaning cannot move: the words are the checked words.
  3. As is (page lines that are already spoken English: view / nav / local / pending / superseded).

`speakable()` is the deterministic tidy every path ends with (and the fallback of path 1): report-speak openers ("The
bar graph displays", "This briefing outlines") become "Here's", ALL-CAPS words normal case, dashes / slashes / brackets /
label colons become commas or sentence ends, "Note:" becomes "Note that", list numbering goes. It never removes or
changes a figure, a name or a caveat word (`meaning_kept`, proved on the corpus in harness/megh/test_natural.py).

Use:  async for sentence in say_naturally(speak, question, kind): ...
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time

import httpx


def _tls_verify():
    """httpx verify= for the LLM gateway: the CA file of FDX_CA_BUNDLE when set (verification on), else the old
    FDX_LLM_INSECURE flag (14 Nov 2026)."""
    bundle = (os.environ.get("FDX_CA_BUNDLE") or "").strip()
    if bundle and os.path.isfile(bundle):
        return bundle
    return os.environ.get("FDX_LLM_INSECURE") != "1"

# the literal lists stay (harness/megh/test_domain_pack.py holds them equal to Megh's registries); the live lists come
# from the domain pack (megh/domain, built from Megh's own registries) when it is there, so a new scheme needs no code
DISTRICTS = ["East Garo Hills", "North Garo Hills", "South Garo Hills", "South West Garo Hills", "West Garo Hills",
             "East Jaintia Hills", "West Jaintia Hills", "Eastern West Khasi Hills", "East Khasi Hills", "Ri Bhoi",
             "South West Khasi Hills", "West Khasi Hills"]
SCHEMES = ["MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy", "CM Elevate Legacy", "CM Elevate"]

try:                                                  # megh/ is on the path when the engine imports us
    import domain as _domain                          # type: ignore
except Exception:  # noqa: BLE001
    try:                                              # imported alone (a test, a probe): megh/ is next to this file
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import domain as _domain                      # type: ignore
    except Exception:  # noqa: BLE001
        _domain = None


# The live lists are read from the pack at every call (the pack reloads itself when its file changes), so a new pack
# (a 7th scheme, a renamed district) is live at once; the literals above are only the fallback when there is no pack.
def _districts() -> list[str]:
    try:
        return _domain.district_names("match") if _domain else DISTRICTS
    except Exception:  # noqa: BLE001
        return DISTRICTS


def _schemes() -> list[str]:
    try:
        return _domain.scheme_names("match") if _domain else SCHEMES
    except Exception:  # noqa: BLE001
        return SCHEMES


STATS = {"calls": 0, "natural": 0, "partial": 0, "fallback": 0, "skipped": 0, "framed": 0, "errors": 0,
         "last_error": "", "first_sentence_ms": [], "guard_fails": 0, "last_fail": "", "fail_reasons": {}}

FIRST_S = float(os.environ.get("FDX_MEGH_NATURAL_FIRST_S", "2.5"))     # no first try done by then: the checked answer
TOTAL_S = float(os.environ.get("FDX_MEGH_NATURAL_TOTAL_S", "9"))
ON = os.environ.get("FDX_MEGH_NATURAL", "1") != "0"
MAX_SLOTS = int(os.environ.get("FDX_MEGH_NATURAL_MAX_FIGS", "12"))     # more content figures than this: framed, not re-said
PARALLEL_TEMPS = [float(x) for x in os.environ.get("FDX_MEGH_NATURAL_TEMPS", "0.3,0.6,0.85").split(",") if x.strip()]
RETRY_BEFORE_S = float(os.environ.get("FDX_MEGH_NATURAL_RETRY_S", "1.5"))   # every try failed this soon: one more

RESAY_KINDS = {"data", "answer", ""}
FRAME_KINDS = {"edge", "denied", "refusal", "refused", "note", "knowledge", "error", "out_of_scope", "blocked"}
ASIS_KINDS = {"nav", "local", "pending", "superseded", "read", "lead", "already_answered"}
FRAME_KINDS.add("view")

SYSTEM = """You are the voice of Megh One AI, speaking out loud to a senior officer of the Government of Meghalaya who has just asked about the state's schemes. You are given the CHECKED ANSWER. Say it to him the way a warm, bright, well-prepared colleague would say it in person: natural, friendly, confident spoken Indian English, with a little life in your voice. You are explaining, not reading a report.

In the checked answer every figure and every year has been replaced by a TAG such as [N1], [N2] or [Y1]. Each tag already holds its exact figure, its rupee sign and its unit (crore, lakh, %).

Hard rules:
1. Use every tag, written exactly like [N1], where its figure belongs. NEVER write a digit, a number, a number word, a year, "rupees", "crore", "lakh" or "percent" yourself: the tag says it.
2. Keep each tag right beside its own label (its district, scheme, year or measure), paired exactly as in the checked answer. Never gather several labels together and then give the tags.
3. Keep every scheme name and place name as it is (MGNREGA, PMAY-G, Focus Plus, Focus Legacy, CM Elevate). Write place names in normal case (West Garo Hills).
4. Add nothing that is not in the checked answer: no reason, no opinion, no advice, no comparison, no extra fact. Keep its caveats (what a figure counts, years with no data, provisional figures), said simply.
5. Lead with the answer itself. Say "sir" exactly once. Never say "This briefing outlines", "The chart displays", "the system shows", "as per the data" or other report language.
6. Spoken style: short sentences, contractions (it's, that's, there are), plain everyday words. No bullet points, no numbering, no brackets, no dashes, no colons, no line breaks, no emojis. A list is one flowing sentence with commas and "and" before the last item. Keep every sentence of the checked answer a sentence of its own: NEVER join two of its sentences into one with "which", "while", "and" or commas.
7. Mention the screen ONLY if the checked answer does, naturally, in the last sentence.
8. If the checked answer asks the officer to choose, ask it warmly in one short sentence and then name every option exactly as written, with "or" before the last one, ending with a question mark. An option's note in brackets may follow its name in plain words ("MGNREGA for rural employment"). Keep any count of further options on the screen. If the checked answer lists the same choices twice, name them once.
9. Be no longer than the checked answer.

Output only the words to be spoken.

Examples (their tags belong to these examples only):

CHECKED ANSWER: Here's MGNREGA person-days generated across all twelve districts of Meghalaya during [Y1]. West Garo Hills is the largest with [N1]; Eastern West Khasi Hills is the smallest with [N2]. The rest of the answer is on your screen.
SPOKEN: So for [Y1], West Garo Hills is right at the top, sir, with [N1] person-days. At the other end is Eastern West Khasi Hills, with [N2]. You'll see the rest of the districts on your screen.

CHECKED ANSWER: The total expenditure in East Khasi Hills across all financial years was [N1]. This is the MGNREGA figure across all financial years.
SPOKEN: That comes to [N1], sir. That's what MGNREGA has spent in East Khasi Hills, across all the financial years.

CHECKED ANSWER: MGNREGA expenditure rose from [N1] in [Y1] to [N2] in [Y2], [N3], [N4]. It peaked in [Y3] at [N5] and fell to its lowest in [Y4] at [N6].
SPOKEN: Right, sir, MGNREGA spending went up from [N1] in [Y1] to [N2] in [Y2], that's [N3], or [N4]. The high point was [Y3], at [N5], and the low point was [Y4], at [N6].

CHECKED ANSWER: All of Meghalaya, all financial years. MGNREGA, [N1] households given work, counted once per financial year. PMAY-G, [N2] houses sanctioned. Focus Plus, [N3] beneficiaries. And [N4] more are on your screen.
SPOKEN: This is all of Meghalaya, sir, over all the financial years. MGNREGA has given work to [N1] households, counted once per financial year. PMAY-G has [N2] houses sanctioned. Focus Plus has [N3] beneficiaries. The other [N4] are on your screen.

CHECKED ANSWER: Which Focus do you mean? The options are Focus Plus or Focus Legacy.
SPOKEN: Sure, sir, which Focus did you have in mind, Focus Plus or Focus Legacy?"""

OPENERS = ["Start straight with the answer itself, with no opening word.",
           "Open with \"So,\".",
           "Open with \"Right, sir,\".",
           "Start straight with the headline figure or name.",
           "Open with \"Okay,\".",
           "Open with \"Sure, sir.\" as its own short sentence.",
           "Open with \"Here's how it looks, sir.\" as its own short sentence."]

# 12 Nov 2026: "Rs" / "INR" only as a word of their own (the round-2 pattern read "years. 6,614" as "Rs. 6,614")
_NUM = re.compile(r"(₹|(?<![A-Za-z])Rs\.?\s?|(?<![A-Za-z])INR\s?)?([+\-−]?)(\d[\d,]*(?:\.\d+)?)"
                  r"(\s?(?:crore|lakh|cr\b|%|per\s?cent|x\b|times\b|K\b))?", re.I)
_SMALL = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
          "nine": "9", "ten": "10", "eleven": "11", "twelve": "12"}


def options_of(speak: str) -> list[str]:
    """The names of a clarifying question's options ("The options are A (note), B or C."), without their notes."""
    mark = "The options are "
    at = speak.rfind(mark)
    if at < 0:
        return []
    tail = speak[at + len(mark):].strip()
    for stop in (". There ", ". There are "):
        k = tail.find(stop)
        if k >= 0:
            tail = tail[:k]
    tail = tail.rstrip(".?")
    # split on ", " and " or " OUTSIDE brackets ("CM Elevate (livelihood / enterprise schemes)" is one option)
    pieces, buf, depth, i = [], "", 0, 0
    while i < len(tail):
        ch = tail[i]
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0 and tail.startswith(", ", i):
            pieces.append(buf)
            buf, i = "", i + 2
            continue
        if depth == 0 and tail.startswith(" or ", i):
            pieces.append(buf)
            buf, i = "", i + 4
            continue
        buf += ch
        i += 1
    pieces.append(buf)
    out = []
    for piece in pieces:
        name = piece.split(" (")[0].strip()
        if name:
            out.append(name)
    return out


CAVEATS = ["not", "no", "typed", "absent", "once", "only", "excluding", "except", "about", "approximately",
           "estimated", "provisional", "partial", "counted", "distinct", "verified", "unverified", "missing", "yet"]
_LIST_MARK = re.compile(r"(?m)^\s*\d{1,2}[.)]\s+|(?<=[:;]\s)\d{1,2}[.)]\s+(?=[A-Z])")
_SENT_END = re.compile(r"(?<=[.!?])[\"'”)\]]?\s+(?=\S)")
_WORD = re.compile(r"[A-Za-z][A-Za-z'’\-]*")
_CAPS_RUN = re.compile(r"\b[A-Z]{2,}(?:\s+[A-Z]{2,})+\b")
_ALLOWED_NAMES = {"i", "i'm", "i've", "i'll", "sir", "meghalaya", "megh", "one", "ai", "fy", "rs", "you'll", "you'd",
                  "here's", "that's", "there's", "it's", "so", "right", "okay", "sure", "sorry"}
_UNIT = {"cr": "crore", "percent": "%", "per cent": "%", "times": "x"}


def _norm_num(s: str) -> str:
    s = s.replace(",", "").rstrip(".")
    return s.rstrip("0").rstrip(".") if "." in s else s


def figures(text: str) -> set[tuple[str, bool, str]]:
    """(number, has a rupee sign, unit) for every figure of the text; list numbering ("1. ", "2) ") is not a figure."""
    out = set()
    for m in _NUM.finditer(_LIST_MARK.sub("", iso_dates(text or ""))):
        unit = " ".join((m.group(4) or "").lower().split())
        out.add((_norm_num(m.group(3)), bool(m.group(1)), _UNIT.get(unit, unit)))
    return out


def _nums(text: str) -> set[str]:
    return {n for n, _, _ in figures(text)}


def _nums_said(text: str) -> set[str]:
    """Figures heard in a sentence: its digits, and a small count said as a word ("two more are on your screen")."""
    return _nums(text) | {d for w, d in _SMALL.items() if w in _vocab(text)}


def _names(text: str) -> set[str]:
    """Capitalised words that do not start a sentence (names), lower-cased."""
    out = set()
    for sent in _SENT_END.split(text or ""):
        words = _WORD.findall(sent)
        for w in words[1:]:
            if w[0].isupper():
                out.add(_bare(w))
    return out


def _bare(w: str) -> str:
    """lower case, a possessive off ("PMAY-G's" -> "pmay-g", "Hills'" -> "hills")."""
    w = w.lower().replace("’", "'")
    if w.endswith("'s"):
        w = w[:-2]
    return w.rstrip("'")


def _vocab(text: str) -> set[str]:
    return {_bare(w) for w in _WORD.findall(text or "")}


# ---------------------------------------------------------------------------------------------------------------------
# the deterministic speech tidy (every path ends here; nothing of meaning is removed)
_ACRONYMS = {"MGNREGA", "NREGA", "PMAY", "PMAY-G", "FY", "SC", "ST", "OBC", "CM", "DBT", "AI", "ID", "GP", "BPL", "APL",
             "SECC", "IAY", "MIS", "PG", "PGS", "SHG", "SHGS", "C&RD", "KRIDL", "NIC", "PFMS", "IFSC", "UPI", "RTI",
             "PDO", "BDO", "DC", "IT", "OK", "MLA", "MP", "GST", "PAN", "LGD", "II", "III", "IV", "PMAYG", "NRLM",
             "MSRLS", "MBDA", "IAS", "SDO", "NGO", "FPO", "FPOS", "JJM", "USA", "UK", "API", "SQL", "PDF"}
_CAPS_WORD = re.compile(r"\b[A-Z][A-Z'\-]*[A-Z]\b")
_REPORT_OPEN = re.compile(r"(?i)^(?:the|this|these)\s+(?:following\s+)?(?:(?:donut|pie|bar|line|horizontal(?:\s+bar)?|"
                          r"stacked(?:\s+bar)?|column)\s+)?(?:chart|graph|briefing|table|visual(?:isation|ization)?|"
                          r"summary|map|ranking|breakdown|report|answer|data|figure|list|line)s?\s+(?:above\s+|below\s+)?"
                          r"(?:displays?|shows?|outlines?|presents?|illustrates?|depicts?|highlights?|lists?|gives?|"
                          r"provides?|compares?|details?|covers?|summari[sz]es?|ranks?|breaks?\s+down)\s+(?:that\s+)?")
_REPORT_MID = [(re.compile(r"(?i)\bas per the data,?\s*"), ""), (re.compile(r"(?i)\baccording to the data,?\s*"), "")]
_BRACKET = re.compile(r"\s*\(([^()]{1,140})\)")
_SLASH = re.compile(r"\s+/\s+")
_NOTE = re.compile(r"(?:^|(?<=[.!?]\s))(?:Note|NB|N\.B\.|Please note)\s*:\s*", re.I)
_COLON = re.compile(r":\s+")
_AFTER_DASH = re.compile(r", (It|The|This|That|These|Those|They|There|A|An|In|For|With|Its|Their|Each|Every|All)\b")


def _blocks() -> list[str]:
    try:
        return _domain.block_names() if _domain else []
    except Exception:  # noqa: BLE001
        return []


def _caps_fix(t: str) -> str:
    # districts and blocks written in capitals get their own spelling ("DAMBO RONGJENG" -> "Dambo Rongjeng"): a TTS may
    # spell a word in capitals letter by letter
    dists = {d.upper(): d for d in _blocks() + _districts() if "-" not in d}
    schemes_up = {s.upper() for s in _schemes()}

    def run(m):
        g = m.group(0)
        return dists.get(g, g.title() if g.title() in dists.values() else g)
    t = _CAPS_RUN.sub(run, t)
    # a district alone in capitals (RI BHOI is two words; "TURA" one)
    for up, d in dists.items():
        t = re.sub(r"\b" + re.escape(up) + r"\b", d, t)

    def word(m):
        w = m.group(0)
        if w in _ACRONYMS or w in schemes_up or any(w in s.split() for s in schemes_up) or len(w) <= 3:
            return w
        # an ordinary word written in capitals for emphasis (PRODUCER GROUPS, INDIVIDUAL) is lower-cased; a name or an
        # acronym (PM-KISAN, KRIDL, MGNREGA: few vowels, a hyphen) stays as it is
        letters = w.replace("'", "")
        vowels = sum(ch in "AEIOU" for ch in letters)
        if "-" in w or len(letters) < 6 or vowels / len(letters) < 0.3:
            return w
        return w.lower()
    t = _CAPS_RUN.sub(lambda m: m.group(0).lower() if all(x not in _ACRONYMS and x not in schemes_up
                                                          for x in m.group(0).split()) else m.group(0), t)
    return _CAPS_WORD.sub(word, t)


_MONTH = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December"]
_ISO = re.compile(r"(?<![\w-])((?:19|20)\d\d)-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])(?![\w-])")


def iso_dates(text: str) -> str:
    """2021-04-01 -> April 2021 (the first of a month: a month of a series), 2021-04-15 -> 15 April 2021."""
    def rep(m):
        y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
        return f"{_MONTH[mo - 1]} {y}" if d == 1 else f"{d} {_MONTH[mo - 1]} {y}"
    return _ISO.sub(rep, text or "")


_YEAR_ROW = re.compile(r"^(?:[-*•]\s*)?(?:(?:FY\s?)?(?:19|20)\d\d\s?[-–]\s?\d{2,4}|(?:19|20)\d\d-\d\d-\d\d|"
                       r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
                       r"\s+(?:19|20)\d\d)\s*[:—–-]\s*(?:about\s+)?(?:₹\s?)?[\d,.]+(?:\s?(?:crore|lakh|%))?\.?$", re.I)
_MORE_LINE = re.compile(r"^and \d+ more (?:rows? )?(?:is|are) on your screen\.?$", re.I)


def trend_summary(speak: str) -> str | None:
    """A trend answer = a summary sentence with its figures + the year-by-year points read as rows + a screen
    mention. The points are on the screen (the checked text says so): the voice says the summary and points to the
    screen for the year-by-year figures. None when the answer is not that shape."""
    lines = [ln.strip() for ln in (speak or "").split("\n") if ln.strip()]
    rows = [ln for ln in lines if _YEAR_ROW.match(ln)]
    if len(rows) < 2 or "on your screen" not in (speak or "").lower():
        return None
    prose = [ln for ln in lines if not _YEAR_ROW.match(ln) and not _MORE_LINE.match(ln)]
    rest = [ln for ln in prose if "on your screen" in ln.lower()]
    prose = [ln for ln in prose if "on your screen" not in ln.lower()]
    if len(content_figures(" ".join(prose))) < 2:
        return None
    prose = [p if p[-1:] in ".!?" else (p[:-1] + "." if p.endswith(":") else p + ".") for p in prose]
    monthly = any(re.search(r"\d{4}-\d\d-\d\d|January|February|March|April|May|June|July|August|September|October|"
                            r"November|December", r) for r in rows)
    return "\n".join(prose + (rest or []) + [f"The {'month' if monthly else 'year'}-by-{'month' if monthly else 'year'}"
                                             " figures are on your screen."])


def _report_open(m) -> str:
    g = m.group(0).lower()
    if g.rstrip().endswith(" that"):
        return ""                                     # "The data shows that 0.00% of ..." -> "0.00% of ..."
    if "compare" in g:
        return "Here's a comparison of "
    if "rank" in g:
        return "Here's a ranking of "
    if "break" in g:
        return "Here's a breakdown of "
    return "Here's "


# ---------------------------------------------------------------------------------------------------------------------
# the page's own screen notes, which mean nothing said aloud (the voice never reads them; 12 Nov 2026)
_VOICE_NOTES = [
    (re.compile(r"\s*\(Drawn here from the answer above; it is not saved with the chat\.?\)", re.I), ""),
    # "Showing results for Amlarem (you typed 'Amalram')." is the screen's spelling note: the officer SPOKE, and the
    # answer itself names the place ("PMAY-G — Amlarem block, ..."). Said as "I took that as Amlarem" the model turned
    # it into "Sorry, sir, I meant Amlarem block", so the voice leaves it out.
    (re.compile(r"(?m)^\s*Showing results for (.+?) \(you typed [‘'\"“][^’'\"”]*[’'\"”]\)\.?\s*$", re.I), ""),
    (re.compile(r"\b(?:year|fy) key:\s*\d{4},\s*", re.I), ""),          # the brain's internal row key
]


def voice_notes(text: str) -> str:
    t = text or ""
    for rx, rep in _VOICE_NOTES:
        t = rx.sub(rep, t)
    return t.strip()


# ---------------------------------------------------------------------------------------------------------------------
# the deterministic spoken structure: rows and lists said as sentences. Figures, names and words are all kept (every
# figure stays beside its own name / year by construction); the model gets this as its input, and it is the fallback.
_FIGTXT = r"(?:about\s+)?(?:₹\s?)?\d(?:[\d,]*\d)?(?:\.\d+)?(?:\s?(?:crore|lakh|%))?(?:\s+[a-z][a-z\-]*(?:\s+[a-z][a-z\-]*)?)?"
_ITEM = re.compile(r"^\s*\d{1,2}[.)]\s+(?P<name>[A-Za-z][^:—–\d]{0,60}?)\s*(?:—|–|-|:)?\s*(?P<fig>" + _FIGTXT + r")\s*\.?$")
_ROW_FY = re.compile(r"^(?:[-*•]\s*)?(?P<when>(?:FY\s?)?(?:19|20)\d\d\s?[-–]\s?\d{2,4}|(?:January|February|March|April|May|"
                     r"June|July|August|September|October|November|December)\s+(?:19|20)\d\d)\s*[:—–-]\s*"
                     r"(?P<fig>(?:about\s+)?(?:₹\s?)?[\d,.]+(?:\s?(?:crore|lakh|%))?)\.?$", re.I)
_HEAD_LINE = re.compile(r"^(?P<where>[A-Z][A-Za-z ,'\-]{2,80}?),\s+(?P<when>all financial years|each financial year[a-z ]*|"
                        r"(?:FY\s?)?(?:19|20)\d\d\s?[-–]\s?\d{2,4})$")
_ONE_FIG_BRACKET = re.compile(r"(?<=[A-Za-z])\s\(((?:about\s+)?(?:₹\s?)?\d[\d,]*(?:\.\d+)?(?:\s?(?:crore|lakh|%))?)\)")


_FIG1 = r"(?:about\s+)?(?:₹\s?)?\d(?:[\d,]*\d)?(?:\.\d+)?(?:\s?(?:crore|lakh|%))?"
_MONEY_LABEL = re.compile(r"(?i)expenditure|amount|money|sanctioned|released|remaining|disbursed|paid|subsidy|loan|wage")
_ROW_MEASURE = re.compile(r"(?:(?<=—\s)|(?<=,\s)|(?<=:\s)|^)(?P<lab>[a-z][a-z ]{2,30}?):\s+(?P<fig>" + _FIG1 + r")")


def _one_fig(m) -> str:
    """'(3.4%)' -> ', or 3.4%,'; '(about ₹886.29 crore)' -> ', that's about ₹886.29 crore,'; '(14,94,437)' -> ', at 14,94,437,'"""
    f = m.group(1)
    if f.endswith("%"):
        return ", or " + f + ","
    if f.startswith("about"):
        return ", that's " + f + ","
    return ", at " + f + ","


def _row_measures(ln: str) -> str:
    """A row of 'measure: figure' pairs said as speech: 'person days: 9,09,15,181, household years: 14,94,437' ->
    '9,09,15,181 person days, 14,94,437 household years'; a money measure -> 'total expenditure of ₹3,628.67 crore'.
    Only when the line holds two or more such pairs (a row), each figure staying beside its own measure."""
    if len(_ROW_MEASURE.findall(ln)) < 2:
        return ln

    def rep(m):
        lab, fig = m.group("lab").strip(), m.group("fig")
        if _MONEY_LABEL.search(lab) and not re.fullmatch(r"[a-z]+ed|remaining|pending", lab):
            return f"{lab} of {fig}"                      # "total expenditure of ₹3,628.67 crore"
        return f"{fig} {lab}"                             # "9,09,15,181 person days", "about ₹30.00 crore released"
    return _ROW_MEASURE.sub(rep, ln)


def _items_sentence(items: list[tuple[str, str]]) -> str:
    parts = [f"{n.strip()} with {f.strip()}" for n, f in items]
    if len(parts) == 1:
        return parts[0] + "."
    return ", then ".join(parts[:-1]) + ", and " + parts[-1] + "."


_LABEL_LINE = re.compile(r"^(?P<lab>[A-Za-z][A-Za-z+\- ]{1,40}?):\s+(?P<rest>(?:about\s+)?(?:₹\s?)?\d.*)$")


def _label_line(ln: str, schemes: set, places: set) -> str:
    """'MGNREGA: 14,94,437 households given work' -> 'MGNREGA has 14,94,437 households given work' (a scheme or a
    place as the label only)."""
    m = _LABEL_LINE.match(ln)
    if m and (m.group("lab").lower() in schemes or m.group("lab").lower() in places):
        return f"{m.group('lab')} has {m.group('rest')}"
    return ln


def restructure(text: str) -> str:
    """Rows and lists of the checked answer as spoken sentences:
    '1. WEST GARO HILLS — 35,039 / 2. ... ' -> 'WEST GARO HILLS with 35,039, then ..., and ...';
    year rows (up to four, the screen not mentioned) -> 'It was 54,89,616 in FY 2023-24, ... and ... in FY 2025-26.';
    'MGNREGA: 14,94,437 households given work' -> 'MGNREGA has 14,94,437 households given work.';
    'All of Meghalaya, all financial years' (a heading) -> 'For all of Meghalaya, over all financial years, <next line>';
    'Next: South Garo Hills (9,969), then ...' -> 'Next comes South Garo Hills, at 9,969, then ...'.
    Kept only when every figure and word survives (meaning_kept); else the text as it was."""
    src = iso_dates(text or "")
    lines = [ln.strip() for ln in src.split("\n") if ln.strip()]
    # inline numbered items "...: 1. A ₹x; 2. B ₹y; 3. ..." -> one line each
    exp = []
    for ln in lines:
        if re.search(r";\s+\d{1,2}[.)]\s", ln):
            head, _, rest = ln.partition(": 1. ") if ": 1. " in ln else ("", "", ln)
            pieces = re.split(r";\s+(?=\d{1,2}[.)]\s)", ("1. " + rest) if head else rest)
            if head:
                exp.append(head + ":")
            exp.extend(p.strip() for p in pieces if p.strip())
        else:
            exp.append(ln)
    lines = exp
    schemes = {s.lower() for s in _schemes()}
    places = {p.lower() for p in _districts() + _blocks()}
    out: list[str] = []
    i = 0
    screen = "on your screen" in src.lower()
    while i < len(lines):
        ln = lines[i]
        # numbered items
        items = []
        j = i
        while j < len(lines):
            m = _ITEM.match(lines[j])
            if not m:
                break
            items.append((m.group("name"), m.group("fig")))
            j += 1
        if len(items) >= 2:
            sent = _items_sentence(items)
            if out and out[-1].endswith(":"):
                out[-1] = out[-1][:-1] + ": " + sent
            else:
                out.append(sent)
            i = j
            continue
        # year rows
        rows = []
        j = i
        while j < len(lines):
            m = _ROW_FY.match(lines[j])
            if not m:
                break
            rows.append((m.group("when"), m.group("fig")))
            j += 1
        if 2 <= len(rows) <= 4 and not (screen and len(rows) == len([x for x in lines if _ROW_FY.match(x)]) and
                                        trend_summary(src)):
            parts = [f"{f} in {w}" for w, f in rows]
            sent = "It was " + (parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]) + "."
            if out and out[-1].endswith(":"):
                out[-1] = out[-1][:-1] + "."
            out.append(sent)
            i = j
            continue
        ln = _label_line(ln, schemes, places)
        # a heading line: "All of Meghalaya, all financial years", "Dalu block, all financial years"
        m = _HEAD_LINE.match(ln)
        if m and i + 1 < len(lines) and not re.search(r"\d", m.group("where")):
            where = m.group("where")
            where = where[0].lower() + where[1:] if where.split()[0] in ("All", "Each") else where
            when = m.group("when")
            lead = f"For {where}, over {when}," if when.startswith("all ") else f"For {where}, {when},"
            out.append(lead)
            i += 1
            nxt = _label_line(lines[i], schemes, places)
            if out and nxt and nxt[0].isupper() and nxt.split()[0].lower() in ("the", "this", "there", "each", "in"):
                nxt = nxt[0].lower() + nxt[1:]
            out[-1] = out[-1] + " " + nxt
            # the line after the heading may itself be a label line or a list: run it through again
            lines[i] = out.pop()
            continue
        ln = re.sub(r"^Next:\s+", "Next comes ", ln)
        ln = _ONE_FIG_BRACKET.sub(_one_fig, ln)
        ln = _row_measures(ln)
        ln = re.sub(r"(?P<s>" + "|".join(re.escape(x) for x in _schemes()) + r")\s+(?P<a>" + _FIG1 + r")\s+/\s+(?P<b>"
                    + _FIG1 + r")", lambda mm: f"{mm.group('s')} with {mm.group('a')} and {mm.group('b')}", ln)
        out.append(ln)
        i += 1
    res = "\n".join(out)
    res = re.sub(r",\s*([.;:])", r"\1", res)
    res = re.sub(r"(\d)x\b", r"\1 times", res)
    return res if not meaning_kept(src, res) else src


def speakable(text: str, brackets: bool = True) -> str:
    """The checked answer as it is best SAID with its own words: line breaks become sentence ends, ALL-CAPS words
    normal case, dashes / slashes / brackets / label colons commas, report-speak openers "Here's", "Note:" "Note that",
    list numbering off. No figure, name or caveat word is removed (meaning_kept)."""
    text = restructure(text)
    lines = [ln.strip() for ln in iso_dates(text).split("\n") if ln.strip()]
    out = []
    join_next = False
    for ln in lines:
        ln = _LIST_MARK.sub("", ln).strip()
        if ln.startswith(("- ", "* ", "• ")):
            ln = ln[2:].strip()
        head = ln.endswith(":") and len(ln.split()) <= 6          # "FY 2022-23:" heads the line under it
        if ln and ln[-1] not in ".!?;,":
            ln = ln[:-1] + ("," if head else ".") if ln[-1] == ":" else ln + "."
        if join_next and out:
            out[-1] = out[-1] + " " + ln
        else:
            out.append(ln)
        join_next = head
    t = " ".join(out)
    t = _caps_fix(t)
    # a dash before a new clause is a sentence end when said ("I'm Megh One AI — I help with ..." -> "... AI. I help
    # with ..."; "— just ask." -> ". Just ask."); other dashes are commas
    t = re.sub(r"\s+[—–]\s+(i|i'm|i've|i'll|we|you|just|it|it's|this|that|that's|there|they|he|she)\b",
               lambda m: ". " + m.group(1)[0].upper() + m.group(1)[1:], t, flags=re.I)
    t = t.replace(" — ", ", ").replace(" – ", ", ").replace("—", ", ").replace(" -- ", ", ")
    t = _AFTER_DASH.sub(lambda m: ", " + m.group(1).lower(), t)
    t = re.sub(r"(?<=[A-Za-z]) [−-] (?=[A-Za-z])", " minus ", t)          # "(sanctioned − released)"
    t = _SLASH.sub(", ", t)
    t = re.sub(r"\s+\|\s+", "; ", t)                                      # "MGNREGA 1,06,136 | PMAY-G 16,899"
    t = re.sub(r"\s+in \(row\)", "", t)                                   # the brain's empty label "to 126 in (row)"
    t = _LIST_MARK.sub("", t)                                           # "...: 1. West Garo Hills 2,61,666; 2. ..."
    t = re.sub(r"\s*→\s*", ", led by ", t)                                # "Total ₹538.24 crore → MGNREGA"
    t = _NOTE.sub("Note that ", t)
    t = re.sub(r"(?i)\be\.g\.,?(?=\s)", "for example,", t)              # said as "e g" otherwise
    t = re.sub(r"(?i)\bi\.e\.,?(?=\s)", "that is,", t)
    if brackets:
        t = _BRACKET.sub(lambda m: ", " + m.group(1).strip() + ",", t)
    t = _COLON.sub(lambda m: ", ", t)
    sents = []
    for s in sentences(t):
        s = _REPORT_OPEN.sub(_report_open, s)
        for rx, rep in _REPORT_MID:
            s = rx.sub(rep, s)
        if s and s[0].islower():
            s = s[0].upper() + s[1:]
        sents.append(s)
    t = " ".join(sents)
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r",(\s*,)+", ",", t)
    t = re.sub(r",\s*([.!?;])", r"\1", t)
    t = re.sub(r"([.!?])\s*,", r"\1", t)
    t = re.sub(r"\.\s*\.", ".", t)
    t = re.sub(r"\b([A-Z][\w\-]+(?: [A-Z][\w\-]+){0,3}), \1\b", r"\1", t)   # "PMAY-G / PMAY-G —" -> one "PMAY-G"
    t = re.sub(r"\s+", " ", t).strip()
    return t


def tidy(text: str) -> str:
    """Kept for callers of round 2: the speech tidy."""
    return speakable(text)


_REMOVABLE = {"displays", "outlines", "shows", "presents", "illustrates", "depicts", "highlights", "lists", "gives",
              "provides", "the", "this", "chart", "graph", "briefing", "table", "visual", "visualisation",
              "visualization", "summary", "map", "ranking", "breakdown", "report", "answer", "data", "figure",
              "donut", "pie", "bar", "line", "horizontal", "stacked", "column", "above", "below", "nb", "n", "b",
              "as", "per", "according", "to", "charts", "graphs", "tables", "figures", "these", "following", "list",
              "lines", "display", "displays", "compares", "compare", "details", "detail", "covers", "cover",
              "summarises", "summarizes", "ranks", "rank", "breaks", "break", "down", "that", "show", "outline",
              "present", "presents", "lists", "row", "e", "g"}         # "e.g." is said "for example"                     # "row": the brain's empty label "in (row)"


def meaning_kept(src: str, out: str) -> str:
    """'' when `out` keeps every figure, every name and every caveat word of `src` (a speech tidy or a frame may only
    ADD a frame and change punctuation / case / a report-speak opener); else what was lost."""
    if figures(src) - figures(out):
        return f"figures lost: {sorted(figures(src) - figures(out))}"
    lost = _vocab(src) - _vocab(out) - _REMOVABLE
    if lost:
        return f"words lost: {sorted(lost)}"
    return ""


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_END.split(text or "") if s.strip()]


# ---------------------------------------------------------------------------------------------------------------------
# the warm frames (no model)
FRAMES = {
    "denied": ["I'm sorry, sir.", "Ah, I'm sorry, sir.", "Sorry, sir."],
    "refuse": ["Sorry, sir.", "I'm sorry, sir.", "Ah, I'm sorry, sir."],
    "unknown": ["Sorry, sir.", "Hmm, sorry, sir.", "I'm sorry, sir."],
    "knowledge": ["Sure, sir.", "Right, sir.", "Of course, sir.", "Good question, sir."],
    "data": ["Sure, sir.", "Right, sir.", "Okay, sir.", "Here's what I have, sir."],
    "clarify": ["Just to be sure, sir.", "Quick check, sir.", "Sure, sir."],
    "note": ["", "Sorry, sir."],
}
_SORRY_HINTS = ("can't", "cannot", "can not", "don't have", "do not have", "unable", "not able", "against the rules",
                "breaks the rules", "not allowed", "don't write", "only know", "not authorised", "not authorized",
                "couldn't", "could not", "no data", "not available", "isn't available", "requires data")


def frame_kind(kind: str, text: str) -> str:
    low = text.lower()
    if kind == "view":
        return "plain"
    if kind == "denied" or "authorised up to" in low or "authorized up to" in low:
        return "denied"
    if kind in ("edge", "refusal", "refused", "blocked", "out_of_scope", "error"):
        if any(h in low for h in ("can't", "cannot", "rules", "don't write", "not allowed", "won't", "stay neutral")):
            return "refuse"
        if any(h in low for h in _SORRY_HINTS):
            return "unknown"
        return "plain"                                    # small talk the brain answered ("You're welcome!", "Hello!")
    if kind == "knowledge":
        return "unknown" if any(h in low for h in ("do not contain", "doesn't contain", "don't have", "no single")) \
            else "knowledge"
    if kind == "clarification":
        return "clarify"
    if kind == "note":
        return "note" if any(h in low for h in _SORRY_HINTS + ("did not catch", "didn't catch")) else ""
    if kind in RESAY_KINDS and any(h in low for h in _SORRY_HINTS + ("couldn't build", "could not build")):
        return "unknown"                              # a data answer that is a failure ("couldn't build a working query")
    return "data"


def framed(speak: str, kind: str, turn: int = 0) -> str:
    """A warm frame around the checked words (kept verbatim apart from the speech tidy)."""
    body = speakable(speak, brackets=kind != "clarification")
    fk = frame_kind(kind, body)
    if kind == "view" and body.lower().startswith("here it is"):
        lead = ["There you go, sir.", "Done, sir.", "Sure, sir."][turn % 3]
        if "sir" in _vocab(body):
            lead = lead.replace(", sir", "")
        return f"{lead} {body}"
    if fk == "plain":
        return _sir_short(body, 8)
    opts = FRAMES.get(fk) or [""]
    lead = opts[turn % len(opts)] if fk != "note" else (opts[1] if fk else "")
    low = body.lower()
    if not lead or low.startswith(("sorry", "i'm sorry", "sure", "right", "okay", "yes", "hello", "here")):
        return body
    if "sir" in _vocab(body):
        lead = lead.replace(", sir", "").replace(" sir", "")
        lead = lead if lead.endswith((".", "!", "?")) else lead + "."
    return f"{lead} {body}".strip()


_CLAR_YEARS = re.compile(
    r"^For (?P<s>[^,]{2,40}), data is available only for the financial years (?P<list>[\d\-–, ]+)\.\s+"
    r"(?:No data is held for [“\"']?(?P<miss>[^”\"'.]+)[”\"']?\.|(?P<miss2>FY \d{4}-\d\d) has no data yet\.)\s+"
    r"Please select one of the financial years listed above, or all of them combined\.\s+The options are (?P<opts>.+?)"
    r"(?:\.\s+There (?:are|is) \d+ more on your screen)?\.?$", re.S)


def clarify_years(speak: str, turn: int = 0) -> str | None:
    """The year clarification ('For Focus Legacy, data is available only for the financial years 2021-22, 2022-23 ...
    No data is held for "2023-24". Please select one of the financial years listed above, or all of them combined. The
    options are FY 2021-22, ... or All available years combined.') said once, warmly, by rule: the model, given the
    list twice, garbled it (an option named twice, a year tag reused for 'all years combined'). Every year and every
    option is kept; the years the screen holds are all in the first list, so nothing is lost by saying it once."""
    m = _CLAR_YEARS.match(" ".join((speak or "").split()))
    if not m:
        return None
    years = [y.strip() for y in re.split(r",\s*", m.group("list")) if y.strip()]
    if not years or not all(re.fullmatch(r"(?:19|20)\d\d\s?[-–]\s?\d\d", y) for y in years):
        return None
    said = [f"FY {y}" for y in years]
    lst = said[0] if len(said) == 1 else ", ".join(said[:-1]) + " and " + said[-1]
    miss = (m.group("miss") or m.group("miss2") or "").strip()
    gap = (f"no data is held for {miss}" if m.group("miss") else f"{miss} has no data yet") if miss else ""
    combined = "all the available years combined" if "all available years combined" in m.group("opts").lower() \
        else "all of them combined"
    lead = ["Just so you know, sir,", "Right, sir,", "Ah, sir,"][turn % 3]
    first = f"{lead} for {m.group('s')} I only have data for {lst}" + (f", and {gap}." if gap else ".")
    ask = (f"Which year would you like, or shall I take {combined}?" if len(said) > 1
           else f"Shall I take {said[0]}, or {combined}?")
    return first + " " + ask


def _sir_short(body: str, max_words: int = 14) -> str:
    """'sir' at the end of a short first sentence ("West Garo Hills leads." -> "West Garo Hills leads, sir.";
    "You're welcome! Let me ..." -> "You're welcome, sir! Let me ..."), when the line does not say it yet."""
    ss = sentences(body)
    if not ss or "sir" in _vocab(body):
        return body
    first = ss[0]
    if len(first.split()) > max_words or first[-1:] not in ".!?" or first.endswith(("...", "?")) and len(ss) == 1:
        return body
    ss[0] = first[:-1].rstrip(",") + ", sir" + first[-1]
    return " ".join(ss)


# ---------------------------------------------------------------------------------------------------------------------
# slots: the figures cut out, the model writes around them, the figures put back by code
_YSPAN = re.compile(r"(?<![\w₹.,])(?:FY\s?)?(?:19|20)\d\d\s?[-–]\s?(?:(?:19|20)\d\d|\d\d)(?![\d%.,]\d|\d|\s?%)")
_FIG = re.compile(r"(?:₹\s?|(?<![A-Za-z])Rs\.?\s?|(?<![A-Za-z])INR\s?)?[+\-−]?\d[\d,]*(?:\.\d+)?"
                  r"(?:\s?(?:crore|lakh|cr\b|%|per\s?cent|x\b|times\b|K\b))?", re.I)
_TAG = re.compile(r"\[([NY])(\d{1,2})\]")
_NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                 "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty",
                 "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "lakh",
                 "lakhs", "crore", "crores", "million", "billion", "percent", "rupee", "rupees", "half", "double",
                 "twice", "triple", "dozen", "per", "cent", "fy"}


def slot(text: str) -> tuple[str, dict[str, str]]:
    """`text` with every year span / year and every figure (rupee sign, sign, digits, unit) replaced by a tag; the same
    literal twice gets the same tag. Returns (templated text, {tag: literal})."""
    tags: dict[str, str] = {}
    by_lit: dict[str, str] = {}
    out, i, n_y, n_n = [], 0, 0, 0
    t = text
    while i < len(t):
        m = _YSPAN.match(t, i) if (i == 0 or not t[i - 1].isalnum()) else None
        kind = "Y"
        if not m:
            m = _FIG.match(t, i) if t[i] in "₹R+-−0123456789I" and (i == 0 or not (t[i - 1].isalnum() or t[i - 1] in ".,")) else None
            kind = "N"
            if m and not re.search(r"\d", m.group(0)):
                m = None
            if m:
                lit = m.group(0).rstrip(",.")
                if re.fullmatch(r"(?:19|20)\d\d", lit):
                    kind = "Y"
        if not m:
            out.append(t[i])
            i += 1
            continue
        lit = m.group(0).rstrip(",.")
        end = i + len(lit)
        key = lit
        if key not in by_lit:
            if kind == "Y":
                n_y += 1
                tag = f"[Y{n_y}]"
            else:
                n_n += 1
                tag = f"[N{n_n}]"
            by_lit[key] = tag
            tags[tag] = lit
        out.append(by_lit[key])
        i = end
    return "".join(out), tags


def fill(templ: str, tags: dict[str, str]) -> str:
    return _TAG.sub(lambda m: tags.get(m.group(0), m.group(0)), templ)


def slot_check(reply: str, templ: str, tags: dict[str, str]) -> str:
    """The model's reply (with tags) against the templated answer: every tag used, no unknown tag, no digit and no
    number word / unit word of its own, every tag at most as often as the answer has it (+1 for a label it repeats)."""
    used = _TAG.findall(reply)
    used_tags = [f"[{a}{b}]" for a, b in used]
    unknown = sorted(set(used_tags) - set(tags))
    if unknown:
        return f"unknown tag(s) {unknown}: use only the tags of the checked answer"
    missing = [tg for tg in tags if tg not in used_tags]
    if missing:
        return "these tags were left out: " + ", ".join(missing)
    for tg in tags:
        if used_tags.count(tg) > templ.count(tg) + (1 if tg.startswith("[Y") else 0):
            return f"the tag {tg} is said more often than in the checked answer"
    bare = _TAG.sub(" ", reply)
    if re.search(r"\d", bare) or "₹" in bare or "%" in bare:
        return "you wrote a number of your own; write figures only as their tags"
    own = (_vocab(bare) & _NUMBER_WORDS) - _vocab(_TAG.sub(" ", templ))
    if own:
        return f"you wrote the number / unit word(s) {sorted(own)} yourself; the tags already say them"
    if any(ch in bare for ch in "*#_|<>{}[]"):
        return "markup"
    return ""


# ---------------------------------------------------------------------------------------------------------------------
# the guard on the filled text (round 2/3, kept)
def sentence_ok(sent: str, src_figs: set, src_vocab: set) -> tuple[bool, str]:
    for f in figures(sent):
        if f not in src_figs:
            return False, f"figure {f} is not in the checked answer"
    extra = _names(sent) - src_vocab - _ALLOWED_NAMES
    if extra:
        return False, f"name(s) {sorted(extra)} are not in the checked answer"
    if any(ch in sent for ch in "*#_|<>{}[]"):
        return False, "markup"
    return True, ""


def content_figures(text: str) -> list[str]:
    """Figures that are not years or year ends (2022-23, FY 2017-18, 2023-2024)."""
    out = []
    t = _LIST_MARK.sub("", iso_dates(text or ""))
    for m in _NUM.finditer(t):
        n = m.group(3).replace(",", "")
        prev = t[max(0, m.start() - 1):m.start()]
        if len(n) == 4 and n[:2] in ("19", "20") and "." not in n:
            continue
        if m.group(2) in ("-", "–") and prev.isdigit() and len(n) in (2, 4):
            continue
        out.append(n)
    return out


def content_spans(text: str) -> list[tuple[int, int]]:
    out = []
    for m in _NUM.finditer(text or ""):
        n = m.group(3).replace(",", "")
        prev = text[max(0, m.start() - 1):m.start()]
        if len(n) == 4 and n[:2] in ("19", "20") and "." not in n:
            continue
        if m.group(2) in ("-", "–") and prev.isdigit() and len(n) in (2, 4):
            continue
        e = m.end()
        while e > m.start() and text[e - 1] in ",.":       # "38,77,036," -> "38,77,036" (the key must match)
            e -= 1
        out.append((m.start(), e))
    return out


def is_row_dump(speak: str) -> bool:
    low = (speak or "").lower()
    if " results:" in low or "here are the" in low and " results" in low:
        return True
    if " / " in speak and ("—" in speak or " - " in speak) and re.search(r"\d", speak.split(" / ", 1)[1][:40]):
        return True                                       # "MGNREGA / 2022-2023 — ..." rows
    if "year key" in low or "fy key" in low:
        return True
    cut = low.find("the rest of the answer is on your screen")
    if cut > 0:
        before = speak[:cut].rstrip()
        if before and before[-1] not in ".!?:)":
            return True                                   # cut off mid-row
    return len(content_figures(speak)) > MAX_SLOTS


_ROW_SPLIT = re.compile(r";\s+(?=\d{1,2}[.)]\s)")        # "1. A 5; 2. B 4" -> items; a "|" row stays whole (its head)
_REST_RX = re.compile(r"\s*The rest of the answer is on your screen\.?\s*$", re.I)
TRIM_FIGS = int(os.environ.get("FDX_MEGH_NATURAL_TRIM_FIGS", "6"))


def trim_rows(speak: str, max_figs: int = TRIM_FIGS) -> str | None:
    """A long row answer that ITSELF says the rest is on the screen -> its first whole rows (at most `max_figs`
    figures) + "The rest is on your screen." Never cuts inside a row; a row the page cut off mid-way is dropped.
    None when the answer does not mention the screen or nothing would be left out."""
    if "on your screen" not in (speak or "").lower():
        return None
    m = _REST_RX.search(speak)
    body = speak[:m.start()] if m else speak
    # units: (line, piece). A numbered item is a line of its own; a "|" row is cut only between its pieces, and the
    # pieces kept stay on their row's line (so each figure keeps its row head: its district)
    units: list[tuple[int, str]] = []
    ln = 0
    for line in body.split("\n"):
        for item in _ROW_SPLIT.split(line):
            if not item.strip():
                continue
            for piece in re.split(r"\s+\|\s+", item.strip()):
                if piece.strip():
                    units.append((ln, piece.strip()))
            ln += 1
    if m and units and units[-1][1][-1:] not in ".!?)":
        units.pop()                                       # the row the page cut off mid-way
    keep: list[tuple[int, str]] = []
    n, data_units = 0, 0
    for u in units:
        k = len(content_figures(u[1]))
        if keep and n + k > max_figs and data_units >= 1:
            break
        keep.append(u)
        n += k
        data_units += k >= 2 or (k == 1 and "result" not in u[1].lower())   # a header's count is not a row
    if len(keep) == len(units) and not m:
        return None
    if not any(content_figures(p) for _, p in keep):
        return None
    lines: dict[int, list[str]] = {}
    for i, p in keep:
        lines.setdefault(i, []).append(p)
    out = [" | ".join(v) for _, v in sorted(lines.items())]
    tail = "" if "on your screen" in out[-1].lower() else "\nThe rest is on your screen."
    return "\n".join(out) + tail


def effective_answer(speak: str, kind: str) -> str:
    """The checked answer the voice works from: a trend whose year-by-year points are on the screen is its summary
    (trend_summary); a long row answer that says the rest is on the screen is its first rows (trim_rows); anything
    else is itself. The page's screen notes are dropped first (voice_notes)."""
    rows = is_row_dump(speak)                         # judged on the page's own text (its "year key" marks a dump)
    speak = voice_notes(speak)
    if kind in RESAY_KINDS:
        t = trend_summary(speak)
        if t:
            return t
    if kind in RESAY_KINDS and rows:
        t = trim_rows(speak)
        if t and len(content_figures(t)) <= MAX_SLOTS:
            return t
    return speak


def worth_it(speak: str, kind: str) -> bool:
    """Which answers go to the model (path 1): data answers that carry figures, and clarifying questions. The rest are
    framed (path 2) or said as they are (path 3)."""
    if not ON or not os.environ.get("FDX_LLM_URL") or len(speak) < 25:
        return False
    if kind == "clarification":
        return True
    if kind not in RESAY_KINDS or not content_figures(speak):
        return False                                  # a year alone ("e.g. PMAY-G sanctions for 2023") is no figure
    return not is_row_dump(speak)


def clean_reply(text: str) -> str:
    """The model's words, punctuation made speakable (a colon or a bracket is only a pause when said)."""
    t = " ".join((text or "").split())
    if t.startswith("SPOKEN:"):
        t = t[7:].strip()
    t = t.replace("—", ", ").replace(" – ", ", ")
    t = re.sub(r"(?<!\d):\s+", ", ", t)
    t = re.sub(r"\s*\(([^()]{1,80})\)", r", \1,", t)
    t = re.sub(r"\s+,", ",", t)
    t = re.sub(r",\s*([.!?;])", r"\1", t)
    t = re.sub(r",(\s*,)+", ",", t)
    return t.strip().strip('"').strip()


def check(reply: str, speak: str, question: str = "", raw: str = "") -> tuple[bool, str]:
    """The whole reply against the checked answer: every sentence passes, and every figure is said. `raw` = the
    checked answer before the speech tidy (its 'label: figure' pairs; the tidy turns colons into commas)."""
    src_figs, src_vocab = figures(speak), _vocab(speak) | _vocab(question)
    money = {(n, True, u) for n, r, u in src_figs if u in ("crore", "lakh")}     # "+29.77 crore" of a rupee series
    sents = sentences(reply)
    if not sents:
        return False, "empty"
    for s in sents:
        ok, why = sentence_ok(s, src_figs | money, src_vocab)
        if not ok:
            return False, why
    said = set()
    for s in sents:
        said |= _nums_said(s)
    missing = _nums(speak) - said
    if missing:
        return False, "these figures were left out: " + ", ".join(sorted(missing))
    out_vocab, src_words = _vocab(reply), _vocab(speak)
    if "screen" in out_vocab and "screen" not in src_words:
        return False, "the checked answer does not mention the screen, so you must not"
    low = reply.lower()
    for w in CAVEATS:                                # a caveat of the checked answer may not be dropped
        if w in ("about", "approximately") and not re.search(r"\b" + w + r"\s+(?:₹|\d|rs\b|inr\b)", speak, re.I):
            continue                                 # "which scheme is your question about?" is not a caveat
        if w in src_words and w not in out_vocab and not (w in ("not", "no") and ("n't" in low or "not" in out_vocab
                                                                                   or "no" in out_vocab or "without" in out_vocab)):
            return False, f"the checked answer's caveat with the word '{w}' was left out"
    for name in options_of(speak):                   # a clarifying question keeps every option, by its own name
        if not option_said(name, reply):
            return False, f"the option '{name}' was left out or renamed"
    bad = pairing_broken(reply, speak) or label_pairing_broken(reply, raw or speak) or link_broken(reply, speak) or \
        names_added(reply, speak) or qualifier_broken(reply, speak) or \
        direction_broken(reply, speak) or measure_broken(reply, speak, question)
    if bad:
        return False, bad
    if len(re.findall(r"\bsir\b", low)) > 1 + len(re.findall(r"\bsir\b", speak.lower())):
        return False, "say 'sir' only once"
    if len(reply) > max(170, int(len(speak) * 1.35)):
        return False, "longer than the checked answer"
    return True, ""


def option_said(name: str, reply: str) -> bool:
    """An option is said when its own words come in order, close together ("FY 2021-22" said as "2021-22" or "FY
    2021-22"; "All available years combined" as "all the available years combined"); a leading "the" / "FY" is
    optional."""
    low = reply.lower()
    nl = name.lower().strip()
    if nl in low or (nl.startswith("the ") and nl[4:] in low):
        return True
    want = [w for w in re.findall(r"[a-z0-9][a-z0-9'\-+]*", nl) if w not in ("the", "fy")]
    have = re.findall(r"[a-z0-9][a-z0-9'\-+]*", low)
    if not want:
        return False
    for i, w in enumerate(have):
        if w != want[0]:
            continue
        k, j = 1, i + 1
        while k < len(want) and j < len(have) and j - i <= len(want) + 2:
            if have[j] == want[k]:
                k += 1
            j += 1
        if k == len(want):
            return True
    return False


_FY = re.compile(r"\b(?:FY\s*)?(20\d\d)\s*[-–]\s*(?:20)?(\d\d)\b")


def _labels(segment: str) -> list[str]:
    low = segment.lower()
    out = [d.lower() for d in _districts() if d.lower() in low]
    out = [d for d in out if not any(d != o and d in o for o in out)]
    sch = _schemes()
    out += [x.lower() for x in sch if x.lower() in low and not any(x.lower() != y.lower() and x.lower() in y.lower()
                                                                    and y.lower() in low for y in sch)]
    out += [f"{a}-{b}" for a, b in _FY.findall(segment)]
    return out


def _label_spans(text: str) -> list[tuple[int, str]]:
    low = text.lower()
    spans = []
    for d in _districts():
        k = low.find(d.lower())
        while k >= 0:
            spans.append((k, d.lower(), len(d)))
            k = low.find(d.lower(), k + 1)
    for x in _schemes():
        k = low.find(x.lower())
        while k >= 0:
            spans.append((k, x.lower(), len(x)))
            k = low.find(x.lower(), k + 1)
    for m in _FY.finditer(text):
        spans.append((m.start(), f"{m.group(1)}-{m.group(2)}", m.end() - m.start()))
    keep = []
    for a in spans:
        if not any(b != a and b[0] <= a[0] and a[0] + a[2] <= b[0] + b[2] and b[2] > a[2] for b in spans):
            keep.append((a[0], a[1]))
    return sorted(set(keep))


_AFTER_LINK = ("in", "for", "during", "of", "at", "under", "from", "with")
_SKIP_AFTER = {"back", "then", "again", "just", "only", "right", "way", "by", "and"}
_UNIT_WORDS = {"crore", "lakh", "cr", "%", "percent", "per", "cent", "rupees", "houses", "person-days", "persons",
               "households", "beneficiaries", "members", "villages", "cards", "job", "days", "applications"}


def label_of(text: str, f_start: int, f_end: int, spans: list, figs: list) -> str | None:
    """The label a figure belongs to in this text: the district / scheme / financial year right after it when they are
    joined by in / for / during / of / at / under within three words ('₹886.29 crore in FY 2022-23'), else the nearest one
    before it in the same clause with no other figure between ('West Garo Hills is the largest with 33,147')."""
    tail = text[f_end:f_end + 60]
    words_after = tail.split()
    k = 0
    while k < len(words_after) and words_after[k].lower().strip(",.;:()") in _UNIT_WORDS:
        k += 1
    if k < len(words_after) and words_after[k].lower() in _AFTER_LINK:
        for pos, key in spans:
            if f_end < pos <= f_end + 60:
                between = text[f_end:pos]
                if not any(ch in between for ch in ".;\n") and len(between.split()) <= k + 3 and \
                        not any(f_end < fs < pos for fs, _ in figs):
                    return key
                break
    clause_start = max(text.rfind(".", 0, f_start), text.rfind(";", 0, f_start), text.rfind("\n", 0, f_start))
    before = [sp for sp in spans if clause_start < sp[0] < f_start]
    if before:
        pos, key = before[-1]
        if not any(pos < fs < f_start for fs, _ in figs):
            return key
    return None


def _typed_spans(text: str) -> list[tuple[int, int, str, str]]:
    """(start, end, type, key) of every place (district / block), scheme and financial-year mention, in order; a name
    inside a longer one of the same place ("West Garo Hills" in "South West Garo Hills") is dropped."""
    low = (text or "").lower()
    out = []
    for typ, names in (("place", _districts() + _blocks()), ("scheme", _schemes())):
        for nm in names:
            key = nm.lower()
            k = low.find(key)
            while k >= 0:
                e = k + len(key)
                if (k == 0 or not low[k - 1].isalnum()) and (e >= len(low) or not low[e].isalnum()):
                    out.append((k, e, typ, key))
                k = low.find(key, k + 1)
    for m in _FY.finditer(text or ""):
        out.append((m.start(), m.end(), "fy", f"{m.group(1)}-{m.group(2)}"))
    for m in _FY_RANGE.finditer(text or ""):            # "FY 2017-18 to FY 2023-24" is one label: the span of years
        out.append((m.start(), m.end(), "fy", f"{m.group(1)}-{m.group(2)}..{m.group(3)}-{m.group(4)}"))
    keep = [a for a in out if not any(b is not a and b[0] <= a[0] and a[1] <= b[1] and (b[1] - b[0]) > (a[1] - a[0])
                                      for b in out)]
    return sorted(set(keep))


_FY_RANGE = re.compile(r"\b(?:FY\s*)?(20\d\d)\s*[-–]\s*(?:20)?(\d\d)\s+(?:to|through|till|until|-|–)\s+"
                       r"(?:FY\s*)?(20\d\d)\s*[-–]\s*(?:20)?(\d\d)\b")


_SENT_BOUND = re.compile(r"[.!?](?=\s|$)")


def figure_labels(text: str, whole: bool = False) -> list[tuple[str, dict]]:
    """Every content figure of the text with its place / scheme / financial-year label: the one joined to it right
    after ("₹886.29 crore in FY 2022-23"), else the nearest one before it in the same sentence; with `whole`, else the
    nearest one before it anywhere (the reply: "MGNREGA leads. It has 14,94,437 ...")."""
    spans = _typed_spans(text)
    figs = content_spans(text)
    bounds = [m.end() for m in _SENT_BOUND.finditer(text)]
    out = []
    for fs, fe in figs:
        s0 = max([b for b in bounds if b <= fs], default=0)
        s1 = min([b for b in bounds if b > fe], default=len(text))
        labs = {}
        tail = text[fe:fe + 70].split()
        k = 0
        while k < len(tail) and (tail[k].lower().strip(",.;:()") in _UNIT_WORDS or
                                 (tail[k].lower() in _SKIP_AFTER and k + 1 < len(tail) and
                                  tail[k + 1].lower().strip(",") in _AFTER_LINK)):
            k += 1
        linked = k < len(tail) and tail[k].lower().strip(",") in _AFTER_LINK
        for typ in ("place", "scheme", "fy"):
            lab = None
            if linked:
                # the label right after the link word ("in FY 2022-23", "in the MGNREGA ...", "under Focus Plus")
                nxt = [sp for sp in spans if sp[2] == typ and fe < sp[0] <= min(s1, fe + 70)]
                if nxt and len(text[fe:nxt[0][0]].split()) <= k + 2 and not any(fe < a < nxt[0][0] for a, _ in figs):
                    lab = nxt[0][3]
            if lab is None:
                before = [sp for sp in spans if sp[2] == typ and s0 <= sp[0] < fs]
                if not before and whole:
                    before = [sp for sp in spans if sp[2] == typ and sp[0] < fs]
                if before:
                    lab = before[-1][3]
            if lab:
                labs[typ] = lab
        out.append((text[fs:fe].lstrip("₹+-−≈ ").strip(), labs))
    return out


_UPW = {"rose", "risen", "increase", "increased", "grew", "grown", "climbed", "jumped", "higher", "gained"}
_DOWNW = {"fell", "fallen", "decrease", "decreased", "declined", "dropped", "drop", "lower", "down", "decline"}


_MEASURE_WORDS = {"person-days", "person-day", "persondays", "households", "household", "houses", "house",
                  "beneficiaries", "beneficiary", "members", "member", "applications", "application", "payments",
                  "payment", "villages", "village", "workers", "worker", "persons", "person", "farmers", "farmer",
                  "groups", "group", "pgs", "cards", "card", "records", "record", "applicants", "applicant", "jobs",
                  "sanctioned", "released", "disbursed", "remitted", "completed", "loans",
                  "loan", "subsidy", "wages", "wage", "women", "blocks", "block"}


def _stem(w: str) -> str:
    w = w.lower().replace("person-days", "personday").replace("person-day", "personday")
    return w[:-1] if w.endswith("s") and len(w) > 3 else w


def measure_broken(reply: str, speak: str, question: str = "") -> str:
    """A measure the checked answer does not name ("2,24,663 person-days" when it said households given work)."""
    have = {_stem(w) for w in _vocab(speak) | _vocab(question)}
    extra = sorted({w for w in _vocab(reply) if w in _MEASURE_WORDS and _stem(w) not in have})
    return f"the measure word(s) {extra} are not in the checked answer" if extra else ""


def direction_broken(reply: str, speak: str) -> str:
    """A trend said the other way round ("rose" in the answer, "fell" in the reply), or a figure made a ceiling
    ("up to")."""
    sv, rv = _vocab(speak), _vocab(reply)
    if sv & _UPW and not sv & _DOWNW and rv & _DOWNW:
        return f"the checked answer goes up, you said {sorted(rv & _DOWNW)}"
    if sv & _DOWNW and not sv & _UPW and rv & _UPW:
        return f"the checked answer goes down, you said {sorted(rv & _UPW)}"
    if "up to" in reply.lower() and "up to" not in speak.lower():
        return "'up to' is not in the checked answer"
    strong = {"rose", "risen", "increased", "grew", "grown", "climbed", "jumped", "fell", "fallen", "decreased",
              "declined", "dropped", "dipped", "surged", "slumped"}
    if rv & strong and not sv & (_UPW | _DOWNW | strong):
        return f"the checked answer does not say it went up or down; you said {sorted(rv & strong)}"
    return ""


def pairing_broken(reply: str, speak: str) -> str:
    """Every figure keeps its OWN place, scheme and financial year (12 Nov 2026: a district row "East Khasi Hills:
    MGNREGA 2,24,663 | PMAY-G 23,952" was re-said as "... West Garo Hills has 23,952"): for each figure of the checked
    answer and each kind of label it has there, the reply must say it with that same label (figure_labels)."""
    # only where a figure COULD be given the wrong one: a kind of label the checked answer has two or more of
    kinds = {}
    for _, _, typ, key in _typed_spans(speak):
        kinds.setdefault(typ, set()).add(key)
    ambiguous = {t for t, keys in kinds.items() if len(keys) >= 2}
    src = [(f, {t: v for t, v in labs.items() if t in ambiguous}) for f, labs in figure_labels(speak)]
    got: dict[str, list[dict]] = {}
    for f, labs in figure_labels(reply, whole=True):
        got.setdefault(f, []).append(labs)
    for f, labs in src:
        if not labs or f not in got:
            continue
        if not any(all(g.get(t) == v for t, v in labs.items()) for g in got[f]):
            want = ", ".join(f"{v}" for v in labs.values())
            return f"the figure {f} is no longer beside its own label ({want})"
    # and the other way: no occurrence in the reply may sit beside a label the figure never has in the checked answer
    # ("2,72,64,054 in FY 2023-24 ... and 2,72,64,054 in FY 2024-25")
    have: dict[str, dict[str, set]] = {}
    for f, labs in src:
        for t in ambiguous:
            have.setdefault(f, {}).setdefault(t, set()).add(labs.get(t))
    for f, labs in figure_labels(reply):
        for t, v in labs.items():
            if t in ambiguous and f in have and v not in have[f].get(t, {None}) and have[f].get(t) != {None}:
                return f"the figure {f} is said beside '{v}', which is not its label"
    return ""


_LABEL_FIG = re.compile(r"([A-Za-z][A-Za-z'’&+()\- ]{1,70}?)\s*(?::|—|–|\s-\s)\s*(?:about\s+|approximately\s+)?"
                        r"((?:₹\s?)?\d[\d,]*(?:\.\d+)?)")
_LABEL_STOP = {"the", "a", "an", "of", "in", "for", "and", "total", "amount", "number", "about", "with", "on", "to", "at",
               "by", "all", "is", "are", "was", "were", "has", "have", "its", "their", "this", "that", "year", "years",
               "financial", "fy", "across", "still", "be", "raw", "count"}


def _lab_tokens(label: str) -> set[str]:
    out = set()
    for w in _WORD.findall(label.lower()):
        w = _bare(w)
        for part in w.split("-"):
            if part and part not in _LABEL_STOP and len(part) > 1:
                out.add(_stem(part))
    return out


def colon_labels(text: str) -> list[tuple[str, set[str]]]:
    """(figure, the words of its own label) for every 'label: figure' / 'label — figure' of the checked answer
    ('person days: 2,55,96,237', 'Amount released: about ₹30.00 crore', '2. Sent back — 48'); the label is the last
    few words before the colon / dash."""
    out = []
    for line in re.split(r"[\n;|/]|,\s(?=[A-Za-z][A-Za-z ]{1,40}:)", iso_dates(text or "")):
        for m in _LABEL_FIG.finditer(line):
            words = m.group(1).replace("(", " ").replace(")", " ").split()
            # the label = the words after the last clause break ("MGNREGA — person days" -> "person days")
            lab = " ".join(words[-5:])
            toks = _lab_tokens(lab)
            if toks:
                out.append((m.group(2).replace("₹", "").strip(), toks))
    return out


def label_pairing_broken(reply: str, speak: str) -> str:
    """Every figure keeps its OWN measure / status label (12 Nov 2026: a row 'year key: 2022, person days: 2,55,96,237,
    households employed: 4,14,251' was re-said as '2022 person days, 2,55,96,237 households employed': every figure moved
    one label along and the place / scheme / year guard could not see it). Only when the checked answer has two or more
    different 'label: figure' pairs. In the reply a figure belongs to the label written right after it (no comma
    between: '2,55,96,237 person days') or else to the nearest label before it; that label must be its own."""
    pairs = colon_labels(speak)
    labels = []
    for _, toks in pairs:
        if toks not in labels:
            labels.append(toks)
    if len(labels) < 2:
        return ""
    own: dict[str, list[set]] = {}
    for f, toks in pairs:
        own.setdefault(f, []).append(toks)

    def best(words: list[str]) -> set | None:
        ws = _lab_tokens(" ".join(words))
        # the label most fully said wins; between two fully said ones the longer ("South West Garo Hills" over
        # "West Garo Hills" when both are complete in the words)
        scored = sorted(((len(t & ws) / len(t), len(t & ws), i) for i, t in enumerate(labels) if t & ws), reverse=True)
        if not scored or (len(scored) > 1 and scored[0][:2] == scored[1][:2]):
            return None                                   # no label word, or two labels equally near: cannot tell
        return labels[scored[0][2]]

    for m in _FIG.finditer(reply):
        lit = m.group(0).rstrip(",.")
        end = m.start() + len(lit)                        # the match may have taken the comma after the figure
        f = re.sub(r"\s?(?:crore|lakh|cr|%|per\s?cent|x|times|K)$", "", lit, flags=re.I).replace("₹", "").strip()
        if f not in own or re.fullmatch(r"(?:19|20)\d\d", f) or \
                re.match(r"\s*[-–]\s*\d", reply[end:]) or re.search(r"\d\s*[-–]\s*$", reply[:m.start()]):
            continue                                      # a year / a year span is the fy guard's business
        after = reply[end:end + 60]
        after = re.split(r"[,;.:!?]", after, maxsplit=1)[0] if not re.match(r"\s*[,;.:]", after) else after
        lab = None
        if not re.match(r"\s*[,;.:]|\s*(?:crore|lakh|%)?\s*(?:and|then|while|but|or|whereas)\b", after, re.I):
            words = [w for w in _WORD.findall(after)[:4]]
            words = [w for w in words if w.lower() not in ("crore", "lakh", "of", "the", "in")][:3]
            lab = best(words) if words else None
        if lab is None:
            before = reply[max(0, m.start() - 70):m.start()]
            k = max(before.rfind(ch) for ch in ".;") if any(ch in before for ch in ".;") else -1
            before = before[k + 1:]
            nums = list(re.finditer(r"\d", before))
            if nums:
                before = before[nums[-1].end():]
            lab = best(_WORD.findall(before)[-8:])
        if lab is not None and lab not in own[f]:
            return f"the figure {f} is no longer beside its own label"
    return ""


def names_added(reply: str, speak: str) -> str:
    """A scheme / district / block the checked answer does not name (12 Nov 2026: a clarification between a block and a
    village was re-said as 'which Focus did you have in mind, Focus Plus for ...': the officer's own question named
    Focus Plus, so the name check of round 2, which also allows the question's words, let it through)."""
    have = {(t, k) for _, _, t, k in _typed_spans(speak) if t in ("place", "scheme")}
    for _, _, t, k in _typed_spans(reply):
        if t in ("place", "scheme") and (t, k) not in have:
            return f"'{k}' is not named in the checked answer; name only what it names"
    return ""


_QUAL = {"first": ("first",), "top": ("top",), "bottom": ("bottom",), "last": ("last",), "at least": ("at least",),
         "more than": ("more than", "over"), "less than": ("less than", "under", "below"), "over": ("over", "more than"),
         "under": ("under", "less than", "below"), "nearly": ("nearly", "almost", "about", "around"),
         "almost": ("almost", "nearly", "about", "around"),
         "about": ("about", "around", "roughly", "approximately", "nearly", "some", "close to")}
_QUAL_RX = re.compile(r"\b(first|top|bottom|last|at least|more than|less than|over|under|nearly|almost|about)\s+"
                      r"((?:₹\s?)?\d(?:[\d,]*\d)?(?:\.\d+)?)", re.I)


def qualifier_broken(reply: str, speak: str) -> str:
    """'the first 1,000' said as 'starting with 1,000', 'about ₹30.89 crore' as a flat '₹30.89 crore': a figure keeps
    the word that qualifies it in the checked answer (or a plain synonym of it), right before it."""
    for m in _QUAL_RX.finditer(speak):
        q, f = m.group(1).lower(), m.group(2)
        if re.fullmatch(r"(?:19|20)\d\d", f.replace("₹", "").strip()):
            continue
        bare_src = [h for h in re.finditer(r"(?<![\d,.])" + re.escape(f) + r"(?![\d])", speak)
                    if not re.search(r"\b" + re.escape(q) + r"\s+$", speak[max(0, h.start() - 30):h.start()].lower())]
        if bare_src:
            continue                                      # the same figure also stands alone ("top 3 ... Resubmit with 3")
        hits = list(re.finditer(r"(?<![\d,.])" + re.escape(f) + r"(?![\d])", reply))
        if not hits:
            continue                                      # the figure-said check reports a missing figure
        ok = False
        for h in hits:
            before = " ".join(reply[max(0, h.start() - 40):h.start()].lower().split()[-4:])
            if any(re.search(r"\b" + re.escape(alt) + r"\b", before) for alt in _QUAL.get(q, (q,))):
                ok = True
                break
        if not ok:
            return f"the figure {f} lost the word '{q}' in front of it"
    return ""


_LINK_FIG = re.compile(r"\b(?:in|during)\s+((?:₹\s?)?\d(?:[\d,]*\d)?(?:\.\d+)?)(?!\d|[.,]\d)(?!\s*[-–]\s*\d)")


def link_broken(reply: str, speak: str) -> str:
    """'fell to 126 in 15,387': a content figure after 'in' / 'during' where a year belongs (the checked answer never
    says that figure after 'in')."""
    for m in _LINK_FIG.finditer(reply):
        f = m.group(1).rstrip(",.")
        if re.fullmatch(r"(?:19|20)\d\d", f):
            continue
        if not re.search(r"\b(?:in|during)\s+" + re.escape(f), speak):
            return f"'{m.group(0)}': a figure is said where a year or a place belongs"
    return ""


def pairing_broken_v3(reply: str, speak: str) -> str:
    """Round 3's rule (kept for reference / tests): one label per figure, in a list answer only."""
    def labelled(text):
        spans = _label_spans(text)
        figs = content_spans(text)
        out = []
        for fs, fe in figs:
            out.append((text[fs:fe].lstrip("₹+-− ").strip(), label_of(text, fs, fe, spans, figs)))
        return out
    src = [(f, lab) for f, lab in labelled(speak) if lab]
    if len({lab for _, lab in src}) < 2:
        return ""
    got = {}
    for f, lab in labelled(reply):
        got.setdefault(f, set()).add(lab)
    for f, lab in src:
        if f in got and lab not in got[f]:
            return f"the figure {f} is no longer beside its own label '{lab}'"
    return ""


def _hints(speak: str, tags: dict) -> str:
    words = _vocab(speak)
    out = []
    if "screen" not in words:
        out.append("This checked answer does not mention the screen, so do not mention the screen.")
    keep = [w for w in CAVEATS if w in words and w not in ("not", "no") and not (
        w in ("about", "approximately") and not re.search(r"\b" + w + r"\s+(?:₹|\d|rs\b|inr\b)", speak, re.I))]
    if keep:
        out.append("Keep these words of it in what you say: " + ", ".join(keep) + ".")
    if tags:
        out.append(f"It has {len(tags)} tags ({', '.join(tags)}); use every one of them.")
    return (" " + " ".join(out)) if out else ""


# ---------------------------------------------------------------------------------------------------------------------
# the model
def llm_config() -> tuple[str, str, str]:
    url = os.environ.get("FDX_MEGH_NATURAL_URL") or os.environ.get("FDX_LLM_URL", "")
    model = os.environ.get("FDX_MEGH_NATURAL_MODEL") or \
        ([m.strip() for m in os.environ.get("FDX_LLM_MODEL", "").split(",") if m.strip()] or [""])[0]
    key = os.environ.get("FDX_MEGH_NATURAL_KEY") or os.environ.get("FDX_LLM_KEY", "")
    return url.rstrip("/"), model, key


async def _stream(messages: list[dict], max_tokens: int, temperature: float = 0.45):
    url, model, key = llm_config()
    body = {"model": model, "temperature": temperature, "top_p": 0.9, "max_tokens": max_tokens, "stream": True,
            "messages": messages, "chat_template_kwargs": {"enable_thinking": False}}
    tmo = httpx.Timeout(TOTAL_S, connect=3.0)
    async with httpx.AsyncClient(verify=_tls_verify(), timeout=tmo) as cli:
        async with cli.stream("POST", url + "/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {key}"} if key else {}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    delta = json.loads(data)["choices"][0].get("delta", {}).get("content") or ""
                except (ValueError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta


async def _complete(messages: list[dict], max_tokens: int, temperature: float = 0.45) -> str:
    t0 = time.time()
    buf = ""
    agen = _stream(messages, max_tokens, temperature)
    try:
        async for delta in agen:
            buf += delta
            if time.time() - t0 > TOTAL_S:
                raise TimeoutError("reply too slow")
        return buf
    finally:
        try:
            await agen.aclose()
        except Exception:  # noqa: BLE001
            pass


def _fail(why: str):
    STATS["guard_fails"] += 1
    STATS["last_fail"] = why[:160]
    key = re.sub(r"\[[NY]\d+\]|[\d,.]+|'[^']*'", "#", why)[:60]
    STATS["fail_reasons"][key] = STATS["fail_reasons"].get(key, 0) + 1


MAX_SENTENCE_WORDS = 32


def merged(reply: str, src: str) -> str:
    """16 Nov 2026 (the user's live test, engine log ~00:15:10): the model joined a four-sentence spoken answer into ONE
    15.7 s sentence ("Okay, sir, Tikrikilla has the most, about 47 lakh ..., which is ..., while Demdema has the
    fewest, 0, and all 8 blocks are on your screen."), and the captions and the picture waited for its end. A reply
    with fewer sentences than the checked answer, or a sentence over MAX_SENTENCE_WORDS words, is refused (the
    checked words are said instead). '' = fine."""
    n_src, sents = len(sentences(src)), sentences(reply)
    if len(sents) < n_src:
        return (f"the checked answer has {n_src} sentences and you said {len(sents)}: keep each of its sentences a "
                "sentence of its own, never join two")
    long_ = [x for x in sents if len(x.split()) > MAX_SENTENCE_WORDS]
    if long_:
        return f"a sentence of {len(long_[0].split())} words is too long: short sentences only"
    return ""


def plan(speak: str, kind: str) -> str:
    """Which path an answer takes: 'model' (slots), 'frame', 'asis'."""
    if kind in ASIS_KINDS:
        return "asis"
    if worth_it(speak, kind):
        return "model"
    return "frame"


async def resay(speak: str, question: str = "", kind: str = "", turn: int = 0) -> tuple[str, str]:
    """(what to say, how it was made: model | fallback | frame | asis | error)."""
    eff = effective_answer(speak, kind)
    path = plan(eff, kind)
    if eff != speak and _nums(eff) and ON and os.environ.get("FDX_LLM_URL"):
        path = "model"                                    # a trimmed row / trend answer: re-said like any data answer
    speak = eff
    if path == "asis":
        STATS["skipped"] += 1
        return " ".join((speak or "").split()), "asis"
    src = speakable(speak)
    if kind == "clarification":
        rule = clarify_years(speak, turn)
        if rule:
            # every year is in the rule's one list, so the page's "There are 2 more on your screen" is said by it
            whole = re.sub(r"\s*There (?:are|is) \d+ more on your screen\.?", "", speak)
            ok, _ = check(rule, speakable(whole, brackets=False), question, raw=whole)
            if ok:
                STATS["framed"] += 1
                return rule, "rules"
    if path == "frame":
        STATS["framed"] += 1
        out = framed(speak, kind, turn)
        if kind in RESAY_KINDS and not content_figures(speak) and frame_kind(kind, src) == "data":
            out = _sir_short(src)                     # a short data line with no figure: "..., sir." at most
        return out, "frame"
    STATS["calls"] += 1
    t0 = time.time()
    # a clarification's options keep their notes in brackets for the model ("MGNREGA (rural employment)"): turned into
    # commas they run into the option names
    if kind == "clarification":
        src = speakable(speak, brackets=False)
    templ, tags = slot(src)
    user = ("The officer asked: " + (question.strip() or "(not given)") + "\n\nCHECKED ANSWER:\n" + templ
            + "\n\nSay it to him now. " + (OPENERS[turn % len(OPENERS)] if kind != "clarification" else "")
            + _hints(src, tags))
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
    max_tokens = min(400, 90 + len(templ) // 2)
    reply, why, how = "", "", "model"

    async def attempt(msgs, temp):
        raw = clean_reply(await _complete(msgs, max_tokens, temp))
        bad = slot_check(raw, templ, tags)
        if bad:
            return raw, "", bad
        filled = fill(raw, tags)
        ok, bad = check(filled, src, question, raw=speak)
        if ok:
            bad = merged(filled, src)
            ok = not bad
        return raw, (filled if ok else ""), bad

    # 12 Nov 2026: two tries IN PARALLEL (two temperatures) instead of one after the other: the first that passes the
    # guard is said, so a failed first try costs no extra time (the gateway answers a long reply in ~0.9 s)
    tasks = [asyncio.create_task(attempt(messages, t)) for t in PARALLEL_TEMPS]
    last_raw = ""
    try:
        for fut in asyncio.as_completed(tasks):
            try:
                raw, filled, why = await fut
            except Exception as e:  # noqa: BLE001
                STATS["errors"] += 1
                STATS["last_error"] = f"{type(e).__name__}: {str(e)[:120]}"
                how = "error"
                continue
            if filled:
                reply, how = filled, "model"
                break
            last_raw = raw
            _fail(why)
        if not reply and last_raw and time.time() - t0 < RETRY_BEFORE_S:
            raw, filled, why = await attempt(messages + [
                {"role": "assistant", "content": last_raw},
                {"role": "user", "content": "That broke a rule: " + why + ". Say it again, following every rule: every "
                 "tag of the checked answer exactly once where its figure belongs, no number of your own, and nothing "
                 "that is not in the checked answer."}], 0.3)
            if filled:
                reply, how = filled, "model"
            else:
                _fail(why)
    except Exception as e:  # noqa: BLE001
        STATS["errors"] += 1
        STATS["last_error"] = f"{type(e).__name__}: {str(e)[:120]}"
        reply, how = "", "error"
    finally:
        for t in tasks:
            if not t.done():
                t.cancel()
    if not reply:
        STATS["fallback"] += 1
        return framed(speak, "clarification" if kind == "clarification" else "data", turn), \
            ("fallback" if how == "model" else how)
    # "there are 1 more figures on your screen" (a tag cannot agree with its noun): one more, singular
    reply = re.sub(r"\b(?:there are|are) 1 more\b", lambda m: m.group(0).replace("there are", "there's")
                   .replace("are", "is"), reply)
    reply = re.sub(r"\b1 more ([a-z]+?[^s\W])s\b", r"1 more \1", reply)
    reply = re.sub(r"\b(1 more(?: [a-z\-]+)?) are\b", r"\1 is", reply)
    STATS["natural"] += 1
    lst = STATS["first_sentence_ms"]
    lst.append(round((time.time() - t0) * 1000))
    del lst[:-300]
    return reply, "model"


async def say_naturally(speak: str, question: str = "", kind: str = "", turn: int = 0):
    """Yields the sentences to say, in order (the engine joins them into one line: one breath)."""
    text, _ = await resay(speak, question, kind, turn)
    for s in sentences(text):
        yield s


def stats() -> dict:
    out = {k: v for k, v in STATS.items() if not isinstance(v, list)}
    ms = sorted(STATS["first_sentence_ms"])
    out["first_sentence_ms"] = {"n": len(ms), "p50": ms[len(ms) // 2] if ms else None,
                                "p95": ms[min(len(ms) - 1, int(len(ms) * 0.95))] if ms else None}
    return out
