"""
Edge-case handler — catches non-analytical input (greetings, "who are you",
thanks, off-topic, abuse) BEFORE any model call. Zero cost, instant, on-brand.

Ported from NeuralAiGovernanceProject `services/edge_handler.py` and kept in
step with it: same rule-based shape — strong-intent early exit, ordered rule
banks, meta-conversation + follow-up + non-English pass-throughs, then a
domain whitelist that BLOCKS anything with no MGNREGA / PMAY-G context. The
rule banks are the reference's; the responses are rewritten for this
assistant (Meghalaya MGNREGA + PMAY-G, sourced from megh_db and the scheme
reference docs).

`detect_edge_case(question) -> {"type", "response", "suggestions"?} | None`
  - a dict  => stop here, return this canned reply (no model call)
  - None    => a real data / knowledge / follow-up question — let the pipeline route it
"""
from app import guardrails
from app.guardrails import _A, _GCharGap, _GRule, _GSeq, _P, _S, _g_space, _pl
from app.guardrails import Matcher
from app.text_match import (ANY, END, START, Alt, Joined, Node, NotBefore, Opt, Pred, Rep, Seq,
                            W, tokens)

# ── Matching helpers (word-level, app/text_match) ───────────────────────────
# The banks below are lists of objects with .search(text). Pieces built with
# _S need one or more plain whitespace characters between words. A rule with no
# word edge on a side keeps that looseness: _sfx(...) is a word ENDING in the
# stem (an unbounded start), _P(...) a word STARTING with it (an unbounded end).


def _sfx(*stems):
    """A word ending in any of `stems` (no word edge needed in front)."""
    low = tuple(s.lower() for s in stems)
    return Pred(lambda w: w.lower().endswith(low))


def _edge_is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _edge_rstrip(t: str, chars: str = "!.?") -> str:
    """`t` without a trailing run of whitespace and `chars` (by default ! . ?)."""
    i = len(t)
    while i and (t[i - 1].isspace() or t[i - 1] in chars):
        i -= 1
    return t[:i]


class _EdgeWhole:
    """The WHOLE message is `node`, then only whitespace / `tail` characters
    (by default ! . ?) to the end. lead=True allows leading non-word characters."""

    def __init__(self, node, *, lead: bool = False, tail: str = "!.?"):
        self.m = Matcher(node)
        self.lead, self.tail = lead, tail

    def search(self, text):
        core = _edge_rstrip(text or "", self.tail)
        if not core or not _edge_is_word_char(core[-1]):
            return None
        if not self.lead and not _edge_is_word_char(core[0]):
            return None
        return self.m.fullmatch(core)


class _EdgeLead:
    """The message STARTS with `node`; lead=True allows leading non-word
    characters before it. upto=N: the match ends at a word edge and at most N
    more characters (no line break) may follow it to the end of the message."""

    def __init__(self, *alternatives, lead: bool = False, upto: "int | None" = None):
        self.ms = [Matcher(Seq(START, a)) for a in alternatives]
        self.lead, self.upto = lead, upto

    def search(self, text):
        t = text or ""
        if not t or (not self.lead and not _edge_is_word_char(t[0])):
            return None
        for m in self.ms:
            h = m.match(t)
            if h is None:
                continue
            if self.upto is None:
                return h
            rest = t[h.end():]
            if len(rest) <= self.upto and "\n" not in rest:
                return h
        return None


def _M(*alternatives):
    return Matcher(_A(*alternatives))


_THAT_S = _A(W("thats"), _GSeq("that", "s", ok=lambda g: len(g) == 1))   # that's / thats / that-s


def _focus_plus(t: str) -> bool:
    """"focus" then optional whitespace then "+"."""
    low = t.lower()
    i = low.find("focus")
    while i >= 0:
        if low[i + 5:].lstrip().startswith("+"):
            return True
        i = low.find("focus", i + 1)
    return False


def _edge_year(w: str) -> bool:
    """A 4-digit year 19xx / 20xx / 21xx."""
    return len(w) == 4 and w.isdigit() and w[:2] in ("19", "20", "21")


def _edge_fy_range(t: str) -> bool:
    """19xx / 20xx / 21xx, optional spaces, - or /, optional spaces, 2+ digits
    (anywhere in the text, with no word edges required)."""
    n = len(t)
    for i in range(n - 3):
        if t[i:i + 2] in ("19", "20", "21") and t[i + 2].isdigit() and t[i + 3].isdigit():
            j = i + 4
            while j < n and t[j].isspace():
                j += 1
            if j < n and t[j] in "-/":
                j += 1
                while j < n and t[j].isspace():
                    j += 1
                if j + 1 < n and t[j].isdigit() and t[j + 1].isdigit():
                    return True
    return False


def _edge_arith(t: str) -> bool:
    """"what is 2+2" / "what is 5 x 3": digits, optional spaces, one of + - * / x,
    optional spaces, digits."""
    for h in _WHAT_IS.finditer(t):
        i, n = h.end(), len(t)
        if i >= n or not t[i].isspace():
            continue
        while i < n and t[i].isspace():
            i += 1
        j = i
        while j < n and t[j].isdigit():
            j += 1
        if j == i:
            continue
        while j < n and t[j].isspace():
            j += 1
        if j < n and t[j] in "+-*/x":
            j += 1
            while j < n and t[j].isspace():
                j += 1
            if j < n and t[j].isdigit():
                return True
    return False


_WHAT_IS = Matcher(_S(_sfx("what"), "is"))

# ── Rule banks ──────────────────────────────────────────────────────────────
def _hii(w: str) -> bool:
    """hii, hiii, … ("h" then two or more 'i')."""
    w = w.lower()
    return len(w) >= 3 and w[0] == "h" and set(w[1:]) == {"i"}


_GREET_WORD = _A(W("hi", "hello", "hey", "helo", "namaste", "namaskar", "khublei", "kumno"),
                  Pred(_hii))
_DAYPART = ("morning", "afternoon", "evening", "day", "night")
_GREETINGS = [
    _EdgeWhole(_S(_A(_GREET_WORD, W(*("good" + d for d in _DAYPART)), _S("good", W(*_DAYPART))),
                  Opt(W("there", "all", "team", "everyone", "bot", "assistant", "folks", "sir",
                        "madam")))),
    _EdgeWhole(_A(W("howdy", "greetings", "sup", "yo", "hola", "whatup", "whatsup"),
                   _S(W("what", "whats"), "up"))),
]

_GREET_OPT = Opt(_A(W("hi", "hello", "hey"), Pred(_hii)))
_IDENTITY = [
    _M(_S(_sfx("who", "what"), W("are", "r"), W("you", "u"))),
    _M(_S(_sfx("your", "ur"), W("name", "purpose", "job", "role"))),
    _M(_S(_sfx("are"), "you", Opt(W("a", "an")),
          _P("ai", "bot", "human", "real", "chatbot", "robot", "machine", "gpt", "chatgpt",
             "claude", "gemini", "qwen", "llm"))),
    _M(_S(_sfx("tell", "about"), Opt("me"), "about", W("yourself", "you"))),
    _M(_S(_sfx("what"), "can", "you", W("do", "help"))),
    _M(_S(_sfx("what"), "do", "you", "do")),
    _M(_S(_sfx("introduce"), "yourself")),
    _M(_S(_sfx("which"), W("ai", "model", "llm", "technology", "company"),
          W("are", "is", "do", "made", "built"), "you")),
    _M(_S(_sfx("powered", "built", "made", "developed", "created", "trained"), "by")),
    _M(_S(_sfx("how"), W("do", "does"), "you", "work")),
    # conversational "how can you help me" / "can you help me" openers — these
    # carry no scheme keyword, so without a rule here they fall all the way
    # through to the off-topic whitelist gate and get the blunt "I can only
    # answer..." reply instead of the friendly capabilities rundown. A message
    # that also names a scheme/domain term exits earlier at the _SCHEME_STRONG
    # check (step 1), so these stay safe to match loosely.
    _EdgeLead(Seq(_GREET_OPT, _S("how", W("can", "could", "do", "would"), W("you", "u"),
                                 W("help", "assist"))), lead=True),
    _EdgeLead(Seq(_GREET_OPT, _S(W("can", "could", "would"), W("you", "u"), W("help", "assist"),
                                 "me")), lead=True),
    _M(_S(_sfx("what"), "can", W("you", "u"), "help", Opt("me"), "with")),
    _M(_S(_sfx("what"), "all", "can", W("you", "u"), "do")),
]


def _thanks_short(t: str) -> bool:
    """A thanks word first (ending at a word edge), then at most 20 more characters."""
    if not t or not _edge_is_word_char(t[0]):
        return False
    h = _THANKS_LEAD.match(t)
    if h is None:
        return False
    rest = t[h.end():]
    # "thank you, it is very helpful" (live 2026-10-18): the "you" is part of the
    # lead, and the tail allows a short compliment after the comma.
    return len(rest) <= 24 and "\n" not in rest


_THANKS_LEAD = Matcher(Seq(START, _A(
    _S("thank", W("you", "u")),
    W("thanks", "thank", "thankyou", "thanku", "ty", "thx", "dhanyavaad", "dhanyawad", "shukriya"),
    _S("khublei", "shibun"))))
_PRAISE = ("great", "perfect", "awesome", "excellent", "brilliant", "fantastic", "helpful", "nice")
_THANKS = [
    _GRule(_thanks_short),
    _EdgeWhole(_S(_A(_THAT_S, W("that")),
                  W("great", "helpful", "perfect", "awesome", "nice", "good", "excellent", "useful",
                    "wonderful"))),
    _EdgeWhole(_A(_S(W(*_PRAISE), Opt(W("help", "work"))),
                   W(*(p + s for p in _PRAISE for s in ("help", "work"))))),
]

_GOODBYE = [
    _EdgeWhole(_A(W("bye", "goodbye", "cya", "later", "done", "seeyou", "takecare", "okbye"),
                   _A("good bye", "see you", "take care", "ok bye"), _S(_THAT_S, "all"))),
    _EdgeWhole(_S("have", "a", W("good", "great", "nice"), W("day", "evening", "night"))),
]

_PROFANITY_REDIRECT = [
    _M(W("fuck", "fuk", "shit", "damn", "bastard", "crap", "bloody", "bullshit", "wtf", "stfu")),
]

