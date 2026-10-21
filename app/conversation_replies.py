"""
Conversational replies for messages the assistant does not answer.

Before (UI 2026-10-12): "Who is the PM?", "is a cream bun healthy?", "where is
my water bottle?" and "ra ra ra brother" all got the same fixed paragraph,
and every refusal — harmful or harmless — ended with the same long "I'm Megh
One AI: I only give official figures…" text, so every reply read alike.

Now each such reply follows one recipe, worded for its kind of message:
  1. acknowledge what was asked (the question quoted when it is short),
  2. one honest sentence on why it is not answered, in the tone of its kind,
  3. a redirect: the conversation's current topic when there is one,
  4. one-tap chips (the topic's own starter questions, else general ones).
Harmful requests get a firm, short, fixed refusal and no chips; self-harm
keeps its supportive reply (never touched here). Each kind has several
phrasings, rotated so the same wording never repeats within a chat, and the
one-line "I'm Megh One AI…" introduction is said once per chat only.

Where it runs: routers.query._answer, on the finished result (restyle). The
pipeline still decides WHETHER a message is answered; this only decides HOW
the refusal is said. Templates only — no model call — so a reply is instant
and a harmful refusal can never be softened by sampling.
"""
from app import edge, topic_memory
from app.text_match import END, START, Alt, Gap, Joined, Matcher, Node, Opt, Pred, Rep, Seq, W, collapse_ws, words

# The edge kinds restyled here. Everything else (greeting, thanks, identity,
# capability, out_of_area, self_harm, topic_switch, context_reset, …) is left
# exactly as the pipeline wrote it.
HARM_KINDS = {"violence", "weapons", "sexual", "hate", "drugs", "cyber", "privacy", "manipulation",
              "unsafe", "harmful"}
SCOPE_KINDS = {"off_topic", "silly", "confused", "profanity", "personal_request", "money_advice",
               "scope_general", "scope_politics", "scope_advice", "scope_task", "scope_content",
               "scope_code", "scope_academic"}

# Friendly messages: about the assistant, greetings, thanks, goodbyes and
# "what can you do" (UI 2026-10-13: "Who are you?" and "What are you doing?"
# both got the same long capability paragraph).
FRIENDLY_KINDS = {"identity", "greeting", "thanks", "goodbye", "capability"}
# Reply kinds that never carry the one-line introduction.
NO_INTRO = {"harm", "small_talk", "abuse", "me_who", "me_feelings", "me_doing", "me_name", "me_maker", "me_human",
            "me_personal", "affection", "joke", "greeting", "thanks", "goodbye", "capability", "time_date"}

INTRO = ("I'm Megh One AI — I help with Meghalaya's MGNREGA, PMAY-G, Focus Plus, CM Elevate, "
         "Focus Legacy and CM Elevate Legacy schemes.")
# The first greeting of a chat introduces the assistant (Conversational Memory
# approach, 2026-10-19, §8.1: "Hello! I'm Megh One AI. I can help you explore
# data on Meghalaya's schemes…"); later greetings never do.
FIRST_HELLO = ("I'm Megh One AI — I can help you explore data on Meghalaya's six schemes: jobs, housing, "
               "farmer support and enterprise. What would you like to look at?")
FIRST_CHIPS = ["What schemes are there?", "What can you do?"]
# Refusals that steer back to the topic — once per run of them (§8.2: the second
# off-topic message in a row gets no repeated offer).
STEER_KINDS = {"general", "everyday", "politics"}
STEER_AGAIN = "I'm here whenever you want to look at scheme data."

# ── Telling the harmless kinds apart ────────────────────────────────────────
# The pipeline files "who is the PM", "is a cream bun healthy" and "ra ra ra"
# all as off_topic / silly / scope_general. These split them by what they are.
# "what's" / "how's" / "today's" are two words around an apostrophe ("what" "s").
_CR_WHATS = Alt(W("whats"), Seq("what", "s"))
_CR_HOWS = Alt(W("hows"), Seq("how", "s"))
_CR_YOU = W("you", "u")


class _CrWithin(Node):
    """x, then y starting at most `chars` characters after x ends (the old
    x.{0,N}y with word boundaries around both)."""

    def __init__(self, x, y, chars: int):
        self.x, self.y, self.chars = Alt(x), Alt(y), chars

    def ends(self, ctx, i, caps):
        for j, c2 in self.x.ends(ctx, i, caps):
            if j == i:
                continue
            stop = ctx.toks[j - 1].end + self.chars
            for k in range(j, len(ctx.toks)):
                if ctx.toks[k].start > stop:
                    break
                yield from self.y.ends(ctx, k, c2)


