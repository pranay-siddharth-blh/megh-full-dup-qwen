"""The question shaper (11 Nov 2026): what the officer SAID, turned into the question Megh's pipeline answers best,
before `ask_megh`. Megh's pipeline is frozen; its follow-up, view-change and clarification matchers are closed word lists
and word-count limits written for typed text (`c01 looks_like_followup` gives up above 12 words; the view list rejects
"mate", "thing"; a "which scheme?" reply takes ONE scheme of at most 6 words). Spoken sentences ramble, restart and
point back ("break that down by district in terms of a bar graph"), so the shaper:

  1. HOLD   a turn that is only fillers ("Okay. Um.") or stops mid-sentence ("I also want you to.") is not sent: its
            audio is heard again with what follows;
  2. CLEAN  fillers anywhere, abandoned openings ("leave this", "wait", "do one thing", "no no" → keep what follows),
            politeness wrappers ("can you please just", "I want you to"), spoken years ("twenty three twenty four" →
            2023-24), "every financial year" → "by financial year" (the user's decision: one row per year);
  3. VIEW   a chart switch that points at what is on screen ("give me this the same thing as a pie chart") becomes the
            exact sentence the page redraws locally ("show it as a pie chart"; map / ranking / horizontal too);
  4. PICK   a reply to a clarifying question becomes the option's own words ("the first one", "I meant Focus Plus"); two
            schemes named to "which scheme?" become a comparison of both (the user's decision);
  5. FOLLOW a follow-up the pipeline's word lists would miss is rewritten, by the on-prem LLM (qwen4-deploy), into ONE
            standalone question from the conversation so far; a guard lets through only schemes, districts and years
            that the officer said or that are in the conversation, else the cleaned words are sent as they are.

  (14 Nov) before step 5, a follow-up of a kind Megh's pipeline answers by its own rules (rank, only one place, a year,
            the year before / after, a place, one scheme of a comparison, a value, a measure) is written in that rule's
            own wording from one table, FOLLOWUP_KINDS (see "follow-ups Megh answers by its own rules").

Everything here is rules except step 5; the LLM never answers anything, it only rewrites the question.

DOMAIN (12 Nov 2026): the schemes, districts, measure words, the assistant's name and the state come from the domain
pack (megh/domain: megh_pack.json, built from Megh's own registries by build_pack.py), not from this file. A new
scheme in Megh's registries reaches the shaper by rebuilding the pack; the pack is re-read when it changes.
"""
from __future__ import annotations

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

if __package__:                                  # imported as megh.shaper
    from . import domain as _domain
else:                                            # megh/ on sys.path (the engine, the harness)
    import domain as _domain

# filled from the domain pack by _domain_sync() (at import, and again whenever the pack file changes)
SCHEMES: list[str] = []                          # longest first: "CM Elevate Legacy" is matched before "CM Elevate"
DISTRICTS: list[str] = []                        # longest first: "South West Garo Hills" before "West Garo Hills"
MEASURES: set[str] = set()
CROSS_SCHEME: tuple[str, ...] = ()
REWRITE_SYSTEM = ""
_DOMAIN_V = [-1]
STATS = {"turns": 0, "held": 0, "views": 0, "picks": 0, "compare_picks": 0, "rules": 0, "llm": 0, "llm_rejected": 0,
         "llm_errors": 0, "retries": 0, "last_llm_ms": None, "last_reject": ""}

# --- words -------------------------------------------------------------------------------------------------------
FILLERS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "ahh", "hmm", "hm", "mm", "mmm", "mate", "yaar", "na",
           "like,"}
_LEAD_BASE = {"okay", "ok", "so", "yeah", "yes", "yep", "right", "alright", "fine", "well", "now", "then", "hey",
              "sir", "please", "kindly", "just", "actually", "basically", "also", "like"}
LEAD_WORDS = set(_LEAD_BASE)                     # + the assistant's own name ("megh"), from the domain pack
WRAPPERS = ["for now", "for the time being", "you can also", "you can", "can you please just", "could you please just", "can you please", "could you please", "would you please",
            "will you please", "can you just", "could you just", "can you also", "could you also", "can you",
            "could you", "would you", "will you", "i want you to also", "i want you to", "i wanted you to",
            "i would like you to", "i'd like you to", "i want to also", "i wanted to also", "i want to", "i wanted to",
            "i would like to", "i'd like to", "i need you to", "i need to", "let me", "let's", "please",
            "just", "kindly", "i want", "i wanted", "i need"]
KEEP_AFTER_WRAPPER = {"show", "give", "tell", "compare", "list", "break", "get", "see", "know", "find", "rank", "plot",
                      "draw", "display", "check", "split", "put"}
ABANDON = ["leave this", "leave that", "leave it", "forget this", "forget that", "forget it", "never mind",
           "nevermind", "scratch that", "do one thing", "one more thing", "no no no", "no no", "hang on", "hold on",
           "wait wait", "wait", "sorry", "i mean", "rather", "instead of that", "let me rephrase", "let me ask"]
DANGLING_END = {"to", "the", "a", "an", "me", "of", "for", "and", "in", "on", "by", "with", "about", "you", "show",
                "give", "tell", "want", "is", "are", "was", "my", "this", "that", "your", "our", "at", "from", "or",
                "under", "per", "also", "like", "into", "as", "than", "between", "which", "what", "how", "can",
                "could", "so"}
DEICTIC = {"it", "this", "that", "these", "those", "them", "same", "there", "above", "previous", "last", "earlier",
           "former", "latter", "both", "either", "each", "one"}
VIEW_WORDS = [  # (spoken words, the page's canonical sentence)
    (("pie", "donut", "doughnut"), "show it as a pie chart"),
    (("line",), "show it as a line chart"),
    (("trend line", "line graph", "line chart"), "show it as a line chart"),
    (("map", "on the map", "map view"), "show it on the map"),
    (("ranking", "rank", "ranked", "leaderboard", "race"), "show it as a ranking"),
    (("horizontal", "horizontal bars", "horizontal bar"), "show it as horizontal bars"),
    (("table", "tabular", "rows"), "show it as a table"),
    (("bar", "bars", "bar chart", "bar graph", "column", "columns", "histogram"), "show it as a bar chart"),
]
CHART_NOUNS = {"chart", "graph", "plot", "view", "visual", "visualisation", "visualization", "diagram", "format", "form"}
VIEW_VERBS = {"show", "make", "change", "switch", "turn", "convert", "give", "put", "display", "draw", "see", "plot",
              "redo", "present", "want", "need"}
FOLLOW_OPS = ["break that down", "break it down", "break down", "breakdown", "broken down", "split by", "split it",
              "split that", "only for", "just for", "only in", "just in", "instead", "what about", "how about",
              "and for", "and in", "same for", "same thing for", "same in", "compare it", "compare that",
              "compare them", "versus", "vs", "against", "of those", "of these", "of them", "among them",
              "out of those", "which of", "drill down", "zoom in", "district wise", "district-wise", "year wise",
              "year-wise", "by district", "by year", "by financial year", "by block", "per district", "per year",
              "top five", "top 5", "top three", "top 3", "top ten", "top 10", "highest", "lowest"]
NUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
       "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
       "seventeen": 17, "eighteen": 18, "nineteen": 19}
ORD = {"first": 0, "1st": 0, "one": 0, "second": 1, "2nd": 1, "two": 1, "third": 2, "3rd": 2, "three": 2,
       "fourth": 3, "4th": 3, "four": 3, "fifth": 4, "5th": 4, "five": 4, "sixth": 5, "6th": 5, "six": 5,
       "last": -1, "latter": -1, "former": 0}

_WS = re.compile(r"\s+")
_WORD = re.compile(r"[a-z0-9][a-z0-9'\-]*")


def _low(t: str) -> str:
    return _WS.sub(" ", (t or "").lower()).strip()


def words(t: str) -> list[str]:
    return _WORD.findall(_low(t))


def _has_phrase(low: str, phrase: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])", low) is not None


def _domain_sync() -> None:
    """(Re)build the domain tables from the pack when it is new or has changed on disk."""
    v = _domain.version()
    if v == _DOMAIN_V[0]:
        return
    global SCHEMES, DISTRICTS, MEASURES, CROSS_SCHEME, REWRITE_SYSTEM, LEAD_WORDS
    p = _domain.pack()
    SCHEMES = _domain.scheme_names("match")
    DISTRICTS = _domain.district_names("match")
    MEASURES = _domain.measure_words()
    call = (p.get("product") or {}).get("call_name")
    LEAD_WORDS = _LEAD_BASE | ({call.lower()} if call else set())
    CROSS_SCHEME = _CROSS_BASE + (f"all {_domain.scheme_count_word()} schemes",)
    REWRITE_SYSTEM = (_REWRITE_TEMPLATE.replace("{state}", (p.get("product") or {}).get("state") or "the state's")
                      .replace("{schemes}", ", ".join(_domain.scheme_names("say"))))
    _DOMAIN_V[0] = v


def schemes_in(text: str) -> list[str]:
    _domain_sync()
    low, out = _low(text), []
    for s in SCHEMES:                      # longest first, so "CM Elevate Legacy" is not also "CM Elevate"
        if _has_phrase(low, s.lower()) and not any(s.lower() in o.lower() for o in out):
            out.append(s)
    return out


def districts_in(text: str) -> list[str]:
    _domain_sync()
    low, out = _low(text), []
    for d in DISTRICTS:
        if _has_phrase(low, d.lower()) and not any(d.lower() in o.lower() for o in out):
            out.append(d)
    return out


def years_in(text: str) -> set[str]:
    return set(re.findall(r"\b20\d\d(?:-\d\d)?\b", text or ""))


# --- step 2: clean -----------------------------------------------------------------------------------------------
def spoken_years(t: str) -> str:
    """'twenty twenty three twenty four' / 'twenty three twenty four' / '2023 24' / '2023-2024' -> '2023-24';
    'two thousand twenty three' -> '2023'. Only consecutive years said BACK TO BACK make a financial year: '2023 to
    2024' and '2023 and 2024' (16 Nov 2026, the voice audit) are two years as said, and the pipeline's own year reader
    decides what they mean, exactly as for a typed question."""
    def two(ws: list[str], i: int) -> tuple[int | None, int]:
        if i < len(ws) and ws[i] in ("twenty", "thirty") and i + 1 < len(ws) and ws[i + 1] in NUM and 0 < NUM[ws[i + 1]] < 10:
            return (20 if ws[i] == "twenty" else 30) + NUM[ws[i + 1]], 2
        if i < len(ws) and ws[i] in NUM and 10 <= NUM[ws[i]] <= 19:
            return NUM[ws[i]], 1
        if i < len(ws) and ws[i] == "twenty":
            return 20, 1
        return None, 0

    # number words written with a hyphen ("twenty-three") are read as two words (12 Nov: "two thousand twenty-three
    # twenty-four" kept its hyphens and no year was read)
    t = re.sub(r"\b(twenty|thirty)-(one|two|three|four|five|six|seven|eight|nine)\b", r"\1 \2", t, flags=re.I)
    toks = t.replace("-", " - ").split()
    low = [x.lower().strip(",.?!") for x in toks]
    out, i = [], 0
    while i < len(toks):
        j, lead20 = i, False
        if low[j] == "twenty" and j + 1 < len(low) and (low[j + 1] in NUM or low[j + 1] in ("twenty", "thirty")):
            # "twenty twenty three ..." = 20 + "twenty three"
            y, n = two(low, j + 1)
            if y is not None and 15 <= y <= 30:
                lead20, j = True, j + 1
        a, na = two(low, j)
        if a is not None and 15 <= a <= 30 and (lead20 or (i > 0 and low[i - 1] in ("in", "for", "fy", "year", "during", "of", "from", "since"))):
            k = j + na
            if k < len(low) and low[k] == "-":
                k += 1
            b, nb = two(low, k)
            if b is not None and b == a + 1:
                out.append(f"20{a:02d}-{b:02d}" + (toks[k + nb - 1][-1] if toks[k + nb - 1][-1] in ",.?!" else ""))
                i = k + nb
                continue
            if lead20:
                out.append(f"20{a:02d}" + (toks[j + na - 1][-1] if toks[j + na - 1][-1] in ",.?!" else ""))
                i = j + na
                continue
        out.append(toks[i])
        i += 1
    s = " ".join(out).replace(" - ", "-")
    s = re.sub(r"\btwo thousand (?:and )?(\w+)(?: (\w+))?", lambda m: _two_thousand(m), s)
    s = re.sub(r"\b(20\d\d)\s*(?:-|–)\s*20(\d\d)\b", lambda m: f"{m.group(1)}-{m.group(2)}"
               if int(m.group(2)) == int(m.group(1)[2:]) + 1 else m.group(0), s)
    s = re.sub(r"\b(20\d\d)\s+(\d\d)\b(?!\s*(?:crore|lakh|%|percent))",
               lambda m: f"{m.group(1)}-{m.group(2)}" if int(m.group(2)) == int(m.group(1)[2:]) + 1 else m.group(0), s)
    # digits then words (12 Nov live spoken run: "2023 twenty four" for 2023-24)
    s = re.sub(r"\b(20\d\d)\s+(?:-\s*)?(twenty|thirty)[\s-]+(one|two|three|four|five|six|seven|eight|nine)\b",
               lambda m: _digits_words(m), s, flags=re.I)
    s = re.sub(r"\b(20\d\d)\s+(?:-\s*)?(eighteen|nineteen|twenty)\b(?![\s-]+(?:one|two|three|four|five|six|seven|eight|nine)\b)",
               lambda m: _digits_words(m, single=True), s, flags=re.I)
    return s