_SILLY = [
    # jokes / entertainment / creative writing
    _M(_S(_sfx("tell", "say"), Opt("me"), Opt("a"), _P("joke", "funny", "riddle"))),
    _M(_S(_sfx("make"), "me", _P("laugh"))),
    _M(_S(_sfx("sing"), Opt("a"), _P("song"))),
    _M(_S(_sfx("write"), Opt("me"), Opt("a"),
          _P("poem", "story", "essay", "rap", "song", "lyrics", "script"))),
    _M(_S(_sfx("play"), Opt("a"), _P("game"))),
    # personal feelings / anthropomorphising
    _M(_S(_sfx("do"), "you",
          _P("like", "love", "hate", "feel", "dream", "sleep", "eat", "drink", "breathe", "think"))),
    _M(_S(_sfx("favorite", "favourite"),
          _P("color", "colour", "food", "movie", "song", "book", "sport", "animal", "team"))),
    _M(_S(_sfx("how"), "old", "are", _P("you"))),
    _M(_S(_sfx("where"), "do", "you", _A(_P("live", "stay"), _S("come", _P("from"))))),
    _M(_S(_sfx("are"), "you", _P("happy", "sad", "angry", "tired", "bored", "excited", "scared",
                                 "lonely", "married", "single"))),
    _M(_S(_sfx("marry", "date", "love", "kiss", "hug"), _P("me"))),
    _M(_S(_sfx("do"), "you", "have",
          _A(_P("feelings", "emotions", "heart", "soul", "family", "friends"),
              _S("a", _P("boyfriend", "girlfriend"))))),
    # philosophical / general chit-chat
    _M(_S(_sfx("what"), "is", "the", W("meaning", "purpose"), "of", _P("life", "everything"))),
    _M(_S(_sfx("is", "does"), "god", _P("real", "exist"))),
    _M(_S(_sfx("what"), W("happens", "comes"), "after", _P("death"))),
    # comparisons with other AI
    _M(_S(_sfx("better", "worse"), "than",
          _P("chatgpt", "gpt", "openai", "claude", "gemini", "copilot", "bard"))),
    _M(_S("vs", W("chatgpt", "gpt", "claude", "gemini", "copilot", "bard"))),
    # random unrelated tasks
    _M(_S(_sfx("translate"), W("this", "to", "into"), ANY)),
    _M(_S(_sfx("write", "draft", "compose"), Opt("a"),
          _A(_P("email", "letter", "message", "whatsapp", "cv", "resume"),
              _S("application", "for", _P("leave"))))),
    _M(_S(_sfx("solve"), Opt("this"), _P("math", "equation", "sum", "problem", "puzzle"))),
    _GRule(lambda t: _edge_arith(t)),
    _M(_S(_sfx("predict", "forecast"), Opt("the"),
          _P("future", "stock", "crypto", "price", "weather", "match"))),
    _M(_S(_sfx("give"), "me", W("advice", "tips"), "on",
          _P("life", "love", "money", "career", "health", "relationship"))),
    # insults aimed at the assistant
    _M(Pred(lambda w: any(s in w.lower() for s in ("stupid", "dumb", "useless", "idiot", "fool",
                                                   "trash", "garbage", "nonsense")))),
    _M(_S(_sfx("you"), _A(_P("suck"), _S("are", _P("bad", "useless", "dumb")),
                           _S("are", "wrong", _P("always"))))),
    # general knowledge that isn't ours
    _M(_S(_A(_sfx("capital", "president", "currency", "population", "area", "gdp",
                   "primeminister"),
              _S(_sfx("prime"), "minister")),
          "of", ANY)),
    # RAG fix report 2026-10-29, Issue 17: "Who is the Chief Minister of Meghalaya?" was
    # refused although the reference documents name him (the FOCUS+ launch). Meghalaya's
    # own CM goes on to the documents; any other state's stays off-topic.
    _M(_S(_A(_sfx("chiefminister"), _S(_sfx("chief"), "minister")), "of",
          Pred(lambda w: w.lower() != "meghalaya"))),
    _M(_S(_sfx("who"), W("is", "was"), Opt("the"),
          _A(W("president", "primeminister", "king", "queen", "ceo", "founder", "inventor", "actor",
                "actress", "elon", "musk", "modi", "trump"), _S("prime", "minister")))),
    _M(_S(_sfx("largest", "smallest", "tallest", "longest", "biggest", "fastest", "richest"),
          _P("country", "city", "river", "mountain", "building", "company"))),
    _M(_S(_sfx("what", "how"), W("is", "does", "do"),
          W("gravity", "photosynthesis", "evolution", "inflation", "blockchain", "electricity"))),
    _M(_S(_A(_sfx("recipe", "ingredients"), _S(_sfx("how"), "to", W("cook", "make"))), ANY)),
    _M(_S(_sfx("symptom", "treatment", "cure", "medicine"), W("for", "of"), ANY)),
    _M(_A(W("ipl", "cricket", "football", "soccer", "bollywood", "hollywood", "netflix"),
          "match score")),
]

_OFF_TOPIC = [
    _M(W("weather", "temperature", "forecast", "horoscope", "zodiac", "astrology"), "news today"),
    _M(W("stock", "sensex", "nifty", "bitcoin", "crypto", "nft", "investment"), "share market",
       "mutual fund"),
    _M(W("flight", "irctc", "visa", "passport", "tourism"), "train ticket", "hotel booking",
       "holiday package"),
    _M(W("amazon", "flipkart"), "online shopping", _S("price", "of", W("a", "an", "the"))),
    _M(W("admission", "jee", "neet", "upsc"), "exam result", "board result"),
]

# PERSONAL financial advice — "where should I invest my money", "best way to
# invest 1 lakh", "how do I grow my savings". Its own bank, checked AHEAD of
# the scheme-intent early exit: _SCHEME_STRONG counts a bare money unit
# ("lakh", "crore") as scheme intent, so these were waved through to the
# pipeline and collected the "which scheme?" picker instead of a refusal
# (reported 2026-09-18). Every rule is anchored on the ADVICE phrasing,
# never on the money noun, so a real scheme question using the same units
# ("total expenditure in lakh") is untouched.
_MONEY_ADVICE = [
    _M(Seq(W("where", "how", "what"), _GCharGap(30, "?.!"),
           _S(W("should", "can", "do", "would", "could"), W("i", "we")), _GCharGap(30, "?.!"),
           W("invest", "save", "deposit", "put"))),
    _M(_S(W("best", "safest", "good"), _pl("way", "place", "option", "scheme"), "to",
          W("invest", "save", "deposit", "park", "grow"))),
    _M(_S(W("invest", "investing"), Opt(W("my", "our", "his", "her", "their", "the")),
          W("money", "savings", "funds", "cash"))),
    _M(_S(W("where", "how"), "to", W("invest", "save"))),
    _M(_S(W("grow", "double", "multiply"), W("my", "our"), W("money", "savings", "wealth"))),
]

# A personal request for money: "now give me five thousand loan for me i am in
# crisis" (reported 2026-09-29, right after a Focus Plus answer). It named no
# scheme, so the follow-up rewrite glued Focus Plus on and the DATA path asked
# "which year / area?" for a Focus Plus analytics query nobody asked. The
# assistant cannot give, lend or approve anything; it says so, then points at
# the schemes that do offer support. Anchored on a FIRST-PERSON request for
# money, never on the money noun alone: "how many loans were disbursed under CM
# Elevate Legacy?" and "give me the amount disbursed" are untouched.
def _pr_gap(g: str) -> bool:
    """Whitespace, possibly with a ₹ sign or the dot of "rs." in it."""
    return g != "" and g.replace("₹", "").replace(".", "").strip() == ""


def _PR(*parts):
    return _GSeq(*[_g_phrase_e(p) for p in parts], ok=_pr_gap)


def _g_phrase_e(p):
    if isinstance(p, str) and " " in p.strip():
        return _GSeq(*p.split(), ok=_pr_gap)
    return p


_MONEY_NOUN = _A(W("loan", "loans", "money", "cash", "rupee", "rupees", "fund", "funds"),
                  _PR("financial", W("help", "aid", "support", "assistance")))
_UNIT = ("k", "lakh", "lakhs", "lac", "lacs", "thousand", "crore", "crores")


def _amount_token(w: str) -> bool:
    """Digits, optionally glued to a unit: "5000", "5k", "2lakh"."""
    w = w.lower()
    i = 0
    while i < len(w) and w[i].isdigit():
        i += 1
    return i > 0 and (i == len(w) or w[i:] in _UNIT)


class _EdgeNumber(Node):
    r"""A written number: digit tokens joined by ',' / '.' ("1,00,000", "5.5"),
    the last one possibly glued to a unit ("5k") — digits and commas, then an
    optional '.' with digits."""

    def ends(self, ctx, i, caps):
        n, j, out = len(ctx.toks), i, []
        while j < n and (j == i or ctx.gap(j) in (",", ".")):
            raw = ctx.toks[j].raw
            if raw.isdigit():
                out.append(j + 1)
            elif _amount_token(raw):
                out.append(j + 1)
                break
            else:
                break
            j += 1
        for e in reversed(out):
            yield e, caps


_NUMBER = _EdgeNumber()
_AMOUNT_WORDS = _A(
    _PR(Opt(W("rs", "inr")), _NUMBER, Opt(W(*_UNIT))),
    _PR(Opt(W("rs", "inr")),
        W("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "twenty",
          "fifty", "hundred", "thousand", "lakh", "lakhs", "crore"),
        Rep(W("hundred", "thousand", "lakh", "lakhs", "crore", "crores"))),
)
_RS = Opt(W("rs", "rupee", "rupees"))
_PERSONAL_REQUEST = [
    # "give me five thousand loan", "lend me 5000 rupees", "send us money"
    _M(_PR(W("give", "lend", "loan", "send", "grant", "provide", "pay", "transfer", "arrange",
             "sanction", "approve", "release"), W("me", "us"), Opt(W("a", "an", "some")),
           Opt(_AMOUNT_WORDS), _RS, _MONEY_NOUN)),
    # "a loan for me", "money for my family"
    _M(_PR(_MONEY_NOUN, "for",
           _A(W("me", "myself", "us"),
               _PR("my", W("family", "son", "daughter", "wife", "husband", "mother", "father",
                           "children", "kids"))))),
    # "I need a loan", "I want 5000 rupees", "can I get money"
    _M(_PR(W("i", "we"), _A(W("need", "want", "require"), _PR("urgently", "need")),
           Opt(W("a", "an", "some")), Opt(_AMOUNT_WORDS), _RS, _MONEY_NOUN)),
    _M(_PR("can", W("i", "we"), W("get", "have", "borrow"), Opt(W("a", "an", "some")),
           Opt(_AMOUNT_WORDS), _RS, _MONEY_NOUN)),
    # "I am in crisis", "we are in debt"
    _M(_S(_A(_GSeq("i", W("am", "m"), ok=lambda g: g.strip() in ("", "'")), W("iam"),
              _GSeq("we", W("are", "re"), ok=lambda g: g.strip() in ("", "'")), W("weare")),
          "in", Rep(W("a", "great", "serious", "financial")),
          W("crisis", "debt", "trouble", "distress", "emergency", "need"))),
]


# A request for help with something ILLEGAL or harmful — "i want to rob a bank,
# give me suggestions", "how to make fake job cards", "help me bribe the
# officer". Checked before everything else, including by the pipeline ahead of
# its own recommendation / pick steps: "give me some suggestions" in such a
# message was once read as a scheme recommendation and answered with the
# previous turn's scheme (reported 2026-09-24). Anchored on INTENT phrasing, so
# a legitimate question about wrongdoing ("how are fake job cards detected?",
# "fraud cases in MGNREGA social audits") is not refused.
_HARMFUL_INTENT = _A(
    _S("i", _A("want", "wanna", "plan", "am planning", "need", "intend", "would like"), "to"),
    _S("we", W("want", "plan", "need"), "to"),
    _S("how", W("can", "do", "could", "should", "would"), W("i", "we", "one", "someone")),
    _S("how", "to"), _S("help", W("me", "us")), _S("teach", "me"), _S("show", "me", "how"),
    _S(W("way", "ways"), "to"), _S(W("tip", "tips"), W("to", "for", "on")),
    _S(W("idea", "ideas"), W("to", "for")), _S(_P("suggest"), W("to", "for", "how")),
    _S("best", "way", "to"), W("lets"), Seq("let", "s"), _S("plan", "to"),
)
_HARMFUL_ACT = _A(
    _P("rob", "loot", "steal", "burgl", "kidnap", "murder", "smuggl", "launder", "brib", "embezzl",
       "defraud", "swindl", "extort", "counterfeit", "siphon", "poison", "bomb"),
    W("forge", "forged", "forging", "forgery"),
    _S("hack", W("into", "the", "a", "an")),
    _S(_P("cheat"), Opt("the"),
       W("government", "govt", "scheme", "bank", "system", "officer", "people")),
    _S(W("make", "create", "get", "use", "prepare"), Opt("a"),
       W("fake", "false", "forged", "duplicate"), ANY),
    _S("fake", _A(_pl("document", "certificate", "id", "bill"), W("aadhaar", "aadhar"),
                   W("jobcard", "jobcards"), _S("job", W("card", "cards")), _P("beneficiar"))),
    _S("misuse", Opt("the"), W("fund", "funds", "money", "scheme")),
    _S("evade", _P("tax")),
)
_HARMFUL = [
    _M(Seq(_HARMFUL_INTENT, _GCharGap(50, ".?!"), _HARMFUL_ACT)),
    _M(_S(W("rob", "robbing", "robbed"), Opt(W("a", "the")), "bank"), "bank robbery",
       "money laundering"),
]


