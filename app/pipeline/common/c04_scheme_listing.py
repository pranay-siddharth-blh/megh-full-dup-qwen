# app/pipeline/common/c04_scheme_listing.py — scheme listing, pick, recommendation, comparison, unsupported schemes.
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files.

# Text matching (D-047): English text is read on WORDS with app/text_match.py.
from app.text_match import (ANY, END, START, Alt, Cap, Matcher, Node, NotBefore, Opt, Pred, Rep, Seq, W,
                            collapse_ws)


# ── word-matching helpers shared by c04/c05/c06 (loaded in that order) ──────
class _C04CharGap(Node):
    """Any number of words, provided the text between the previous word's end and
    the next word's start is at most `hi` characters and holds none of `forbid`
    (e.g. A, then up to 40 characters with no '?', then B). Fewest words first; hi=None: no limit."""

    def __init__(self, hi=None, forbid=""):
        self.hi, self.forbid = hi, forbid

    def ends(self, ctx, i, caps):
        toks, text = ctx.toks, ctx.text
        prev_end = toks[i - 1].end if i > 0 else 0
        for j in range(i, len(toks) + 1):
            nxt = toks[j].start if j < len(toks) else len(text)
            span = text[prev_end:nxt]
            if (self.hi is not None and len(span) > self.hi) or any(c in self.forbid for c in span):
                return
            yield j, caps


class _C04Tail(Node):
    """The end of the text, provided ok(text after the last word) holds."""

    def __init__(self, ok):
        self.ok = ok

    def ends(self, ctx, i, caps):
        if i != len(ctx.toks):
            return
        start = ctx.toks[-1].end if ctx.toks else 0
        if self.ok(ctx.text[start:]):
            yield i, caps


class _C04Lead(Node):
    """The start of the text, provided ok(text before the first word) holds."""

    def __init__(self, ok):
        self.ok = ok

    def ends(self, ctx, i, caps):
        if i != 0:
            return
        end = ctx.toks[0].start if ctx.toks else len(ctx.text)
        if self.ok(ctx.text[:end]):
            yield i, caps


class _C04GapBefore(Node):
    """Zero-width: ok(the separator text right before the next word) holds.
    first=False: never at the first word (there is no word before it)."""

    def __init__(self, ok, first=True):
        self.ok, self.first = ok, first

    def ends(self, ctx, i, caps):
        if i == 0 and not self.first:
            return
        prev_end = ctx.toks[i - 1].end if i > 0 else 0
        nxt = ctx.toks[i].start if i < len(ctx.toks) else len(ctx.text)
        if self.ok(ctx.text[prev_end:nxt]):
            yield i, caps


class _C04SepSeq(Seq):
    """Seq whose separators must satisfy ok(separator_text)."""

    def __init__(self, *parts, ok):
        super().__init__(*parts)
        self._ok = ok

    def _sep_ok(self, ctx, i):
        return self._ok(ctx.gap(i))


def _c04Joined(*parts):
    """A compound written as separate words or as one word (no '_' form) — "a b",
    "a-b" or "ab". Each part is a word or a tuple of words."""
    alts = [tuple(p) if isinstance(p, (tuple, list)) else (p,) for p in parts]
    combos = [""]
    for a in alts:
        combos = [c + x.lower() for c in combos for x in a]
    return Alt(W(*combos), Seq(*[W(*a) for a in alts]))


def _c04JoinedPrefix(a, b):
    """Two words joined by a space, a dash or nothing, the second with any ending: "bank account", "bank-accounts", "bankaccount"."""
    return Alt(Seq(a, W(b, prefix=True)), W(a + b, prefix=True))


def _c04_digits(lo=1, hi=None):
    """Pred: a word of ASCII digits, lo..hi long."""
    return Pred(lambda w: w.isascii() and w.isdigit() and lo <= len(w) <= (hi or len(w)))


def _c04_is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _c04_replace_ci(text: str, needle: str, repl: str) -> str:
    """Replace every case-insensitive occurrence of `needle` (literal text)."""
    if not needle:
        return text
    low, nl, n = text.lower(), needle.lower(), len(needle)
    if len(low) != len(text):                       # case-folding changed lengths: compare per slice
        out, i = [], 0
        while i < len(text):
            if text[i:i + n].lower() == nl:
                out.append(repl)
                i += n
            else:
                out.append(text[i])
                i += 1
        return "".join(out)
    out, i = [], 0
    while True:
        k = low.find(nl, i)
        if k < 0:
            out.append(text[i:])
            return "".join(out)
        out.append(text[i:k])
        out.append(repl)
        i = k + n



# Focus Legacy answer notes (use-case QA, 2026-09-25).
#
# TC-19 "Which Producer Groups received more than ₹1,00,000?": 541 groups
# qualify, but the generator capped the list at LIMIT 10/100 and the answer named
# 23 groups without ever saying how many qualify — it read as the complete list.


# Plain-language, user-facing scheme summaries — separate from SCHEME_CATALOG
# in schema_context.py, which is written for the SQL-generation prompt (DB
# grain, money units, join keys) and reads as database jargon to an end user.
_SCHEME_USER_SUMMARY = {
    "MGNREGA": "Rural employment guarantee scheme — up to 100 days of guaranteed "
               "wage employment per household per year.",
    "PMAY-G": "Rural housing scheme (Gramin) — financial assistance to build a "
              "pucca house for eligible rural households.",
    "Focus Plus": "Meghalaya state farmer cash-benefit scheme — direct cash "
                  "payments (DBT) to registered farmers.",
    "CM Elevate": "Meghalaya livelihood & enterprise support programme — covers "
                  "15 individual schemes (piggery, poultry, small enterprise "
                  "loans, tourism vehicles, and more) under one umbrella.",
    "Focus Legacy": "Meghalaya state producer-group scheme (the original FOCUS) — "
                    "payments to farmer Producer Groups at Rs 5,000 per member. "
                    "Different from Focus Plus, which pays individual farmers.",
    "CM Elevate Legacy": "CM-ELEVATE sanction and disbursement records — the amount "
                         "sanctioned to each applicant across 13 schemes (piggery, "
                         "poultry, dairy, warehouse, tourism vehicles and more) and the "
                         "subsidy and loans actually paid, FY 2024-25 and 2025-26. "
                         "Different from CM Elevate, which holds the applications.",
    "CMSS": "Chief Minister's Scholarship Scheme — a flat Rs 6,000 a year for eligible "
            "post-matric students from Meghalaya.",
    "Homestay": "Chief Minister's Meghalaya Homestay Mission (Tourism Department) — support to build a new "
            "homestay or upgrade an existing one; the data is its online applications since October 2025.",
}

# "What schemes are available?" / "what can you help with?" — answered directly
# and concisely instead of falling through to RAG, which has no single document
# listing all 4 schemes and tends to elaborate at length on whichever one scores
# highest in vector search (QA repeatedly saw an over-detailed PMAY-only answer).
#
# The bare "(what|which) schemes?" alternative used to have NO tail anchor, so it
# also swallowed every "which scheme has the most applications?" / "which scheme
# dominates each district?" / "which schemes are not statewide?" DATA question —
# CM Elevate's few-shot corpus alone has a dozen of exactly this shape (superlative
# or filter questions over its 15 sub-schemes), and every one of them was being
# answered with the generic four-scheme blurb instead of a real query (confirmed
# live 2026-09-11: "which scheme has the most applications under CM Elevate?" ->
# the canned listing, never reaching classify_scheme/resolve_entities/SQL gen).
# Anchoring the bare form to the tail of the question — "which schemes?" / "what
# schemes are there/available/offered/supported" / "do you have/know/cover" —
# keeps the genuinely scheme-agnostic listing asks while letting a superlative or
# filter question (which always has more text after "scheme(s)") fall through to
# normal DATA routing.
def _c04_q_tail(t: str) -> bool:
    """After the last word: an optional '?', then only whitespace."""
    return (t[1:] if t.startswith("?") else t).strip() == ""