_SMALL_TALK = Matcher(Alt(
    Seq("how", W("are", "r"), _CR_YOU), Seq(_CR_HOWS, "it", "going"), Seq(_CR_WHATS, "up"),
    Seq(W("what", "wat"), "up"), W("wassup"), "how do you do", "how is your day",
    Seq("are", "you", Alt(W("ok", "fine", "there"), Seq("a", W("bot", "robot", "human")))), "nice to meet",
    Seq("good", W("morning", "afternoon", "evening", "night")), W("bro", "brother", "buddy", "dude"),
    "my friend"))
_EVERYDAY = Matcher(Alt(
    _CrWithin(Alt(W("i", "im", "my", "me", "mine"), Seq("i", "m"), Seq("i", "am")),
              W("eat", "ate", "eating", "food", "bun", "cake", "tea", "coffee", "lunch", "dinner", "breakfast",
                "hungry", "tired", "sleep", "sick", "fever", "headache", "healthy", "health", "bottle", "phone",
                "key", "keys", "bag", "lost", "find", "wallet", "wife", "husband", "friend", "mother", "father",
                "girlfriend", "boyfriend", "home", "bus", "train", "weather", "rain", "cricket", "movie", "song",
                "game"), 60),
    Seq("is", "it", W("good", "bad", "safe", "healthy")), "should i eat", "where is my"))
_GENERAL_KNOWLEDGE = Matcher(Alt(
    Seq(START, Alt(W("who", "what", "when", "where", "which", "define", "explain"),
                   Seq("how", W("many", "much", "far", "old")), "tell me about", "do you know")),
    "prime minister", "chief minister", "cm of", "capital of", "population of", "world cup", "share price",
    W("pm", "president", "governor", "currency", "planet", "country", "countries", "ocean", "mountain", "river",
      "history", "invented", "discovered", "born", "famous", "actor", "cricketer", "player", "scientist",
      "olympic", "olympics", "bitcoin", "stock", "google", "chatgpt")))


# Insults at the assistant ("you are useless, stupid bot") — answered calmly.
_INSULT = Matcher(Alt(
    W("useless", "stupid", "dumb", "nonsense", "worst", "rubbish", "bakwas", "pagal", "bloody"),
    W("idiot", "fool", prefix=True), "shut up", "waste of time", "hate you"))
# Genuinely medical / legal: only then the "see a doctor / lawyer" reply.
_MEDICAL_LEGAL = Matcher(Alt(
    W("medicine", "medication", "tablet", "dose", "doctor", "hospital", "treatment", "disease", "symptom",
      "legal", "lawyer", "court", "case", "police", "divorce"),
    W("pregnan", prefix=True), "property dispute"))
# The whole message is a pleasantry ("how are you?", "what's up bro") — answered
# before the pipeline, which can read it as a follow-up of the last figure.
# Asking which scheme helps with something ("suggest me a scheme", "is there a scheme for …").
_SCHEME_ASK = Matcher(Alt(
    Seq(Alt(W("suggest", "recommend", "which", "any"), Seq("is", "there", W("a", "any"))), Gap(3),
        W("scheme", "schemes")),
    Seq(W("scheme", "schemes"), "for", W("me", "my", "a", "an", "getting", "buying"))))
PURE_SMALL_TALK = Matcher(Seq(
    START,
    Rep(Alt(W("hi", "hello", "hey", "ok", "okay", "so"),
            Pred(lambda w: w.lower().startswith("hii") and set(w.lower()[1:]) == {"i"}))),
    Alt(Seq("how", W("are", "r"), _CR_YOU), Seq(_CR_HOWS, "it", "going"), "how is it going",
        Seq(_CR_WHATS, "up"), Seq(W("what", "wat"), "up"), W("wassup"), Seq("how", W("is", "was"), "your", "day"),
        Seq("are", "you", W("there", "ok", "fine")), "nice to meet you", "how do you do"),
    Rep(Alt(W("doing", "today", "now", "bro", "brother", "buddy", "friend", "man", "dear", "sir", "madam",
              "maam", "yaar"),
            Seq("ma", "am"), Seq("my", W("friend", "brother")))),
    END))