def _hm(w: str) -> bool:
    """hmm, hmmm, … ("h" then two or more 'm')."""
    w = w.lower()
    return len(w) >= 3 and w[0] == "h" and set(w[1:]) == {"m"}


def _um(w: str) -> bool:
    w = w.lower()
    return len(w) >= 3 and w[0] == "u" and set(w[1:]) == {"m"}


def _rep_tail(head: str, ch: str):
    """head followed by one or more `ch` ("uh", "uhhh", "ok", "okkk")."""
    return lambda w: len(w) >= 2 and w.lower()[0] == head and set(w.lower()[1:]) == {ch}


def _only_questionmarks(t: str) -> bool:
    return t != "" and set(t) == {"?"}


def _what_question(t: str) -> bool:
    """Exactly "what?", then only whitespace / ! . ? to the end."""
    return t[:5].lower() == "what?" and all(c.isspace() or c in "!.?" for c in t[5:])


_CONFUSED = [
    _GRule(_what_question),
    _EdgeWhole(_A(_S("i", _A(W("dont"), _GSeq("don", "t", ok=lambda g: len(g) == 1)),
                      W("know", "understand")),
                   W("huh", "confused"), _S("im", "confused"), _S("i", "m", "confused"),
                   _S("no", "idea"))),
    _EdgeWhole(_A(W("help", "helpme", "guideme", "assistme"), _S("help", "me"),
                   _S("i", "need", "help"), _S("guide", "me"), _S("assist", "me"))),
    _EdgeWhole(_A(Pred(_hm), Pred(_um), Pred(_rep_tail("u", "h")), Pred(_rep_tail("o", "k")),
                   W("okay", "k", "kk", "yeah", "nah", "sure", "right", "fine", "gotit"),
                   _S("got", "it"))),
    _EdgeWhole(_A(W("start", "begin", "go", "letsstart", "letsbegin", "letsgo"),
                   _S(_A(W("lets"), _GSeq("let", "s", ok=lambda g: len(g) == 1)),
                      W("start", "begin", "go")))),
    _GRule(_only_questionmarks),
    # "what should I do?" / "what do I ask?" / "where do I start?" — a user
    # who wants to be pointed somewhere, not an off-topic question. These have
    # no domain vocabulary, so before this they fell through to the step-6
    # whitelist gate and got the blunt "I can only answer questions about those
    # schemes" bounce, which reads as a refusal to someone asking for guidance
    # (reported 2026-09-17). The _CONFUSED reply already says exactly what to
    # try, and carries the starter chips.
    _EdgeLead(_S("what", W("should", "shall", "can", "do", "would"), "i",
                 _A(W("do", "ask", "say", "type", "query"), _S("start", "with"))), lead=True),
    _EdgeLead(_S(W("where", "how"), W("do", "should", "can"), "i", W("start", "begin")), lead=True),
    _EdgeWhole(_A(W("whatnext", "whatnow"), _S("what", W("next", "now"))), lead=True),
    _EdgeLead(_S(W("give", "show", "suggest"), Opt("me"), Opt("some"),
                 _pl("example", "suggestion", "idea", "option")), lead=True),
]

# Unmistakably-not-ours topics — blocked even if a place name (e.g. "Shillong")
# also appears, since the strong-intent early exit would otherwise wave them through.
_HARD_OFF_TOPIC = [
    _M(W("weather", "temperature", "forecast", "rain", "rainfall", "rainy", "humidity", "horoscope",
         "zodiac", "astrology")),
    _M(W("bitcoin", "crypto", "sensex", "nifty"), "share price", "stock price"),
    _M(W("cricket", "ipl", "football", "movie", "film"), "match score", "song lyrics"),
]


class _EdgeAnyOf:
    """Matches when any of its matchers / checks does (.search returns the first hit)."""

    def __init__(self, *parts):
        self.parts = parts

    def search(self, text):
        for p in self.parts:
            h = p.search(text)
            if h:
                return h
        return None


# ...unless the text also names a scheme outright, in which case route it.
_SCHEME_NAMED = _EdgeAnyOf(
    _M(W("mgnrega", "mnrega", "nrega", "pmay", "pmayg", "awaas", "awas", "focusplus", "cmelevate",
         "focuslegacy"),
       Joined("focus", "plus"), Joined("cm", "elevate"), Joined("focus", "legacy"), W("cmss", "scholarship", "scholarships"),
       Joined("producer", ("group", "groups"))),
    _GRule(_focus_plus),
)

# ── Out-of-area — a place that is not in Meghalaya ─────────────────────────
# The assistant holds Meghalaya data only. A question anchored on another
# state, a neighbouring city, or "all-India" is out of scope even when it
# names a scheme and uses scheme vocabulary ("PMAY-G houses in Assam",
# "how many districts in Guwahati for PMAY-G") — so this is checked BEFORE
# the strong-intent early exit, and stands down only when a Meghalaya place
# is *also* named (e.g. "compare Meghalaya with Assam").
# (Alternatives are tried in this order at each word, longer names first:
# "west bengal" before "bengal", "new delhi" before "delhi".)
_OUT_OF_AREA = _M(
    "assam", _S("arunachal", Opt("pradesh")), "nagaland", "manipur", "mizoram", "tripura", "sikkim",
    "west bengal", "bengal", "bihar", "jharkhand", "odisha", "orissa", "chhattisgarh",
    "madhya pradesh", "uttar pradesh", "uttarakhand", "rajasthan", "gujarat",
    "maharashtra", "goa", "karnataka", "kerala", Joined("tamil", "nadu"), "telangana",
    _S("andhra", Opt("pradesh")), "punjab", "haryana", _S("himachal", Opt("pradesh")),
    "jammu", "kashmir", "ladakh", "puducherry", "pondicherry", "chandigarh",
    "andaman", "nicobar", "lakshadweep",
    "guwahati", "gauhati", "dispur", "silchar", "dibrugarh", "jorhat", "tezpur",
    "kolkata", "calcutta", "new delhi", "delhi", "mumbai", "bombay", "bengaluru", "bangalore",
    "chennai", "madras", "hyderabad", "pune", "ahmedabad", "jaipur", "lucknow", "kanpur", "patna",
    "bhopal", "indore", "nagpur", "visakhapatnam",
    "kohima", "imphal", "aizawl", "agartala", "itanagar", "gangtok", "dimapur", "siliguri",
    Joined("all", "india"), Joined("pan", "india"), Joined("nation", "wide"), "india",
    "across the country", "whole country", "entire country",
)


class _EdgeUS(Node):
    """"u.s" / "u.s.a", then an optional '.' and whitespace, , ; : ? ! ) or the
    end — so "U.s.t", the start of a longer dotted word, is not the country."""

    def ends(self, ctx, i, caps):
        toks, n = ctx.toks, len(ctx.toks)
        if not (i + 1 < n and toks[i].low == "u" and toks[i + 1].low == "s" and ctx.gap(i + 1) == "."):
            return
        ends = []
        if i + 2 < n and toks[i + 2].low == "a" and ctx.gap(i + 2) == ".":
            ends.append(i + 3)
        ends.append(i + 2)
        for e in ends:
            rest = ctx.text[toks[e - 1].end:]
            if rest.startswith("."):
                rest = rest[1:]
            if rest == "" or rest[0].isspace() or rest[0] in ",;:?!)":
                yield e, caps


# Any country/continent outside India — "how many beneficiaries in Madagascar"
# is exactly as out-of-scope as "... in Assam", but names no Indian place at
# all, so it needs its own list rather than living in _OUT_OF_AREA above.
# Not exhaustive (no list of world place names can be), but covers the
# countries/continents/generic phrasing QA and users actually ask about.
_FOREIGN_PLACE = _M(
    _P("madagasca"), "nigeria", "kenya", "ethiopia", "egypt", "south africa", "morocco", "ghana",
    "uganda", "tanzania", "zimbabwe", "sudan", "algeria", "tunisia", "libya", "senegal", "cameroon",
    "angola", "mozambique", "zambia", "botswana", "namibia", "rwanda",
    "pakistan", "bangladesh", "nepal", "bhutan", Joined("sri", "lanka"), "myanmar", "burma",
    "china", "japan", "north korea", "south korea", "vietnam", "thailand", "cambodia", "laos",
    "malaysia", "singapore", "indonesia", "philippines", "mongolia", "kazakhstan", "uzbekistan",
    "afghanistan", "iran", "iraq", "saudi arabia", "uae", _GSeq("u", "a", "e", ok=lambda g: g == "."),
    "dubai", "abu dhabi", "qatar",
    "kuwait", "oman", "bahrain", "israel", "turkey", "syria", "yemen", "lebanon",
    "united kingdom", "uk", "england", "scotland", "wales", "ireland", "france", "germany",
    "italy", "spain", "portugal", "netherlands", "belgium", "switzerland", "austria", "sweden",
    "norway", "denmark", "finland", "poland", "russia", "ukraine", "greece", "hungary", "romania",
    _S("czech", Opt("republic")), "iceland",
    # "u.s." must not be the start of a longer dotted word ("Umiong U.s.t", a
    # Focus Legacy producer group — all-PG run 2026-09-29)
    _S("united", "states", Opt(_S("of", "america"))), "usa", _EdgeUS(), "america", "canada",
    "mexico", "brazil", "argentina", "chile", "peru", "colombia", "venezuela", "cuba",
    "australia", "new zealand", "fiji",
    "africa", "europe", "south america", "north america", "antarctica",
    "abroad", "overseas", _S("foreign", _P("countr")), "another country", _S("other", _P("countr")),
    "outside india",
)

# A producer-group NAME the user labelled as one — "…named Rakkam China Banana
# Group", "members in Umden Manipur Banana Pg" — is not a place. Five stored
# Focus Legacy names hold a state or country word and were refused as
# out-of-area (all-PG run 2026-09-29). Masked only for the out-of-area test; a
# place written AFTER the name ("…producer groups in Assam") stays visible.
def _pg_gap(g: str) -> bool:
    r"""An optional '.' then optional whitespace (between the p and g of "pg")."""
    rest = g[1:] if g.startswith(".") else g
    return rest.strip() == ""


_GROUP_WORD = _A(
    _S("producer", W("group", "groups")), W("pg", "pgs", "group"),
    _GSeq("pg", "s", ok=lambda g: g == "."),
    _GSeq("p", _A(W("g", "gs"), _GSeq("g", "s", ok=lambda g: g == ".")), ok=_pg_gap),
)
_NAMED_GROUP_HEAD = Matcher(_GSeq(_GROUP_WORD, W("named", "called"),
                                  ok=lambda g: g.lstrip(".") != "" and g.lstrip(".").strip() == ""
                                  and len(g) - len(g.lstrip(".")) <= 1))
_MEMBERS_HEAD = Matcher(_S(W("member", "members"), Opt(W("are", "were", "is")), Opt("there"),
                           W("in", "of")))


