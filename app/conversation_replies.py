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
import re

from app import edge, topic_memory

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

# ── Telling the harmless kinds apart ────────────────────────────────────────
# The pipeline files "who is the PM", "is a cream bun healthy" and "ra ra ra"
# all as off_topic / silly / scope_general. These split them by what they are.
_SMALL_TALK = re.compile(
    r"\b(?:how\s+(?:are|r)\s+(?:you|u)|how'?s\s+it\s+going|what'?s\s+up|wh?at\s+up|wassup|how\s+do\s+you\s+do|"
    r"how\s+is\s+your\s+day|are\s+you\s+(?:ok|fine|there|a\s+(?:bot|robot|human))|nice\s+to\s+meet|"
    r"good\s+(?:morning|afternoon|evening|night)|bro(?:ther)?|buddy|dude|my\s+friend)\b",
    re.IGNORECASE)
_EVERYDAY = re.compile(
    r"\b(?:i|i'?m|i\s+am|my|me|mine)\b.{0,60}\b(?:eat|ate|eating|food|bun|cake|tea|coffee|lunch|dinner|breakfast|"
    r"hungry|tired|sleep|sick|fever|headache|healthy|health|bottle|phone|keys?|bag|lost|find|wallet|"
    r"wife|husband|friend|mother|father|girlfriend|boyfriend|home|bus|train|weather|rain|cricket|movie|song|game)\b"
    r"|\b(?:is\s+it\s+(?:good|bad|safe|healthy)|should\s+i\s+eat|where\s+is\s+my)\b",
    re.IGNORECASE | re.DOTALL)
_GENERAL_KNOWLEDGE = re.compile(
    r"^\W*(?:who|what|when|where|which|how\s+many|how\s+much|how\s+far|how\s+old|tell\s+me\s+about|"
    r"do\s+you\s+know|define|explain)\b"
    r"|\b(?:prime\s+minister|\bpm\b|president|chief\s+minister|\bcm\s+of\b|governor|capital\s+of|population\s+of|"
    r"currency|planet|country|countries|ocean|mountain|river|history|invented|discovered|born|famous|"
    r"actor|cricketer|player|scientist|world\s+cup|olympics?|bitcoin|stock|share\s+price|google|chatgpt)\b",
    re.IGNORECASE)


# Insults at the assistant ("you are useless, stupid bot") — answered calmly.
_INSULT = re.compile(r"\b(?:useless|stupid|idiot\w*|dumb|fool\w*|nonsense|shut\s+up|worst|rubbish|bakwas|pagal|"
                     r"waste\s+of\s+time|hate\s+you|bloody)\b", re.IGNORECASE)
# Genuinely medical / legal: only then the "see a doctor / lawyer" reply.
_MEDICAL_LEGAL = re.compile(r"\b(?:medicine|medication|tablet|dose|doctor|hospital|treatment|disease|symptom|"
                            r"pregnan\w*|legal|lawyer|court|case|police|divorce|property\s+dispute)\b", re.IGNORECASE)
# The whole message is a pleasantry ("how are you?", "what's up bro") — answered
# before the pipeline, which can read it as a follow-up of the last figure.
# Asking which scheme helps with something ("suggest me a scheme", "is there a scheme for …").
_SCHEME_ASK = re.compile(r"\b(?:suggest|recommend|which|any|is\s+there\s+(?:a|any))\s+(?:\w+\s+){0,3}schemes?\b"
                         r"|\bschemes?\s+for\s+(?:me|my|a|an|getting|buying)\b", re.IGNORECASE)
PURE_SMALL_TALK = re.compile(
    r"^\W*(?:(?:hi|hello|hey|hii+|ok(?:ay)?|so)\W+)*"
    r"(?:how\s+(?:are|r)\s+(?:you|u)|how'?s\s+it\s+going|how\s+is\s+it\s+going|what'?s\s+up|wh?at\s+up|wassup|"
    r"how\s+(?:is|was)\s+your\s+day|are\s+you\s+(?:there|ok|fine)|nice\s+to\s+meet\s+you|how\s+do\s+you\s+do)"
    r"(?:\W+(?:doing|today|now|bro(?:ther)?|buddy|friend|my\s+(?:friend|brother)|man|dear|sir|madam|ma'?am|yaar))*\W*$",
    re.IGNORECASE)