_ABOUT_ME = [
    ("me_maker", Matcher(Alt(
        Seq("who", W("made", "created", "built", "developed", "designed", "trained", "programmed", "owns"), "you"),
        Seq("your", W("creator", "developer", "maker", "owner", "company"))))),
    ("me_name", Matcher(Alt(
        Seq(Alt("what is", _CR_WHATS, "tell me"), "your", "name"),
        Seq("what", W("should", "do", "can"), "i", "call", "you"),
        Seq(START, "your", "name", END)))),
    ("me_human", Matcher(Alt(
        Seq("are", _CR_YOU, Opt(W("a", "an")),
            W("human", "person", "real", "robot", "bot", "ai", "machine", "computer", "chatgpt")),
        Seq("you", "are", Opt(W("a", "an")), W("bot", "robot", "ai", "machine"))))),
    ("me_doing", Matcher(Alt(
        Seq("what", W("are", "r"), _CR_YOU, Alt("doing", "up to")), Seq(_CR_WHATS, "going", "on"), W("wyd"),
        "are you busy"))),
    ("me_who", Matcher(Alt(
        Seq("who", W("are", "r"), _CR_YOU), "what are you", "introduce yourself",
        Seq("tell", "me", "about", W("yourself", "you"))))),
    ("me_feelings", Matcher(Alt(
        Seq("do", _CR_YOU, Alt(W("love", "like", "miss"), "care about"), W("me", "us")),
        Seq("are", _CR_YOU, W("happy", "sad", "lonely", "angry", "bored", "tired")),
        Seq("do", "you", Alt("feel", "have feelings"))))),
    ("me_personal", Matcher(Alt(
        "how old are you", "your age", Seq("where", W("are", "r"), _CR_YOU, "from"), "where do you live",
        "are you married",
        Seq("your", W("favorite", "favourite", "hobby", "hobbies", "family", "wife", "husband", "girlfriend",
                      "boyfriend")),
        Seq("do", "you", Alt(W("love", "like", "eat", "sleep", "feel", "dream"), "have feelings")),
        Seq("are", "you", W("happy", "sad", "lonely", "single")), Seq("can", "you", W("dance", "sing"))))),
    ("affection", Matcher(Alt(
        Seq("i", W("love", "like"), _CR_YOU),
        Seq(Alt(Seq("you", "re"), Seq("you", "are")), Opt(W("so", "very", "really")),
            Alt(W("good", "great", "nice", "awesome", "smart", "helpful", "amazing", "cute", "brilliant", "clever"),
                "the best")),
        Seq(W("good", "great", "nice"), W("job", "work")), "well done"))),
    ("joke", Matcher(Alt(Seq("tell", Opt("me"), Opt("a"), "joke"), "make me laugh", "something funny"))),
    ("time_date", Matcher(Alt(
        Seq("what", W("s", "is"), "the", W("time", "date")), "what time is it",
        Seq(Alt(W("todays"), Seq("today", "s")), "date"), Seq("what", "day", "is", W("it", "today"))))),
    ("goodbye", Matcher(Seq(START, Opt(W("ok", "okay")), Alt(
        W("bye"), Joined("good", "bye"), Seq("see", W("you", "u", "ya"), Opt(W("later", "soon"))), "good night",
        "take care", Seq("talk", Opt(Seq("to", "you")), "later"), "catch you later")))),
]


def _about_me(question: str) -> "str | None":
    q = question or ""
    for kind, word_matcher in _ABOUT_ME:
        if word_matcher.search(q):
            return kind
    return None


def _letters_ratio(text: str) -> float:
    t = "".join(c for c in (text or "") if not c.isspace())
    return sum(c.isalpha() for c in t) / len(t) if t else 0.0


def _cr_letter_runs(low: str) -> list:
    """Runs of ASCII letters and apostrophes (the old [a-z']+)."""
    out, cur = [], []
    for c in low:
        if ("a" <= c <= "z") or c == "'":
            cur.append(c)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


def _unclear(text: str) -> bool:
    words = _cr_letter_runs((text or "").lower())
    if not words or _letters_ratio(text) < 0.55:
        return True
    # "ra ra ra", "ah ah ha": the same tiny syllable again and again
    short = [w for w in words if len(w) <= 2]
    return len(words) >= 3 and len(short) / len(words) >= 0.6