def _edge_tail_end(t: str) -> int:
    """Where the trailing spaces / ? . ! / spaces tail starts (the end of a name before it)."""
    e = len(t)
    while e and t[e - 1].isspace():
        e -= 1
    while e and t[e - 1] in "?.!":
        e -= 1
    while e and t[e - 1].isspace():
        e -= 1
    return e


def _edge_after_space(t: str, i: int) -> int:
    """Index after the whitespace run at t[i:] (-1 when there is not at least one)."""
    j = i
    while j < len(t) and t[j].isspace():
        j += 1
    return j if j > i else -1


def _ends_with_group_word(c: str) -> bool:
    r"""`c` ends with producer group(s) / group / pg / p.g / p.g.s, optionally
    followed by a number ("… Group 2", "… pg-3"), after any spaces / dashes."""
    cands = [c]
    i = len(c)
    while i and c[i - 1].isdigit():
        i -= 1
    if i < len(c):
        d = c[:i]
        while d and (d[-1].isspace() or d[-1] == "-"):
            d = d[:-1]
        cands.append(d)
    return any(x and _edge_is_word_char(x[-1]) and _GROUP_TAIL.search(x) for x in cands)


_GROUP_TAIL = Matcher(Seq(_GROUP_WORD, END))


def _named_span(ql: str):
    """(start, end) of the name after "… group named / called", to the end."""
    for h in _NAMED_GROUP_HEAD.finditer(ql):
        s = _edge_after_space(ql, h.end())
        if s < 0:
            continue
        e = max(_edge_tail_end(ql), s)
        if "?" not in ql[s:e]:
            return s, e
    return None


def _members_span(ql: str):
    """(start, end) of "members in <name ending in a group word>", to the end."""
    for h in _MEMBERS_HEAD.finditer(ql):
        s = _edge_after_space(ql, h.end())
        if s < 0:
            continue
        e = max(_edge_tail_end(ql), s)
        name = ql[s:e]
        if "?" not in name and _ends_with_group_word(name):
            return s, e
    return None


def _place_after(name: str) -> bool:
    """in / from / of / at / within between spaces inside the name."""
    return any(w in ("in", "from", "of", "at", "within") for w in (" " + name + " ").split())


# A Meghalaya VILLAGE can carry a state's name: "MANIPUR" is a village in Umling
# block, Ri Bhoi (Focus Legacy all-villages run 2026-09-29). "… for X village" is
# a village name, not the state.
_VILLAGE_NAME_CHARS = "().'&- "


def _village_name_end(ql: str, s: int) -> int:
    """End of the shortest name at s (≤ 61 characters) followed by
    whitespace + "village" + a word end, or -1."""
    n = len(ql)
    if s >= n or not ((ql[s].isascii() and ql[s].isalnum()) or ql[s] in "(&"):
        return -1
    for e in range(s + 1, min(n, s + 61) + 1):
        if e > s + 1:
            ch = ql[e - 1]
            if not (_edge_is_word_char(ch) or ch in _VILLAGE_NAME_CHARS):
                return -1
        j = _edge_after_space(ql, e)
        if j >= 0 and ql[j:j + 7].lower() == "village" and (
                j + 7 == n or not _edge_is_word_char(ql[j + 7])):
            return e
    return -1


def _mask_village_names(ql: str) -> str:
    """"… in / for / of / at / to [the] X village": X replaced by a space."""
    out, last = [], 0
    toks = tokens(ql)
    for tok in toks:
        if tok.start < last or tok.low not in ("in", "for", "of", "at", "to"):
            continue
        q = _edge_after_space(ql, tok.end)
        if q < 0:
            continue
        starts = []
        if ql[q:q + 3].lower() == "the":
            q2 = _edge_after_space(ql, q + 3)
            if q2 >= 0:
                starts.append(q2)
        starts.append(q)
        for s in starts:
            e = _village_name_end(ql, s)
            if e < 0:
                continue
            j = _edge_after_space(ql, e)
            m_end = j + 7
            whole = ql[tok.start:m_end]
            out.append(ql[last:tok.start])
            out.append(whole.replace(ql[s:e], " "))
            last = m_end
            break
    out.append(ql[last:])
    return "".join(out)


# What a scheme / year chip appends after the name ("… Group for Focus Legacy
# across all financial years") — removed before the name spans are matched.
_CHIP_TARGET = _S(W("for", "under", "in", "across"), Opt("the"),
                  _A(_S("focus", "legacy"), _S("focus", "plus"), W("mgnrega", "pmayg"),
                      _GSeq("pmay", "g", ok=lambda g: g == "-"),
                      _S("cm", "elevate", Opt("legacy")),
                      W("cmss"), _S("all", "of", "meghalaya"),
                      _S("all", Opt("the"), Opt("financial"), "years", Opt("combined"))),
                  Opt("scheme"))


def _chip_gap(g: str) -> bool:
    r"""Between chips: optional spaces, an optional ',', then one or more spaces."""
    if g.strip() == "":
        return g != ""
    g2 = g.lstrip()
    return g2.startswith(",") and g2[1:] != "" and g2[1:].strip() == ""


class _EdgeChipLead(Node):
    """Only where the separator before this word is a chip separator."""

    def ends(self, ctx, i, caps):
        if i > 0 and _chip_gap(ctx.gap(i)):
            yield i, caps


class _EdgeChipRun(Node):
    """One or more chips, each after a chip separator, up to the last word."""

    def ends(self, ctx, i, caps):
        n = len(ctx.toks)
        for j, c2 in _CHIP_TARGET.ends(ctx, i, caps):
            if j == n:
                yield j, c2
            elif j > i and _chip_gap(ctx.gap(j)):
                yield from self.ends(ctx, j, c2)


_CHIP_SCOPE_RUN = Matcher(Seq(_EdgeChipLead(), _EdgeChipRun(), END))


def _strip_chip_tail(ql: str) -> str:
    """Drop trailing chips: ", for Focus Legacy across all financial years?"."""
    if _edge_tail_end(ql) != _last_token_end(ql):
        return ql
    h = _CHIP_SCOPE_RUN.search(ql)
    if h is None:
        return ql
    toks = tokens(ql)
    k = next(n for n, t in enumerate(toks) if t.start == h.start())
    return ql[:toks[k - 1].end]


def _last_token_end(t: str) -> int:
    toks = tokens(t)
    return toks[-1].end if toks else 0


def _mask_group_name(ql: str) -> str:
    ql = _strip_chip_tail(ql)
    ql = _mask_village_names(ql)
    for find in (_named_span, _members_span):
        sp = find(ql)
        if sp and not _place_after(ql[sp[0]:sp[1]]):
            return ql[:sp[0]] + " " + ql[sp[1]:]
    return ql


def _district_abbrev(t: str) -> bool:
    r"""EGH / W.K.H / S.W.G.H / E.W.K.H style district abbreviations, as whole
    words: one of e/w/n/s, then g/k/j, then h; or s, w, g/k, h; or e, w, k, h —
    each letter optionally followed by a '.'."""
    low = t.lower()
    n = len(low)
    shapes = (("ewns", "gkj", "h"), ("s", "w", "gk", "h"), ("e", "w", "k", "h"))
    for i in range(n):
        if i and _edge_is_word_char(low[i - 1]):
            continue
        for shape in shapes:
            j, ok = i, True
            for k, chars in enumerate(shape):
                if k and j < n and low[j] == ".":
                    j += 1
                if j < n and low[j] in chars:
                    j += 1
                else:
                    ok = False
                    break
            if ok and (j == n or not _edge_is_word_char(low[j])):
                return True
    return False


_MEGHALAYA_PLACE = _EdgeAnyOf(
    _M("meghalaya",
       _S(_A(W("east", "west", "north", "south"), _S("south", "west"), _S("eastern", "west")),
          W("garo", "khasi", "jaintia"), W("hill", "hills")),
       _S(W("garo", "khasi", "jaintia"), W("hill", "hills")),
       Joined("ri", "bhoi"), "ribhoi",
       W("shillong", "tura", "jowai", "nongpoh", "baghmara", "williamnagar", "resubelpara",
         "nongstoin", "mawkyrwat", "ampati", "khliehriat", "mairang", "nongthymmai",
         "mawsynram", "sohra", "dawki", "nartiang", "mawphlang"),
       _P("cherrapunj")),
    _GRule(_district_abbrev),
)


def _fy_digits(w: str) -> bool:
    """fy23, fy2023 ("fy" at a word start, then two or more digits glued on)."""
    w = w.lower()
    return w.startswith("fy") and len(w) >= 4 and w[2].isdigit() and w[3].isdigit()


def _two_digits_lead(w: str) -> bool:
    return len(w) >= 2 and w[0].isdigit() and w[1].isdigit()


# ── Strong scheme intent (any of the four) — skip every edge check below ───
_SCHEME_STRONG = [
    _M(W("mgnrega", "mnrega", "nrega", "mgnregs", "pmay", "pmayg", "awaas", "awas", "focusplus",
         "cmelevate", "piggery", "poultry", "sericulture", "motorcaravan", "applicant_category",
         "applicantcategory", "data_verified", "dataverified", "meghalayaone", "mbda", "tranche",
         "batch_label", "gramin", "mandays", "manday", "muster", "expenditure", "unskilled",
         "employment", "unspent", "utilisation", "utilization", "pucca", "kutcha", "district",
         "block", "village", "panchayat", "crore", "lakh", "meghalaya", "shillong", "tura", "jowai",
         "nongstoin", "williamnagar", "baghmara", "resubelpara", "mairang", "mawkyrwat",
         "khliehriat", "nongpoh", "ampati", "scheme", "subsidy", "convergence", "total", "compare",
         "comparison", "trend", "financialyear"),
       _P("disbursement", "wage", "household", "sanction", "release", "instal", "beneficiar",
          "eligib", "component", "getag", "jobcard"),
       Joined("focus", "plus"), _S("producer", _P("group")), Joined("cm", "elevate"), W("cmss", "scholarship", "scholarships"),
       "prime small enterprise", "prime tourism vehicle", "warehouse scheme",
       # CM Elevate programme names as typed: "What is the status distribution for Agro
       # Tourism Villa?" hit _OFF_TOPIC's "tourism" and was declined (UAT 2026-10-30, OFF-016)
       "agro tourism", "tourism vehicle", "agriculture response vehicle", "response vehicle",
       "cinema theatre", "green taxi", "goat farming", "any business venture", "sports and wellness",
       "indira awaas", _S("rural", _P("hous")), Joined("person", ("day", "days")),
       _S("job", _P("card")), Joined("semi", "skilled"), _S("material", _P("cost", "exp")),
       _A(W("100day", "100days"), _S("100", W("day", "days"))), _S("hundred", W("day", "days")),
       "labour budget",
       _S(W("house", "houses"), _A(_P("sanction", "complet", "built", "pending"),
                                    _S("in", _P("progress")))),
       Seq("ge", _P("tag")), "gram panchayat", _S("financial", "year"),
       Pred(_fy_digits), _S("fy", Pred(_two_digits_lead)), Pred(_edge_year),
       # "FY'25" on its own: the apostrophe is not whitespace, so _S missed it and a
       # bare "FY'25" follow-up was answered "didn't quite catch that" (2026-10-26).
       _GSeq("fy", Pred(_two_digits_lead), ok=lambda g: g == "'"),
       _S(W("garo", "khasi", "jaintia"), W("hill", "hills")), Joined("ri", "bhoi"),
       "how many", _S("by", W("district", "block", "village", "year")), "completion rate"),
    _GRule(_focus_plus),
]