def _digits_words(m, single: bool = False) -> str:
    y = int(m.group(1))
    if single:
        b = NUM.get(m.group(2).lower(), 20 if m.group(2).lower() == "twenty" else -1)
    else:
        b = (20 if m.group(2).lower() == "twenty" else 30) + NUM[m.group(3).lower()]
    return f"{y}-{b:02d}" if b == (y % 100) + 1 else m.group(0)


def _two_thousand(m) -> str:
    a = m.group(1).lower()
    b = (m.group(2) or "").lower()
    if a in ("twenty", "thirty") and b in NUM and 0 < NUM[b] < 10:
        return str(2000 + (20 if a == "twenty" else 30) + NUM[b])
    if a in NUM:
        return str(2000 + NUM[a]) + ("" if not b else " " + m.group(2))
    return m.group(0)


# --- amounts said in words (16 Nov 2026, the voice audit) ---------------------------------------------------------
# A typed question writes "₹5 lakh" / "2.5 crore" / "20,000"; the recogniser often writes the words ("five lakh",
# "two point five crore", "twenty thousand"), which Megh's number readers do not read. Rule-based, before the
# pipeline: a run of number words that holds a scale word (hundred / thousand / lakh / crore) or a decimal "point" is
# written in digits ("5 lakh", "2.5 crore", "20,000", "1,50,000"); a bare "five" or "twenty twenty three" is left
# to the other readers (a rank "top five", a year).
_UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
          "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
          "seventeen": 17, "eighteen": 18, "nineteen": 19, "a": 1, "an": 1}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "lakhs": 100000, "lac": 100000, "lacs": 100000,
           "crore": 10000000, "crores": 10000000}
_UNIT_WORD = {"lakh": "lakh", "lakhs": "lakh", "lac": "lakh", "lacs": "lakh", "crore": "crore", "crores": "crore"}