_C04_SCHEME_W = W("scheme", "schemes")
_SCHEME_LISTING_CUE = Matcher(Alt(
    Seq(W("what", "which"), _C04_SCHEME_W, _C04Tail(_c04_q_tail)),
    Seq(W("what", "which"), _C04_SCHEME_W,
        Alt(Seq("are", W("there", "available", "offered", "supported")), "exist",
            Seq("do", W("you", "i"), W("have", "know", "cover")), Seq("can", "you", W("tell", "list")))),
    Seq(_C04_SCHEME_W, W("are", "is"), "available"),
    Seq("list", Opt(W("the", "all")), _C04_SCHEME_W),
    Seq(_C04_SCHEME_W, Alt(Seq("do", "you"), "you"), W("support", "cover", "know", "have")),
    Seq("what", W("can", "do"), "you", Alt(Seq("help", "with"), Seq("assist", "with"), "cover")),
    # "How many schemes are onboarded / covered / there?" asked "which scheme?"
    # (user session 2026-10-13)
    Seq(NotBefore(Seq("how", "many", Opt(ANY), _C04_SCHEME_W),
                  Seq(_C04CharGap(40, "?"), W("in", "under", "of", "within"),
                      Alt("cm", Seq("the", "cm"), "elevate", "focus"))),
        _C04CharGap(30, "?"),
        Alt("onboarded", _c04Joined("on", "board"), "covered", "supported", "available", "there",
            Seq("do", "you", W("have", "cover", "know")), Seq("you", W("have", "cover")))),
))

# A vague eligibility ask — "is there any scheme that can help my family?",
# "which scheme should I apply for?" — carries no vocabulary naming a scheme
# outright, so it used to fall into the "which scheme does your question
# concern?" pause. That pause is the wrong move here: unlike a DATA question
# (where guessing the scheme risks a confidently wrong number), there's
# nothing to get wrong about naming all four — so skip the tap and lay them
# out directly. When the wording DOES carry scheme-specific vocabulary (e.g.
# "...to help me build a house") _infer_scheme_from_terms already pins it to
# one scheme and _needs_scheme_clarification never pauses in the first place —
# this cue only needs to cover the genuinely scheme-agnostic case, so it
# defers to that inference rather than overriding it.
_SCHEME_HELP_CUE = Matcher(Alt(
    Seq("is", "there", W("any", "a"), Opt(W("govt", "government")), _C04_SCHEME_W),
    Seq(W("any", "a"), "scheme", W("that", "which", "to"), Opt(W("can", "could")), "help"),
    Seq(_C04_SCHEME_W, W("that", "which"), W("can", "could"), "help"),
    Seq("which", "scheme", W("can", "could", "should"), W("i", "we")),
    Seq("what", "scheme", "should", W("i", "we")),
))


# CM Elevate and CM Elevate Legacy are ONE programme (CM-ELEVATE) held as two
# datasets — its applications, and its sanctions and disbursements. Listed as
# two schemes, the reply read as if there were two unrelated programmes (and the
# count was hard-coded "four" against six lines). The listing shows the
# programme once and names its two data parts; every other scheme's line is
# unchanged. _SCHEME_USER_SUMMARY keeps both entries, for the comparison answer.
_PROGRAMME_DATASETS = {"CM Elevate": ["CM Elevate Legacy"]}
_COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
                7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _count_word(n: int) -> str:
    return _COUNT_WORDS.get(n, str(n))


def _scheme_listing_lines() -> list[str]:
    # All six, each on its own line: folding CM Elevate Legacy into the CM Elevate
    # line made the reply say "I cover five schemes" while the scheme picker and
    # every refusal message say six (General TC-001/016, test run 2026-10-09).
    # The two CM-ELEVATE lines say plainly that they are one programme.
    lines = []
    for name, desc in _SCHEME_USER_SUMMARY.items():
        if name == "CM Elevate":
            desc = (
                "Meghalaya livelihood & enterprise support programme (CM-ELEVATE) — "
                "piggery, poultry, dairy, small enterprise, tourism vehicles and more. "
                "Holds the **applications** (15 schemes — status, verification, applicant "
                "type; no amounts)."
            )
        elif name == "CM Elevate Legacy":
            desc = (
                "the same CM-ELEVATE programme's **sanctions and disbursements** (13 "
                "schemes — amount sanctioned, subsidy and loans paid, FY 2024-25 and 2025-26)."
            )
        lines.append(f"- **{name}** — {desc}")
    return lines


# ── "Pick any scheme and explain it" — the user hands the CHOICE to the bot ──
# "pick any scheme out of these and explain", "no, pick yourself any scheme",
# "you choose one", "tell me about any one of them", "explain a scheme of your
# choice", "surprise me"... The user is not naming a scheme and does not want to
# be asked for one — asking "which scheme?" is the exact opposite of the request
# (reported 2026-09-24: three turns of the bot either asking back or answering
# "not covered" against the raw wording). Answered deterministically: the scheme
# the user did name if any, else one this conversation has not covered yet,
# explained as key points from that scheme's own reference docs.
_PICK_VERB = Alt(W("pick", "choose", "chose", "select", "take", "explain", "describe", "give", "show",
                   "share", "summarise", "summarize", "brief", "elaborate"),
                 Seq("go", "with"), Seq("tell", Opt("me"), "about"), Seq("talk", "about"))
_C04_PROGRAMME_W = W("programme", "programe")
_C04_ANY_ONE = Alt(_c04Joined("any", "one"), "any")


def _c04_word_plus_digit(stem: str):
    """"top5" as one word: the stem followed by exactly one digit."""
    n = len(stem)
    return Pred(lambda w: len(w) == n + 1 and w.lower().startswith(stem) and w[n:].isascii() and w[n:].isdigit())


_PICK_DELEGATION = Matcher(Alt(
    # "pick any scheme", "choose one of these", "take a random scheme", "pick yourself",
    # "select one scheme", "pick another scheme"
    Seq(_PICK_VERB, _C04CharGap(40, ".?!"),
        Alt(_C04_ANY_ONE, "some", Seq("a", "random"), "random", Seq("one", "of"), "another",
            _c04Joined("your", "self"), Seq("your", "own"), Seq("of", "your", "choice"), "whichever",
            Seq(W("a", "one"), Opt("single"), Alt("scheme", _C04_PROGRAMME_W)))),
    # "any one of these / them", "any scheme", "one of the schemes"
    Seq(_c04Joined("any", ("one", "1")), Opt("of"),
        Alt(W("these", "them", "those"), Seq("the", _C04_SCHEME_W))),
    Seq(Alt("any", Seq("a", "random"), "random"), "scheme"),
    # "you choose", "your choice", "you decide", "up to you", "surprise me"
    Seq(W("you", "u"), W("pick", "choose", "decide", "select")),
    Seq("your", W("choice", "pick", "call")),
    Seq("up", "to", "you"), Seq("surprise", "me"), Seq("whichever", W("you", "u")),
))
# What makes it a question about a SCHEME (not "pick any district and show ..."):
# the word scheme / programme, a reference back to the list just shown, or a
# delegation phrase that can only mean the scheme choice.
_PICK_OBJECT = Matcher(Alt(
    _C04_SCHEME_W,
    W("program", "programs", "programme", "programmes", "programe", "programes"),
    W("these", "them", "those"), Seq("one", "of"),
    _c04Joined("your", "self"), Seq("your", W("own", "choice", "pick", "call")), Seq("up", "to", "you"),
    Seq("surprise", "me"), Seq(W("you", "u"), W("pick", "choose", "decide", "select")),
    # a bare "just pick any" / "pick any one" / "choose another" — nothing else in
    # the message, so the only thing on offer to pick is a scheme
    Seq(START, Opt(W("no", "ok", "okay", "then", "so")), Opt("just"), W("pick", "choose", "select"),
        Alt(_C04_ANY_ONE, "one", Seq("another", Opt("one")), Seq("one", "more"),
            Seq("the", "next", "one"), Seq("next", "one")),
        END),
))
# "another one" / "one more" / "next one" / "explain another" on its own. Only a
# pick when the PREVIOUS answer was a pick — after a data answer the same words
# mean another district or year, and go to the follow-up rewrite as before.
_PICK_CONTINUE = Matcher(Seq(
    START, Opt(W("no", "ok", "okay", "then", "so", "and")),
    Opt(Seq(Alt("explain", Seq("tell", Opt("me"), "about"), "describe", "give", "show"), Opt("me"))),
    Alt(Seq("another", Opt(W("one", "scheme"))), Seq("one", "more"), Seq(Opt("the"), "next", W("one", "scheme"))),
    END,
))
_PICK_OVERVIEW_PREFIX = "Explain its key points — the objective"
# A NEED-based ask ("is there any scheme that can help my family?", "any scheme
# for farmers?") wants the scheme that FITS — the existing help/listing path
# answers that. Picking one arbitrarily would be the wrong answer to it.
_PICK_NEED_GUARD = Matcher(Alt(
    W("help", "helps", "helpful", "eligible", "suitable"),
    Seq(W("should", "can", "could"), "i"), Seq("apply", "for"), Seq("is", "there"),
    Seq("for", Alt(W("farmer", "farmers", "women", "youth", "student", "students", "poor", "my", "us",
                     "families", "entrepreneur", "entrepreneurs", "widow", "widows", "elderly", "disabled"),
                   Seq("the", "poor"))),
))
# A request for a FIGURE is a data question even when it says "pick any".
_C04_YEAR20 = Pred(lambda w: len(w) == 4 and w.startswith("20") and w.isascii() and w.isdigit())
_PICK_DATA_GUARD = Matcher(Alt(
    Seq("how", W("many", "much")), Seq("number", "of"),
    W("total", "count", "sum", "average", "highest", "lowest", "most", "least", "district", "block",
      "village", "panchayat", "expenditure", "house", "houses", "amount", "payment", "payments",
      "record", "records", "application", "applications", "data", "figure", "figures", "numbers",
      "statistics", "stats"),
    Seq("top", _c04_digits(1, 1)), _c04_word_plus_digit("top"),
    W("rank", "disburs", "beneficiar", prefix=True),
    Seq("financial", "year"),
    Seq("fy", _c04_digits(1, 1)), _c04_word_plus_digit("fy"),
    _C04_YEAR20, _c04Joined("person", ("day", "days")),
))
# "another" / "different" / "other" / "next" — explicitly not the one just done.
_PICK_ANOTHER = Matcher(W("another", "different", "other", "next", "new", "else"))