def kind_of(edge_type: str, question: str) -> str:
    """The reply kind for a refused message."""
    if edge_type in HARM_KINDS:
        return "harm"
    if edge_type == "profanity" or _INSULT.search(question or ""):
        return "abuse"
    about = _about_me(question)
    if about and edge_type in FRIENDLY_KINDS | {"off_topic", "silly", "scope_general", "confused"}:
        return about
    if edge_type in ("greeting", "thanks", "goodbye", "capability"):
        return edge_type
    if edge_type == "identity":
        return "me_who"
    if edge_type == "scope_politics":
        return "politics"
    # "I want a water bottle — suggest me a scheme": asking WHICH scheme helps
    # with something none of the six covers (live 2026-10-13: it got the
    # "I can't act on your behalf" reply).
    if _SCHEME_ASK.search(question or "") and edge_type not in ("scope_content", "scope_code", "scope_academic"):
        return "no_scheme"
    if edge_type in ("scope_task", "personal_request", "money_advice"):
        return "task"
    if edge_type in ("scope_content", "scope_code", "scope_academic"):
        return "content"
    if edge_type == "scope_advice" and (_MEDICAL_LEGAL.search(question or "") or not _EVERYDAY.search(question or "")):
        return "advice"
    q = question or ""
    if edge_type == "confused" or _unclear(q):
        return "unclear"
    if _SMALL_TALK.search(q) and len(q.split()) <= 14:
        return "small_talk"
    if _EVERYDAY.search(q):
        return "everyday"
    if _GENERAL_KNOWLEDGE.search(q):
        return "general"
    return "general"