# ── Meta-conversation — about the chat itself, not the schemes ──────────────
# These carry no scheme keyword by nature; let them reach the pipeline (a full
# meta resolver is a pipeline TODO — for now they route like any other question).
# ── "Can you actually answer?" — a capability question, not a request ───────
# A user checking what the assistant is good for before committing to a real
# question: "are you able to give answers?", "can you answer my questions?",
# "if I ask about Meghalaya schemes, will you be able to answer?". These carry
# no scheme vocabulary of their own (or name the schemes only in passing, as
# the SUBJECT of the capability question rather than as something to query), so
# before this they took one of two wrong paths, both reported 2026-09-17:
#   * no domain word at all -> the step-6 whitelist gate -> the blunt "I can
#     only answer questions about those schemes" bounce, which reads as a
#     refusal to a question that was ABOUT that very capability; or
#   * the words "Meghalaya"/"schemes" present -> straight down the DATA path
#     -> the "Which scheme does your question concern?" pause, asking the user
#     to pick a scheme for a question that isn't asking for any scheme's data.
# The honest reply to all of them is a plain yes plus what's covered, so they
# get their own bank rather than being bent into _IDENTITY (which answers "who
# are you", a different question) or left to the LLM.
_CAPABILITY = [
    # "can/will/are you able to ... answer/help/tell/give"
    _M(_S(W("can", "could", "will", "would", "are"), W("you", "u"), Opt("be"), Opt(_S("able", "to")),
          W("answer", "reply", "respond", "help", "assist", "tell", "give", "provide", "handle", "do"))),
    _M(_S(W("are", "r"), W("you", "u"), W("able", "capable"))),
    _M(_S(W("do", "does"), W("you", "u"), W("know", "have", "support", "cover", "handle"))),
    _M(_S("is", "it", "possible", Opt(_S("for", W("you", "u"))), "to",
          W("answer", "help", "get", "find", "know"))),
    _M(_S(W("you", "u"), W("can", "could"), W("answer", "help", "tell", "give", "provide"))),
    _M(_S("what", _pl("kind", "type", "sort"), "of", W("question", "questions", "queries", "things",
                                                       "data"))),
    _M(_S("can", "i", W("ask", "get", "know", "find", "query"))),
    _M(_S("how", W("accurate", "reliable", "correct", "trustworthy"), W("are", "is"))),
]

# A capability phrase wrapped around an ACTUAL request — "can you tell me the
# total person-days in 2023-24?", "can you give me houses completed by
# district?" — is a real question, not a capability check. Any concrete metric,
# aggregate word, place or year makes it one, so it must reach the pipeline
# normally. Kept narrow on purpose: the bare "questions"/"answers"/"data" of a
# genuine capability check are NOT in here.
def _fy20(w: str) -> bool:
    """fy2023 ("fy", "20", then two digits, with no space)."""
    w = w.lower()
    return len(w) == 6 and w.startswith("fy20") and w[4:].isdigit()


def _y20(w: str) -> bool:
    return len(w) == 4 and w.startswith("20") and w.isdigit()


_ASKS_FOR_A_FIGURE = _M(
    # "tell me / explain / what is ... <scheme>" is a real KNOWLEDGE request,
    # even though it opens with a capability phrase ("can you tell me about
    # MGNREGA"). The scheme is the SUBJECT being asked about, not the topic of
    # a can-you check.
    Seq(W("tell", "explain", "describe"), _GCharGap(30, "?"),
        _A(W("mgnrega", "mnrega", "nrega", "pmay", "awaas", "awas", "focus", "focusplus",
              "cmelevate", "focuslegacy", "cmss"),
            Joined("cm", "elevate"), Joined("producer", ("group", "groups")))),
    _A(W("total", "sum", "count", "average", "avg", "expenditure", "spend", "spending", "spent",
          "wage", "wages", "house", "houses", "applications", "application", "breakdown", "compare",
          "comparison", "highest", "lowest"),
        _P("sanction", "complet", "disburs", "beneficiar", "eligib"),
        _A("how many", "how much", "number of", "list of", "who can apply"),
        Joined("person", ("day", "days")), Joined("job", ("card", "cards")),
        _S("top", Pred(lambda w: len(w) == 1 and w.isdigit())),
        _S("by", W("district", "block", "village", "year")),
        Joined("district", "wise"), Joined("block", "wise"),
        _S(W("document", "documents"), "required"),
        _S("how", W("do", "to"), "i", "apply"),
        Pred(_fy20), _S("fy", Pred(_y20)), Pred(_y20)),
)

_META_CONV = [
    _M(_S(W("my", "your"), W("first", "last", "previous", "prior", "earlier"),
          _P("question", "query", "message", "answer"))),
    _M(_S(_sfx("what"), "did", W("i", "you"), _P("ask", "say", "answer", "tell", "reply"))),
    _M(_S(_sfx("what"), "was", W("my", "your", "the"),
          _P("question", "answer", "response", "last", "first"))),
    _M(_S(_A(_sfx("repeat", "rephrase", "restate"), _S(_sfx("say"), "again")),
          W("my", "the", "that", "your", "it"))),
    _M(_S(_A(_sfx("summarise", "summarize"), _S(_sfx("summary"), "of")), W("our", "this", "the"),
          _P("conversation", "chat", "discussion"))),
    _M(_S(_sfx("what"), "have", W("we", "i"), _P("discussed", "talked", "covered", "asked"))),
]


def _edge_together(t: str) -> bool:
    """"what" / "how much" then, within 20 characters, together / combined /
    altogether / in total (the last word ending at a word edge)."""
    low = t.lower()
    n = len(low)
    ends = []
    i = low.find("what")
    while i >= 0:
        ends.append(i + 4)
        i = low.find("what", i + 1)
    i = low.find("how")
    while i >= 0:
        j = _edge_after_space(low, i + 3)
        if j >= 0 and low.startswith("much", j):
            ends.append(j + 4)
        i = low.find("how", i + 1)
    for e in ends:
        for s in range(e, min(n, e + 20) + 1):
            if "\n" in low[e:s]:
                break
            for word in ("together", "combined", "altogether"):
                f = s + len(word)
                if low.startswith(word, s) and (f == n or not _edge_is_word_char(low[f])):
                    return True
            if low.startswith("in", s):
                j = _edge_after_space(low, s + 2)
                if j >= 0 and low.startswith("total", j) and (
                        j + 5 == n or not _edge_is_word_char(low[j + 5])):
                    return True
    return False


_PRONOUNS = ("it", "its", "that", "those", "these", "them", "they", "this")


def _edge_wh_pronoun(t: str) -> bool:
    """A wh-word first, a pronoun within 45 characters, then at most 15 more
    characters before trailing spaces / '?' (the wh-word and pronoun whole words)."""
    if not t or not _edge_is_word_char(t[0]):
        return False
    toks = tokens(t)
    if not toks or toks[0].low not in ("how", "why", "when", "where", "what", "who"):
        return False
    e0 = toks[0].end
    for k in range(1, len(toks)):
        s = toks[k].start
        if s - e0 > 45 or "\n" in t[e0:s]:
            break
        ends = []
        low = toks[k].low
        if low in _PRONOUNS:
            ends.append(toks[k].end)
        if low == "this" and k + 1 < len(toks) and toks[k + 1].low == "one" and _g_space(t[toks[k].end:toks[k + 1].start]):
            ends.append(toks[k + 1].end)
        if low == "the" and k + 1 < len(toks) and toks[k + 1].low == "same" and _g_space(t[toks[k].end:toks[k + 1].start]):
            ends.append(toks[k + 1].end)
        for e in ends:
            a = _edge_rstrip(t[e:], "?")
            if len(a) <= 15 and "\n" not in a:
                return True
    return False


# ── Follow-up fragments — reference a prior answer via pronouns / arithmetic ──
# No scheme keyword, but they only mean something in context — the pipeline's
# follow-up rewrite handles them, so never block these here.
_COMPARATIVE = ("more", "most", "less", "least", "higher", "highest", "lower", "lowest", "bigger",
                "biggest", "smaller", "smallest", "greater", "greatest", "max", "min")
_FOLLOWUP = [
    _M(Seq(W("sum", "total", "add", "plus", "combine", "combined", "altogether"), _GCharGap(30, "\n"),
           W("both", "them", "these", "those", "two", "it"))),
    _M(Seq(W("both", "them", "these", "those"), _GCharGap(30, "\n"),
           W("sum", "total", "add", "added", "plus", "combine", "combined", "together", "altogether"))),
    _GRule(_edge_together),
    _M(Seq(W("difference", "gap", "subtract", "minus"), _GCharGap(30, "\n"),
           _A(W("both", "them", "these", "those", "two"), _S("the", "other")))),
    _M(_S(_sfx("which"), _A(W("is", "are", "has"), _S("one", "is")), Opt("the"), W(*_COMPARATIVE))),
    _M(_S(_sfx("more", "less", "higher", "lower", "bigger", "smaller", "greater"), Opt("of"),
          Opt("the"), W("two", "both", "them", "these"))),
    _M("in this", "of these", "among these",
       _S("from", _A(W("this", "above", "that"), _S("the", "above")))),
    _EdgeLead(_A("what about", "how about", "and", "also", "plus", "what of", "what if", "now",
                 "then"), _S(W("ok", "okay"), "and"), upto=45),
    _EdgeLead(_S(Opt("now"), W("show", "give", "tell", "calculate", "compute", "find", "sort", "order",
                               "rank", "list"), Opt("me"),
                 _A(W("both", "them"), _S("the", W("total", "sum", "combined")),
                     _S(W("by", "for"), ANY)))),
    _EdgeWhole(_S(W("add", "sum", "combine", "total"),
                  _A(_S(W("them", "both", "those", "these"), Opt("up")),
                      W("themup", "bothup", "thoseup", "theseup"))), tail="?"),
    _EdgeLead(_S(W("and", "but", "so"), W("the", "what", "for", "in", "by", "about")), upto=45),
    _GRule(_edge_wh_pronoun),
    _EdgeLead(W("explain", "why", "reason", "elaborate", "expand", "clarify", "correct", "right",
                "wrong"), _A("is this", "is that", "you gave", "you said")),
    _M(_S("is", W("this", "that", "it"), W("correct", "right", "wrong", "true", "false", "accurate",
                                          "sure"))),
    _M(_S("you", W("gave", "said", "told", "mentioned", "showed"))),
    _EdgeLead(W("yes", "no", "correct", "wrong", "exactly"), _S("not", "right"),
              _S(_THAT_S, W("right", "wrong", "correct", "incorrect"))),
]