def _is_scheme_pick_request(question: str) -> bool:
    q = question or ""
    # "why did you choose MGNREGA?" asks for a REASON, not another pick.
    if _WHY_CHOICE.search(q):
        return False
    if not _PICK_DELEGATION.search(q) or not _PICK_OBJECT.search(q):
        return False
    return not (_PICK_DATA_GUARD.search(q) or _PICK_NEED_GUARD.search(q))


def _pickable_schemes() -> list[str]:
    """The programmes a user can be given, in listing order. CM Elevate Legacy
    is CM Elevate's data, not a separate programme (see _PROGRAMME_DATASETS)."""
    folded = {d for ds in _PROGRAMME_DATASETS.values() for d in ds}
    return [s for s in _SCHEME_USER_SUMMARY if s not in folded]


def _pick_scheme(question: str, session: "Session | None") -> tuple[str, bool]:
    """(scheme, chosen_by_bot). A scheme the user named wins. Otherwise the first
    programme this conversation has not been told about yet, so "pick another"
    / a repeated "pick one yourself" moves on instead of repeating itself."""
    named = [s for s in _named_schemes(question) if s in _SCHEME_USER_SUMMARY]
    if named:
        folded = {d: p for p, ds in _PROGRAMME_DATASETS.items() for d in ds}
        return folded.get(named[0], named[0]), False
    options = _pickable_schemes()
    folded = {d: p for p, ds in _PROGRAMME_DATASETS.items() for d in ds}
    covered: list[str] = []
    for t in (getattr(session, "turns", None) or []):
        for s in (t.schemes or []):
            s = folded.get(s, s)
            if s in options and s not in covered:
                covered.append(s)
    fresh = [s for s in options if s not in covered]
    if fresh:
        return fresh[0], True
    # Everything has been covered once — cycle on from the most recent one.
    last = covered[-1] if covered else options[-1]
    return options[(options.index(last) + 1) % len(options)], True


# A request for a summary of the scheme as a whole (see the knowledge route).
_OVERVIEW_REQUEST = Matcher(Alt(
    "overview", "briefing", Seq("brief", W("note", "summary", "introduction")),
    Seq(W("summary", "summarise", "summarize"), Opt("of"), Opt("the"),
        W("scheme", "programme", "program", "focus")),
    Seq("at", "a", "glance"), Seq("executive", "summary"),
))


def _scheme_overview_question(scheme: str) -> str:
    """The standalone knowledge question the pick is answered with — phrased as
    the reference docs are written, so retrieval lands on the overview sections
    rather than on whatever the user's delegation wording happened to match."""
    return (f"What is {scheme}? Explain its key points — the objective, who is "
            f"eligible, the benefits it provides and how to apply.")