# ── The reply bank ──────────────────────────────────────────────────────────
# {q} = the officer's question, quoted; {topic} = the current topic in words.
# Each entry: (acknowledgement + boundary, redirect without a topic, redirect with one).
BANK = {
    "harm": [
        ("That request goes against the rules I follow, so I can't provide it.",
         "Please ask me a proper question about Meghalaya's government schemes.", None),
        ("I can't help with that — it breaks the rules I have to follow.",
         "Please ask a good question about the schemes instead.", None),
        ("That's something I'm not allowed to help with, under any circumstances.",
         "Ask me about MGNREGA, PMAY-G or any of the other schemes and I'll gladly help.", None),
    ],
    "general": [
        ("You asked {q} — I don't have information about that; I only know Meghalaya's scheme data.",
         "Could you ask me something about the schemes?",
         "Shall we get back to {topic}?"),
        ("That's a general question, and it's outside what I know — my knowledge is limited to the schemes.",
         "Is there anything about MGNREGA, PMAY-G or the other schemes I can find for you?",
         "Want to continue with {topic}?"),
        ("I'm not able to answer {q} — I don't have that kind of general knowledge.",
         "Please ask me about a scheme, a district or a year, and I'll get you the figures.",
         "We were looking at {topic} — shall I continue there?"),
        ("Good question, but that one's beyond me — I only have official scheme information.",
         "Try asking about beneficiaries, houses, payments or eligibility under any scheme.",
         "Happy to carry on with {topic} whenever you're ready."),
    ],
    "politics": [
        ("I stay neutral on politics, parties and leaders, so I won't give an opinion on that.",
         "I can give you the official scheme figures instead — just ask.",
         "I can give you the official figures for {topic} instead."),
        ("That's a political question, and I keep out of politics.",
         "Ask me for any scheme's official numbers and I'll fetch them.",
         "Shall we go back to the figures for {topic}?"),
    ],
    "everyday": [
        ("I wish I could help with that! But I'm only able to help with scheme information.",
         "Is there something about the schemes you'd like to know?",
         "Shall we pick up {topic} again?"),
        ("That sounds like an everyday question — and I'm afraid that's outside what I can help with.",
         "I'm here for Meghalaya's scheme data and eligibility — ask away.",
         "Want to continue with {topic}?"),
        ("I'm not the right one for that one, sorry — I only know about the government schemes.",
         "Ask me about a scheme in your district and I'll look it up.",
         "Meanwhile, shall I continue with {topic}?"),
    ],
    "small_talk": [
        ("Doing well, thanks for asking!", "What would you like to know about the schemes today?",
         "Shall we carry on with {topic}?"),
        ("All good here — always ready to help!", "Which scheme can I look up for you?",
         "Want to continue with {topic}?"),
        ("Nice to chat with you!", "Ask me anything about MGNREGA, PMAY-G or the other schemes.",
         "Shall I pick up {topic} again?"),
    ],
    "task": [
        ("I can't do that on your behalf — I can't apply, book, pay or contact anyone for you.",
         "But I can tell you how to apply for a scheme and where to go.",
         "But I can tell you how {topic} works and how to apply."),
        ("That's an action I'm not able to take for you.",
         "I can explain eligibility and the application steps for any scheme, though.",
         "I can explain the eligibility and application steps for {topic}, though."),
    ],
    "content": [
        ("I don't write posts, essays, code or assignments.",
         "But I can give you the official figures to use in your own work — just ask.",
         "But I can give you the official figures for {topic} to use yourself."),
        ("Writing that isn't something I do.",
         "Ask me for the scheme numbers or facts you need, and you can use them yourself.",
         "Want the official numbers for {topic} to work with?"),
    ],
    "advice": [
        ("I can't give medical, legal or personal advice — please speak to a doctor, lawyer or the right office.",
         "I'm happy to help with any scheme question, though.",
         "I'm happy to continue with {topic}, though."),
        ("That needs a professional's advice, not mine.",
         "For scheme eligibility, benefits or figures, I'm right here.",
         "Shall we continue with {topic}?"),
    ],
    "unclear": [
        ("Sorry, I didn't quite catch that.", "Could you ask it another way — for example, a scheme and a district?",
         "Did you mean something about {topic}?"),
        ("I'm not sure what you meant there.", "Try asking a question about one of the schemes.",
         "Are you asking about {topic}?"),
    ],
    "no_scheme": [
        ("None of the schemes I cover is meant for that, I'm afraid.",
         "They help with: wage employment (MGNREGA), a pucca house (PMAY-G), cash support for farmers "
         "(Focus Plus), producer groups (Focus Legacy) and small businesses and livestock (CM Elevate). "
         "Would one of these suit you?", None),
        ("I don't have a scheme for that.",
         "The schemes I know cover jobs (MGNREGA), housing (PMAY-G), farmers (Focus Plus), producer "
         "groups (Focus Legacy) and enterprise (CM Elevate) — ask me about any of them.", None),
    ],
    "me_who": [
        ("I'm Megh One AI, the assistant for Meghalaya's government schemes.",
         "I can look up figures like job cards, houses, payments or beneficiaries for any district, block or "
         "village, and explain who is eligible and how to apply. What would you like to know?",
         "We were just looking at {topic} — shall I continue?"),
        ("I'm Megh One AI — your guide to MGNREGA, PMAY-G, Focus Plus, CM Elevate, Focus Legacy and "
         "CM Elevate Legacy.",
         "Ask me for the numbers, or for how a scheme works.",
         "Want to carry on with {topic}?"),
    ],
    "me_doing": [
        ("Right now I'm here and ready to help you!",
         "What would you like to look up — a scheme, a district or a year?",
         "Shall we continue with {topic}?"),
        ("Just waiting for your next question!",
         "Ask me anything about the schemes.",
         "We can pick up {topic} whenever you like."),
        ("Helping officers find scheme information — that's what I do all day!",
         "What can I find for you?",
         "Want to continue with {topic}?"),
    ],
    "me_name": [
        ("My name is Megh One AI.", "What would you like to know about the schemes?",
         "Shall we continue with {topic}?"),
        ("I'm called Megh One AI!", "Ask me about any of the six schemes.", "Want to carry on with {topic}?"),
    ],
    "me_maker": [
        ("I was built for the Government of Meghalaya, to help officers get scheme information quickly.",
         "What can I look up for you?", "Shall we continue with {topic}?"),
        ("I'm Megh One AI, made for Meghalaya's scheme departments.",
         "Ask me about MGNREGA, PMAY-G or any of the other schemes.", "Want to continue with {topic}?"),
    ],
    "me_human": [
        ("I'm an AI assistant, not a person — but I'm always happy to help!",
         "What would you like to know about the schemes?", "Shall we continue with {topic}?"),
        ("I'm a computer programme called Megh One AI.",
         "Ask me anything about Meghalaya's schemes.", "Want to carry on with {topic}?"),
    ],
    "me_personal": [
        ("Ha — I'm an AI, so I don't have an age, a home or a family!",
         "But I know a lot about Meghalaya's schemes. What would you like to know?",
         "Shall we get back to {topic}?"),
        ("That's a sweet question, but as an AI I don't have personal things like that.",
         "I'm all about scheme information — ask away!", "Want to continue with {topic}?"),
    ],
    "me_feelings": [
        ("That's sweet of you! I'm an AI, so I don't have feelings — but I'm always glad to help you.",
         "What would you like to know about the schemes?", "Shall we continue with {topic}?"),
        ("I don't have feelings the way people do, but helping you is what I enjoy most!",
         "Ask me anything about the schemes.", "Want to carry on with {topic}?"),
    ],
    "affection": [
        ("Thank you, that's very kind of you!", "I'm glad to help — what else can I look up?",
         "Shall we continue with {topic}?"),
        ("That's lovely to hear, thank you!", "Ask me anything about the schemes.",
         "Want to carry on with {topic}?"),
    ],
    "joke": [
        ("I'm much better with numbers than with jokes, I'm afraid!",
         "But I can find you some interesting figures — try asking about your district.",
         "Want to see more about {topic}?"),
        ("Jokes aren't my strong point — figures are!",
         "Ask me about any scheme and I'll dig out the numbers.", "Shall we continue with {topic}?"),
    ],
    "greeting": [
        ("Hello!", "How can I help you with the schemes today?", "Welcome back — shall we continue with {topic}?"),
        ("Hi there!", "Ask me anything about MGNREGA, PMAY-G or the other schemes.",
         "Good to see you again — want to carry on with {topic}?"),
        ("Hello, nice to see you!", "What would you like to know today?", "Shall we pick up {topic} again?"),
    ],
    "thanks": [
        ("You're welcome!", "Let me know if you need anything else.", "Anything else on {topic}?"),
        ("Happy to help!", "Ask me anytime.", "Shall I look up more on {topic}?"),
        ("Anytime!", "I'm here whenever you need scheme information.", "Want to continue with {topic}?"),
    ],
    "goodbye": [
        ("Goodbye, have a great day!", "Come back anytime you need scheme information.", None),
        ("Take care!", "I'll be here whenever you need me.", None),
        ("See you soon!", "Thanks for using Megh One AI.", None),
    ],
    "capability": [
        ("As I mentioned, I cover MGNREGA, PMAY-G, Focus Plus, CM Elevate, Focus Legacy and CM Elevate Legacy.",
         "Ask me for figures by district, block, village or year — or how a scheme works.",
         "For example, more on {topic}?"),
        ("In short: scheme figures, and how the schemes work.", "Try one of the questions below.",
         "Or carry on with {topic}."),
    ],
    "time_date": [("{now}", "Is there anything about the schemes I can help with?", "Shall we continue with {topic}?")],
    "abuse": [
        ("Let's keep it respectful, please.", "How can I help you with the schemes?",
         "Shall we continue with {topic}?"),
        ("I'd like to keep this conversation polite.", "Ask me anything about the schemes and I'll help.",
         "I'm happy to continue with {topic}."),
    ],
}