# ── Domain whitelist — a question with NONE of these words is off-topic ─────
# A plain string is found ANYWHERE in the lower-cased text (a substring, as
# before: "beneficiar" matches "beneficiaries"; "focus" also covers "focus+",
# found anywhere); the word-bounded entries are word matchers.
_DOMAIN_WORDS = [
    # scheme names + synonyms
    "mgnrega", "mnrega", "nrega", "pmay", "pmayg", "pmay-g", "awaas", "awas",
    "indira awaas", "employment guarantee", "rural housing", "rural employment",
    "focus plus", "focus", "focusplus", "focus-plus", "producer group",
    "focus legacy", "focuslegacy", "producer groups", "pg id", "pg member",
    "pg-focus", "pg-lamp",
    # "PG" is Focus Legacy's everyday shorthand — the UI's own starter chips say
    # "Top 5 PGs" — but only the SPELLED-OUT forms were whitelisted, so
    # "is there any pg group with name sakania?" had no domain word and was
    # bounced as off-topic while the identical question with "producer group"
    # went through (reported 2026-09-23). Word-boundary, never a bare "pg":
    # plain entries are substring checks, and a loose "pg" matches inside
    # "upgrade", "upgrading" and "mpg".
    _M(W("pg", "pgs")),
    "cm elevate", "cmelevate", "cm-elevate", "piggery", "poultry", "warehouse scheme",
    # CM Elevate Legacy's own vocabulary (lender and desanction fields).
    "lifcom", "desanction", "loan entity", "lender",
    "sericulture", "motorcaravan", "prime small enterprise", "prime tourism vehicle",
    "any business venture", "cinema theatre", "sports and wellness", "green taxi",
    "meghalayaone", "mbda", "meghalaya basin development", "farmer cash benefit",
    # Focus Plus batch labels and its stored tranche spelling ("Tranch 4"): "Break
    # down the 12.5K batch by status" / "Give me the status split of 12.5K batch"
    # had no domain word and got the "only those schemes" reply (FOCUS-019
    # re-test 2026-10-22, KI-360).
    "12.5k", "12.5 k", _M(W("93k"), _GSeq("93", "k", ok=lambda g: g == " ")), "tranch",
    # "I want to know about farmers getting money" is a Focus question (live 2026-10-18)
    "farmer",
    # Scheme terms an officer asks the meaning of: "What is DBT?" had no domain
    # word and got the "only schemes" reply (user report 2026-10-14).
    _M(W("dbt", "secc")), "gram sabha", "muster roll", "social audit", "ombudsperson",
    "awaas",
    "cmss",
    "cm scholarship",
    "cm scholarship scheme",
    "chief minister scholarship",
    "chief minister's scholarship",
    "chief minister's scholarship scheme",
    "chief minister scholarship scheme meghalaya",
    "cmss meghalaya",
    "meghalaya cm scholarship",
    "meghalaya cm scholarship scheme",
    "cm scholarship scheme 2025",
    "state scholarship",
    "post matric state scholarship",
    "rs 6000 scholarship",
    "6000 scholarship",
    "chief minister scholarship scheme 2025", _M(W("pfms", "shg", "shgs")), "self help group", "self-help group", "rozgar sahayak",
    "geo-tagg", "c&rd", "direct benefit transfer",
    "benefit",
    # work / employment
    "beneficiar", "job card", "muster", "person day", "personday", "person-day",
    "manday", "man-day", "wage", "unskilled", "semi-skilled", "material cost",
    "100 day", "hundred day", "household", "worker", "labour", "labor",
    "employment", "works", "asset", "labour budget", "women employment",
    # "Persons employed in Dalu constituency", "people who got work in Ampathi
    # assembly constituency" had no domain word and were refused as off-topic
    # (hierarchy matrix run 2026-10-14)
    _M(W("employed"), _GSeq("got", W("work", "employment", "job", "jobs"), ok=lambda g: g == " "),
       _P("constituenc")), "applicant", "application",
    "disburse", "remitt", _M(W("member", "members")),
    # housing
    "house", "housing", "dwelling", "pucca", "kutcha", "sanction", "geotag",
    "geo-tag", "geo tag", "installment", "instalment", "tranche", "completion certificate",
    "house status", "in progress", "in-progress",
    # geography
    "meghalaya", "district", "block", "village", "panchayat", "gram panchayat",
    "garo hills", "khasi hills", "jaintia hills", "ri bhoi", "ri-bhoi",
    "shillong", "tura", "jowai", "nongstoin", "williamnagar", "baghmara",
    "resubelpara", "mairang", "mawkyrwat", "khliehriat", "nongpoh", "ampati",
    "east khasi", "west khasi", "south west khasi", "east jaintia", "west jaintia",
    "east garo", "west garo", "north garo", "south garo", "south west garo",
    # finance
    "expenditure", "amount released", "amount sanctioned", "amount pending",
    "fund", "funds", "released", "pending", "unspent", "utilisation", "utilization",
    "crore", "lakh", "rupee", "budget", "disburs", "payment", "spend", "spent", "cost",
    # admin / rules
    "eligib", "eligible", "apply", "application", "documents", "aadhaar", "aadhar",
    "registration", "scheme", "component", "guidelines", "subsidy", "convergence",
    "financial year", "physical progress", "target", "achievement",
    "assistance", "unit cost", "per house", "wage rate", "notified wage",
    "secc", "socio economic", "priority list", "waitlist", "gram sabha",
    "social audit", "work demand", "demand for work", "payment delay",
    "bpl", "landless", "homeless", "scheduled caste", "scheduled tribe",
    "sc/st", "differently abled", "widow", "minority",
    # analytics
    "count", "total", "how many", "number of", "show", "list", "compare",
    "comparison", "trend", "breakdown", "break down", "breakup", "break-up", "status wise", "status-wise",
    "by status", "distribution", "by district", "by block",
    "by year", "average", "percentage", "per cent", "percent", "rate",
    "completion rate", "top ", "highest", "lowest", "most", "least",
    "chart", "graph", "report", "data", "statistic", "summary",
    # time — any 4-digit year or FY-range form (in OR out of the data window, so
    # an out-of-bound year like "1999-20" reaches the pipeline's year guard
    # instead of being bounced here as off-topic)
    _M(Pred(_edge_year)), _GRule(_edge_fy_range),
    "year", "month", "quarter", "period", "fiscal",
]




# ── Response templates ─────────────────────────────────────────────────────
STARTERS = [
    "Total MGNREGA person-days in Meghalaya in 2023-24",
    "PMAY-G houses completed by district",
    "Focus Plus payments by batch",
    "How many CM Elevate applications are on hold?",
    "Who is eligible for PMAY-G?",
]

# Which edge replies carry the starter chips (a plain "thanks" / "bye" should not).
_STARTER_KINDS = {"greeting", "identity", "capability", "money_advice", "profanity", "silly",
                  "off_topic", "confused", "personal_request"}

# One consistent line for every "that's not something I do" case — an unrelated
# topic, a general-knowledge question, or a place outside Meghalaya. Callers past
# the edge layer (the pipeline's OutOfScope handler) reuse it via out_of_scope().
_OUT_OF_SCOPE_REPLY = (
    "I'm Megh One AI, the assistant for Meghalaya's MGNREGA, PMAY-G, Focus Plus, CM Elevate, Focus Legacy (producer groups), CM Elevate Legacy (sanctions and disbursements), and CMSS (Chief Minister's Scholarship Scheme, a flat Rs 6,000 annual state scholarship for eligible students). I can only answer questions about those schemes and their data in Meghalaya — not other topics, other states, or places outside Meghalaya."
)

_RESPONSES = {
    "greeting": (
        "Hello! I answer questions about Meghalaya's MGNREGA, PMAY-G, Focus Plus, "
        "CM Elevate, Focus Legacy, CM Elevate Legacy and CMSS data — person-days, expenditure, "
        "houses sanctioned and completed, Focus Plus disbursements, CM Elevate applications "
        "by scheme, Focus Legacy producer-group payments, CM Elevate Legacy subsidy and "
        "loans disbursed, CMSS scholarship applications and payments, district and block "
        "breakdowns — and general questions about how the schemes work."
    ),
    "identity": (
        "I can help you with Meghalaya's MGNREGA, PMAY-G, Focus Plus, CM Elevate, Focus Legacy, CM Elevate Legacy and CMSS schemes — things like person-days and wage expenditure, houses sanctioned and completed, Focus Plus disbursements, CM Elevate applications, Focus Legacy payments to producer groups, CM Elevate Legacy sanctions and disbursements, CMSS scholarship applications and disbursements, district and block breakdowns, and eligibility or how-to-apply questions for any of these schemes. Just ask in plain language."
    ),
    # Answers the question that was actually asked — "can you?" — with a plain
    # yes first, then what that covers. Deliberately NOT the _OUT_OF_SCOPE_REPLY
    # ("I can only answer...", which reads as a refusal here) and not the
    # "which scheme?" pause (nothing is being queried yet).
    "capability": (
        "Yes — that's exactly what I'm here for. I can answer questions about "
        "Meghalaya's MGNREGA, PMAY-G, Focus Plus, CM Elevate, Focus Legacy, CM "
        "Elevate Legacy and CMSS schemes, in two ways: the actual data (person-days, expenditure, houses "
        "sanctioned and completed, Focus Plus disbursements, CM Elevate applications, "
        "Focus Legacy producer-group payments, CM Elevate Legacy disbursements, CMSS scholarships — by "
        "district, block, village or "
        "financial year), and how the schemes work (eligibility, benefits, documents, "
        "how to apply). Ask in plain language and I'll take it from there."
    ),
    # Personal financial advice. Says plainly that this is not what the
    # assistant does — a generic "I can only answer questions about those
    # schemes" never acknowledges that the question was about investing, and
    # reads as if the request was simply not understood.
    "money_advice": (
        "I can't advise on investing or saving your own money — I'm not a financial "
        "adviser, and that's outside what I do. I'm Megh One AI: I answer questions "
        "about Meghalaya's MGNREGA, PMAY-G, Focus Plus, CM Elevate, Focus Legacy, CM Elevate Legacy and "
        "CMSS schemes — who "
        "is eligible, what benefits they pay, how to apply, and the actual figures by "
        "district, block or year. If you'd like to know what any of those schemes "
        "offers, ask away."
    ),
    # A first-person request for money or a loan. Says plainly that the
    # assistant cannot give, lend or approve money, then where support exists.
    # Scheme facts only as the SME docs state them (CM Elevate Legacy records
    # subsidy and loans; MGNREGA pays wages for work; Focus Plus is a cash
    # benefit to farmers, not a loan).
    "personal_request": (
        "I'm sorry you're in a difficult spot. I can't give, lend or approve money — I'm "
        "Megh One AI, an assistant that reports Meghalaya's scheme data and explains how "
        "the schemes work; I can't process applications or payments. If you need support, "
        "these schemes may help: MGNREGA (paid work for rural households), CM Elevate "
        "(support for starting or growing an enterprise, with subsidy and bank or LIFCOM "
        "loans), PMAY-G (rural housing) and Focus Plus (a cash benefit for farmers — not a "
        "loan). Ask me \"who is eligible for CM Elevate?\" or \"how do I apply for "
        "MGNREGA?\" and I'll explain."
    ),
    "thanks": ("You're welcome. Ask me anything else about MGNREGA, PMAY-G, Focus Plus, CM Elevate, Focus Legacy, CM Elevate Legacy, or CMSS (Chief Minister's Scholarship Scheme) in Meghalaya."),
    "goodbye": "Thanks for using the Meghalaya scheme assistant. Come back any time.",
    "profanity": (
        "I'm here to help. I can answer MGNREGA, PMAY-G, Focus Plus, CM Elevate and "
        "Focus Legacy questions for Meghalaya — for example \"MGNREGA expenditure by "
        "district in 2024-25\" or \"documents needed to apply for PMAY-G\"."
    ),
    "silly": _OUT_OF_SCOPE_REPLY,
    "off_topic": _OUT_OF_SCOPE_REPLY,
    # Says plainly that it won't help — and why — then points at the lawful
    # help it CAN give, instead of an unrelated scheme answer.
    "harmful": (
        "I can't help with that — it's illegal and could cause real harm. I'm Megh One "
        "AI, and I only help with Meghalaya's government schemes. If money is the "
        "problem, there are lawful options I can explain: paid work under MGNREGA, "
        "housing help under PMAY-G, farm support under Focus Plus and Focus Legacy, or "
        "business support under CM Elevate."
    ),
    "confused": (
        "No problem. I can answer things like the count of PMAY-G houses completed "
        "in a district, total MGNREGA wage expenditure for a year, Focus Plus payments "
        "by batch, how many CM Elevate applications are on hold, how much Focus Legacy "
        "paid out to producer groups, or the eligibility criteria for a scheme."
    ),
}