# ── "Suggest a scheme that suits me" — a RECOMMENDATION from the user's profile ──
# "i am living in rural area, suggest me the best scheme", "my friend is starting
# a startup, suggest him a scheme", "i am a farmer, suggest a scheme". None of
# these names a scheme, so the knowledge route inherited the PREVIOUS turn's
# scheme and searched only its documents — every one of them was answered from
# MGNREGA's material, or "not covered" (reported 2026-09-24). A recommendation
# is a question ACROSS schemes: it is answered here, deterministically, by
# matching what the user says about themselves to who each scheme is for.
#
# Who each scheme is for — taken from each scheme's own reference FAQ
# (data/incoming/<scheme>/*_general_faq.md, FOCUS_LEGACY_FAQ.md), not invented. Focus
# Plus in particular is NOT for any farmer: its FAQ makes Producer Group
# membership the precondition.
_SCHEME_FIT = {
    "MGNREGA": (
        "guaranteed paid work",
        "any adult member of a rural household who is willing to do unskilled manual "
        "work can get up to 100 days of paid work a year, with no income test — you "
        "register for a job card at your Gram Panchayat."),
    "PMAY-G": (
        "a permanent (pucca) house",
        "for rural households that do not own a pucca house and have not had government "
        "housing help before; households are identified from the SECC / Awaas+ list "
        "through the Gram Panchayat."),
    "Focus Plus": (
        "direct cash support for farm and livelihood activity",
        "cash paid directly (DBT) to Meghalaya households that are members of a Producer "
        "Group of 10 or more, for farm inputs and extra income activities such as "
        "piggery, poultry, horticulture, ginger or turmeric."),
    "Focus Legacy": (
        "seed money for a farmers' Producer Group",
        "farmers organised into (or willing to form) a Producer Group get ₹5,000 per "
        "member as seed / working capital; urban groups of 10 or more members are also "
        "eligible — register at the C&RD Block office."),
    "CM Elevate": (
        "starting or growing a business",
        "individuals, registered businesses, SHGs and Producer Groups in Meghalaya can "
        "get support for a venture in one of 15 sectors — piggery, poultry, dairy, goat "
        "farming, warehousing, tourism vehicles and more — or under the \"Any Business "
        "Venture\" category; you apply on the MeghalayaOne portal."),
    "CMSS": (
    "a flat Rs 6,000 annual scholarship for eligible students",
    "domicile of Meghalaya and enrolled in a full-time post-matriculation programme (Class XI/XII, Diploma, UG, PG, M.Phil., or Ph.D.)"),
    "Homestay": (
    "building or upgrading a homestay",
    "Indian citizens and permanent residents of Meghalaya aged 18+ who are functionally literate, have no credit defaults, and are not already receiving assistance for a homestay under this scheme; the scheme supports new construction (up to ₹10 lakh), upgradation of existing operational homestays (up to ₹2 lakh), and boutique facilities (minimum ₹80 lakh investment)."),
}
# (profile, what it says about the user, matcher, schemes in order of fit)
_PROFILE_RULES = (
    ("business", "starting or running a business",
     Matcher(Alt(
         _c04Joined("start", ("up", "ups")),
         Seq(W("start", "starting", "started"),
             Opt(W("a", "an", "my", "our", "his", "her", "their", "the")),
             Rep(W("own", "new", "small")),
             W("business", "company", "venture", "enterprise", "shop", "unit", "firm")),
         W("business", "entrepreneur", "goat", prefix=True),
         W("enterprise", "enterprises", "venture", "ventures", "company", "shop", "msme", "piggery",
           "poultry", "dairy", "tourism", "taxi", "warehouse", "homestay"),
         _c04JoinedPrefix("self", "employ"),
     )),
     ["CM Elevate"]),
    ("group", "part of a farmers' group / SHG",
     Matcher(Alt(
         Seq("producer", W("group", "groups")), Seq(W("farmer", "farmers"), W("group", "groups")),
         Seq("group", "of", "farmers"), W("shg", "shgs"),
         Seq(_c04Joined("self", "help"), W("group", "groups")), "collective",
         W("cooperative"), _C04SepSeq("co", "operative", ok=lambda g: g == "-"), W("pg", "pgs"),
     )),
     ["Focus Legacy", "Focus Plus", "CM Elevate"]),
    ("farmer", "a farmer",
     Matcher(Alt(W("farm", "farmer", "farmers", "farming", "crop", "crops", "kisan", "kheti"),
                 W("agricultur", "cultivat", "horticultur", prefix=True))),
     ["Focus Plus", "Focus Legacy", "CM Elevate", "MGNREGA"]),
    ("housing", "in need of a house",
     Matcher(W("house", "houses", "home", "housing", "kutcha", "homeless", "shelter", "roof", "pucca")),
     ["PMAY-G"]),
    ("work", "looking for work / income",
     Matcher(Alt(
         W("job", "jobs", "employment", "wage", "wages"),
         W("unemploy", "labor", "labour", prefix=True),
         Seq("daily", "wage"),
         Seq("need", Opt("some"), W("work", "income", "money")),
         Seq("looking", "for", "work"),
         Seq("no", W("work", "income", "job")),
     )),
     ["MGNREGA"]),
    ("rural", "living in a rural area",
     Matcher(W("rural", "village", "villages", "gaon", "countryside")),
     ["MGNREGA", "PMAY-G"]),
)
_C04_PRONOUN_OBJ = W("me", "him", "her", "us", "them", "my", "our")
_RECOMMEND_CUE = Matcher(Alt(
    W("suggest", "recommend", prefix=True), W("advice", "advise"),
    Seq("best", Opt("suited"), _C04_SCHEME_W),
    Seq("right", "scheme"), W("suit", "suits", "suitable", "suited"),
    Seq(W("fit", "fits"), _C04_PRONOUN_OBJ),
    Seq(W("which", "what"), _C04_SCHEME_W, W("should", "can", "could", "would", "will", "do", "does"),
        Alt(W("i", "we", "he", "she", "they", "my", "our"), Seq("you", W("suggest", "recommend")))),
    Seq(W("which", "what"), _C04_SCHEME_W, Alt("is", "are", Seq("would", "be")), Opt("the"),
        W("best", "good", "right", "suitable", "useful"), "for"),
    Seq(_C04_SCHEME_W, "for", W("me", "him", "her", "us", "them", "my", "our", "a", "an")),
    Seq("any", _C04_SCHEME_W, "for"),
    Seq("eligible", "for", W("which", "what")),
    Seq("help", W("me", "him", "her", "us"), W("choose", "find", "pick")),
))
# Looser question shapes that are a recommendation ONLY when the message also
# describes the person's need ("my friend is starting a startup, which scheme
# benefits him"). On their own they are far too common in data and listing
# questions ("which scheme has the most houses", "is there any scheme that can
# help my family?"), which keep their existing handling.
_C04_SUBJ = Alt(W("i", "he", "she", "we", "they"), Seq("my", ANY))
_RECOMMEND_CUE_WITH_NEED = Matcher(Alt(
    Seq(W("which", "what"), _C04_SCHEME_W), Seq("any", _C04_SCHEME_W), Seq("is", "there", W("any", "a")),
    Seq(_C04_SCHEME_W, _C04CharGap(40, "?.!"),
        W("benefit", "help", "support", "useful", "avail", "apply", "get", "give", "offer", prefix=True)),
    Seq(W("benefit", "help", "support", prefix=True), Opt(W("to", "for")),
        W("me", "him", "her", "us", "them", "my", "our", "his")),
    Seq(W("can", "could", "will", "would"), _C04_SUBJ, W("get", "avail", "apply", "benefit")),
    Seq("what", W("can", "could", "will"), _C04_SUBJ, "get"),
))
_RECOMMENDATION_LEAD = "Based on what you've told me"


def _user_profile(text: str) -> list[tuple[str, str, list[str]]]:
    return [(k, desc, schemes) for k, desc, word_matcher, schemes in _PROFILE_RULES if word_matcher.search(text or "")]


def _latest_profile(session: "Session | None", n: int = 4) -> list[tuple[str, str, list[str]]]:
    """The profile from the MOST RECENT of the user's last n messages that
    described someone. Never a blend of several messages: "my friend is
    starting a startup" and later "I am a farmer" are two different people,
    and merging them recommended the friend's scheme to the farmer."""
    for t in reversed((getattr(session, "turns", None) or [])[-n:]):
        prof = _user_profile(t.raw_question or "")
        if prof:
            return prof
    return []


# "Is there any Producer Group named Nongstoin PG?" is a NAME LOOKUP in the data,
# not a person describing themselves: the loose cue "is there any" plus the
# "group" profile word sent it to the recommender, which replied with a list of
# schemes (Focus Legacy QA TC-13, 2026-09-25). A naming word attached to a group
# noun vetoes the recommendation; "my friend named Ram is a farmer" is untouched.
_GROUP_NAME_LOOKUP = Matcher(Seq(
    Alt(Seq("producer", W("group", "groups")), W("pg", "pgs", "group", "groups", "shg", "shgs")),
    Opt(W("is", "are", "was")),
    Alt(W("named", "called", "titled"), Seq(W("with", "by"), Opt("the"), "name")),
))


def _is_recommendation_request(question: str) -> bool:
    q = question or ""
    if _WHY_CHOICE.search(q):
        return False
    if _GROUP_NAME_LOOKUP.search(q):
        return False
    if not (_RECOMMEND_CUE.search(q)
            or (_RECOMMEND_CUE_WITH_NEED.search(q) and _user_profile(q))):
        return False
    # "is PMAY-G suitable for me?" is an eligibility question about THAT scheme
    # — its own reference docs answer it (the normal knowledge route).
    if _named_schemes(q):
        return False
    if _RECOMMEND_DATA_GUARD.search(q):
        return False
    # It must actually be about a scheme: a scheme word, or a need a scheme can
    # meet stated in the message itself. "give me some suggestions" on its own
    # is not a scheme question — reading it as one borrowed the previous turn's
    # need and recommended PMAY-G to "i want to rob bank, give me some
    # suggestions" (reported 2026-09-24).
    return bool(_SCHEME_CONTEXT.search(q) or _user_profile(q))


_SCHEME_CONTEXT = Matcher(Alt(
    W("scheme", "schemes", "yojana", "yojna", "program", "programs", "programme", "programmes",
      "programe", "programes", "govt", "government", "assistance", "benefit", "benefits", "eligible",
      "eligibility", "apply"),
    W("subsid", prefix=True),
))


# Only FIGURE words — unlike the pick guard, "house" / "village" / "district"
# describe the user's situation here ("I live in a village, I need a house").
_RECOMMEND_DATA_GUARD = Matcher(Alt(
    Seq("how", W("many", "much")), Seq("number", "of"),
    W("total", "count", "sum", "average", "highest", "lowest", "most", "least", "maximum", "minimum",
      "largest", "biggest", "smallest", "expenditure", "data", "figure", "figures", "statistics", "stats"),
    Seq("top", _c04_digits(1, 1)), _c04_word_plus_digit("top"),
    W("rank", "disburs", prefix=True), _c04Joined("person", ("day", "days")),
    Seq("amount", W("of", "paid", "spent")), _C04_YEAR20,
))