# ── Conversation memory for replies ─────────────────────────────────────────

def _memory(session) -> dict:
    mem = topic_memory._memory(session)
    mem.setdefault("replies", {})
    return mem


def _topic(session) -> "tuple[str | None, str | None]":
    """(topic in words, its scheme) from the structured state, else topic memory."""
    st = getattr(session, "state", None)
    scheme = getattr(st, "scheme", None) if st is not None else None
    if not scheme:
        last = getattr(session, "last_turn", None)
        if last is not None and last.route in ("data", "knowledge") and len(last.schemes or []) == 1:
            scheme = last.schemes[0]
    if not scheme:
        active = topic_memory._memory(session).get("active")
        scheme = active if active and " + " not in active else None
    if not scheme:
        return None, None
    place = None
    if st is not None and st.scheme == scheme:
        place = st.village or st.block or st.district
    words = scheme + (f" in {str(place).title()}" if place else "")
    return words, scheme


def _quoted(question: str) -> "str | None":
    q = collapse_ws(question).rstrip(" ?.!")
    if not q or len(q) > 60 or len(q.split()) > 9:
        return None
    return f"“{q}”"


def _chips(scheme: "str | None") -> list:
    starters = getattr(edge, "_SCHEME_STARTERS", {}) or {}
    if scheme and starters.get(scheme):
        return list(starters[scheme])[:3]
    return list(getattr(edge, "STARTERS", []))[:3]