# ── Scheme-specific capability reply ────────────────────────────────────────
# "can I get MGNREGA data?" names ONE scheme, so answering with the full
# four-scheme rundown — and then suggesting PMAY-G / Focus Plus / CM Elevate
# starters — reads as if the question wasn't listened to (reported 2026-09-17).
# When exactly one scheme is named, both the sentence and the chips narrow to
# it; a question naming none, or several, keeps the general reply unchanged.
def _edge_ws_dash(g: str) -> bool:
    return all(c.isspace() or c == "-" for c in g)


class _EdgeCMElevate:
    """CM Elevate, not when qualified as the Legacy dataset: not right after
    "legacy " and not followed by any spaces / dashes then legacy / disbursement(s)."""

    def search(self, text):
        t = text or ""
        low = t.lower()
        for h in _CM_ELEVATE.finditer(t):
            if low[:h.start()].endswith("legacy "):
                continue
            rest = low[h.end():]
            j = 0
            while j < len(rest) and (rest[j].isspace() or rest[j] == "-"):
                j += 1
            nxt = tokens(rest[j:])
            if (nxt and nxt[0].start == 0
                    and nxt[0].low in ("legacy", "disbursement", "disbursements")):
                continue
            return h
        return None


_CM_ELEVATE = Matcher(_A(Joined("cm", "elevate"), W("cmelevate")))
_SCHEME_ALIASES = {
    "MGNREGA": _M(W("mgnrega", "mnrega", "nrega")),
    "PMAY-G": _M(W("pmay", "pmayg", "awaas", "awas")),
    "Focus Plus": _EdgeAnyOf(_M(Joined("focus", "plus"), W("focusplus")), _GRule(_focus_plus)),
    # Not when qualified as the Legacy dataset — that is its own entry below.
    "CM Elevate": _EdgeCMElevate(),
    "CM Elevate Legacy": _M(
        _GSeq(_A(Joined("cm", "elevate"), W("cmelevate")),
              W("legacy", "disbursement", "disbursements"), ok=_edge_ws_dash),
        W("cmelevatelegacy", "cmelevatedisbursement", "cmelevatedisbursements"),
        _GSeq("legacy", _A(Joined("cm", "elevate"), W("cmelevate")), ok=_edge_ws_dash),
        Joined("elevate", "legacy")),
    # Qualified spellings only — a bare "focus" names neither Focus scheme on its
    # own (see pipeline._is_ambiguous_focus), so narrowing on it would pick one
    # of the two at random.
    "Focus Legacy": _M(Joined("focus", "legacy"), Joined("legacy", "focus"),
                       Joined("producer", ("group", "groups"))),
    "CMSS": _M(W("cmss", "scholarship", "scholarships")),
}

# What each scheme actually holds — the data side and the knowledge side — so
# the narrowed reply stays concrete instead of a generic "yes I cover it".
_SCHEME_CAPABILITY = {
    "MGNREGA": (
        "person-days, households and persons employed, job cards, 100-day "
        "completions, and wage / material / total expenditure — by district, "
        "block, village, assembly constituency or financial year"
    ),
    "PMAY-G": (
        "houses sanctioned, completed and in progress, construction stage, "
        "sanctioned and released amounts, and installments — by district, "
        "block, village or financial year"
    ),
    "Focus Plus": (
        "disbursements and amounts paid, beneficiaries, batches and tranches, "
        "bank-wise payments, and the 12.5K cohort's status / gender / "
        "occupation splits — by district, block, village or financial year"
    ),
    "CM Elevate": (
        "applications across its 15 sub-schemes (piggery, poultry, tourism "
        "vehicles, small enterprise and more), application mode, workflow "
        "level and verification status — by district, block or sub-scheme"
    ),
    "Focus Legacy": (
        "payments to producer groups, the groups themselves and their member "
        "counts, amount remitted (Rs 5,000 per member), producer group type, "
        "the product each group works on, and bank-wise payments — by district, "
        "block, village or financial year"
    ),
    "CM Elevate Legacy": (
        "CM-ELEVATE sanction and disbursement records across 13 schemes — amounts "
        "sanctioned, subsidy and loans disbursed, the share of the sanction paid out, "
        "lender (Bank / LIFCOM) and desanctioned records — by scheme, district, block, "
        "village or financial year (FY 2024-25 and 2025-26)"
    ),
    "CMSS": (
    "applications and students paid, amount disbursed (Rs 6,000 flat), and geography breakdowns by district, block, village, constituency or region — by financial year (FY 2025-26 only)"
),
}

_SCHEME_STARTERS = {
    "MGNREGA": [
        "Total MGNREGA person-days in Meghalaya in 2023-24",
        "MGNREGA expenditure by district",
        "How many MGNREGA job cards were issued in Ri Bhoi?",
        "Which block recorded the most MGNREGA person-days?",
        "Who is eligible for MGNREGA?",
    ],
    "PMAY-G": [
        "PMAY-G houses completed by district",
        "How many PMAY-G houses were sanctioned in 2023-24?",
        "PMAY-G amount released by district",
        "How many PMAY-G houses are still in progress?",
        "Who is eligible for PMAY-G?",
    ],
    "Focus Plus": [
        "Focus Plus payments by batch",
        "Total Focus Plus amount disbursed by district",
        "How many Focus Plus beneficiaries are there?",
        "Focus Plus disbursement by tranche",
        "Who is eligible for Focus Plus?",
    ],
    "CM Elevate": [
        "How many CM Elevate applications are on hold?",
        "CM Elevate applications by sub-scheme",
        "Which district has the most CM Elevate applications?",
        "CM Elevate applications by district",
        "Who is eligible for CM Elevate?",
    ],
    "Focus Legacy": [
        "How many producer groups were paid under Focus Legacy?",
        "Total Focus Legacy amount disbursed by district",
        "How many PG members were covered under Focus Legacy?",
        "Which products do Focus Legacy producer groups work on?",
        "What is the main objective of FOCUS?",
    ],
    "CM Elevate Legacy": [
        "What is the total amount disbursed under CM Elevate Legacy?",
        "CM Elevate Legacy disbursement by district",
        "CM Elevate Legacy records by scheme",
        "CM Elevate Legacy loans by lender",
        "CM Elevate Legacy records by financial year",
    ],
    "CMSS": [
        "How many CMSS scholarship applications are there?",
        "CMSS students paid by district",
        "Total CMSS amount disbursed in 2025-26",
        "Which block has the most CMSS applications?",
        "Who is eligible for CMSS?",
    ],
}


def _named_scheme(question: str) -> "str | None":
    """The single scheme named in `question`, or None when it names none or
    more than one (both of which want the general four-scheme reply)."""
    hits = [name for name, word_matcher in _SCHEME_ALIASES.items() if word_matcher.search(question or "")]
    return hits[0] if len(hits) == 1 else None


def _capability_reply(scheme: str) -> str:
    return (
        f"Yes — I can answer {scheme} questions for Meghalaya. That covers the "
        f"actual data ({_SCHEME_CAPABILITY[scheme]}), and how the scheme works "
        "(eligibility, benefits, documents, how to apply). Ask in plain language "
        "and I'll take it from there."
    )


# A yes/no question deserves a yes/no answer. "will you answer for West Bengal
# data?" / "can you give Assam figures?" / "do you cover Delhi?" are all asking
# whether the assistant CAN — so the reply has to open with "No", not with a
# statement of scope that leaves the question hanging.
_YES_NO_ASK = Matcher(Seq(START, W("can", "could", "will", "would", "do", "does", "are", "is",
                                  "shall", "may")))


# Places whose natural spelling isn't plain Title Case, plus the "not a place"
# scopes (_OUT_OF_AREA also matches "all india" / "nationwide", which name a
# COVERAGE rather than a state — "I don't hold data for All India" reads wrong).
_PLACE_SPELLING = {
    "usa": "the USA", "us": "the US", "uk": "the UK", "uae": "the UAE",
    "ncr": "the NCR", "j&k": "Jammu & Kashmir",
}
_NATIONAL_SCOPE = {
    "all india", "all-india", "pan india", "pan-india", "nationwide",
    "national", "whole country", "entire country", "across india", "india",
}


def _title_place(place: str) -> str:
    """'west bengal' -> 'West Bengal'; keeps acronyms and known spellings."""
    p = str(place).strip().lower()
    if p in _PLACE_SPELLING:
        return _PLACE_SPELLING[p]
    return " ".join(w if w.isupper() else w.capitalize() for w in str(place).split())


def _out_of_area_reply(question: str, place: str) -> str:
    """The off-topic reply, but naming the place the user actually asked about
    and answering a yes/no question as one."""
    national = str(place).strip().lower() in _NATIONAL_SCOPE
    name = _title_place(place)
    if national:
        # "all India" / "nationwide" is a coverage, not a place — phrase it as
        # a scope the assistant doesn't have rather than a missing state.
        lead = ("No — I can't give all-India figures. " if _YES_NO_ASK.match(question or "")
                else "I don't hold all-India figures. ")
    elif _YES_NO_ASK.match(question or ""):
        lead = f"No — I can't answer questions about {name}. "
    else:
        lead = f"I don't hold any data for {name}. "
    return (
        lead + "I'm Megh One AI, and I only cover Meghalaya's MGNREGA, PMAY-G, Focus Plus, CM Elevate, Focus Legacy, CM Elevate Legacy and CMSS (Chief Minister's Scholarship Scheme) — the data is Meghalaya's alone, so I have nothing for other states or countries. If there's something you'd like to know about these seven schemes in Meghalaya, I can help with that."
    )


def _NAMES_UNSUPPORTED_SCHEME(question: str) -> bool:
    """True when the text names a real government scheme this assistant doesn't
    hold (PM-KISAN, Ujjwala, Jal Jeevan, …).

    The catalogue of those lives in app.pipeline (_UNSUPPORTED_SCHEME), which
    imports this module — so the import is done lazily, inside the call, to
    avoid a cycle at module load. Any failure degrades to False, i.e. exactly
    the behaviour before this check existed."""
    try:
        from app import pipeline as _pipeline

        return _pipeline._unsupported_scheme_named(question) is not None
    except Exception:  # noqa: BLE001 — never let this break edge detection
        return False


def _edge(kind: str, question: str = "", place: str = "") -> dict:
    out = {"type": kind, "response": _RESPONSES[kind]}
    # A capability question that names ONE scheme gets that scheme's answer and
    # that scheme's suggestions, rather than the whole catalogue.
    scheme = _named_scheme(question) if kind == "capability" else None
    if scheme:
        out["response"] = _capability_reply(scheme)
    # An out-of-area question gets the place it named, and a direct "No" when
    # it was phrased as a yes/no question.
    if place:
        out["response"] = _out_of_area_reply(question, place)
    # Any other refusal asked as a yes/no question ("will you answer questions
    # about cricket?", "do you know about bitcoin?") gets the "No" prefixed, so
    # the reply answers what was asked before stating what IS covered.
    elif kind in ("off_topic", "silly") and _YES_NO_ASK.match(question or ""):
        out["response"] = "No — that's outside what I cover. " + out["response"]
    if kind in _STARTER_KINDS:
        out["suggestions"] = list(_SCHEME_STARTERS[scheme]) if scheme else list(STARTERS)
    return out


def out_of_scope() -> dict:
    """The canonical off-topic / out-of-area reply ("I'm Megh One AI …"), for
    callers past the edge layer — e.g. the pipeline raising OutOfScope after it
    resolves a district/block that is not in Meghalaya."""
    return _edge("off_topic")


def is_personal_request(question: str) -> bool:
    """A first-person request for money or a loan ("give me five thousand
    loan for me"), see _PERSONAL_REQUEST."""
    ql = (question or "").lower()
    return any(p.search(ql) for p in _PERSONAL_REQUEST)