def _recommendation_clarification(question: str) -> "ClarificationNeeded":
    stem = question.strip().rstrip(" ?.")
    needs = [("I need paid work", "I need work"), ("I need a house", "I need a house"),
             ("I am a farmer", "I am a farmer"),
             ("I am in a farmers' group / SHG", "I am in a farmers' producer group"),
             ("I want to start a business", "I want to start a business")]
    return ClarificationNeeded(
        "Happy to suggest one — tell me a little about the need, so I can match it to "
        "the right scheme:",
        options=[{"label": lbl, "question": f"{stem} — {why}"} for lbl, why in needs],
        rule="recommendation-needs-profile",
    )


_SCHEMES_I_CAN_GET = Matcher(Seq(
    W("what", "which"), Opt("all"), Opt(W("govt", "government")), "schemes", _C04CharGap(30, "?"),
    W("can", "could", "may"), W("i", "we"), Alt("get", "avail", Seq("apply", "for"), "join", "access"),
))


def _scheme_recommendation_answer(question: str, session: "Session | None") -> "dict | None":
    if not _is_recommendation_request(question):
        return None
    profile = _user_profile(question)
    from_history = False
    if not profile:
        profile = _latest_profile(session)
        from_history = bool(profile)
    if not profile and _SCHEMES_I_CAN_GET.search(question or ""):
        # "What schemes can I get in Meghalaya?" asks what exists, with no need
        # stated: list them and offer the recommendation, rather than answering
        # with a question (General TC-016, test run 2026-10-06; TC-001 lists).
        lines = _scheme_listing_lines()
        return {"route": "knowledge", "intent": "RAG", "confidence": "high", "sources": [],
                "answer": (f"These {_count_word(len(lines))} Meghalaya government schemes are "
                           "available:\n\n" + "\n".join(lines) +
                           "\n\nTell me a little about your need — work, a house, farming, or "
                           "starting a business — and I'll suggest the best fit."),
                **_empty_data_fields()}
    if not profile:
        raise _recommendation_clarification(question)
    ranked: list[str] = []
    for _k, _d, schemes in profile:
        for s in schemes:
            if s not in ranked:
                ranked.append(s)
    about = " and ".join(d for _k, d, _s in profile)
    lead = f"{_RECOMMENDATION_LEAD} ({about}{', from earlier in our chat' if from_history else ''}), "
    lead += ("this scheme fits best:" if len(ranked) == 1 else "these schemes fit, best match first:")
    lines = []
    for i, s in enumerate(ranked, 1):
        what, who = _SCHEME_FIT[s]
        lines.append(f"{i}. **{s}** — for {what}: {who}")
    tail = ("\n\nThese are suggestions based on each scheme's published eligibility — the "
            "implementing department makes the final decision. Ask me \"how to apply for "
            f"{ranked[0]}\" for the steps.")
    logger.info("scheme recommendation: %r -> %s (profile=%s)", question, ranked,
                [k for k, _d, _s in profile])
    return {"route": "knowledge", "intent": "RAG", "confidence": "high", "sources": [],
            "answer": f"{lead}\n\n" + "\n".join(lines) + tail,
            **_empty_data_fields(), "schemes": [ranked[0]]}


# ── "my friend is starting a startup, which PMAY-G benefits him?" ───────────
# A named scheme plus a stated need it does NOT serve. The scheme's own documents
# cannot say "this is the wrong scheme for you" — they either describe the scheme
# anyway or reply that startups are "not mentioned" (reported 2026-09-24). Said
# plainly here, with the scheme that does fit. When the named scheme DOES fit the
# need, this steps aside and its own documents answer, exactly as before.
_FIT_CUE = Matcher(Alt(W("eligib", "suit", prefix=True), W("fit", "fits", "useful"),
                       Seq(W("good", "right"), "for")))


def _scheme_fit_check_answer(question: str) -> "dict | None":
    q = question or ""
    if _WHY_CHOICE.search(q) or _RECOMMEND_DATA_GUARD.search(q):
        return None
    if not (_FIT_CUE.search(q) or _RECOMMEND_CUE.search(q) or _RECOMMEND_CUE_WITH_NEED.search(q)):
        return None
    folded = {d: p for p, ds in _PROGRAMME_DATASETS.items() for d in ds}
    named = list(dict.fromkeys(folded.get(s, s) for s in _named_schemes(q)))
    if len(named) != 1 or named[0] not in _SCHEME_FIT:
        return None
    profile = _user_profile(q)
    if not profile:
        return None
    ranked: list[str] = []
    for _k, _d, schemes in profile:
        ranked += [s for s in schemes if s not in ranked]
    x = named[0]
    if x in ranked:
        return None
    about = " and ".join(d for _k, d, _s in profile)
    what, who = _SCHEME_FIT[x]
    parts = [f"**{x}** isn't meant for this need ({about}): it is for {what} — {who}"]
    best = ranked[0]
    parts.append(f"For this need, **{best}** fits: {_SCHEME_FIT[best][1]}")
    if len(ranked) > 1:
        parts.append("Also worth a look: " + ", ".join(f"**{s}** ({_SCHEME_FIT[s][0]})"
                                                      for s in ranked[1:]) + ".")
    parts.append(f"Ask me \"how to apply for {best}\" for the steps.")
    logger.info("scheme fit check: %r -> %s does not fit %s; suggest %s", q, x,
                [k for k, _d, _s in profile], best)
    return {"route": "knowledge", "intent": "RAG", "confidence": "high", "sources": [],
            "answer": "\n\n".join(parts), **_empty_data_fields(), "schemes": [best]}


# ── "Why did you choose / give MGNREGA (instead of Focus)?" ─────────────────
# A question about the BOT'S OWN previous answer, not about a scheme's rules —
# no reference document can answer it, so the knowledge route either repeated
# the overview or said "not covered" (reported 2026-09-24). It is answered from
# what the previous answer actually was: a pick, a recommendation, or a scheme
# the conversation was already on.
_WHY_CHOICE = Matcher(Seq(
    "why", _C04CharGap(40, "?.!"),
    Alt(W("choose", "chose", "chosen", "pick", "picked", "picking", "give", "given", "gave",
          "instead", "rather", "only", "not"),
        W("suggest", "recommend", "select", prefix=True)),
))
_INSTEAD_OF = Matcher(Seq(
    Alt(Seq("instead", "of"), Seq("rather", "than"), "over", Seq("and", "not"), "not"),
    Cap(Rep(ANY, 1), "alt"), END,
))


def _c04_numbered_bold_items(text: str) -> list[str]:
    """The bold names of a numbered list: "1. **MGNREGA** — ..." -> ["MGNREGA"]
    (line start, digits, '.', whitespace, then **name**)."""
    out = []
    for line in (text or "").split("\n"):
        k = 0
        while k < len(line) and line[k].isdigit():
            k += 1
        if k == 0 or line[k:k + 1] != ".":
            continue
        rest = line[k + 1:]
        body = rest.lstrip()
        if len(body) == len(rest) or not body.startswith("**"):
            continue
        body = body[2:]
        end = body.find("**", 1)
        if end >= 1:
            out.append(body[:end])
    return out