_ABOUT_ME = [
    ("me_maker", re.compile(r"\bwho\s+(?:made|created|built|developed|designed|trained|programmed|owns)\s+you\b"
                            r"|\byour\s+(?:creator|developer|maker|owner|company)\b", re.IGNORECASE)),
    ("me_name", re.compile(r"\b(?:what\s+is|what'?s|tell\s+me)\s+your\s+name\b|\bwhat\s+(?:should|do|can)\s+i\s+call\s+you\b"
                           r"|^\W*your\s+name\W*$", re.IGNORECASE)),
    ("me_human", re.compile(r"\bare\s+(?:you|u)\s+(?:a\s+|an\s+)?(?:human|person|real|robot|bot|ai|machine|computer|chatgpt)\b"
                            r"|\byou\s+are\s+(?:a\s+|an\s+)?(?:bot|robot|ai|machine)\b", re.IGNORECASE)),
    ("me_doing", re.compile(r"\bwhat\s+(?:are|r)\s+(?:you|u)\s+(?:doing|up\s+to)\b|\bwhat'?s\s+going\s+on\b|\bwyd\b"
                            r"|\bare\s+you\s+busy\b", re.IGNORECASE)),
    ("me_who", re.compile(r"\bwho\s+(?:are|r)\s+(?:you|u)\b|\bwhat\s+are\s+you\b|\bintroduce\s+yourself\b"
                          r"|\btell\s+me\s+about\s+(?:yourself|you)\b", re.IGNORECASE)),
    ("me_feelings", re.compile(r"\bdo\s+(?:you|u)\s+(?:love|like|miss|care\s+about)\s+(?:me|us)\b"
                               r"|\bare\s+(?:you|u)\s+(?:happy|sad|lonely|angry|bored|tired)\b"
                               r"|\bdo\s+you\s+(?:feel|have\s+feelings)\b", re.IGNORECASE)),
    ("me_personal", re.compile(r"\bhow\s+old\s+are\s+you\b|\byour\s+age\b|\bwhere\s+(?:are|r)\s+(?:you|u)\s+from\b"
                               r"|\bwhere\s+do\s+you\s+live\b|\bare\s+you\s+married\b"
                               r"|\byour\s+(?:favou?rite|hobby|hobbies|family|wife|husband|girlfriend|boyfriend)\b"
                               r"|\bdo\s+you\s+(?:love|like|eat|sleep|feel|dream|have\s+feelings)\b"
                               r"|\bare\s+you\s+(?:happy|sad|lonely|single)\b|\bcan\s+you\s+(?:dance|sing)\b", re.IGNORECASE)),
    ("affection", re.compile(r"\bi\s+(?:love|like)\s+(?:you|u)\b|\byou(?:'re|\s+are)\s+(?:so\s+|very\s+|really\s+)?"
                             r"(?:good|great|nice|awesome|smart|helpful|the\s+best|amazing|cute|brilliant|clever)\b"
                             r"|\b(?:good|great|nice)\s+(?:job|work)\b|\bwell\s+done\b", re.IGNORECASE)),
    ("joke", re.compile(r"\btell\s+(?:me\s+)?(?:a\s+)?joke\b|\bmake\s+me\s+laugh\b|\bsomething\s+funny\b", re.IGNORECASE)),
    ("time_date", re.compile(r"\bwhat(?:'s|\s+is)\s+the\s+(?:time|date)\b|\bwhat\s+time\s+is\s+it\b|\btoday'?s\s+date\b"
                             r"|\bwhat\s+day\s+is\s+(?:it|today)\b", re.IGNORECASE)),
    ("goodbye", re.compile(r"^\W*(?:ok(?:ay)?\W+)?(?:bye|good\s*bye|see\s+(?:you|u|ya)(?:\s+later|\s+soon)?|good\s+night"
                           r"|take\s+care|talk\s+(?:to\s+you\s+)?later|catch\s+you\s+later)\b", re.IGNORECASE)),
]


def _about_me(question: str) -> "str | None":
    q = question or ""
    for kind, rx in _ABOUT_ME:
        if rx.search(q):
            return kind
    return None


def _letters_ratio(text: str) -> float:
    t = re.sub(r"\s", "", text or "")
    return sum(c.isalpha() for c in t) / len(t) if t else 0.0


def _unclear(text: str) -> bool:
    words = re.findall(r"[a-z']+", (text or "").lower())
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
    q = re.sub(r"\s+", " ", (question or "").strip()).rstrip(" ?.!")
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
PURE_GREETING = re.compile(
    r"^\W*(?:hi+|hello+|hey+|hai|hlo|namaste|namaskar|good\s+(?:morning|afternoon|evening|day))"
    r"(?:\W+(?:again|there|all|everyone|bro(?:ther)?|buddy|friend|sir|madam|ma'?am|dear|team|megh(?:\s+one)?(?:\s+ai)?))*\W*$",
    re.IGNORECASE)


def small_talk_reply(session, question: str) -> "dict | None":
    """The reply to a message that is only a pleasantry or a greeting, or None."""
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
    parts = [first_line, redirect]
    # The introduction once per chat, and never on a harmful refusal, small talk
    # or a friendly reply (those say who the assistant is where it fits).
    if not mem.get("intro_shown") and kind not in NO_INTRO:
        parts.append(INTRO)
        mem["intro_shown"] = True
    if kind in ("me_who", "me_name"):
        mem["intro_shown"] = True
    # Remember this aside so a follow-up after it still continues the topic
    # (conversation_layer.resume_after_small_talk).
    if kind != "harm":
        mem["aside"] = question
    out = dict(result)
    out["answer"] = " ".join(p for p in parts if p)
    out["reply_kind"] = kind
    out["suggestions"] = [] if kind in ("harm", "thanks", "goodbye", "time_date") else _chips(scheme)
    return out


def _now_line() -> str:
    """Today's date and time in Meghalaya (IST)."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    return f"It's {now.strftime('%I:%M %p').lstrip('0').lower()} on {now.strftime('%A, %d %B %Y')} (IST)."