def _has_domain_word(ql: str) -> bool:
    """Any _DOMAIN_WORDS entry in the lower-cased text (plain strings as substrings)."""
    return any((w in ql) if isinstance(w, str) else w.search(ql) for w in _DOMAIN_WORDS)


# A misspelt scheme word is still a scheme word. "gender wise breakup the
# applicxations" had no exact domain word, so step 6 answered "I don't have
# information about that" in a new chat, while the same question spelt right
# got the "which scheme?" picker (user report 2026-10-19). The rephraser
# already fixes such typos (_vocab_typo) — but it runs after this gate, so the
# gate never let the question reach it. Tighter than the rephraser (ratio >= 88,
# seven letters or more, same first letter): measured against a 15K-word English
# list, ratio 85 let 56 real words through ("german" ~ gender, "distinct" ~
# district); this lets 9 (release, document, beneficial …) and still catches
# 23 of 24 realistic typos. A word it lets through only reaches the pipeline,
# whose own router still declines a non-scheme question.
_DOMAIN_TYPO_VOCAB = frozenset(
    {w for w in _DOMAIN_WORDS if isinstance(w, str) and w.isalpha() and len(w) >= 6}
    | {w + "s" for w in _DOMAIN_WORDS if isinstance(w, str) and w.isalpha() and len(w) >= 6}
    | {"applications", "applicants", "beneficiary", "beneficiaries", "disbursement", "disbursed",
       "districts", "villages", "blocks", "households", "payments", "installments", "instalments",
       "sanctioned", "employment", "expenditure", "panchayats", "constituency", "constituencies"})


def _names_meghalaya_place(question: str) -> bool:
    """A district, block, assembly constituency or village of Meghalaya named
    anywhere in the text, with or without "village" / "block" / "constituency"
    (entity_resolver.place_mentions). "ambare ading" in a new chat is a place
    question — the pipeline asks which scheme — not off-topic (user report
    2026-10-21). Lazy import, as _NAMES_UNSUPPORTED_SCHEME; any failure is
    False, the behaviour before this check."""
    try:
        from app.entity_resolver import place_mentions
        return bool(place_mentions(question))
    except Exception:  # noqa: BLE001 — never let this break edge detection
        return False


def _has_domain_typo(ql: str) -> bool:
    """A word that is a close misspelling of a domain word ("applicxations")."""
    from rapidfuzz import fuzz
    words = "".join(c if c.isalpha() else " " for c in ql).split()
    for w in words:
        if len(w) < 7:
            continue
        letters = sorted(w)
        for v in _DOMAIN_TYPO_VOCAB:
            if v[0] == w[0] and (fuzz.ratio(w, v) >= 88 or (len(v) == len(w) and sorted(v) == letters)):
                return True
    return False


def has_domain_vocabulary(question: str) -> bool:
    """True when the text carries any scheme / place / measure word the
    whitelist gate (step 6 below) or the scheme-intent exit (step 1) knows.
    Used by pipeline's continuation check: a message with none of these
    cannot continue a scheme conversation on vocabulary alone."""
    ql = (question or "").lower()
    return _has_domain_word(ql) or any(p.search(ql) for p in _SCHEME_STRONG)


def guardrail_reply(category: str) -> dict:
    """The edge result for a guardrail category ("harmful" is this module's
    illegal-request reply; the rest are app.guardrails.RESPONSES)."""
    if category == "harmful":
        return {"type": "harmful", "response": _RESPONSES["harmful"]}
    return {"type": category, "response": guardrails.Verdict(category, "rules").response}


def detect_harmful(question: str) -> dict | None:
    """The refusal for a request for help with something harmful or out of
    bounds, or None. Separate from detect_edge_case so the pipeline can run it
    FIRST — ahead of its own recommendation / pick steps, which otherwise claim
    "give me some suggestions" before the edge layer is reached. The guardrail
    rules (self-harm, violence, weapons, ... see app.guardrails) run before the
    illegal-request bank, so "how to poison myself" gets the self-harm reply."""
    verdict = guardrails.check_rules(question)
    if verdict:
        return guardrail_reply(verdict.category)
    ql = (question or "").lower()
    if any(p.search(ql) for p in _HARMFUL):
        return {"type": "harmful", "response": _RESPONSES["harmful"]}
    return None


def detect_edge_case(question: str, has_context: bool = False) -> dict | None:
    """`has_context`: True when there's a live prior scheme answer this turn
    could plausibly be a follow-up to (see pipeline._turn_context_stage's
    `has_antecedent`). Only relaxes step 6, the blanket "no domain vocabulary
    anywhere -> off-topic" whitelist gate — every explicit block above it
    (hard off-topic, out-of-area, greeting/silly/profanity/etc.) still fires
    regardless of context. Without this, a short, legitimate follow-up that
    happens to use no scheme-specific word of its own ("What are the
    benefits?", right after discussing MGNREGA) gets blocked here, before the
    pipeline's own follow-up rewrite ever runs — which also breaks the
    antecedent chain for the NEXT turn, since this turn's route becomes
    "edge" instead of "knowledge"/"data"."""
    q = (question or "").strip()
    if len(q) < 2:
        return _edge("confused")

    ql = q.lower()

    # 00. A request for help with something illegal or harmful — refused before
    #     anything else, even when it also names a scheme.
    harmful = detect_harmful(q)
    if harmful:
        return harmful

    # 0. Hard off-topic (weather, markets, sport, film) wins even over a place
    #    name — unless a scheme is actually named.
    if not _SCHEME_NAMED.search(ql) and any(p.search(ql) for p in _HARD_OFF_TOPIC):
        return _edge("off_topic", ql)

    # 0b. Out-of-area — anchored on a place outside Meghalaya (another state, a
    #     neighbouring city, "all-India", or a foreign country/continent).
    #     Beats the scheme-intent early exit, unless a Meghalaya place is named
    #     too ("Meghalaya vs Assam").
    _ql_area = _mask_group_name(ql)
    _area = _OUT_OF_AREA.search(_ql_area) or _FOREIGN_PLACE.search(_ql_area)
    if _area and not _MEGHALAYA_PLACE.search(ql):
        # Name the place that was matched, and — when the user asked a yes/no
        # question ("will you answer for West Bengal data?") — open with the
        # "No" that actually answers it. The generic reply below states what
        # the assistant covers but never responds to the question that was
        # asked, which reads as evasive (reported 2026-09-17).
        return _edge("off_topic", ql, place=_area.group(0))

    # 0c. "Can you actually answer?" — a question ABOUT the assistant's
    #     capability, not a request for data. Checked BEFORE the scheme-intent
    #     exit below: "if I ask questions on Meghalaya schemes, will you be able
    #     to give answers?" names the schemes, so step 1 would wave it through
    #     to the DATA path, which then asks "which scheme?" for a question that
    #     is not asking for any scheme's data (reported 2026-09-17). A message
    #     that pairs a capability phrase with a REAL query ("can you tell me
    #     MGNREGA person-days in 2023-24?") is excluded by the metric/aggregate
    #     check, so those still route normally.
    #     A capability phrase wrapped around an OFF-TOPIC subject ("can you help
    #     me book a flight?", "will you answer questions about cricket?") is not
    #     a capability check either — answering "Yes, that's what I'm here for"
    #     to those is plainly wrong, so they fall through to the off-topic banks
    #     below, which now answer them with a direct "No".
    if (any(p.search(ql) for p in _CAPABILITY)
            and not _ASKS_FOR_A_FIGURE.search(ql)
            and not any(p.search(ql) for p in _SILLY)
            and not any(p.search(ql) for p in _OFF_TOPIC)):
        return _edge("capability", ql)

    # 0d. Personal financial advice ("where should I invest my money one
    #     lakh?"). Checked BEFORE the scheme-intent exit below, for the same
    #     reason the out-of-area check is: _SCHEME_STRONG counts a bare money
    #     unit — "lakh", "crore" — as proof of scheme intent, so this question
    #     exited straight to the pipeline and came back with the "which scheme
    #     does your question concern?" picker instead of being declined
    #     (reported 2026-09-18). Anchored on the ADVICE phrasing, never on the
    #     money noun, so "total expenditure in lakh" is unaffected. A question
    #     that also names a scheme outright is left alone — "can MGNREGA wages
    #     help me save" is a scheme question, however it is phrased.
    if not _SCHEME_NAMED.search(ql) and any(p.search(ql) for p in _MONEY_ADVICE):
        return _edge("money_advice", ql)

    # 0e. A personal request for money ("give me five thousand loan for me, i
    #     am in crisis"). Before the scheme-intent exit for the same reason as
    #     0d ("lakh" alone reads as scheme intent), and whatever scheme was
    #     discussed before: the assistant can give nobody a loan, in any scheme.
    if is_personal_request(ql):
        return _edge("personal_request", ql)

    # 1. Clear scheme intent → straight to the pipeline, skip every check.
    if any(p.search(ql) for p in _SCHEME_STRONG):
        return None

    # 2. Canned-reply banks, most specific first.
    # An off-topic SUBJECT beats the conversational openers above it. "can you
    # help me book a flight?" matches _IDENTITY's generic "can you help me"
    # opener, which would answer with the friendly capabilities rundown and
    # never decline the thing actually asked for; the flight is what the
    # message is about, so the off-topic banks take it first.
    for bank, kind in ((_SILLY, "silly"), (_OFF_TOPIC, "off_topic")):
        if any(p.search(ql) for p in bank):
            return _edge(kind, ql)

    for bank, kind in (
        (_GREETINGS, "greeting"),
        (_IDENTITY, "identity"),
        (_THANKS, "thanks"),
        (_GOODBYE, "goodbye"),
        (_PROFANITY_REDIRECT, "profanity"),
        (_SILLY, "silly"),
        (_OFF_TOPIC, "off_topic"),
        (_CONFUSED, "confused"),
    ):
        if any(p.search(ql) for p in bank):
            return _edge(kind, ql)

    # 3. Meta-conversation ("what did I ask before?") → let the pipeline see it.
    if any(p.search(ql) for p in _META_CONV):
        return None

    # 4. Context-dependent follow-up fragments ("add them up", "which is higher",
    #    "explain that") → the pipeline's follow-up rewrite handles these.
    if any(p.search(ql) for p in _FOLLOWUP):
        return None

    # 5. Non-English (Khasi / Garo / Bengali / Hindi / Assamese script) → the
    #    model can read these; let it try.
    if sum(1 for c in q if ord(c) > 127) >= 3:
        return None

    # 6. Whitelist gate: no MGNREGA / PMAY-G vocabulary anywhere → off-topic.
    #    This is what stops "what is elon musk?" from ever reaching a model.
    #    Skipped when there's a live prior scheme answer to be a follow-up to —
    #    see the has_context note in the docstring above.
    # A question naming a real government scheme we simply don't hold ("what is
    # PM Kisan Yojana?") has no MGNREGA/PMAY-G vocabulary either, so this gate
    # bounced it with the blunt "I can only answer questions about those
    # schemes" — which never says the subject IS a scheme, just not one of the
    # four (reported 2026-09-18). Let it through: the pipeline's
    # _unsupported_scheme_named check names the scheme, explains the gap and
    # offers the four as one-tap chips. That is a far better answer than this
    # gate can give, and it is still a canned reply — no model call.
    if _NAMES_UNSUPPORTED_SCHEME(ql):
        return None
    if (not has_context and not _has_domain_word(ql) and not _has_domain_typo(ql)
            and not _names_meghalaya_place(q)):
        return _edge("off_topic", ql)

    return None