def _why_choice_answer(question: str, session: "Session | None") -> "dict | None":
    q = question or ""
    if not _WHY_CHOICE.search(q):
        return None
    last = getattr(session, "last_turn", None) if session is not None else None
    if last is None:
        return None
    folded = {d: p for p, ds in _PROGRAMME_DATASETS.items() for d in ds}
    # The scheme the question says was given, and the alternative it names.
    m = _INSTEAD_OF.search(q)
    alt_text = m.group("alt") if m else ""
    given_text = q[: m.start()] if m else q
    given = [folded.get(s, s) for s in _named_schemes(given_text)]
    given = given or [folded.get(s, s) for s in (last.schemes or [])]
    alts = [folded.get(s, s) for s in _named_schemes(alt_text)] if alt_text else []
    if alt_text and not alts and _BARE_FOCUS_WORD.search(alt_text):
        alts = ["Focus Plus", "Focus Legacy"]
    alts = [a for a in dict.fromkeys(alts) if a in _SCHEME_FIT and a not in given]
    x = given[0] if given and given[0] in _SCHEME_FIT else None
    if x is None:
        return None

    was_pick = _PICK_OVERVIEW_PREFIX in (last.question or "")
    was_rec = (last.answer or "").startswith(_RECOMMENDATION_LEAD)
    if was_pick:
        why = (f"I picked **{x}** only because you left the choice to me and it was the "
               "first scheme on my list we hadn't covered yet — it isn't a ranking, and it "
               "doesn't mean it suits you best.")
    elif was_rec:
        # Where each scheme actually sat in that list — the question may assume
        # one was left out when it was in fact ranked higher.
        listed = _c04_numbered_bold_items(last.answer or "")
        rank = {s: i + 1 for i, s in enumerate(listed)}
        if x in rank and len(listed) > 1:
            why = (f"**{x}** was number {rank[x]} of {len(listed)} in my suggestions, not the "
                   f"only one — it is there for {_SCHEME_FIT[x][0]}: {_SCHEME_FIT[x][1]}")
        else:
            why = (f"I suggested **{x}** because of what you told me about yourself: it is for "
                   f"{_SCHEME_FIT[x][0]} — {_SCHEME_FIT[x][1]}")
        ranked_above = [a for a in alts if a in rank and (x not in rank or rank[a] < rank[x])]
        if ranked_above:
            why += ("\n\nIn fact " + " and ".join(f"**{a}** (number {rank[a]})" for a in ranked_above)
                    + (" was" if len(ranked_above) == 1 else " were")
                    + f" ranked above {x} in that same list.")
            alts = [a for a in alts if a not in ranked_above]
    else:
        why = (f"My last answer drew only on **{x}**'s published information because our "
               f"conversation was about {x} at that point — I didn't compare it with the "
               "other schemes.")
    parts = [why]
    for a in alts:
        what, who = _SCHEME_FIT[a]
        parts.append(f"**{a}** is for {what}: {who}")
    profile = _user_profile(q) or _latest_profile(session)
    if profile and not was_rec:
        ranked: list[str] = []
        for _k, _d, schemes in profile:
            ranked += [s for s in schemes if s not in ranked]
        about = " and ".join(d for _k, d, _s in profile)
        parts.append(f"From what you've said ({about}), the best match is **{ranked[0]}**"
                     + (f", then {', '.join(ranked[1:3])}" if len(ranked) > 1 else "") + ".")
    elif not profile:
        parts.append("Tell me what you need — paid work, a house, farming support or starting "
                     "a business — and I'll suggest the scheme that fits best.")
    return {"route": "knowledge", "intent": "RAG", "confidence": "high", "sources": [],
            "answer": "\n\n".join(parts), **_empty_data_fields(),
            "schemes": [alts[0] if alts else x]}


def _last_turn_was_pick(session: "Session | None") -> bool:
    last = getattr(session, "last_turn", None) if session is not None else None
    return bool(last and _PICK_OVERVIEW_PREFIX in (last.question or ""))


async def _scheme_pick_answer(question: str, session: "Session | None") -> "dict | None":
    if not (_is_scheme_pick_request(question)
            or (_PICK_CONTINUE.match(question or "") and _last_turn_was_pick(session))):
        return None
    scheme, chosen = _pick_scheme(question, session)
    overview_q = _scheme_overview_question(scheme)
    kb = None
    try:
        kb = await rag.answer_from_kb(overview_q, scheme=scheme)
    except Exception:  # noqa: BLE001 — fall back to the summary below
        logger.warning("scheme pick: knowledge lookup failed for %s", scheme, exc_info=True)
    lead = (f"I'll pick **{scheme}** — here are its key points:" if chosen
            else f"Here are the key points of **{scheme}**:")
    if kb:
        body, conf, sources = kb["answer"], kb["confidence"], kb["sources"]
    else:
        # No passage retrieved (KB unreachable, or nothing scored): still answer
        # the request from the scheme's own one-line summary, never "not covered".
        body, conf, sources = f"- {_SCHEME_USER_SUMMARY[scheme]}", "medium", []
    others = [s for s in _pickable_schemes() if s != scheme]
    tail = ("\n\nWant me to explain another one? I also cover "
            + ", ".join(others[:-1]) + " and " + others[-1] + "." if chosen and others else "")
    logger.info("scheme pick: %r -> %s (chosen_by_bot=%s)", question, scheme, chosen)
    return {"route": "knowledge", "intent": "RAG", "confidence": conf,
            "answer": f"{lead}\n\n{body}{tail}", "sources": sources,
            "rewritten_question": overview_q,
            **_empty_data_fields(), "schemes": [scheme]}


def _scheme_listing_answer(question: str) -> "dict | None":
    explicit = _SCHEME_LISTING_CUE.search(question or "")
    if not explicit:
        if not _SCHEME_HELP_CUE.search(question or ""):
            return None
        # A "help me" ask that already names scheme-specific vocabulary (a
        # house, job cards, farmer cash, an enterprise, ...) has a clear
        # intent to route on — leave it to the normal KNOWLEDGE/RAG path
        # instead of burying that signal under the generic four-scheme list.
        if _infer_scheme_from_terms(question) is not None:
            return None
    lines = _scheme_listing_lines()
    answer = (
        f"I cover {_count_word(len(lines))} Meghalaya government schemes:\n\n" + "\n".join(lines) +
        "\n\nWhich one would you like to explore? I can give you the figures (by district, block, village "
        "or year) or explain eligibility, benefits and how to apply."
    )
    # One next step per scheme (Conversational Memory approach §8.3). The
    # finalize node's knowledge follow-ups would all be about one scheme, so
    # these are kept (keep_follow_ups, _attach_followups).
    chips = [f"Tell me about {name}" for name in _SCHEME_USER_SUMMARY]
    return {"route": "knowledge", "intent": "RAG", "confidence": "high", "sources": [],
            "answer": answer, **_empty_data_fields(), "suggestions": chips,
            "follow_up_options": [{"label": c, "question": c} for c in chips],
            "follow_ups": chips, "follow_up": chips[0], "keep_follow_ups": True}


# "What is the difference between the schemes?" / "compare MGNREGA and PMAY-G" as
# a KNOWLEDGE question — no per-scheme reference doc contains a cross-scheme
# comparison, so plain RAG retrieval reliably comes back "not covered". Compose
# a structured side-by-side directly from _SCHEME_USER_SUMMARY instead.
_SCHEME_COMPARISON_CUE = Matcher(Alt(
    Seq("difference", "between", _C04CharGap(40, "?"), _C04_SCHEME_W),
    Seq(_C04_SCHEME_W, _C04CharGap(40, "?"), W("differ", "difference")),
    Seq("compare", _C04CharGap(40, "?"), _C04_SCHEME_W),
    Seq("how", W("do", "does"), _C04CharGap(40, "?"), _C04_SCHEME_W, _C04CharGap(20, "?"), "differ"),
    Seq("difference", "between", _C04CharGap(60, "\n"),
        Alt(W("mgnrega", "pmay", "focusplus", "cmelevate"), Seq("focus", "plus", sep="space"),
            Seq("cm", "elevate", sep="space"),
            W("cmss"),
            W("homestay")),
        _C04CharGap(20, "\n"), W("and", "vs", "versus")),
))
# "compare Focus Plus and CM Elevate schemes BY BENEFICIARIES" / "... by amount" /
# "... by expenditure" names a real figure to pull from megh_db, not "how do the
# schemes differ conceptually" — _SCHEME_COMPARISON_CUE's bare "compare ... schemes"
# still matches that (it doesn't require a metric to be absent), so without this
# guard _scheme_comparison_answer intercepts a genuine statistics question at step
# 0-a, before classify_intent / DATA routing ever runs, and answers it with the
# canned RAG-style scheme blurb instead of a queried number.
_C04_GEO_PLURALS = W("district", "districts", "block", "blocks", "village", "villages")
_SCHEME_COMPARISON_METRIC_GUARD = Matcher(Alt(
    W("beneficiar", "spend", "disburs", "constituenc", prefix=True),
    W("amount", "amounts", "expenditure", "wage", "wages", "house", "houses", "payment", "payments",
      "total", "percentage", "rate"),
    _c04Joined("person", ("day", "days")), _c04Joined("job", ("card", "cards")),
    Seq("number", "of"), Seq("how", W("many", "much")), Seq("count", "of"), _c04Joined("per", "cent"),
    # a breakdown by place is a data request too: "Compare the schemes
    # district-wise" drew the "which schemes?" pause (cross-scheme run 2026-10-13)
    _c04Joined(("district", "block", "village", "year", "constituency"), "wise"),
    _C04_GEO_PLURALS,
))
# "Compare all six schemes" names every scheme; asking "which schemes?" back is a
# needless pause (cross-scheme run 2026-10-13).
_ALL_SCHEMES_NAMED = Matcher(Alt(
    Seq("all", Opt("the"), Opt(W("six", "6")), "schemes"), Seq(W("every", "each"), "scheme"),
    Seq(W("six", "6"), "schemes"),
))