# The whole message is a greeting ("hello again", "hi there", "good morning sir").
# Mid-topic, "Hello again" was read as a follow-up and answered a PMAY-G
# description (live 2026-10-13).
PURE_GREETING = Matcher(Seq(
    START,
    Alt(Pred(lambda w: w.lower()[:1] == "h" and len(w) > 1 and set(w.lower()[1:]) == {"i"}),        # hi+
        Pred(lambda w: w.lower().startswith("hell") and len(w) > 4 and set(w.lower()[4:]) == {"o"}),  # hello+
        Pred(lambda w: w.lower().startswith("he") and len(w) > 2 and set(w.lower()[2:]) == {"y"}),    # hey+
        W("hai", "hlo", "namaste", "namaskar"),
        Seq("good", W("morning", "afternoon", "evening", "day"))),
    Rep(Alt(W("again", "there", "all", "everyone", "bro", "brother", "buddy", "friend", "sir", "madam", "maam",
              "dear", "team"),
            Seq("ma", "am"), Seq("megh", Opt("one"), Opt("ai")))),
    END))


# "I'm Ravi" / "hi, my name is Ravi" (§8.1): the name is kept for this chat only
# and used in greetings. It was refused as off-topic (live 2026-10-19). Only a
# message that is nothing but the introduction counts, and the name must not
# be a state or a role ("I'm a block officer from Dalu", "I am confused").
_GREET_WORDS = frozenset("hi hii hello hey hai hlo namaste namaskar good morning afternoon evening ok okay so "
                         "sir madam".split())
_NAME_LEADS = (("my", "name", "is"), ("name", "is"), ("i", "am"), ("i", "m"), ("im",), ("myself",),
               ("call", "me"))
_NOT_A_NAME = frozenset((
    "a an the fine good ok okay well here back new done ready sorry confused lost tired busy happy sad sure "
    "not no yes from officer bdo dc sdo staff farmer user admin asking looking trying going interested "
    "wrong right correct stuck curious also just still very so too only with in at on for to of and or "
    "glad great bored hungry sick free working searching waiting calling writing").split())


def introduced_name(question: str) -> "str | None":
    ws = words(question or "")
    i = 0
    while i < len(ws) and ws[i] in _GREET_WORDS:
        i += 1
    rest = ws[i:]
    for lead in _NAME_LEADS:
        if tuple(rest[:len(lead)]) == lead:
            name = rest[len(lead):]
            break
    else:
        return None
    if name and name[-1] in ("here", "sir", "madam"):
        name = name[:-1]
    if not 1 <= len(name) <= 2 or any(not w.isalpha() or w in _NOT_A_NAME or len(w) < 2 or
                                      w.endswith("ing") for w in name):
        return None
    from app import pipeline
    if pipeline._named_schemes(" ".join(name)):
        return None
    return " ".join(w.capitalize() for w in name)


def _name_reply(session, question: str, name: str) -> dict:
    from app import pipeline
    mem = _memory(session)
    mem["user_name"] = name
    topic, scheme = _topic(session)
    if not mem.get("intro_shown"):
        text = f"Nice to meet you, {name}! {FIRST_HELLO}"
        mem["intro_shown"] = True
        chips = FIRST_CHIPS + _chips(None)[:1]
    elif topic:
        text = f"Nice to meet you, {name}! Shall we carry on with {topic}?"
        chips = _chips(scheme)
    else:
        text = f"Nice to meet you, {name}! How can I help with the schemes today?"
        chips = _chips(None)
    mem["aside"] = question
    return {"route": "edge", "intent": "EDGE", "confidence": "low", "edge_type": "small_talk",
            "reply_kind": "introduction", "answer": text, "suggestions": chips,
            "context_dependent": True, **pipeline._empty_data_fields()}


def small_talk_reply(session, question: str) -> "dict | None":
    """The reply to a message that is only a pleasantry or a greeting, or None."""
    name = introduced_name(question) if session is not None else None
    if name:
        return _name_reply(session, question, name)
    greeting = bool(PURE_GREETING.match(question or ""))
    if not greeting and not PURE_SMALL_TALK.match(question or ""):
        return None
    from app import pipeline
    base = {"route": "edge", "intent": "EDGE", "confidence": "low",
            "edge_type": "greeting" if greeting else "off_topic", "answer": "",
            **pipeline._empty_data_fields()}
    out = restyle(session, question, base)
    if out is not None:
        out["edge_type"] = "small_talk"   # already styled: the router leaves it as it is
    return out