def _indian(n: int) -> str:
    """12345678 -> '1,23,45,678' (the Indian grouping Megh writes)."""
    d = str(n)
    if len(d) <= 3:
        return d
    head, tail = d[:-3], d[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def _read_amount(toks: list, i: int):
    """(end index, value, decimals text, unit word or '', had a scale / point) for the number words from i, else None."""
    total, cur, j, scale_seen, last_scale = 0, 0, i, False, None
    any_num = False
    frac = ""
    while j < len(toks):
        w = toks[j].lower().strip(",")
        if w in _UNITS and not (w in ("a", "an") and (j + 1 >= len(toks) or toks[j + 1].lower() not in _SCALES)):
            if any_num and cur % 10 and cur < 100 and _UNITS[w] < 10 and w not in ("a", "an"):
                break                                            # "five six": two numbers
            cur += _UNITS[w]
            any_num = True
        elif w in _TENS:
            if cur % 100:
                break
            cur += _TENS[w]
            any_num = True
        elif w == "hundred" and any_num:
            cur = (cur or 1) * 100
            scale_seen = True
        elif w in ("thousand", "lakh", "lakhs", "lac", "lacs", "crore", "crores") and any_num:
            sc = _SCALES[w]
            if last_scale is not None and sc >= last_scale:
                break
            total += (cur or 1) * sc
            cur, scale_seen, last_scale = 0, True, sc
        elif w == "point" and any_num and j + 1 < len(toks) and toks[j + 1].lower() in _UNITS:
            k = j + 1
            while k < len(toks) and toks[k].lower() in _UNITS and _UNITS[toks[k].lower()] < 10 \
                    and toks[k].lower() not in ("a", "an"):
                frac += str(_UNITS[toks[k].lower()])
                k += 1
            if not frac:
                break
            j = k
            scale_seen = True
            break
        elif w == "and" and any_num and j + 1 < len(toks) and (toks[j + 1].lower() in _UNITS or toks[j + 1].lower() in _TENS):
            pass                                                 # "one hundred and twenty"
        else:
            break
        j += 1
    if not any_num or not scale_seen:
        return None
    unit = ""
    if frac:
        # "two point five" + "crore" / "lakh" after it
        if j < len(toks) and toks[j].lower().strip(",.?!") in _UNIT_WORD:
            unit = _UNIT_WORD[toks[j].lower().strip(",.?!")]
            j += 1
        return j, total + cur, frac, unit, True
    return j, total + cur, "", "", True


def spoken_amounts(t: str) -> str:
    """'five lakh' -> '5 lakh', 'two point five crore' -> '2.5 crore', 'twenty thousand' -> '20,000',
    'one lakh fifty thousand' -> '1,50,000', 'rupees ten lakh' -> 'rupees 10 lakh'."""
    toks = (t or "").split()
    out, i = [], 0
    while i < len(toks):
        core = toks[i].lower().strip(",.?!")
        if core in _UNITS or core in _TENS:
            bare = [x.strip(",.?!") for x in toks]
            hit = _read_amount(bare, i)
            if hit is not None:
                end, value, frac, unit, _ = hit
                tail = toks[end - 1][len(toks[end - 1].rstrip(",.?!")):] if end - 1 < len(toks) else ""
                if frac:
                    num = f"{value}.{frac}" + (f" {unit}" if unit else "")
                else:
                    # a whole multiple of a lakh / crore is said in that unit ("5 lakh"), anything else in digits
                    ws_used = [x.lower() for x in bare[i:end]]
                    top = next((u for u in ("crore", "crores", "lakh", "lakhs", "lac", "lacs") if u in ws_used), "")
                    scale = _SCALES.get(top, 0)
                    if scale and value % scale == 0:
                        num = f"{value // scale} {_UNIT_WORD[top]}"
                    else:
                        num = _indian(value)
                out.append(num + tail)
                i = end
                continue
        out.append(toks[i])
        i += 1
    return " ".join(out)


EVERY_YEAR = ["of every financial year", "of each financial year", "of every year", "of each year",
              "for every financial year", "for each financial year", "in every financial year", "in each financial year",
              "every financial year", "each financial year", "for every year", "for each year", "in every year",
              "in each year", "every year", "each year", "year by year", "year on year", "year-wise", "year wise",
              "yearwise", "per financial year", "per year", "over the years", "across the years", "through the years",
              "over the financial years", "all the years one by one", "annually", "yearly"]


# 16 Nov 2026 (the voice audit): "average MGNREGA expenditure per year" became "... by financial year" (a year list
# instead of one average). An average / ratio word makes "per year" / "annually" part of the measure: left as said.
RATIO_WORDS = {"average", "averages", "avg", "mean", "median", "typical", "typically", "ratio"}


def by_year(t: str) -> str:
    """The user's decision (11 Nov): 'every financial year' means one row per year, never one total. Not when the
    sentence asks for an average or a ratio ("average ... per year"): that is one figure, the pipeline's to read."""
    low = t.lower()
    ws = set(words(low))
    if ws & RATIO_WORDS:
        return t
    for ph in EVERY_YEAR:
        k = low.find(ph)
        if k == 0 and ph in ("each year", "every year", "yearly", "annually"):
            k = low.find(ph, 1)
        while k > 0 or (k == 0 and ph not in ("each year", "every year", "yearly", "annually")):
            if not _has_phrase(low[max(0, k - 1):k + len(ph) + 1], ph):
                break
            if "by financial year" in low:
                t = t[:k] + t[k + len(ph):]
            else:
                t = t[:k] + "by financial year" + t[k + len(ph):]
            low = t.lower()
            k = low.find(ph, 1)
    return _WS.sub(" ", t).replace(" ,", ",").strip()


def strip_fillers(t: str) -> str:
    out = []
    for tok in t.split():
        core = tok.lower().strip(",.?!;:")
        if core in FILLERS:
            if tok[-1] in ".?!" and out and out[-1][-1] not in ".?!":
                out[-1] += tok[-1]
            continue
        if out and core and core == out[-1].lower().strip(",.?!;:") and core in LEAD_WORDS | {"no", "the", "a"}:
            if tok[-1] in ".?!" and out[-1][-1] not in ".?!":
                out[-1] += tok[-1]                              # "No no." -> "No." (the sentence still ends)
            continue                                            # "okay okay", "the the"
        out.append(tok)
    return " ".join(out)


def drop_abandoned(t: str) -> str:
    """Keep what follows the LAST restart marker ('leave this', 'wait', 'do one thing', 'no no', 'sorry, I mean'), when
    something real follows it. 16 Nov 2026: only when what is dropped is harmless (`benign`): "I want to kill
    someone, sorry, show me MGNREGA" goes to the pipeline whole, so its guardrail judges what was said."""
    low = t.lower()
    best = -1
    for m in ABANDON:
        for mo in re.finditer(r"(?<![a-z0-9])" + re.escape(m) + r"(?![a-z0-9])", low):
            # "waiting list", "rather than" are not restarts
            after = low[mo.end():mo.end() + 6]
            if m == "rather" and after.startswith(" than"):
                continue
            best = max(best, mo.end())
    if best < 0:
        return t
    rest = t[best:].lstrip(" ,.;:!?-")
    if len(words(rest)) < 2:
        return t
    return rest if benign(t[:best]) else t


def strip_wrappers(t: str) -> str:
    """'Okay, can you please just show me ...' -> 'show me ...'. Only leading words, repeatedly; a sentence that would
    lose its verb keeps them."""
    s = t.strip()
    for _ in range(8):
        low = s.lower().lstrip(" ,.;:!?")
        s = s.lstrip(" ,.;:!?")
        changed = False
        first = (low.split() or [""])[0].strip(",.;:!?")
        if first in LEAD_WORDS and len(low.split()) > 2:
            s = s[len(s.split()[0]):]
            changed = True
        else:
            for w in WRAPPERS:
                if low.startswith(w + " ") or low.startswith(w + ","):
                    nxt = (low[len(w):].split() or [""])[0].strip(",.;:!?")
                    if w in ("i want", "i wanted", "i need") and nxt not in ("the", "a", "all", "to"):
                        continue
                    s = s[len(w):]
                    changed = True
                    break
        if not changed:
            break
    s = s.strip(" ,;:")
    if s and _low(s) != _low(t):                     # an opening was taken off: the question starts with a capital
        return s[:1].upper() + s[1:]
    return s


# MEASURES (the words that say what to count) come from the domain pack: shaper.common_measure_words of the overlay +
# each scheme's measure words (tuned in the overlay, or derived from its registry's measure_vocabulary)


DISCOURSE = {"okay", "ok", "so", "alright", "fine", "now", "well", "right", "yeah", "yes", "hmm", "um", "uh"}


def strip_discourse(t: str) -> str:
    """16 Nov 2026 (log bank): "Okay, now give me the headline figure of every scheme" -> "give me the headline figure
    of every scheme". Leading discourse words only ("and" / "then" stay: Megh's follow-up readers use them); never the
    whole sentence."""
    toks = t.split()
    i = 0
    while i < len(toks) - 1 and toks[i].lower().strip(",.;:!") in DISCOURSE and toks[i][-1:] not in ".?!":
        i += 1
    if i and i < len(toks):
        rest = " ".join(toks[i:])
        return rest[:1].upper() + rest[1:] if t[:1].isupper() else rest
    return t


def dedupe_repeats(t: str) -> str:
    """'show to me as a show to me as a bar graph' -> 'show to me as a bar graph' (a stutter repeated 2-5 words)."""
    toks = t.split()
    changed = True
    while changed:
        changed = False
        for n in range(5, 1, -1):
            for i in range(len(toks) - 2 * n + 1):
                if any(x[-1] in ".?!" for x in toks[i:i + n]):
                    continue                                     # a sentence said again is not a stutter (keep_sentences)
                a = [x.lower().strip(",.") for x in toks[i:i + n]]
                b = [x.lower().strip(",.") for x in toks[i + n:i + 2 * n]]
                if a == b:
                    del toks[i + n:i + 2 * n]
                    changed = True
                    break
            if changed:
                break
    # 16 Nov 2026 (log bank): an opening restarted a few words in ("show me the show me MGNREGA person-days trend"):
    # what follows the restart is the sentence
    low = [x.lower().strip(",.") for x in toks]
    for i in range(len(low)):
        if low[i] not in _RESTART_VERBS:
            continue
        hit = next((k for k in range(2, 5) if i + k + 3 <= len(low) and low[i + k:i + k + 2] == low[i:i + 2]
                    and not any(x[-1:] in ".?!" for x in toks[i:i + k])), None)
        if hit:
            toks = toks[:i] + toks[i + hit:]
            break
    return " ".join(toks)


# an opening that is restarted ("show me the show me ...") starts with one of these
_RESTART_VERBS = {"show", "give", "tell", "list", "display", "get", "can", "could", "what", "which", "how", "break"}


def self_sufficient(sentence: str) -> bool:
    return bool(schemes_in(sentence) or districts_in(sentence) or (set(words(sentence)) & MEASURES))


def last_sentence_question(t: str) -> str:
    """(Before 16 Nov 2026) A turn of several sentences: the question was the last sentence that had real content; every
    earlier one was dropped. The independent voice audit (15-16 Nov) found what that lost: "How many PMAY-G houses were
    sanctioned in Ri Bhoi? And how many were completed?" became "And how many were completed?", and "I want to kill
    someone. Show me MGNREGA by district" sent only the data question (the harmful sentence never reached the
    pipeline's guardrail or its audit). Kept as the name of keep_sentences() for old callers."""
    return keep_sentences(t)


# --- 16 Nov 2026: every sentence that is not filler reaches the pipeline ------------------------------------------
# A typed question goes to the pipeline whole: its guardrails, audit and multi-ask reader (c17 _c17_sub_asks, which
# splits at "?" / "," / "and") see every sentence. A spoken turn now does too. Dropped, as before, are only what a
# typist would never have sent: sentences of fillers and acknowledgements ("Okay.", "Yeah, that's good."), an
# earlier sentence the officer then said again more fully (a restart: its words are all in a later sentence), and an
# unfinished false start ("I also want you to show me.") -- and that last one only when every word of it is one of
# the domain's harmless words (BENIGN: grammar, scheme / place / measure / chart words, numbers). Anything else
# ("I want to kill someone.") goes with the question, so the pipeline's guardrail judges exactly what was said.
ACK_WORDS = {"good", "great", "nice", "fine", "perfect", "excellent", "wonderful", "super", "cool", "interesting",
             "wow", "oh", "ah", "aha", "thanks", "thank", "understood", "noted", "correct", "exactly", "sure",
             "that's", "thats", "it's", "its", "got", "see", "i", "it", "this", "that", "is", "was", "very", "really",
             "quite", "much", "you", "a", "lot", "the", "makes", "sense", "acha", "accha", "theek", "hai", "haan",
             "hmm", "no", "wait", "one", "second", "minute", "moment", "sec"}
_BENIGN_BASE = set("""a an the of for in on at by to from with about into as than per and or but also too then now so
    me us you i we my our your it its it's that this those these them they there here same thing things one ones all
    any each every both either whole entire total overall show give tell list get see know find check display draw
    plot put make change switch turn convert present want wanted need needed would could can will shall should may
    might must do does did done is are was were be been being has have had having what which who where when how why
    much many number numbers figure figures data detail details result results answer answers question questions
    please kindly just only also again more less most least top bottom highest lowest high low best worst first
    second third last next previous before after earlier later like okay ok yes yeah no not wait sorry mean meant
    leave forget never mind scratch hang hold on rather instead let lets let's rephrase ask asking tell telling
    actually basically really so well right alright hmm um uh er erm ah sir madam megh one two three four five six
    seven eight nine ten twenty thirty hundred thousand lakh lakhs crore crores percent per cent point year years
    financial fiscal fy month months district districts block blocks village villages constituency constituencies
    scheme schemes state statewide meghalaya wise level basis chart graph bar bars line pie donut doughnut map table
    ranking rank ranked trend view visual picture dashboard overview break breakdown down split compare comparison
    versus vs against between among across over under within during since until till go going back home screen
    open close clear bring take""".split())
BENIGN: set = set()
BENIGN_V = [-1]
_ORDINAL_OR_YEAR = re.compile(r"20\d\d(?:-\d\d)?|\d+(?:st|nd|rd|th)")


def _benign_words() -> set:
    """The harmless words a dropped fragment may consist of (built once per domain pack)."""
    if BENIGN and BENIGN_V[0] == _DOMAIN_V[0]:
        return BENIGN
    BENIGN.clear()
    BENIGN.update(_BENIGN_BASE | LEAD_WORDS | FILLERS | DANGLING_END | DEICTIC | CHART_NOUNS | VIEW_VERBS | MEASURES
                  | set(REGROUP_DIM) | REGROUP_TRIGGER | REGROUP_FILLER | FU_SHARED | FU_RANK_UP | FU_RANK_DOWN
                  | FU_YEAR_WORDS | set(FU_YEAR_STEP) | set(NUM) | set(VALUE_WORDS) | ACK_WORDS)
    for name in SCHEMES + DISTRICTS:
        BENIGN.update(words(name))
    for form, _c, _l in _place_index():
        BENIGN.update(words(form))
    for m in _measure_index():
        BENIGN.update(words(m))
    BENIGN_V[0] = _DOMAIN_V[0]
    return BENIGN


def benign(text: str) -> bool:
    """Every word of `text` is a harmless domain / grammar word (a false start made only of them can be dropped)."""
    ok = _benign_words()
    for w in words(text):
        if w in ok or w.isdecimal() or _ORDINAL_OR_YEAR.fullmatch(w):
            continue
        if w.endswith("'s") and w[:-2] in ok:
            continue
        if w.endswith("s") and w[:-1] in ok:
            continue
        return False
    return True


_RESTATE_STOP = set("""a an the of for in on at by to me us you i we my our it its that this those these them there
    show give tell get see display can could would will please just also now so then okay ok yes yeah well right
    want wanted need like what how is are was were be do does did all""".split())


def _content_set(t: str) -> set:
    return {w for w in words(t) if w not in _RESTATE_STOP}


def is_filler_sentence(t: str) -> bool:
    """Only fillers, lead words and acknowledgements ("Okay.", "Yeah, that's very good.", "Hmm, one second.")."""
    ws = [w for w in words(t) if w not in FILLERS]
    return all(w in LEAD_WORDS or w in ACK_WORDS for w in ws)


def split_sentences(t: str) -> list:
    return [p.strip() for p in re.split(r"(?<=[.?!])\s+", t or "") if p.strip()]


def keep_sentences(t: str) -> str:
    """The sentences of a turn that go to the pipeline (see above), in the order said. A last sentence that only asks
    for a picture of the one before it ("... in PMAY-G and MGNREGA. Show it as a bar graph.") is joined to it."""
    parts = split_sentences(t)
    if len(parts) <= 1:
        return t
    keep: list = []
    for k, p in enumerate(parts):
        last = k == len(parts) - 1
        if is_filler_sentence(p):
            continue                                              # "Okay." "Yeah, that's good."
        if not last:
            mine = _content_set(p)
            later = set().union(*[_content_set(x) for x in parts[k + 1:]])
            if mine and mine <= later:
                continue                                          # said again, more fully, later: a restart
            if benign(p) and restated_later(p, parts[k + 1:]):
                continue                                          # the same ask said again in other words
            short = len([w for w in words(p) if w not in LEAD_WORDS and w not in FILLERS]) < 3
            if (short or is_unfinished(p, p)) and benign(p):
                continue                                          # "I also want you to show me." (a false start)
        keep.append(p)
    if not keep:
        return parts[-1]
    if len(keep) >= 2 and not self_sufficient(keep[-1]) and (set(words(keep[-1])) & DEICTIC) \
            and view_words_in(keep[-1]) and not schemes_in(keep[-1]):
        # the last sentence only asks for a picture of the one before it
        keep = keep[:-2] + [keep[-2].rstrip(".?! ") + ", " + keep[-1][:1].lower() + keep[-1][1:]]
    return " ".join(keep)


def restated_later(p: str, later: list) -> bool:
    """A later sentence asks the same thing in other words: the same schemes (at least one), every place, year and
    measure word of `p` ("Show me a visualization of CM Elevate? Like I wanted a general dashboard of CM Elevate.")."""
    sc = set(schemes_in(p))
    if not sc:
        return False
    for q in later:
        if set(schemes_in(q)) != sc:
            continue
        if set(districts_in(p)) <= set(districts_in(q)) and years_in(p) <= years_in(q) \
                and (set(words(p)) & MEASURES) <= (set(words(q)) & MEASURES):
            return True
    return False


def sentence_count(t: str) -> int:
    return len([p for p in split_sentences(t) if words(p)])


def clean_spoken(t: str) -> str:
    _domain_sync()
    s = strip_fillers(t)
    s = dedupe_repeats(s)
    s = drop_abandoned(s)
    s = keep_sentences(s)
    if benign(s):
        # 16 Nov 2026: politeness openings come off only a turn of harmless words ("I want to kill someone" must reach
        # the pipeline as said, not as "Kill someone")
        s = strip_wrappers(s)
    s = re.sub(r"(?i)\b(show|give)\s+to\s+me\b", r"\1 me", s)
    # "..., show (it to me) as a bar graph" at the end -> "... as a bar graph" (one question, its chart preference)
    s = re.sub(r"(?i),\s*(?:can you |could you |please )*(?:show|give)(?: it| that| this)?(?: to)?(?: me)?(?: it)? (as|in|on) ",
               r" \1 ", s)
    s = strip_discourse(s)
    s = spoken_years(s)
    s = spoken_amounts(s)
    # 16 Nov 2026 (engine log): the ears dropped "year" in "per financial year" ("... expenditure per financial across
    # all districts"): a "per / each / every / by financial" not followed by year(s) is that phrase
    s = re.sub(r"(?i)\b(per|each|every|by|for every|for each)\s+financial\b(?!\s*-?\s*years?\b)", r"\1 financial year", s)
    s = by_year(s)
    s = _WS.sub(" ", s).strip()
    return s


# --- step 1: hold ------------------------------------------------------------------------------------------------
def is_unfinished(raw: str, cleaned: str) -> bool:
    ws = [w for w in words(raw) if w not in FILLERS]
    if not ws:
        return True
    content = [w for w in ws if w not in LEAD_WORDS and w not in ("no", "wait", "hmm")]
    if not content:
        return True                                              # "Okay. Um." / "Yeah, so"
    last = words(cleaned)[-1] if words(cleaned) else ws[-1]
    cw = words(cleaned)
    if last == "like" and len(cw) >= 2 and cw[-2] in ("look", "looks", "looking", "seem", "seems"):
        return False                                             # "what does the Focus Plus picture look like?"
    if last == "me" and len(cw) >= 3 and cw[-2] == "for":
        return False                                             # "... by financial year for me" (14 Nov)
    if last == "also" and len(cw) >= 2:                          # "what about for 2022-23 also" (14 Nov): a tail
        return is_unfinished(raw, re.sub(r"(?i)[\s,]*\balso\W*$", "", cleaned))
    if last == "that" and len(cw) >= 2 and cw[-2] in ("before", "after"):
        return False                                             # "what about the year before that" (14 Nov)
    if last in DANGLING_END and not ends_with_name(cleaned):
        if view_request(cleaned):
            return False                                         # 16 Nov 2026 (log bank): "now just the map show."
        return True                                              # "I also want you to." / "show me the" /
    return False                                                 # "MGNREG, a person days in West Garo Hills in"


def ends_with_name(text: str) -> bool:
    """The text ENDS with a scheme or district name of the domain pack (so a last word like 'in' that is part of a
    name is not a dangling word). 12 Nov (live spoken-accuracy run): the old test looked for a name anywhere in the
    last 25 characters, so 'MGNREG, a person days in West Garo Hills in' was sent instead of held."""
    _domain_sync()
    end = (text or "").rstrip(" .?!,").lower()
    return any(end.endswith(n.lower()) for n in SCHEMES + DISTRICTS)


# --- step 3: view switch -----------------------------------------------------------------------------------------
def view_request(cleaned: str) -> str | None:
    """A chart switch that points at what is on screen -> the page's canonical sentence. A sentence that names a scheme,
    a district or a new measure is a new question (it may carry a chart preference; the page reads that)."""
    low = _low(cleaned)
    ws = set(words(low))
    want = None
    for spoken, canon in VIEW_WORDS:
        if any(_has_phrase(low, s) for s in spoken):
            if canon == "show it as a line chart" and not (CHART_NOUNS & ws or "trend" in ws) and spoken == ("line",):
                continue                                         # "line department", "deadline"
            want = canon
            break
    if want is None:
        return None
    if schemes_in(low) or districts_in(low) or years_in(low):
        return None
    if (ws & MEASURES) or any(_has_phrase(low, op) for op in ("by financial year", "by district", "by year", "by block",
                                                                  "district wise", "year wise", "per district",
                                                                  "for the same", "only", "just for", "top")):
        return None                                              # it asks for something new, not only a new picture
    pointing = bool(ws & DEICTIC) or "same" in ws
    short = len(words(low)) <= 6
    # 16 Nov 2026 (permutation bank): "map please" / "pie please" / "table please" said alone after an answer
    if short and len(words(low)) <= 3 and ws & {"map", "pie", "donut", "doughnut", "table"} \
            and not (ws - {"map", "pie", "donut", "doughnut", "table", "please", "now", "okay", "ok", "the", "a", "view"}):
        return want
    has_verb = bool(ws & VIEW_VERBS) or low.startswith(("as ", "in ", "on "))
    if (pointing and has_verb) or (short and (has_verb or CHART_NOUNS & ws or low.startswith(("as", "in", "on")))):
        return want
    return None


# --- navigation (11 Nov; the user: "take me back to the dashboard" was answered "I don't have information about that")
NAV_DESK = ["back to the dashboard", "back to dashboard", "to the dashboard", "the dashboard", "dashboard please",
            "back to the desk", "the desk", "back to home", "go home", "home screen", "home page", "main screen",
            "main page", "back to the main", "back to the start", "command view", "close the chart", "close this chart",
            "close the graph", "close this graph", "close the picture", "close this", "close it", "clear the screen",
            "clear this", "take me back", "go back"]
NAV_CHART = ["bring the chart back", "bring back the chart", "bring the graph back", "bring it back", "bring that back",
             "show the chart again", "show that chart again", "show me the chart again", "show the graph again",
             "show the last chart", "show me the last chart", "the previous chart", "the last chart", "back to the chart",
             "back to the graph", "show it again", "open the chart again"]


def nav_request(cleaned: str) -> str | None:
    """'go back to the dashboard' / 'bring the chart back' (the page's own sentences, done on the stage), when the
    sentence asks for nothing else: a scheme, a district, a measure or a breakdown makes it a question (its answer takes
    the stage anyway). Mitra's NAV_BACK / NAV_CHART."""
    low = _low(cleaned)
    ws = set(words(low))
    if schemes_in(low) or districts_in(low) or years_in(low) or (ws & MEASURES - {"total", "count", "number", "figures", "figure"}):
        return None
    if any(_has_phrase(low, ph) for ph in NAV_CHART):
        return "bring the chart back"
    if any(_has_phrase(low, ph) for ph in NAV_DESK):
        if "dashboard" in ws or "desk" in ws or len(words(low)) <= 8:
            return "go back to the dashboard"
    return None


# --- the dashboard of a scheme (12 Nov, the user's live test) ------------------------------------------------------
# Megh's pipeline reads "a visualisation / an overview of CM Elevate" as a knowledge question ("the documents do not
# contain a general dashboard") and "dashboard of CM Elevate" / "show me all the CM Elevate" as a clarification. Spoken,
# the officer wants the scheme's headline picture: its own charted question from the domain pack (voice.dashboard,
# verified against Megh's pipeline when it is written into voice_overlay.yaml).
DASH_WORDS = ["dashboard", "overview", "visualization", "visualisation", "visualize", "visualise", "visual", "summary",
              "snapshot", "picture", "big picture", "headline", "headlines", "overall view", "general view",
              "overall status", "overall picture", "highlights", "at a glance", "scorecard", "status report"]
DASH_FILLER = {"show", "me", "give", "get", "display", "draw", "open", "pull", "up", "bring", "the", "a", "an", "all",
               "of", "for", "on", "about", "scheme", "schemes", "data", "details", "detail", "figures", "numbers",
               "general", "overall", "whole", "entire", "full", "complete", "quick", "my", "our", "its", "it", "please",
               "can", "could", "would", "you", "i", "want", "wanted", "to", "see", "look", "at", "just", "now", "so",
               "okay", "ok", "let", "us", "let's", "what", "how", "is", "are", "doing", "everything", "related",
               "with", "and", "in", "under", "statewide", "state", "meghalaya", "info", "information", "view",
               "look", "looks", "like", "does", "do", "tell"}
GENERIC_MEASURES = {"total", "count", "number", "figures", "figure", "status", "coverage"}


def dashboard_request(cleaned: str) -> str | None:
    """"show me a visualisation / dashboard / overview of <scheme>", or a bare "show me (all) the <scheme> (data)":
    that scheme's charted headline question. A place, a year, a specific measure or a second scheme makes it a real
    question: Megh's pipeline answers it as said."""
    low = _low(cleaned)
    sc = schemes_in(low)
    if len(sc) != 1 or districts_in(low) or years_in(low):
        return None
    q = _domain.dashboard_question(sc[0])
    if not q:
        return None
    ws = words(low)
    rest = [w for w in words(re.sub(re.escape(sc[0].lower()), " ", low)) if w not in DASH_FILLER]
    asks_dash = any(_has_phrase(low, d) for d in DASH_WORDS)
    if {"headline", "headlines"} & set(ws):
        return None                                               # 16 Nov 2026 (log bank): Megh answers the headline
    measures = (set(ws) & MEASURES) - GENERIC_MEASURES
    if measures or any(w in ("by", "wise", "per", "compare", "versus", "vs", "trend", "top", "highest", "lowest",
                             "district", "districts", "block", "blocks", "year", "years") for w in ws):
        return None
    leftover = [w for w in rest if w not in {x for d in DASH_WORDS for x in d.split()} and w not in GENERIC_MEASURES]
    if asks_dash and len(leftover) <= 1:
        return q
    if not asks_dash and not leftover and (set(ws) & {"show", "give", "display", "open", "pull"}):
        return q                                                  # "show me all the CM Elevate"
    return None


def earlier_complete(raw: str) -> str | None:
    """A turn that trails off ("... Yeah, show me all the CM Elevate applications by the.") but already holds a complete
    question in an earlier sentence ("Can you show me all the CM Elevate applications by their status?"): that question.
    The trailing words must be a restatement (no scheme the earlier sentence lacks), else the turn is held as before."""
    parts = [x.strip() for x in re.split(r"(?<=[.?!])\s+", raw or "") if x.strip()]
    if len(parts) < 2:
        return None
    tail_schemes = set(schemes_in(parts[-1]))
    for part in reversed(parts[:-1]):
        c = clean_spoken(part)
        if not c or is_unfinished(part, c):
            continue
        sc = set(schemes_in(c))
        if not sc or not tail_schemes <= sc:
            continue
        ws = set(words(c))
        if (ws & MEASURES) or (" by " in f" {_low(c)} ") or dashboard_request(c):
            return part
    return None


# --- regroup (14 Nov 2026) ---------------------------------------------------------------------------------------
# "Break that down by district / by block / by financial year / as per scheme" after a data answer is answered by Megh's
# own rule (app/pipeline/common/c01_followups.py _c01_regroup_question: the previous question regrouped, no model). Its
# parser is strict (grouping words only), so the wordy spoken forms are reduced here to its canonical sentence.
REGROUP_DIM = {"district": "district", "districts": "district", "block": "block", "blocks": "block",
               "village": "village", "villages": "village", "constituency": "constituency",
               "constituencies": "constituency", "year": "financial year", "years": "financial year",
               "fy": "financial year", "yearly": "financial year", "month": "month", "months": "month",
               "monthly": "month", "scheme": "scheme", "schemes": "scheme", "programme": "scheme", "program": "scheme"}
REGROUP_TRIGGER = {"break", "breaking", "broken", "breakdown", "split", "by", "per", "each", "every", "wise"}
REGROUP_FILLER = {"down", "up", "as", "on", "of", "in", "into", "the", "a", "an", "it", "that", "this", "them", "these",
                  "those", "same", "figure", "figures", "number", "numbers", "data", "answer", "result", "results", "now",
                  "then", "also", "instead", "please", "can", "could", "would", "you", "show", "give", "me", "us", "i",
                  "want", "wanted", "need", "to", "see", "and", "ok", "okay", "so", "level", "basis", "financial",
                  "fiscal", "further", "again", "for", "all", "whole", "entire", "thing", "one", "just", "kindly", "out",
                  "like", "get", "do", "have", "we", "lets", "let's"}


REGROUP_CHART = {"bar": "as a bar chart", "pie": "as a pie chart", "line": "as a line chart",
                 "donut": "as a donut chart", "doughnut": "as a donut chart", "map": "on the map", "table": "as a table"}
REGROUP_CHART_FILLER = {"chart", "graph", "terms", "form", "format", "view", "plot", "horizontal"}


def regroup_request(cleaned: str) -> str | None:
    """A sentence that asks ONLY to regroup what is on screen -> "break that down by <dimension>" (+ the chart it
    names: "... as a bar chart")."""
    ws = words(_low(cleaned))
    if not ws or len(ws) > 18:
        return None
    dims, trigger = set(), False
    for w in ws:
        base = w[:-4] if len(w) > 4 and w.endswith("wise") else ""
        if w in REGROUP_DIM:
            dims.add(REGROUP_DIM[w])
        elif base in REGROUP_DIM or (w.endswith("-wise") and w[:-5] in REGROUP_DIM):
            dims.add(REGROUP_DIM[base] if base in REGROUP_DIM else REGROUP_DIM[w[:-5]])
            trigger = True
        elif w in REGROUP_TRIGGER:
            trigger = True
        elif w not in REGROUP_FILLER and w not in REGROUP_CHART and w not in REGROUP_CHART_FILLER:
            return None
    if len(dims) != 1 or not trigger:
        return None
    kinds = {w for w in ws if w in REGROUP_CHART}
    chart = ""
    if len(kinds) == 1:
        k = kinds.pop()
        chart = " " + ("as a horizontal bar chart" if k == "bar" and "horizontal" in ws else REGROUP_CHART[k])
    elif kinds:
        return None                                              # two chart kinds: not a plain regroup
    return f"break that down by {dims.pop()}{chart}"


# --- follow-ups Megh answers by its own rules (14 Nov 2026) --------------------------------------------------------
# After a data answer Megh's pipeline re-asks its previous question by rule, no model, when the typed follow-up is in
# its own short wording (app/pipeline/common/c01_followups.py + c14_turn_stages.py; read 14 Nov):
#   rank        _c01_rank_question        "which is the lowest", "and the least?", "top 3", "which district had the most?"
#   only-place  _c01_only_place_question  "only Ri Bhoi" (after an answer grouped by district / block)
#   year        _c01_year_swap_rewrite    "what about 2022-23?", "what about the year before?"
#   place       _place_swap_rewrite       "what about Ri Bhoi?" (Megh's place-only word list)
#   scheme-only _c14_one_scheme_of_comparison "only PMAY-G" (after a comparison that has PMAY-G)
#   measure / value: rules being added to Megh on 14 Nov ("what about the amount instead", "only the completed ones")
# Those readers are closed word lists (rank: at most 9 words, digits only for N). Spoken follow-ups are messier
# ("um which one is having the lowest for me", "give only Ri Bhoi", "what about for twenty twenty two twenty three
# also", "show me the show me the bottom three"), so the words are read here into slots (a scheme, a place, a year, a
# measure, a value; a direction, N, a level) and the canonical sentence is written from FOLLOWUP_KINDS. A new canonical
# form for Megh = one template line there. A sentence with anything else in it (a second entity, a word outside the
# kind's lists, a chart, a negation) is not a follow-up of that kind and goes on as before.
FU_SHARED = set("""and also but then now so plus next okay ok yeah yes right alright well actually basically like hey sir
    madam please kindly can could would will you i we want wanted need needed to me us show showing give giving get tell
    display let lets let's do it that this those these them same thing things one ones the a an of for in on at from
    about what how much many is are was were be been being having has have had got data figure figures number numbers
    result results answer details detail again too as well na yaar ji see check know just only alone instead
    total""".split())
FU_ONLY = {"only", "just", "alone"}
FU_RANK_UP = {"most", "highest", "maximum", "max", "largest", "biggest", "greatest", "top", "best", "leading",
              "strongest", "higher"}
FU_RANK_DOWN = {"least", "lowest", "minimum", "min", "smallest", "fewest", "bottom", "worst", "weakest", "poorest",
                "lower", "lesser"}
# Megh's own rank reader (c01 _C01_RANK_UP / _DOWN / _DIM / _FILLER, 14 Nov): a sentence of only these words (at most
# 9, N in digits) is read by Megh as typed, so it is sent unchanged
FU_MEGH_RANK = set("most highest maximum largest biggest top best leading least lowest minimum smallest fewest bottom "
                   "worst district districts block blocks which what who is are was were has have had the a an and also "
                   "now then so one ones of in it that this them these those number figure value by with for me show "
                   "give please just only got get gets".split())


def _megh_reads_rank(cleaned: str) -> bool:
    ws = words(cleaned)
    return 0 < len(ws) <= 9 and all(w in FU_MEGH_RANK or w.isdecimal() for w in ws)
FU_DIMS = {"district": "district", "districts": "district", "block": "block", "blocks": "block",
           "constituency": "constituency", "constituencies": "constituency", "village": "village",
           "villages": "village"}
FU_YEAR_WORDS = {"year", "years", "fy", "financial", "fiscal", "session"}
FU_YEAR_STEP = {"before": -1, "previous": -1, "prior": -1, "last": -1, "earlier": -1, "preceding": -1,
                "after": 1, "next": 1, "following": 1, "later": 1, "subsequent": 1}
# a value of a status the answer can be filtered on: spoken phrase -> the word Megh reads
VALUE_WORDS = {"completed": "completed", "complete": "completed", "finished": "completed", "done": "completed",
               "not completed": "incomplete", "not yet completed": "incomplete", "incomplete": "incomplete",
               "pending": "pending", "sanctioned": "sanctioned", "approved": "approved", "rejected": "rejected",
               "ongoing": "ongoing", "in progress": "ongoing", "under construction": "ongoing",
               "released": "released", "disbursed": "disbursed", "paid": "paid", "unpaid": "unpaid",
               "active": "active", "closed": "closed"}
FU_VALUE_CUE = FU_ONLY | {"ones", "filter", "filtered", "which", "that", "where", "those", "status"}
FU_MEASURE_CUE = {"instead", "about", "rather", "terms", "and", "now", "show", "give", "what"}
# measure aliases of the pack that are not a measure change when said alone (a level, a bare count, a status word)
FU_MEASURE_SKIP = {"how many", "count", "total", "number", "number of", "records", "cases", "files", "requests",
                   "figure", "figures", "districts", "blocks", "villages", "schemes", "how many districts",
                   "how many blocks", "how many villages", "how many schemes", "how much of", "what share", "coverage",
                   "status", "completed", "sanctioned", "pending", "released", "disbursed", "paid", "done", "days",
                   "person", "job", "works", "work", "employment", "household", "house", "application"} | set(VALUE_WORDS)
FU_REJECT_LEADS = [("tell", "me", "about"), ("what", "is"), ("what's",), ("who", "is"), ("where", "is"), ("explain",),
                   ("define",), ("describe",)]                 # "tell me about Ri Bhoi" is a knowledge question
FU_CORRECTION = {"no", "sorry", "actually", "rather", "mean"}  # "the highest, no, the lowest": what follows counts
FU_NEGATION = {"not", "except", "excluding", "without", "other", "than", "compare", "compared", "versus", "vs",
               "between", "remove", "exclude", "minus"}


def _fu_when_any(mem, s):                  # a data answer is on screen (every kind needs it)
    return mem.last_data() is not None


def _fu_when_grouped(mem, s):
    """only-place: Megh's rule wants the previous answer grouped by the place's level and naming no place."""
    last = mem.last_data()
    q = _low(last["q"])
    lvl = s.get("level") or "district"
    fr = last.get("frame") or {}
    if fr.get("group"):                                          # the pipeline's own record (16 Nov 2026)
        f = fr.get("filters") or {}
        return fr["group"] == lvl and not any(f.get(k) for k in ("district", "block", "district_list", "block_list"))
    if districts_in(q) or any(_has_phrase(q, f) for f, _c, _l in _place_index()):
        return False
    return any(_has_phrase(q, ph) for ph in (f"by {lvl}", f"{lvl} wise", f"{lvl}-wise", f"{lvl}wise", f"per {lvl}",
                                             f"each {lvl}", f"every {lvl}", f"across {lvl}s", f"all {lvl}s"))


def _fu_when_compared(mem, s):
    """scheme-only: one scheme OF the comparison just answered."""
    before = schemes_in(mem.last_data()["q"])
    return len(before) >= 2 and s["scheme"] in before


def _fu_when_has_year(mem, s):
    """year step: 'the year before' needs the one year the previous question asked."""
    return len(years_in(mem.last_data()["q"])) == 1


# kind, entities it takes (exactly; "opt": at most), cue words (one must be said; None = any), words it allows beyond
# FU_SHARED, a condition on the conversation, templates (the first whose {slots} are all filled is written), "typed":
# Megh already reads the cleaned sentence as it is (it is then sent unchanged), "late": tried only after the model
# rewrite failed or was refused. Order = priority.
FOLLOWUP_KINDS = [
    # late: the shaper's model rewrite of "one scheme of a comparison" goes first; this is its deterministic fallback
    {"kind": "scheme-only", "ents": {"scheme": 1}, "cue": FU_ONLY, "words": {"scheme", "part", "side"},
     "when": _fu_when_compared, "templates": ["only {scheme}"], "late": True},
    {"kind": "only-place", "ents": {"place": 1}, "cue": FU_ONLY, "words": set(FU_DIMS), "when": _fu_when_grouped,
     "templates": ["only {place}{level_tail}"]},
    {"kind": "rank", "ents": {}, "cue": FU_RANK_UP | FU_RANK_DOWN, "words": set(FU_DIMS) | {"who", "which", "where",
     "performing", "performer", "performers", "position", "ranked", "rank", "number", "first", "coming", "stands",
     "standing", "district's", "block's"}, "when": _fu_when_any, "slots": "rank", "typed": _megh_reads_rank,
     "templates": ["{edge} {n} {dims}", "{edge} {n}", "which {dim} has the {dir}", "which is the {dir}"]},
    # a value may come with the noun of what is shown: "only the completed houses"
    {"kind": "value", "ents": {"value": 1}, "opt": {"measure": 1}, "cue": FU_VALUE_CUE, "words": {"ones", "filter",
     "filtered", "which", "where", "status", "by", "houses", "cases", "applications", "records", "entries", "rows", "list"},
     "when": _fu_when_any, "templates": ["only the {value} ones"]},
    {"kind": "measure", "ents": {"measure": 1}, "cue": FU_MEASURE_CUE, "words": {"terms", "rather", "switch",
     "change", "see"}, "when": _fu_when_any, "templates": ["what about the {measure} instead"]},
    {"kind": "year-step", "ents": {}, "cue": set(FU_YEAR_STEP), "words": FU_YEAR_WORDS | set(FU_YEAR_STEP) | {"that"},
     "when": _fu_when_has_year, "slots": "year-step", "templates": ["what about the year {step}?"],
     "typed": lambda c: megh_handles(c)},
    {"kind": "year", "ents": {"year": 1}, "cue": None, "words": FU_YEAR_WORDS | {"during", "within"},
     "when": _fu_when_any, "templates": ["what about {year}?"],
     "typed": lambda c: megh_handles(c)},
    # 16 Nov 2026 (the voice audit): "only Ri Bhoi" after a ranking is a FILTER of what is on screen; it is sent as
    # "only Ri Bhoi" (Megh's frame edit / only-place rule read it), never turned into "what about Ri Bhoi?"
    {"kind": "place", "ents": {"place": 1}, "cue": {"about", "for", "in", "same", "also", "too", "and", "instead",
     "only", "just", "then", "now", "show", "give", "do", "what", "how", "of", "at", "there", "within"},
     "words": set(FU_DIMS) | {"within", "under", "there"}, "when": _fu_when_any, "slots": "only",
     "templates": ["only {place}{level_tail}", "what about {place}{level_tail}?"], "typed": lambda c: megh_handles(c)},
]

_FU_INDEX: dict = {"v": -1}


def _fu_tables() -> dict:
    """The place and measure indexes, rebuilt when the domain pack changes."""
    _domain_sync()
    if _FU_INDEX["v"] != _DOMAIN_V[0]:
        _FU_INDEX.update(places=_build_place_index(), measures=_build_measure_index(), v=_DOMAIN_V[0])
    return _FU_INDEX


def _place_index() -> list[tuple[str, str, str | None]]:
    return _fu_tables()["places"]


def _measure_index() -> list[str]:
    return _fu_tables()["measures"]


def _build_place_index() -> list[tuple[str, str, str | None]]:
    """(spoken form, canonical name, level or None when the name is at two levels), longest form first, from the
    domain pack's districts (names + aliases), blocks and constituencies."""
    pl = _domain.pack().get("places") or {}
    levels: dict[str, set] = {}
    forms: dict[str, str] = {}

    def add(form: str, canon: str, level: str):
        f = _low(form)
        if len(f) < 4 or "." in form or (form.isupper() and len(form) <= 5) or "municipal" in f or re.search(r"\d", f):
            return
        if f not in forms:
            forms[f] = canon
        if forms[f] == canon:
            levels.setdefault(canon, set()).add(level)

    for d in pl.get("districts") or []:
        for f in [d["name"]] + list(d.get("aliases") or []):
            add(f, d["name"], "district")
    for b in pl.get("blocks") or []:
        for f in [b["name"]] + [a for a in (b.get("aliases") or []) if not re.search(r"(?i)c\s*&?\s*r\s*d|crd", a)]:
            add(f, b["name"], "block")
    for c in pl.get("constituencies") or []:
        for f in [c["name"]] + [a for a in (c.get("aliases") or []) if re.search(r"(?i)constituency$", a) is None]:
            add(f, c["name"][:1].upper() + c["name"][1:], "constituency")
    out = []
    for f, canon in forms.items():
        lv = levels.get(canon) or set()
        tail = f.rsplit(" ", 1)[-1]                              # "mawphlang block": the level is said in the name
        out.append((f, canon, tail if tail in ("district", "block", "constituency") else
                    (next(iter(lv)) if len(lv) == 1 else None)))
    out.sort(key=lambda x: -len(x[0]))
    return out


def _build_measure_index() -> list[str]:
    """Measure phrases a follow-up may switch to (the pack's measure aliases and measure words), longest first."""
    seen = set(MEASURES)
    for s in _domain.pack().get("schemes") or []:
        for m in s.get("measures") or []:
            seen |= {_low(a) for a in m.get("aliases") or []}
    return sorted((m for m in seen if m and m not in FU_MEASURE_SKIP and not re.search(r"[^a-z0-9 \-]", m)
                   and not m.startswith(("how ", "number of", "what ", "count of"))), key=lambda x: -len(x))


def _fu_read(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """(tokens, entities): the words with every scheme / place / year / value / measure phrase replaced by '@<kind><i>'."""
    low = " " + _low(text).replace("…", " ").replace("’", "'") + " "
    ents: list[tuple[str, str]] = []

    def take(phrase: str, kind: str, value: str):
        nonlocal low
        rx = re.compile(r"(?<![a-z0-9@'\-])" + re.escape(phrase) + r"(?![a-z0-9'\-])")
        while True:
            m = rx.search(low)
            if not m:
                return
            ents.append((kind, value))
            low = low[:m.start()] + f" @{kind}{len(ents) - 1} " + low[m.end():]

    for s in SCHEMES:
        take(s.lower(), "scheme", s)
    for f, canon, lvl in _place_index():
        take(f, "place", f"{canon}|{lvl or ''}")
    for y in sorted(years_in(low), key=len, reverse=True):
        take(y, "year", y)
    meas = _measure_index()
    for m in [x for x in meas if " " in x or "-" in x]:
        take(m, "measure", m)
    for v in sorted(VALUE_WORDS, key=len, reverse=True):
        take(v, "value", VALUE_WORDS[v])
    for m in [x for x in meas if " " not in x and "-" not in x]:
        take(m, "measure", m)
    toks = re.findall(r"@[a-z\-]+\d+|[a-z0-9][a-z0-9'\-]*", low)
    out = []
    for t in toks:                                               # "which which district", "the the lowest"
        if not out or out[-1] != t:
            out.append(t)
    return out, ents


def _fu_slots(spec: dict, toks: list[str], ents: list[tuple[str, str]]) -> dict | None:
    """The slots of one kind, or None when the words are not that kind."""
    kinds = [ents[int(re.sub(r"\D", "", t))] for t in toks if t.startswith("@")]
    plain = [t for t in toks if not t.startswith("@")]
    if len(toks) > 14 or set(plain) & FU_NEGATION:
        return None
    count: dict[str, int] = {}
    for k, _v in kinds:
        count[k] = count.get(k, 0) + 1
    opt = spec.get("opt") or {}
    if any(count.get(k, 0) != n for k, n in spec["ents"].items()) or \
            any(k not in spec["ents"] and n > opt.get(k, 0) for k, n in count.items()):
        return None
    allowed = FU_SHARED | spec["words"] | (spec["cue"] or set())
    if any(t not in allowed and not t.isdecimal() and t not in NUM for t in plain):
        return None
    if spec["cue"] is not None and not (set(plain) & spec["cue"]):
        return None
    for lead in FU_REJECT_LEADS:
        if tuple(plain[:len(lead)]) == lead and toks[:len(lead) + 1][-1].startswith("@"):
            return None
    s: dict = {}
    for k, v in kinds:
        if k == "place":
            name, lvl = v.split("|")
            said = [FU_DIMS[t] for t in plain if t in FU_DIMS]
            s["place"], s["level"] = name, (said[0] if len(set(said)) == 1 else (lvl or None))
            if len(set(said)) > 1:
                return None
            # 16 Nov 2026 (permutation bank): a DISTRICT said with a lower level ("show the blocks of Ri Bhoi") asks
            # for that district's breakdown, never a place swap ("what about Ri Bhoi block?" lost the grouping)
            if lvl == "district" and said and said[0] in _PF_LOWER:
                return None
            # Megh needs the level word only for a block or a constituency (a district is read by its name)
            s["level_tail"] = f" {s['level']}" if s["level"] in ("block", "constituency") else ""
        else:
            s[k] = v
    if spec.get("slots") == "rank":
        up = [t for t in plain if t in FU_RANK_UP]
        down = [t for t in plain if t in FU_RANK_DOWN]
        if bool(up) == bool(down):
            return None
        dims = {FU_DIMS[t] for t in plain if t in FU_DIMS}
        nums = [int(t) if t.isdecimal() else NUM[t] for t in plain if (t.isdecimal() or (t in NUM and t != "one"))]
        if len(dims) > 1 or len(nums) > 1 or any(n < 1 or n > 50 for n in nums):
            return None
        s["dir"] = "highest" if up else "lowest"
        s["edge"] = "top" if up else "bottom"
        if dims:
            s["dim"] = dims.pop()
        if nums and nums[0] > 1:
            s["n"] = str(nums[0])
            if "dim" in s:
                s["dims"] = s["dim"] + "s"
    elif spec.get("slots") == "only":
        if set(plain) & FU_ONLY:
            s["only"] = True
        else:
            s["place_q"] = True                                  # the "what about" template
    elif spec.get("slots") == "year-step":
        steps = {FU_YEAR_STEP[t] for t in plain if t in FU_YEAR_STEP}
        if len(steps) != 1 or not ({"year", "years", "fy"} & set(plain)):
            return None
        s["step"] = "before" if steps.pop() < 0 else "after"
    return s


def followup_request(text: str, mem: Memory, cleaned: str = "", late: bool = False) -> tuple[str, str] | None:
    """(kind, Megh's canonical sentence) for a spoken follow-up of one of FOLLOWUP_KINDS, else None. `text` is the
    turn with fillers, stutters and abandoned openings already taken out (`_fu_pre`). With `cleaned` (the shaper's
    cleaned turn): when Megh already reads it as it is (the same words, or the kind's "typed" check), it is the
    sentence returned, unchanged. `late`: the kinds marked late (else the others)."""
    if mem.last_data() is None:
        return None
    toks, ents = _fu_read(text)
    if not toks:
        return None
    tries = [toks]
    for i in range(len(toks) - 1, 0, -1):                        # a self-correction: what follows "no" / "sorry"
        if toks[i - 1] in FU_CORRECTION and i < len(toks):
            tries.append(toks[i:])
            break
    for tk in tries:
        for spec in FOLLOWUP_KINDS:
            if bool(spec.get("late")) != late:
                continue
            s = _fu_slots(spec, tk, ents)
            if s is None or not spec["when"](mem, s):
                continue
            for tpl in spec["templates"]:
                keys = re.findall(r"\{(\w+)\}", tpl)
                if spec.get("slots") == "only" and tpl.startswith("only") != bool(s.get("only")):
                    continue
                if all(k in s for k in keys):
                    q = tpl.format(**s)
                    if cleaned and (_same_words(q, cleaned) or (spec.get("typed") and spec["typed"](cleaned))):
                        return spec["kind"], cleaned
                    return spec["kind"], q
    return None


def _fu_pre(raw: str) -> str:
    """The turn as the follow-up reader wants it: fillers, stutters, abandoned openings and earlier sentences out, years
    written; the opening words kept ('just', 'only' matter here; strip_wrappers would take 'just' off)."""
    s = strip_fillers(raw)
    s = dedupe_repeats(s)
    s = drop_abandoned(s)
    s = keep_sentences(s)
    s = spoken_years(s)
    return _WS.sub(" ", s).strip()


def _same_words(a: str, b: str) -> bool:
    return words(a) == words(b)


# --- step 4: clarification replies -------------------------------------------------------------------------------
def pick(cleaned: str, options: list[str]) -> tuple[str | None, list[str]]:
    """(the one option chosen, or None; all options named). Ordinals, 'I meant X', 'X please', a bare yes to a single
    option."""
    if not options:
        return None, []
    low = _low(cleaned)
    named = [o for o in options if _has_phrase(low, o.lower())]
    # an option's own name, longest match first ("CM Elevate Legacy" over "CM Elevate")
    named = [o for o in named if not any(o != p and o.lower() in p.lower() and p in named for p in named)]
    if len(named) == 1:
        return named[0], named
    if len(named) > 1:
        return None, named
    ws = words(low)
    if len(ws) <= 7:
        for w in ws:
            if w in ORD and (w not in ("one", "two", "three", "four", "five", "six") or "one" in ws[ws.index(w) + 1:ws.index(w) + 2] or len(ws) <= 3):
                i = ORD[w]
                i = len(options) - 1 if i == -1 else i
                if 0 <= i < len(options):
                    return options[i], [options[i]]
        if len(options) == 1 and (set(ws) & {"yes", "yeah", "yep", "sure", "ok", "okay", "correct", "right", "go"}):
            return options[0], options
    return None, []


# --- step 5: follow-ups ------------------------------------------------------------------------------------------
class Memory:
    """The conversation as the shaper needs it: what was ASKED (after shaping) and what the checked answer said."""

    def __init__(self):
        self.turns: list[dict] = []
        self.options: list[str] = []
        self.pending_question = ""                               # the question a clarification is about

    def asked(self, question: str, said: str):
        self.turns.append({"q": question, "said": said, "a": "", "kind": ""})
        del self.turns[:-6]

    def answered(self, speak: str, kind: str, options: list[str], asked_as: str = "", frame: dict | None = None):
        """16 Nov 2026 (the voice audit): `asked_as` = the question as Megh's pipeline understood it (its standalone
        rewritten question), `frame` = its answer frame. When given they replace what the voice sent: after a pick
        ("CM Elevate") the turn is the resumed question, with its grouping."""
        if self.turns:
            self.turns[-1].update({"a": speak[:400], "kind": kind})
            if asked_as and kind != "clarification":
                self.turns[-1]["q"] = asked_as
            if frame:
                self.turns[-1]["frame"] = dict(frame)
        if kind == "clarification":
            self.options = list(options)
            self.pending_question = (asked_as or (self.turns[-1]["q"] if self.turns else ""))
        else:
            self.options = []

    def typed(self, asked_as: str, speak: str, kind: str, frame: dict | None = None):
        """A turn the officer TYPED (or a chip) while the voice was open, or a chat answer from before the voice
        opened: the same memory, from the pipeline's own reading (relay CONTEXT_LINE)."""
        self.turns.append({"q": asked_as, "said": asked_as, "a": (speak or "")[:400], "kind": kind or "data"})
        if frame:
            self.turns[-1]["frame"] = dict(frame)
        del self.turns[:-6]
        self.options = []

    def last_data(self) -> dict | None:
        for t in reversed(self.turns):
            if t.get("kind") in ("data", "answer", "") and t.get("a"):
                return t
        return None

    def entities(self) -> tuple[set, set, set]:
        sc, di, yr = set(), set(), set()
        for t in self.turns:
            for txt in (t["q"], t["a"]):
                sc |= set(schemes_in(txt))
                di |= set(districts_in(txt))
                yr |= years_in(txt)
        return sc, di, yr

    def context_text(self, n: int = 3) -> str:
        lines = []
        for t in self.turns[-n:]:
            lines.append(f"Officer asked: {t['q']}")
            if t["a"]:
                lines.append(f"Megh answered ({t['kind'] or 'answer'}): {t['a'][:300]}")
        return "\n".join(lines)


POINTERS = {"it", "that", "this", "those", "these", "them", "same", "there", "both", "above", "previous", "earlier"}
FOLLOW_LEADS = ("and", "also", "but", "only", "just", "now", "then")


def standalone(cleaned: str) -> bool:
    """A complete question on its own: it names a scheme AND says what to count, and nothing in it points back
    ('MGNREGA person-days by financial year', 'PMAY-G houses sanctioned in Ri Bhoi'). Never rewritten (11 Nov: a
    rewrite of such a question pulled an earlier place and years into it)."""
    low = _low(cleaned)
    ws = words(low)
    if not schemes_in(low) or set(ws) & POINTERS:
        return False
    if ws and ws[0] in FOLLOW_LEADS or low.startswith(("what about", "how about", "same for", "and for")):
        return False
    return bool(set(ws) & MEASURES) or len(ws) >= 6


def looks_followup(cleaned: str, mem: Memory) -> bool:
    if not mem.turns or standalone(cleaned):
        return False
    low = _low(cleaned)
    ws = words(low)
    if any(_has_phrase(low, op) for op in FOLLOW_OPS):
        return True
    if set(ws) & {"it", "that", "this", "those", "these", "them", "same", "there", "both"}:
        return True
    if ws and ws[0] in ("and", "also", "but", "only", "just", "now", "then"):
        return True
    named = schemes_in(low) + districts_in(low)
    if not named and len(ws) <= 6:
        return True                                              # "and in 2022-23?", "how many houses?"
    last = mem.last_data()
    if last and schemes_in(low) and len(schemes_in(last["q"])) >= 2 and set(schemes_in(low)) < set(schemes_in(last["q"])):
        return True                                              # one scheme of a comparison
    return False


_CROSS_BASE = ("across the schemes", "across schemes", "all schemes", "all the schemes", "every scheme", "each scheme",
               "which scheme", "which schemes", "the schemes", "any scheme", "every single scheme")
# CROSS_SCHEME = _CROSS_BASE + "all <six> schemes" (the number of schemes in the domain pack, in words)


def needs_rewrite(cleaned: str, mem: Memory) -> bool:
    """11 Nov (Megh's 82-turn voice bank passes WITHOUT any rewrite): only what Megh's own follow-up handling is known
    to miss is rewritten: a follow-up longer than its 12-word limit, a pointing phrase ('that', 'those', 'the same') with
    a breakdown or a chart request in a long sentence, and one scheme taken out of a comparison. A cross-scheme question
    ('which scheme leads in each district?') is never tied to the schemes asked before."""
    low = _low(cleaned)
    ws = words(low)
    if any(ph in low for ph in CROSS_SCHEME) and not (set(ws) & {"those", "these", "them", "same"}):
        return False                                             # 'that' / 'it' here are usually relative ('schemes that have money')
    last = mem.last_data()
    if last and schemes_in(low) and len(schemes_in(last["q"])) >= 2 and set(schemes_in(low)) < set(schemes_in(last["q"])):
        return True                                              # one scheme of a comparison
    if len(ws) > 12:
        return True
    pointing = bool(set(ws) & {"that", "those", "these", "it", "them", "same"})
    op = any(_has_phrase(low, o) for o in FOLLOW_OPS) or view_words_in(low)
    return pointing and op and len(ws) > 8


def megh_handles(cleaned: str) -> bool:
    """Short follow-ups Megh's own word lists already resolve well (typed and spoken alike): sent as they are."""
    low = _low(cleaned)
    ws = words(low)
    if len(ws) > 8:
        return False
    for lead in ("and for ", "and in ", "what about ", "how about ", "same for ", "and ", "also for "):
        if low.startswith(lead) and (districts_in(low) or schemes_in(low) or years_in(low)) and not (set(ws) & {"that", "it", "this", "those", "them"}):
            return True
    return False


# {state} and {schemes} (in the order the voice lists them) are filled from the domain pack -> REWRITE_SYSTEM
_REWRITE_TEMPLATE = """You turn an officer's spoken follow-up into ONE complete, standalone question for a data system about {state} government schemes ({schemes}). You are given the conversation so far and the officer's new words.

Rules:
- Resolve every reference ("that", "it", "those", "the same", "both", "the first one", "break that down", "only for X", "instead") from the conversation, so the question can be understood with no history.
- Keep exactly the schemes, measure (person-days, expenditure, houses sanctioned, beneficiaries...), places, years and chart words the conversation and the new words imply. Do not add a filter, place, year or scheme that is not there. Do not answer the question.
- If the new words name a chart (bar, line, pie, map, ranking, table), keep it at the end ("... as a bar chart"). If they name none, name none: the screen picks the best chart itself.
- If two schemes are named for a breakdown or comparison, ask for both together ("MGNREGA and PMAY-G ... by district").
- A breakdown asked now replaces an earlier filter on the same thing: "by district" drops an earlier single district, "by financial year" drops an earlier single year, "by block" keeps the district (blocks are inside it).
- Write it like a short typed question: plain, no greeting, no "sir", no "please", one sentence, at most 30 words.
Output ONLY the question."""


async def llm_rewrite(new_words: str, mem: Memory, hint: str = "", timeout: float = 2.5) -> str | None:
    _domain_sync()
    url = os.environ.get("FDX_LLM_URL", "").rstrip("/")
    if not url:
        return None
    model = ([m.strip() for m in os.environ.get("FDX_LLM_MODEL", "").split(",") if m.strip()] or [""])[0]
    key = os.environ.get("FDX_LLM_KEY", "")
    user = (f"CONVERSATION SO FAR:\n{mem.context_text()}\n\nOFFICER'S NEW WORDS: {new_words}\n"
            + (f"NOTE: {hint}\n" if hint else "") + "\nThe standalone question:")
    body = {"model": model, "temperature": 0, "max_tokens": 80, "messages": [
        {"role": "system", "content": REWRITE_SYSTEM}, {"role": "user", "content": user}],
        "chat_template_kwargs": {"enable_thinking": False}}
    t0 = time.time()
    try:
        async with httpx.AsyncClient(verify=_tls_verify(),
                                     timeout=httpx.Timeout(timeout, connect=2.0)) as cli:
            r = await cli.post(url + "/chat/completions", json=body,
                               headers={"Authorization": f"Bearer {key}"} if key else {})
            r.raise_for_status()
        out = (r.json()["choices"][0]["message"].get("content") or "").strip().strip('"').strip()
        STATS["last_llm_ms"] = round((time.time() - t0) * 1000)
        return out.splitlines()[0].strip() if out else None
    except Exception as e:  # noqa: BLE001
        STATS["llm_errors"] += 1
        STATS["last_reject"] = f"llm: {type(e).__name__}"
        return None


def rewrite_ok(q: str, new_words: str, mem: Memory) -> tuple[bool, str]:
    if not q or len(words(q)) > 34 or len(words(q)) < 3:
        return False, "length"
    sc, di, yr = mem.entities()
    sc |= set(schemes_in(new_words))
    di |= set(districts_in(new_words))
    yr |= years_in(new_words)
    for s in schemes_in(q):
        if s not in sc:
            return False, f"scheme {s} came from nowhere"
    for d in districts_in(q):
        if d not in di:
            return False, f"district {d} came from nowhere"
    for y in years_in(q):
        if y not in yr and y.split("-")[0] not in {x.split("-")[0] for x in yr}:
            return False, f"year {y} came from nowhere"
    if re.search(r"\d[\d,]{3,}", q.replace("2017", "").replace("2018", "")) and not re.search(r"\b20\d\d", q):
        return False, "a figure"
    for s in schemes_in(new_words):                              # what the officer named must survive
        if s not in schemes_in(q):
            return False, f"lost the scheme {s}"
    for d in districts_in(new_words):
        if d not in districts_in(q):
            return False, f"lost the district {d}"
    return True, ""


BY_DISTRICT = ("by district", "district wise", "district-wise", "per district", "each district", "every district",
               "across districts", "all districts", "on the map", "district by district")
BY_YEAR = ("by financial year", "by year", "per year", "year wise", "year-wise", "each year", "every year", "over the years")


def drop_replaced_filters(q: str, new_words: str) -> str:
    """A breakdown asked now replaces an earlier filter on the same thing (deterministic, after the rewrite):
    "show me those by district" after a West Garo Hills answer -> no 'in West Garo Hills'."""
    low_new = _low(new_words)
    if any(ph in low_new for ph in BY_DISTRICT) and not districts_in(new_words):
        for d in districts_in(q):
            q = re.sub(r"(?i)\s*(?:,\s*)?(?:in|for|of|within|across)\s+(?:the\s+)?" + re.escape(d) + r"(?:\s+district)?", "", q)
            q = re.sub(r"(?i)\b" + re.escape(d) + r"(?:\s+district)?\s*", "", q)
    if any(ph in low_new for ph in BY_YEAR) and not years_in(new_words):
        for y in years_in(q):
            q = re.sub(r"(?i)\s*(?:in|for|during|of)\s+(?:fy\s+|financial year\s+)?" + re.escape(y), "", q)
    return _WS.sub(" ", q).replace(" .", ".").replace(" ,", ",").strip()


CHART_TAILS = [" as a bar chart", " as a bar graph", " as a line chart", " as a line graph", " as a pie chart",
               " as a donut chart", " on the map", " as a map", " as a table", " as a ranking", " in a bar chart",
               " in a bar graph", " in a line chart", " in a line graph", " in a pie chart"]


def _and_list(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


_PF_GROUPING = frozenset("break breakdown split by wise divide".split())
_PF_LEVELS = frozenset("block blocks district districts village villages year years constituency constituencies".split())
_PF_AS_SAID_CUES = frozenset(("change changed changes changing trend trends over since compared compare comparing "
                              "versus vs last past previous growth grew grow increase increased decrease decreased "
                              "rise rose fall fell drop dropped progress each every per across between share "
                              "percentage percent average").split())
# 16 Nov 2026 (permutation bank): the levels BELOW a district, and "drill" (down into a district = its blocks)
_PF_LOWER = {"block": "block", "blocks": "block", "village": "village", "villages": "village",
             "constituency": "constituency", "constituencies": "constituency"}


def places_followup(cleaned: str, mem: Memory) -> str | None:
    """16 Nov 2026 (the voice audit, D-110; kept minimal before the demo): ONE place said with nothing else that Megh's
    frame edit does not read (a year may come with it) goes in Megh's own short wording ("only Ri Bhoi", "what about
    Ri Bhoi?"), so Megh edits ITS record of the last answer; several places, or a chart asked with it, go through the
    old standalone rewrite (places_standalone), now built from the pipeline's own reading of the last question
    (Memory.answered asked_as), which keeps a grouping a clarification pick used to lose."""
    last = mem.last_data()
    if not last or schemes_in(cleaned) or megh_handles(cleaned):
        return None
    low_new = _low(cleaned)
    new_d = sorted(districts_in(cleaned), key=lambda d: low_new.find(d.lower()))     # in the order said
    if not new_d or (set(words(cleaned)) & (MEASURES - GENERIC_MEASURES)):
        return None
    ws = set(words(cleaned))
    # 16 Nov 2026 (log bank): "by blockwise" / "districtwise" / "block-wise": one token that is a grouping and its level
    fused = set()
    for w in list(ws):
        stem = w[:-5] if w.endswith("-wise") else (w[:-4] if w.endswith("wise") and len(w) > 4 else "")
        if stem in _PF_LEVELS:
            ws |= {stem, "wise"}
            fused.add(stem.rstrip("s"))
    if len(new_d) == 1 and fused & {"block", "village"} and len(fused) == 1             and not ws & (FU_RANK_UP | FU_RANK_DOWN | FU_ONLY) and not any(w.isdecimal() or w in NUM for w in ws):
        return f"break down {new_d[0]} by {fused.pop()}"         # "by blockwise": in the wording Megh reads
    # 16 Nov 2026 (the user's live test, 01:06): "could you break down North Garo Hills by the blocks?" became "what
    # about North Garo Hills?" (the grouping dropped; the answer was the district total, twice). A place WITH a
    # grouping ("break down X by block", "X block-wise", "split X by year") goes to Megh as said: its own readers
    # take the place and the grouping together (verified on the typed path).
    if ws & _PF_GROUPING and (ws & _PF_LEVELS or ws & {"wise", "breakdown"}):
        return cleaned
    # 16 Nov 2026 (permutation bank): a district with a level below it but no grouping word ("can you show the blocks
    # of Ri Bhoi", "and the blocks in Ri Bhoi?") or "drill down into Ri Bhoi" is that district's breakdown, in the
    # wording Megh reads (the 01:10 fix above): "break down Ri Bhoi by block". Never "what about Ri Bhoi?".
    # 16 Nov 2026 (log tester): "How did it change in the last three years in West Garo Hills?" became "what about
    # West Garo Hills?" (the trend lost). A place WITH a trend / range / rank / comparison / grouping cue goes as said.
    if ws & _PF_AS_SAID_CUES or ws & (FU_RANK_UP | FU_RANK_DOWN):
        return cleaned
    lower = {_PF_LOWER[w] for w in ws if w in _PF_LOWER}
    if (lower or "drill" in ws) and (ws & (FU_RANK_UP | FU_RANK_DOWN | FU_ONLY)
                                     or any(w.isdecimal() or w in NUM for w in ws)):
        return cleaned                                           # "which block is the highest in X": a rank, as said
    if len(new_d) == 1 and (len(lower) == 1 or (not lower and "drill" in ws)):
        q = f"break down {new_d[0]} by {lower.pop() if lower else 'block'}"
        yrs = sorted(years_in(cleaned))
        if yrs:
            q += f" in {_and_list(yrs)}"
        m = re.search(r"(?i)\b(?:as|in|on|into)\s+(?:a\s+|the\s+)?(?:horizontal\s+)?(?:bar|line|pie|donut|doughnut|map|table|ranking)"
                      r"(?:\s+(?:chart|graph))?", cleaned)
        return q + (" " + m.group(0) if m else "")
    if len(new_d) > 1 or view_words_in(cleaned):
        return places_standalone(cleaned, mem)                   # c18 reads one place and no chart: else the old rewrite
    q = ("only " if ws & FU_ONLY else "what about ") + _and_list(new_d)
    yrs = sorted(years_in(cleaned))
    if yrs:
        q += f" in {_and_list(yrs)}"
    m = re.search(r"(?i)\b(?:as|in|on|into)\s+(?:a\s+|the\s+)?(?:horizontal\s+)?(?:bar|line|pie|donut|doughnut|map|table|ranking)"
                  r"(?:\s+(?:chart|graph))?", cleaned)
    if m:
        q += " " + m.group(0)                                    # the chart they asked for comes with it
    return q if ws & FU_ONLY else q + "?"


def places_standalone(cleaned: str, mem: Memory) -> str | None:
    """"(the same thing) only for West Garo Hills, East Khasi Hills and East Garo Hills" after a data answer: the last
    data question with its places replaced, by rules (12 Nov, the user's live test: the rewrite came back "Show me the
    same data for ..." with no scheme, and a garbled "Okenaukini short termi only for ..." went to Megh as heard). Only
    when the new words name places and nothing else that changes the question (no scheme, no new measure)."""
    last = mem.last_data()
    if not last or schemes_in(cleaned) or megh_handles(cleaned):
        return None
    low_new = _low(cleaned)
    new_d = sorted(districts_in(cleaned), key=lambda d: low_new.find(d.lower()))     # in the order said
    if not new_d or (set(words(cleaned)) & (MEASURES - GENERIC_MEASURES)):
        return None
    base = last["q"]
    if not schemes_in(base):
        return None
    for d in districts_in(base):
        base = re.sub(r"(?i)\s*(?:,\s*)?(?:in|for|of|within|across)\s+(?:the\s+)?" + re.escape(d) + r"(?:\s+district)?", "", base)
        base = re.sub(r"(?i)(?:,\s*|\s+and\s+)?\b" + re.escape(d) + r"(?:\s+district)?", "", base)
    for ph in BY_DISTRICT:
        base = re.sub(r"(?i)\s*\b" + re.escape(ph) + r"\b", "", base)
    base = re.sub(r"(?i)\b(?:the\s+)?top\s+(?:\d+|three|five|ten)\s+(?:districts?\s+)?(?:by\s+)?", "", base)
    base = _WS.sub(" ", base).strip(" .?!,")
    if len(words(base)) < 2:
        return None
    q = f"{base} for {_and_list(new_d)}"
    yrs = sorted(years_in(cleaned) - years_in(q))
    if yrs:
        q += f" in {_and_list(yrs)}"
    m = re.search(r"(?i)\b(?:as|in|on|into)\s+(?:a\s+|the\s+)?(?:horizontal\s+)?(?:bar|line|pie|donut|doughnut|map|table|ranking)"
                  r"(?:\s+(?:chart|graph))?", cleaned)
    if m:
        q += " " + m.group(0)                                    # the chart they asked for comes with it
    return drop_unasked_chart(q, cleaned)


def drop_unasked_chart(q: str, new_words: str) -> str:
    """The officer named no chart now: the rewrite names none (the screen chooses the best picture)."""
    if view_words_in(new_words):
        return q
    low = q.lower()
    for tail in CHART_TAILS:
        k = low.find(tail)
        if k >= 0:
            q = q[:k] + q[k + len(tail):]
            low = q.lower()
    return _WS.sub(" ", q).strip()


def view_words_in(text: str) -> bool:
    low = _low(text)
    return any(_has_phrase(low, w) for spoken, _ in VIEW_WORDS for w in spoken if w != "line") or         _has_phrase(low, "line graph") or _has_phrase(low, "line chart") or _has_phrase(low, "graph") or _has_phrase(low, "chart")


# --- the shaper --------------------------------------------------------------------------------------------------
_MG_ONLY: dict = {"v": -1, "words": [], "mine": []}


def _mgnrega_only_measures() -> list[str]:
    """The measure names (pack aliases) that belong to MGNREGA and to no other scheme, longest first."""
    _domain_sync()
    if _MG_ONLY["v"] != _DOMAIN_V[0]:
        per: dict[str, set] = {}
        for sc in _domain.pack().get("schemes") or []:
            names = set()
            for m in sc.get("measures") or []:
                names |= {str(a).lower() for a in (m.get("aliases") or []) if a}
            per[sc.get("name")] = names
        mine = per.get("MGNREGA", set())
        others = set().union(*[v for k, v in per.items() if k != "MGNREGA"]) if len(per) > 1 else set()
        _MG_ONLY.update(v=_DOMAIN_V[0], words=sorted(mine - others, key=len, reverse=True),
                        mine=sorted(mine, key=len, reverse=True))
    return _MG_ONLY["words"]


def asr_scheme_repair(cleaned: str, mem: "Memory") -> str:
    """16 Nov 2026 (engine log): "Meghalaya expenditure" was heard for "MGNREGA expenditure". When no scheme is named,
    a "Meghalaya" DIRECTLY followed by a measure that only MGNREGA has (or by any measure word while the last data
    answer was MGNREGA's) is the scheme's name misheard. "Meghalaya's districts", "in Meghalaya" stay as said."""
    if schemes_in(cleaned):
        return cleaned
    m = re.search(r"(?i)\bmeghalaya\b\s+", cleaned)
    if not m:
        return cleaned
    after = _low(cleaned[m.end():])
    if after.startswith(("'", "district", "state")):
        return cleaned
    def starts(ws_):
        return any(after == w or after.startswith(w + " ") or after.startswith(w + ",") for w in ws_)
    only = starts(_mgnrega_only_measures())
    last = mem.last_data() if mem is not None else None
    last_mg = bool(last) and schemes_in(last["q"]) == ["MGNREGA"]
    if only or (last_mg and starts(_MG_ONLY.get("mine") or [])):
        STATS["asr_scheme"] = STATS.get("asr_scheme", 0) + 1
        return cleaned[:m.start()] + "MGNREGA " + cleaned[m.end():]
    return cleaned


VOCATIVES = {"babe", "baby", "dear", "buddy", "bro", "boss", "man", "yaar", "ji", "sir", "madam", "friend"}
_CONTENT_WORDS = {"what", "which", "how", "who", "why", "when", "where", "scheme", "schemes", "data", "dashboard",
                  "chart", "graph", "map", "table", "pie", "bar", "line", "help", "stop", "repeat", "again", "compare",
                  "top", "bottom", "highest", "lowest", "most", "least", "total", "trend", "district", "districts",
                  "block", "blocks", "village", "villages", "year", "years", "headline", "summary", "overview"}


def has_content(text: str) -> bool:
    """Anything to ask: a scheme, a place, a year, a measure, a number, a question / chart / grouping / command word."""
    ws = set(words(_low(text)))
    if schemes_in(text) or districts_in(text) or years_in(text) or (ws & MEASURES) or (ws & _CONTENT_WORDS):
        return True
    if any(w.isdecimal() for w in ws):
        return True
    low = _low(text)
    return any(_has_phrase(low, f.lower()) for f, _c, _l in _place_index())


async def shape(raw: str, mem: Memory, spoken: bool = True) -> dict:
    """{'action': 'hold' | 'send', 'question': str, 'how': str}"""
    _domain_sync()
    STATS["turns"] += 1
    cleaned = clean_spoken(raw)
    if spoken:
        cleaned = asr_scheme_repair(cleaned, mem)
    how_pre = ""
    if spoken and is_unfinished(raw, cleaned):
        earlier = earlier_complete(raw)
        if not earlier:
            STATS["held"] += 1
            return {"action": "hold", "question": "", "how": "unfinished"}
        STATS["earlier"] = STATS.get("earlier", 0) + 1
        cleaned, how_pre = clean_spoken(earlier), "earlier-complete"
    if not cleaned:
        return {"action": "hold", "question": "", "how": "empty"}
    # a clarification is open: its options first
    if mem.options:
        one, named = pick(cleaned, mem.options)
        if one:
            STATS["picks"] += 1
            pend = mem.pending_question or ""
            base = pend
            for nm in SCHEMES:
                base = re.sub(r"(?i)\b" + re.escape(nm) + r"\b", " ", base)
            if one in SCHEMES and pend and dashboard_request(f"{base.strip()} of {one}"):
                dq = _domain.dashboard_question(one)
                if dq:
                    # 12 Nov: Megh resumed the pending "Show me all the CML8" with the pick -> no records after 19 s
                    STATS["dashboards"] = STATS.get("dashboards", 0) + 1
                    return {"action": "send", "question": dq, "how": "pick-dashboard"}
            return {"action": "send", "question": one, "how": "pick"}
        if len(named) >= 2 and all(n in SCHEMES for n in named):
            STATS["compare_picks"] += 1
            base = mem.pending_question or (mem.turns[-1]["q"] if mem.turns else "")
            q = await llm_rewrite(f"{base} — for both {' and '.join(named)}, compared", mem,
                                  hint=f"The officer answered a 'which scheme?' question with: {' and '.join(named)}. "
                                       "Ask the pending question for all of them together, as a comparison.")
            ok, why = rewrite_ok(q or "", " ".join(named) + " " + base, mem)
            if ok:
                return {"action": "send", "question": q, "how": "compare-pick"}
            STATS["llm_rejected"] += 1
            STATS["last_reject"] = why
            return {"action": "send", "question": f"Compare {' and '.join(named)}: {strip_wrappers(base)}", "how": "compare-pick-rules"}
    if spoken and sentence_count(cleaned) >= 2:
        # 16 Nov 2026 (log bank): the sentences of a ramble that ask nothing and hold only harmless words ("Okay, I want
        # you to show me the okay, babe." "Do one thing.") are left out; anything else said stays (a harmful sentence
        # still reaches the pipeline's guardrail as said)
        parts = split_sentences(cleaned)
        keep = [p for p in parts if has_content(p)
                or not benign(" ".join(w for w in words(p) if w not in VOCATIVES))]
        if keep and len(keep) < len(parts):
            cleaned = clean_spoken(" ".join(keep))
    if spoken and sentence_count(cleaned) >= 2 and not has_content(cleaned):
        # 16 Nov 2026 (log bank): a ramble with nothing to ask ("So let's say okay, fine. I want you to basically first
        # off.") is heard again with what follows, never sent
        STATS["held"] += 1
        return {"action": "hold", "question": "", "how": "no-content"}
    if sentence_count(cleaned) >= 2:
        # 16 Nov 2026: several sentences (two questions, or anything but filler before the question) go to the
        # pipeline as said: its multi-ask reader answers each, its guardrail judges all of them
        STATS["multi"] = STATS.get("multi", 0) + 1
        return {"action": "send", "question": cleaned, "how": "multi"}
    nav = nav_request(cleaned)
    if nav:
        STATS["nav"] = STATS.get("nav", 0) + 1
        return {"action": "send", "question": nav, "how": "nav"}
    rg = regroup_request(cleaned) if mem.last_data() is not None else None
    if rg:
        STATS["regroups"] = STATS.get("regroups", 0) + 1
        return {"action": "send", "question": rg, "how": "regroup"}
    # 14 Nov: rank / only-place / year / place / scheme-only / value / measure follow-ups -> Megh's own wording. A
    # sentence already in that wording, or a place / year follow-up Megh's word lists take as said, goes on unchanged.
    fu = followup_request(cleaned if how_pre else _fu_pre(raw), mem, cleaned)
    if fu and fu[1] == cleaned:
        STATS["rules"] += 1
        return {"action": "send", "question": cleaned, "how": how_pre or "rules"}
    if fu:
        STATS["followups"] = STATS.get("followups", 0) + 1
        return {"action": "send", "question": fu[1], "how": f"followup-{fu[0]}"}
    dq = dashboard_request(cleaned)
    if dq and followup_request(cleaned if how_pre else _fu_pre(raw), mem, late=True):
        dq = None                                                # "show me just PMAY-G" after a comparison with it
    if dq:
        STATS["dashboards"] = STATS.get("dashboards", 0) + 1
        return {"action": "send", "question": dq, "how": "dashboard"}
    v = view_request(cleaned)
    if v and mem.last_data() is not None:
        STATS["views"] += 1
        return {"action": "send", "question": v, "how": "view"}
    if v and not mem.turns:
        return {"action": "send", "question": v, "how": "view-nothing-on-screen"}
    if looks_followup(cleaned, mem) and not megh_handles(cleaned):
        pq = places_followup(cleaned, mem)
        if pq:
            STATS["places"] = STATS.get("places", 0) + 1
            return {"action": "send", "question": pq, "how": "followup-places"}
    if looks_followup(cleaned, mem) and not megh_handles(cleaned) and needs_rewrite(cleaned, mem):
        q = await llm_rewrite(cleaned, mem)
        q = drop_replaced_filters(q, cleaned) if q else q
        q = drop_unasked_chart(q, cleaned) if q else q
        ok, why = rewrite_ok(q or "", cleaned, mem)
        last = mem.last_data()
        if ok and q and last and schemes_in(last["q"]) and not schemes_in(q) \
                and not any(ph in _low(q) for ph in CROSS_SCHEME):
            ok, why = False, "no scheme in the rewrite"
        if ok and q and re.search(r"(?i)\bthe same (?:data|thing|figures|numbers|one)\b", q):
            ok, why = False, "still points back"
        if ok:
            STATS["llm"] += 1
            return {"action": "send", "question": q, "how": "followup-rewrite"}
        STATS["llm_rejected"] += 1
        STATS["last_reject"] = why
    # 14 Nov: no usable rewrite (the model down or refused): a late follow-up kind in Megh's own wording
    fu = followup_request(cleaned if how_pre else _fu_pre(raw), mem, cleaned, late=True)
    if fu and fu[1] != cleaned:
        STATS["followups"] = STATS.get("followups", 0) + 1
        return {"action": "send", "question": fu[1], "how": f"followup-{fu[0]}"}
    STATS["rules"] += 1
    return {"action": "send", "question": cleaned, "how": how_pre or "rules"}


FAILED_MARKS = ("couldn't build a working query", "could not build a working query", "i understood the question but")


def failed_answer(speak: str) -> bool:
    low = (speak or "").lower()
    return any(m in low for m in FAILED_MARKS)


async def retry_question(question: str, mem: Memory) -> str | None:
    """The pipeline could not build a query for the question as shaped: one standalone rewrite from the conversation."""
    q = await llm_rewrite(question, mem, hint="The data system could not answer this wording. Restate it as the "
                                              "simplest complete question with the scheme, the measure and any place "
                                              "or year it needs.")
    ok, why = rewrite_ok(q or "", question, mem)
    if ok and _low(q) != _low(question):
        STATS["retries"] += 1
        return q
    return None


def stats() -> dict:
    return dict(STATS)


_domain_sync()                                   # the domain tables are filled at import


if __name__ == "__main__":
    import sys
    for line in sys.argv[1:]:
        print(json.dumps({"in": line, "clean": clean_spoken(line), "unfinished": is_unfinished(line, clean_spoken(line)),
                          "view": view_request(clean_spoken(line))}, ensure_ascii=False))