def _scheme_comparison_clarification(question: str = "") -> "ClarificationNeeded":
    names = list(SCHEME_CATALOG)
    # F-2 (chat UI audit 2026-10-29): a pause over a question that asks figures
    # ("compare beneficiaries of the schemes") asked "difference between A and B"
    # on the chip, which is answered from the documents with no figures. The chip
    # asks for the figures the officer named; a question with none keeps the
    # "how do they differ" wording.
    from app import cross_scheme
    q = question or ""
    measure = ("money spent" if cross_scheme._MONEY.search(q) else
               "beneficiaries" if cross_scheme._COUNT.search(q) else None)
    ask = (lambda a, b: f"Compare {measure} in {a} and {b}") if measure else         (lambda a, b: f"difference between {a} and {b}")
    options = [
        {"label": f"{a} vs {b}", "question": ask(a, b)}
        for a, b in itertools.combinations(names, 2)
    ]
    _all = ", ".join(names[:-1]) + " and " + names[-1]
    _any = ", ".join(names[:-1]) + ", or " + names[-1]
    options.append({"label": f"All {len(names)} schemes",
                     "question": f"difference between {_all}"})
    return ClarificationNeeded(
        f"Which schemes would you like to compare — {_any}? Pick a pair, or compare "
        f"all {len(names)}.",
        options=options,
        rule="scheme-comparison-not-specified",
    )


# "the two schemes" / "both schemes" / "these schemes" point back at schemes the
# previous turn named: "Tell me about MGNREGA and PMAY-G" -> "What is the
# difference between the two schemes?" was answered "Which schemes would you like
# to compare?" (General TC-007, test run 2026-10-06).
_DEICTIC_SCHEMES_MATCH = Matcher(Alt(
    Seq(W("the", "these", "those", "both"), Opt(W("two", "2")), "schemes"),
    Seq("both", "of", "them"), Seq("the", "two"),
))


def _previous_turn_schemes(session: "Session | None") -> list[str]:
    """The schemes the last turn was about: its own list, else the ones its text named."""
    prev = getattr(session, "last_turn", None) if session is not None else None
    if prev is None:
        return []
    own = [s for s in (getattr(prev, "schemes", None) or []) if s in SCHEME_CATALOG]
    if len(own) >= 2:
        return own
    text = getattr(prev, "raw_question", None) or getattr(prev, "question", "") or ""
    return _named_schemes(text) or own


def _recent_compared_schemes(session: "Session | None", n: int = 4) -> list[str]:
    """The schemes "the two schemes" points back at. One turn that named both
    wins; otherwise the distinct schemes of the last few turns, most recent
    first. "What is Focus Plus?" -> "What is Focus Legacy?" -> "What is the
    difference between the two schemes?" asked the user to pick a pair from 15,
    because only the LAST turn was read (General TC-007, test run 2026-10-09)."""
    own = _previous_turn_schemes(session)
    if len(own) >= 2:
        return own
    seen: list[str] = []
    for t in reversed((getattr(session, "turns", None) or [])[-n:]):
        names = [s for s in (getattr(t, "schemes", None) or []) if s in SCHEME_CATALOG]
        names = names or _named_schemes(getattr(t, "raw_question", None) or getattr(t, "question", "") or "")
        for s in names:
            if s not in seen:
                seen.append(s)
        if len(seen) >= 2:
            break
    return list(reversed(seen[:2])) if len(seen) >= 2 else own


# Inside a CM Elevate conversation, "each scheme" means that dataset's own
# sub-schemes (Piggery, Poultry, …), which CM-ELEVATE itself calls schemes.
# "What is the total amount disbursed under each scheme?" right after a CM
# Elevate Legacy turn was read as all six top-level schemes (CM Elevate Legacy
# TC-18, test run 2026-10-06). With no such conversation it stays cross-scheme.
# "Which schemes have the highest number of applications?" / "across schemes" / "by
# scheme" in the same conversation were still read as every government scheme, even
# after the user tapped the CM Elevate Legacy topic (Legacy sheet one-chat run
# 2026-10-22: TC-13, TC-25).
_EACH_SCHEME_MATCH = Matcher(Alt(
    Seq(Alt("each", "every", "per", Seq("all", "the"), "individual"), _C04_SCHEME_W),
    _c04Joined("scheme", "wise"),
    Seq(W("which", "what"), W("schemes")), Seq("across", Opt("the"), W("schemes")), Seq("by", W("scheme")),
))


def _each_scheme_in_cm_thread(question: str, session: "Session | None") -> str:
    q = question or ""
    # The question's own words may point at a CM Elevate dataset ("sanctioned
    # applications" is Legacy vocabulary, TC-19) — that is the same conversation, not
    # another scheme; any other scheme's words leave the question alone.
    inferred = _infer_scheme_from_terms(q)
    if not _EACH_SCHEME_MATCH.search(q) or _named_schemes(q) \
            or (inferred and inferred not in (["CM Elevate"], ["CM Elevate Legacy"])):
        return question
    # The dataset the last answer came from wins over the name its question
    # typed: "loan entities … CM-ELEVATE applications" was answered from CM
    # Elevate Legacy, and the next "each scheme" was sent to the applications
    # data as "under CM Elevate" (Legacy sheet one-chat run 2026-10-22).
    last = getattr(session, "last_turn", None) if session is not None else None
    own = [s for s in (getattr(last, "schemes", None) or []) if s in ("CM Elevate", "CM Elevate Legacy")]
    prev = own if len(own) == 1 and len(getattr(last, "schemes", None) or []) == 1 \
        else _previous_turn_schemes(session)
    if prev not in (["CM Elevate"], ["CM Elevate Legacy"]):
        return question
    out = _EACH_SCHEME_MATCH.sub(lambda m: f"{m.group(0)} under {prev[0]}", q, count=1)
    logger.info("'each scheme' inside a %s conversation -> %r", prev[0], out)
    return out