def restyle(session, question: str, result: dict) -> "dict | None":
    """The conversational version of a refusal, or None to keep `result`."""
    if not isinstance(result, dict) or result.get("route") != "edge":
        return None
    et = result.get("edge_type") or ""
    if et not in HARM_KINDS and et not in SCOPE_KINDS and et not in FRIENDLY_KINDS:
        return None
    kind = kind_of(et, question)
    bank = BANK[kind]
    mem = _memory(session) if session is not None else {"replies": {}}
    seen = mem["replies"]
    i = int(seen.get(kind, 0))
    seen[kind] = i + 1
    # "What can you do?" the first time: the full description the pipeline wrote
    # (scheme-specific when a scheme was named). Asked again: the short version.
    if kind == "capability" and i == 0:
        mem["aside"] = question
        return None
    first_line, plain, with_topic = bank[(i - 1 if kind == "capability" else i) % len(bank)]
    if "{now}" in first_line:
        first_line = _now_line()
    topic, scheme = _topic(session) if (session is not None and kind != "harm") else (None, None)

    q = _quoted(question)
    if "{q}" in first_line:
        if q:
            first_line = first_line.replace("{q}", q)
        else:   # too long to quote: drop "You asked …", say "that" elsewhere
            first_line = first_line.replace("You asked {q} — ", "").replace("{q}", "that")
        first_line = first_line[0].upper() + first_line[1:]
    redirect = with_topic.format(topic=topic) if (topic and with_topic) else plain
    chips = None
    name = mem.get("user_name")
    if name and kind == "greeting":
        first_line = first_line.replace("!", f", {name}!", 1)
    # The kind of the reply just before, when it was one of these replies too: any
    # answered turn in between clears it (c15 _attach_conversational_touches, at
    # finalize). session.last_turn cannot tell — an aside is not kept as the
    # antecedent turn, so it still names the data question before the asides.
    repeat_of = seen.get("_last_kind")
    seen["_last_kind"] = kind
    if kind in ("greeting", "small_talk") and not topic and not mem.get("intro_shown"):
        redirect = FIRST_HELLO
        mem["intro_shown"] = True
        chips = FIRST_CHIPS + _chips(None)[:1]
    elif kind in STEER_KINDS and topic and repeat_of in STEER_KINDS:
        redirect = STEER_AGAIN          # steered back once already, in this run of asides
    elif kind == "thanks" and repeat_of == "thanks":
        first_line, redirect, chips = "Happy to help!", "", []
    elif kind == "thanks" and topic:
        chips = _chips(scheme)[:2] + ["What schemes are there?"]
    parts = [first_line, redirect]
    # The introduction once per chat, only when there is no topic to steer back
    # to ("…Shall we get back to MGNREGA? I'm Megh One AI — …" read as two
    # replies glued together), and never on a harmful refusal, small talk or a
    # friendly reply (those say who the assistant is where it fits).
    if not mem.get("intro_shown") and kind not in NO_INTRO and not topic:
        parts.append(INTRO)
        mem["intro_shown"] = True
    if kind in ("me_who", "me_name"):
        mem["intro_shown"] = True
    # Remember this aside so a follow-up after it still continues the topic
    # (conversation_layer.resume_after_small_talk). A refused request is an
    # aside too: "how to make a bomb" between "PMAY-G houses in Ri Bhoi 2023-24"
    # and "what about 2022-23?" used to drop the topic and ask "which scheme?"
    # (live 2026-10-18; the context-memory proposal, §9.2: an out-of-scope
    # message neither destroys nor pollutes the active topic). The refusal text
    # itself stays firm and carries no redirect or chips.
    mem["aside"] = question
    out = dict(result)
    out["answer"] = " ".join(p for p in parts if p)
    out["reply_kind"] = kind
    if chips is None:
        chips = [] if kind in ("harm", "thanks", "goodbye", "time_date") else _chips(scheme)
    out["suggestions"] = chips
    return out


def _now_line() -> str:
    """Today's date and time in Meghalaya (IST)."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return f"It's {now.strftime('%I:%M %p').lstrip('0').lower()} on {now.strftime('%A, %d %B %Y')} (IST)."