def _scheme_comparison_answer(question: str, prev_schemes: "list[str] | None" = None) -> "dict | None":
    if not _SCHEME_COMPARISON_CUE.search(question or ""):
        return None
    if _SCHEME_COMPARISON_METRIC_GUARD.search(question or ""):
        return None  # names a real figure — let classify_intent send it to DATA
    named = _named_schemes(question)
    if len(named) < 2 and prev_schemes and len(prev_schemes) >= 2 \
            and _DEICTIC_SCHEMES_MATCH.search(question or ""):
        named = list(prev_schemes)
    if len(named) == 1 or (not named and _infer_scheme_from_terms(question) is not None):
        # The question already resolves to exactly one of the 4 top-level schemes
        # — this is a WITHIN-scheme comparison ("compare Piggery and Poultry
        # schemes under CM Elevate", "compare the three PRIME schemes"), not a
        # cross-scheme "MGNREGA vs PMAY-G" ask. CM Elevate's 15 sub-units are
        # themselves called "schemes", so the bare _SCHEME_COMPARISON_CUE word
        # "scheme(s)" fires here too; asking "which of the 4 schemes?" is
        # nonsensical when the question already named the one it means (confirmed
        # live 2026-09-11: "compare Piggery and Poultry schemes under CM Elevate"
        # raised the 4-way clarification instead of running the sub-scheme
        # comparison in cmelevate_few_shot.yaml). Let normal DATA routing handle it.
        return None
    if len(named) < 2 and _ALL_SCHEMES_NAMED.search(question or ""):
        named = list(SCHEME_CATALOG)
    if len(named) < 2:
        raise _scheme_comparison_clarification(question)
    targets = named
    folded = {d: p for p, ds in _PROGRAMME_DATASETS.items() for d in ds}
    lines = []
    for name in targets:
        line = f"- **{name}** — {_SCHEME_USER_SUMMARY.get(name, '')}"
        fit = _SCHEME_FIT.get(name)
        if name in folded:
            line += (f" Same programme and eligibility as {folded[name]}; this is its "
                     "sanction and disbursement data.")
        elif fit:
            # Who it is for and what it gives, from the same FAQ-derived table the
            # recommendations use — the summary alone did not say who qualifies.
            line += f" Who it is for: {fit[1]}"
        lines.append(line)
    answer = (
        "Here's a high-level comparison:\n\n" + "\n".join(lines) +
        "\n\nAsk about a specific one — eligibility, benefits, or the application "
        "process — for more detail."
    )
    out = {"route": "knowledge", "intent": "RAG", "confidence": "high", "sources": [],
           "answer": answer, **_empty_data_fields()}
    # B-6 (chat UI audit 2026-10-29): "Compare MGNREGA and PMAY-G" (no figure named)
    # gave text only; the chips ask the two figures every scheme pair can compare
    pair = " and ".join(targets) if len(targets) == 2 else ", ".join(targets[:-1]) + " and " + targets[-1]
    chips = [{"label": f"Compare beneficiaries in {pair}", "question": f"Compare beneficiaries in {pair}"},
             {"label": f"Compare money spent in {pair}", "question": f"Compare money spent in {pair}"}]
    out.update(follow_up_options=chips, follow_ups=[c["question"] for c in chips],
               follow_up=chips[0]["question"], keep_follow_ups=True)
    return out


# ── Named a scheme we simply don't hold ─────────────────────────────────────
# A user can reasonably name another Meghalaya / central scheme ("PM-KISAN",
# "Ujjwala", "Jal Jeevan"). The right answer is not the generic "which scheme?"
# prompt — it's to say plainly that only four schemes are loaded right now,
# then let them pick one. Keep this list to real scheme names/aliases; a bare
# word that is also scheme vocabulary must not appear. CM Elevate is now a
# supported scheme (see _SCHEME_NAME_MATCHER) and must NOT appear here.
_UNSUPPORTED_SCHEME = Matcher(Alt(
    Seq("prime", "meghalaya"), Seq("meghalaya", "prime"),
    _c04Joined("pm", "kisan"), Seq("kisan", "samman"),
    _c04Joined("pmay", "u"), Seq("pmay", "urban"), Seq("awas", "yojana", "urban"),
    "pmgsy", Seq("gram", "sadak"),
    W("pmuy", "ujjwala", "ujwala", "saubhagya"),
    Seq("jal", "jeevan", Opt("mission")), "jjm", Seq("har", "ghar", "jal"), Seq("nal", "se", "jal"),
    Seq("ayushman", Opt("bharat")), _c04Joined("pm", "jay"),
    W("mhis", "cmhis"), Seq("megha", "health"),
    W("nsap", "ignoaps"), Seq(_c04Joined("old", "age"), "pension"),
    Seq(W("widow", "disability"), "pension"),
    "nrlm", _c04Joined("day", "nrlm"), W("aajeevika", "ajeevika"),
    Seq(W("livelihood", "livelihoods"), "mission"),
    Seq("swachh", "bharat"), "sbm", Seq("nirmal", "bharat"),
    Seq(_c04Joined("mid", "day"), "meal"), _c04Joined("pm", "poshan"),
    W("icds", "anganwadi"), Seq("poshan", W("abhiyan", "abhiyaan")),
    W("kanyashree", "ladli", "sukanya"),
    Seq("atal", "pension"), "apy",
    W("mudra", "pmmy"), Seq(_c04Joined("stand", "up"), "india"),
    Seq("kisan", "credit", "card"), "kcc",
    Seq("fasal", "bima"), "pmfby", Seq("crop", "insurance"),
    _c04Joined("e", "shram"),
    "nfsa", Seq("one", "nation", "one", "ration"), Seq("public", "distribution"), Seq("ration", "card"),
))


def _unsupported_scheme_named(question: str) -> "str | None":
    """The name of a scheme the user asked about that we don't hold — or None.
    Only fires when NO supported scheme is also named, so mixed questions
    ("compare CM Elevate with MGNREGA") still route normally. The unsupported
    match is blanked out before the supported-scheme check so a near-miss like
    "PMAY-U" isn't swallowed by the PMAY-G matcher."""
    m = _UNSUPPORTED_SCHEME.search(question or "")
    if not m:
        return None
    without = (question[:m.start()] + " " + question[m.end():])
    if any(p.search(without) for p in _SCHEME_NAME_MATCHER.values()):
        return None
    return m.group(0)


def _unsupported_scheme_clarification(question: str, name: str) -> "ClarificationNeeded":
    # Drop the unsupported scheme name (plus any preposition left dangling by
    # its removal, e.g. "... years in pm-kisan?" -> "... years") so the
    # resumed one-tap question reads cleanly.
    stem = _c04_replace_ci(question, name, " ")
    stem = collapse_ws(stem).rstrip(" ?.")
    _head, _sp, _last = stem.rpartition(" ")
    if _sp and _last.lower() in ("in", "for", "of", "under", "from", "about", "on"):
        stem = _head.strip()
    stem = stem or question.strip().rstrip(" ?.")
    options = [
        {"label": "MGNREGA (rural employment)",
         "question": _scheme_option_question(stem, "MGNREGA")},
        {"label": "PMAY-G (rural housing)",
         "question": _scheme_option_question(stem, "PMAY-G")},
        {"label": "Focus Plus (farmer cash benefit)",
         "question": _scheme_option_question(stem, "Focus Plus")},
        {"label": "CM Elevate (livelihood / enterprise schemes)",
         "question": _scheme_option_question(stem, "CM Elevate")},
        {"label": "Focus Legacy (producer group payments)",
         "question": _scheme_option_question(stem, "Focus Legacy")},
        {"label": "CM Elevate Legacy (sanctions & disbursements)",
         "question": _scheme_option_question(stem, "CM Elevate Legacy")},
        {"label": "CMSS (Chief Minister's Scholarship Scheme)", "question": _scheme_option_question(stem, "CMSS")},
        {"label": "Homestay (tourism homestay scheme)", "question": _scheme_option_question(stem, "Homestay")},
    ]
    # Names the scheme asked for, says plainly that it is outside what is
    # loaded, then points somewhere useful. Deliberately about SCHEME COVERAGE
    # rather than "no data": the user asked about a real government scheme that
    # simply isn't one of the four here, and "I don't have information about
    # that" reads as though the assistant is broken rather than out of scope
    # (reported 2026-09-18).
    # Echo the scheme name back in a presentable form — the matched text is
    # whatever the user typed ("ujjwala", "pm kisan"), and a reply that opens
    # with a lowercase scheme name reads careless. An all-caps acronym
    # ("PM-KISAN", "JJM") is already right and left alone.
    _display = " ".join(w if w.isupper() else w.capitalize()
                        for w in name.strip().split())
    return ClarificationNeeded(
        # The schemes themselves are the cards under this line, so they are not
        # listed again in the text (user, 2026-10-18).
        f"{_display} isn't one of the schemes I cover, so I can't answer questions "
        "about it — its rules, eligibility or data. These are the schemes I do cover. "
        "Pick one below and I'll take your question there.",
        options=options,
        rule="scheme-not-available",
    )
