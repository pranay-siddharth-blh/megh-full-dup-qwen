# app/pipeline/common/c15_conversation_meta.py — talking about the conversation itself (D-052).
# Part of the app.pipeline package: executed by app/pipeline/__init__.py into the package
# namespace, in load order, so it shares every name with the other files. Loaded after
# c14; the turn stages call these functions at run time.
#
# Reported 2026-10-18 (live probe of a natural conversation): right after a data answer,
#   "why are you not giving me district wise?"        -> the reference documents (KNOWLEDGE)
#   "that's wrong, I asked for completed houses"       -> answered, but the year was lost
#   "can you explain this number?"                     -> "the documents do not contain…"
#   "what should I ask next?" / "I don't understand"   -> "Sorry, I didn't quite catch that"
#   "what did you just tell me?" / "you are not understanding me" -> off-topic bounce
# Each of these is about the PREVIOUS turn, not a new question. They are read here, on the
# user's own words, before the edge banks or the router see them:
#   recap      -> the last answer, said again
#   explain    -> what the figure means, in plain words (9B, grounded on the last answer)
#   misread    -> an apology that says what was understood, and asks for the real ask
#   suggest    -> concrete next questions for the current topic
#   correction -> the complaint lead is dropped and the correction runs as a follow-up
#   breakdown  -> the previous question, broken down by the dimension asked for
# The first four answer from the previous turn (edge stage, _conversation_meta_answer); the
# last two change the question (follow-up stage, _meta_question) and the answer opens with
# an apology (_attach_preface, finalize node). Every reply is an aside: the topic goes on.
from app import entity_resolver as _c15_entity_resolver
from app.text_match import collapse_ws, numbers as _c15_numbers, tokens as _c15_tokens, words as _c15_words

_C15_SCHEME_MEANING = {
    "MGNREGA": "rural employment: person-days of work, wages and expenditure for job-card households",
    "PMAY-G": "rural housing: houses sanctioned and completed, and the amounts released to beneficiaries",
    "Focus Plus": "a direct cash benefit paid to individual farmers, in batches",
    "CM Elevate": "livelihood and enterprise applications (piggery, dairy, …) and their status",
    "Focus Legacy": "payments to producer groups, one payment per group",
    "CM Elevate Legacy": "sanctions and disbursements under the earlier CM Elevate rounds",
}

# Words that open a message without saying anything ("ok so", "no wait", "sorry but").
_C15_FILLERS = frozenset("ok okay k so no nope nah hey hmm hm sorry but actually see look and wait well "
                         "please pls bro yaar sir madam again now".split())
# What is left of a complaint when it names nothing: "why are you not giving THIS THING".
_C15_EMPTY_OBJECT = frozenset("this that it thing things me the a an answer answers data information info "
                              "properly correctly right correct anything something for of about please pls "
                              "again now ok okay bro yaar sir madam my question what i asked".split())
_C15_DIMENSION_WORDS = {"district": "district", "districts": "district", "block": "block", "blocks": "block",
                        "village": "village", "villages": "village", "constituency": "constituency",
                        "constituencies": "constituency", "ac": "constituency"}
_C15_BREAKDOWN_ONLY = frozenset("wise by per each every breakdown break down level all the of in".split())

# A complaint that may carry the correction after it. Longest first. The words are
# tokens (an apostrophe splits: "didn't" -> "didn", "t").
_C15_COMPLAINT_LEADS = [
    ("why", "are", "you", "not", "giving", "me"), ("why", "are", "you", "not", "showing", "me"),
    ("why", "you", "are", "not", "giving", "me"), ("why", "are", "you", "not", "giving"),
    ("why", "are", "you", "not", "showing"), ("why", "are", "you", "not", "answering"),
    ("why", "you", "are", "not", "giving"), ("why", "you", "are", "not", "showing"),
    ("why", "did", "you", "not", "give", "me"), ("why", "didn", "t", "you", "give", "me"),
    ("why", "didnt", "you", "give", "me"), ("why", "did", "you", "not", "give"),
    ("why", "didn", "t", "you", "give"), ("why", "didnt", "you", "give"),
    ("why", "did", "you", "not", "show"), ("why", "didn", "t", "you", "show"),
    ("why", "u", "r", "not", "giving"), ("why", "u", "not", "giving"),
    ("you", "are", "not", "giving", "me"), ("you", "are", "not", "giving"),
    ("you", "did", "not", "give", "me"), ("you", "didn", "t", "give", "me"), ("you", "didnt", "give", "me"),
    ("why", "not"),
]
# "that's wrong, I ASKED FOR completed houses" / "no, I MEANT the completed ones".
_C15_CORRECTION_LEADS = [
    ("i", "asked", "you", "for"), ("i", "asked", "you", "about"), ("i", "asked", "for"), ("i", "asked", "about"),
    ("i", "am", "asking", "for"), ("i", "m", "asking", "for"), ("im", "asking", "for"),
    ("i", "am", "asking", "about"), ("i", "m", "asking", "about"), ("i", "was", "asking", "for"),
    ("i", "was", "asking", "about"), ("i", "meant"), ("i", "mean"), ("i", "said"), ("i", "wanted"),
    ("not", "that"), ("i", "asked"),
]
# Only these may stand alone; the others need a complaint word before them ("I want" is
# usually a new question: "I want to know about farmers getting money").
_C15_STRONG_CORRECTION = {("i", "asked", "you", "for"), ("i", "asked", "you", "about"), ("i", "asked", "for"),
                          ("i", "asked", "about"), ("i", "meant"), ("not", "that")}
_C15_COMPLAINT_WORDS = frozenset("wrong incorrect no nope nah not mistake galat nahi".split())

_C15_RECAP = [
    ("what", "did", "you", "just"), ("what", "did", "you", "tell"), ("what", "did", "you", "say"),
    ("what", "did", "u", "say"), ("what", "did", "u", "tell"), ("what", "was", "your", "answer"),
    ("what", "was", "the", "answer"), ("what", "was", "your", "last"), ("what", "is", "your", "answer"),
    ("say", "that", "again"), ("say", "it", "again"), ("repeat", "that"), ("repeat", "it"),
    ("repeat", "the", "answer"), ("repeat", "your", "answer"), ("once", "again"), ("tell", "me", "again"),
    ("show", "me", "again"), ("come", "again"),
]
_C15_EXPLAIN = [
    ("explain",), ("elaborate",), ("clarify",), ("what", "does", "this", "mean"), ("what", "does", "that", "mean"),
    ("what", "does", "it", "mean"), ("what", "do", "you", "mean"), ("what", "is", "this", "number"),
    ("what", "is", "that", "number"), ("what", "is", "this", "figure"), ("in", "simple", "words"),
    ("in", "simple", "terms"), ("simpler",), ("i", "don", "t", "understand"), ("i", "dont", "understand"),
    ("i", "do", "not", "understand"), ("i", "didn", "t", "understand"), ("i", "didnt", "understand"),
    ("not", "clear"), ("didn", "t", "get", "it"), ("didnt", "get", "it"), ("did", "not", "get", "it"),
    ("i", "don", "t", "get", "it"), ("i", "dont", "get", "it"), ("confusing",), ("i", "am", "confused"),
    ("i", "m", "confused"), ("im", "confused"), ("means", "what"), ("meaning", "of", "this"),
    ("how", "did", "you", "get", "this"), ("how", "did", "you", "get", "that"), ("how", "did", "you", "calculate"),
    ("where", "is", "this", "from"), ("where", "did", "you", "get"), ("source", "of", "this"),
]
_C15_MISREAD = [
    ("you", "are", "not", "understanding"), ("you", "re", "not", "understanding"), ("u", "r", "not", "understanding"),
    ("you", "are", "not", "getting"), ("not", "understanding", "me"), ("you", "don", "t", "understand"),
    ("you", "dont", "understand"), ("you", "didn", "t", "understand"), ("you", "didnt", "understand"),
    ("you", "did", "not", "understand"), ("you", "misunderstood"), ("you", "have", "misunderstood"),
    ("not", "what", "i", "asked"), ("not", "what", "i", "meant"), ("not", "what", "i", "want"),
    ("not", "what", "i", "wanted"), ("not", "my", "question"), ("wrong", "answer"), ("incorrect", "answer"),
    ("answer", "is", "wrong"), ("this", "is", "wrong"), ("that", "is", "wrong"), ("that", "s", "wrong"),
    ("thats", "wrong"), ("it", "s", "wrong"), ("its", "wrong"), ("you", "are", "wrong"), ("you", "re", "wrong"),
    ("not", "correct"), ("you", "are", "not", "answering"), ("not", "answering", "my"), ("not", "answering", "me"),
    ("not", "helping",), ("you", "are", "not", "helping"), ("not", "what", "i", "am", "asking"),
    ("this", "is", "not", "it"), ("that", "is", "not", "it"),
]
_C15_SUGGEST = [
    ("what", "should", "i", "ask"), ("what", "can", "i", "ask"), ("what", "else", "can", "i", "ask"),
    ("what", "else", "can", "you", "tell"), ("what", "else", "can", "you", "show"), ("what", "else", "can", "u"),
    ("what", "else", "do", "you", "have"), ("what", "else", "do", "you", "know"), ("what", "else"),
    ("what", "more", "can"), ("what", "more", "do", "you"), ("anything", "else"), ("what", "next"),
    ("what", "now"), ("what", "do", "i", "ask"), ("what", "to", "ask"), ("what", "all", "can", "i", "ask"),
    ("where", "do", "i", "start"), ("where", "should", "i", "start"), ("how", "do", "i", "start"),
    ("give", "me", "some", "questions"), ("suggest", "me", "some", "questions"), ("suggest", "some", "questions"),
    ("suggest", "questions"), ("suggest", "something"), ("suggest", "me", "something"), ("any", "suggestions"),
    ("some", "examples"), ("example", "questions"), ("sample", "questions"), ("what", "questions", "can", "i"),
    ("what", "can", "you", "tell", "me", "about", "this"), ("what", "can", "i", "do", "here"),
]


# "Why is it so low?" / "what is the reason?" after a figure: the records hold the
# figures, not the reasons (live 2026-10-18: it re-ran the same question).
_C15_REASON = [
    ("why", "is", "it"), ("why", "is", "this"), ("why", "is", "that"), ("why", "so"), ("why", "such"),
    ("why", "this", "much"), ("why", "only"), ("why", "the"), ("reason",), ("reasons",), ("what", "explains"),
    ("how", "come"), ("why", "has", "it"), ("why", "did", "it"), ("why", "does", "it"), ("why", "was", "it"),
    ("what", "caused"), ("what", "is", "causing"), ("why", "less"), ("why", "more"), ("why", "low"), ("why", "high"),
]


def _c15_has(ws: list, phrases) -> bool:
    for ph in phrases:
        n = len(ph)
        if n <= len(ws) and any(ws[i:i + n] == list(ph) for i in range(len(ws) - n + 1)):
            return True
    return False


def _c15_new_content(text: str) -> bool:
    """Does the message bring a scheme, a place, a year or a measure of its own? Then it
    is a question, however it is worded ("explain the MGNREGA wage rate")."""
    if _mentions_scheme(text) or named_places(text) or context_policy.extract_year_keys(text):
        return True
    if _measure_labels(text) or context_policy.metric_families(text):
        return True
    return "scheme" in _c15_words(text)


def _c15_lead_split(text: str) -> "tuple[tuple, str] | None":
    """(the complaint lead found, the text after it), or None. Fillers before the lead
    are skipped; a plain correction lead ("I meant …") needs a complaint word before it
    unless it is one of the strong ones ("I asked for …", "not that …")."""
    toks = _c15_tokens(text or "")
    ws = [t.low for t in toks]
    for i in range(min(len(ws), 9)):
        for lead in _C15_COMPLAINT_LEADS + _C15_CORRECTION_LEADS:
            n = len(lead)
            if ws[i:i + n] != list(lead):
                continue
            before = ws[:i]
            if any(w not in _C15_FILLERS for w in before) and len(before) > 8:
                return None
            is_correction = lead in _C15_CORRECTION_LEADS
            if is_correction and lead not in _C15_STRONG_CORRECTION \
                    and not (set(before) & _C15_COMPLAINT_WORDS):
                continue
            if is_correction and not (set(before) <= _C15_FILLERS | _C15_COMPLAINT_WORDS
                                      | {"that", "this", "it", "is", "s", "was", "answer", "i", "think"}):
                continue
            rest = text[toks[i + n - 1].end:] if i + n - 1 < len(toks) else ""
            return lead, rest.strip(" ,.:;!?-—–")
    return None


def _c15_breakdown_dimension(rest: str) -> "str | None":
    """"district wise" / "by district" / "block-wise breakdown" -> the dimension, else None."""
    ws = _c15_words(rest)
    dims = {_C15_DIMENSION_WORDS[w] for w in ws if w in _C15_DIMENSION_WORDS}
    if len(dims) != 1:
        return None
    if any(w not in _C15_BREAKDOWN_ONLY and w not in _C15_DIMENSION_WORDS and w not in _C15_EMPTY_OBJECT
           for w in ws):
        return None
    return dims.pop()


def _meta_kind(raw_question: str, prev) -> "str | None":
    """Which conversation-meta kind the typed message is, or None for a question.
    recap / explain / misread / suggest are answered from the previous turn;
    correction / breakdown change the question. `prev` is the previous answered turn."""
    text = raw_question or ""
    ws = _c15_words(text)
    if not ws or len(ws) > 40:
        return None
    has_prev = prev is not None and getattr(prev, "route", None) in _ANTECEDENT_ROUTES
    split = _c15_lead_split(text)
    if split is not None:
        lead, rest = split
        content = [w for w in _c15_words(rest) if w not in _C15_EMPTY_OBJECT]
        if content and has_prev and getattr(prev, "route", None) == "data" and _c15_breakdown_dimension(rest):
            return "breakdown"
        if content and has_prev and lead in _C15_CORRECTION_LEADS:
            return "correction"
        if content and has_prev and _c15_new_content(rest):
            return "correction"
        if not content:
            return "misread"
    if _c15_has(ws, _C15_SUGGEST) and not _c15_new_content(text):
        return "suggest"
    if _c15_has(ws, _C15_MISREAD) and not _c15_new_content(text):
        return "misread"
    if not has_prev:
        return None
    if _c15_has(ws, _C15_RECAP) and not _c15_new_content(text):
        return "recap"
    if _c15_has(ws, _C15_EXPLAIN) and not _c15_new_content(text) and len(ws) <= 16:
        return "explain"
    if (getattr(prev, "route", None) == "data" and _c15_has(ws, _C15_REASON) and len(ws) <= 14
            and not ({"you", "u", "your"} & set(ws)) and not _c15_new_content(text)):
        return "reason"
    return None


def _meta_question(raw_question: str, prev) -> "tuple[str, str, bool] | None":
    """For a correction / breakdown: (the question to run, the apology that opens the
    answer, whether the question is already standalone). None when nothing to run."""
    split = _c15_lead_split(raw_question or "")
    if split is None or prev is None:
        return None
    _lead, rest = split
    dim = _c15_breakdown_dimension(rest) if getattr(prev, "route", None) == "data" else None
    if dim:
        stem = _c05_statewide_stem(getattr(prev, "question", "") or "")
        if not stem:
            return None
        return f"{stem} by {dim}", f"Sorry — here it is {dim}-wise.", True
    content = [w for w in _c15_words(rest) if w not in _C15_EMPTY_OBJECT]
    if not content:
        return None
    frag = collapse_ws(rest)
    for lead_word in ("for", "about", "the"):
        if frag.lower().startswith(lead_word + " ") and len(frag.split()) > 1:
            frag = frag[len(lead_word) + 1:]
    return frag, "Sorry about that — here's what you asked for.", False


def _c15_scope_line(prev) -> str:
    resolved = getattr(prev, "resolved_entities", None) or {}
    try:
        place = _scope_banner_place(resolved)
        year = _scope_banner_year(resolved)
    except Exception:  # noqa: BLE001 — the scope line is optional
        return ""
    parts = [p for p in (place, year) if p]
    return ", ".join(parts)


def _c15_scheme(prev) -> "str | None":
    schemes = list(getattr(prev, "schemes", None) or []) if prev is not None else []
    return schemes[0] if len(schemes) == 1 else None


def _c15_chips(prev) -> list:
    """Next questions for the current topic: the breakdown / comparison the last data
    answer allows, then the scheme's own starters."""
    items: list[str] = []
    scheme = _c15_scheme(prev)
    if prev is not None and getattr(prev, "route", None) == "data":
        resolved = getattr(prev, "resolved_entities", None) or {}
        levels = {k: resolved.get(k) for k in ("district", "block", "village", "assembly_constituency")}
        if levels["district"] and not (levels["block"] or levels["village"]):
            items.append("Break that down by block")
        elif not any(levels.values()):
            items.append("Break that down by district")
        items.append("Compare with the previous financial year")
    starters = (getattr(edge, "_SCHEME_STARTERS", {}) or {}).get(scheme) or list(edge.STARTERS)
    for s in starters:
        if len(items) >= 5:
            break
        if s not in items:
            items.append(s)
    return items


def _c15_reply(kind: str, answer: str, prev, *, chips: "list | None" = None) -> dict:
    return {"route": "edge", "intent": "EDGE", "confidence": "high", "edge_type": kind,
            "answer": answer, "suggestions": chips if chips is not None else _c15_chips(prev),
            "context_dependent": True, **_empty_data_fields()}


def _c15_number_set(text: str) -> set:
    return {n.replace(",", "") for n in _c15_numbers(text or "")}


_C15_EXPLAIN_PROMPT = """You are Megh One AI, explaining your own previous answer to a Meghalaya government officer, in plain and friendly English.
Scheme: {scheme} — {meaning}.
The officer asked: "{question}"
You answered: "{answer}"
The rows behind it: {rows}
Scope: {scope}
Now the officer says: "{typed}"

Write 2 to 4 short sentences that explain what the figure means: what is counted, for which area and period, and that it comes from {scheme}'s own records. Use ONLY numbers that appear above — never add, estimate, convert or compare numbers. Do not repeat the question. End with one short offer of what you can do next (a breakdown by district or block, another year, another place).
Explanation:"""


_C15_EXPLAIN_KNOWLEDGE_PROMPT = """You are Megh One AI, explaining your own previous answer to a Meghalaya government officer, in plain and friendly English.
Scheme: {scheme} — {meaning}.
The officer asked: "{question}"
You answered: "{answer}"
Now the officer says: "{typed}"

Say the same thing again in 2 to 4 short, simple sentences, as you would to a colleague — no jargon, no new facts, no numbers that are not in the answer above. End with one short offer: which part they would like in more detail, or that you can look up the scheme's figures for a place.
Explanation:"""


def _c15_explain_fallback(prev, scheme: "str | None") -> str:
    scope = _c15_scope_line(prev)
    meaning = _C15_SCHEME_MEANING.get(scheme or "", "")
    if getattr(prev, "route", None) == "knowledge":
        # A rules answer, not a figure: say what it was about and offer detail.
        about = f" about {scheme}" if scheme else ""
        return (f"My last answer{about} was: {collapse_ws(getattr(prev, 'answer', '') or '')} "
                "Tell me which part is unclear and I'll put it more simply — or ask me for the scheme's "
                "figures for a district, block or village.")
    first = f"My last answer — {collapse_ws(getattr(prev, 'answer', '') or '')}"
    first += f" — is {scheme}'s own recorded figure" if scheme else " — comes straight from the scheme data"
    first += f" for {scope}." if scope else "."
    second = f" {scheme} covers {meaning}." if meaning else ""
    return (first + second + " Tell me which part is unclear — the number, the area or the period — and I'll "
            "go through it, or I can break it down by district or block.")


async def _c15_explain(prev, typed: str) -> str:
    """The 9B's plain-words explanation of the previous answer, grounded on that answer:
    every number it says must already be in the question, the answer or the rows, or the
    deterministic fallback is used instead."""
    scheme = _c15_scheme(prev)
    fallback = _c15_explain_fallback(prev, scheme)
    if not getattr(settings, "LLM_REFERENCE_ENABLED", True):
        return fallback
    allowed = _c15_number_set(" ".join([getattr(prev, "question", "") or "", getattr(prev, "answer", "") or "",
                                        getattr(prev, "result_summary", "") or ""]))
    template = _C15_EXPLAIN_KNOWLEDGE_PROMPT if getattr(prev, "route", None) == "knowledge" else _C15_EXPLAIN_PROMPT
    prompt = template.format(
        scheme=scheme or "the scheme", meaning=_C15_SCHEME_MEANING.get(scheme or "", "its recorded figures"),
        question=getattr(prev, "question", "") or "", answer=collapse_ws(getattr(prev, "answer", "") or ""),
        rows=getattr(prev, "result_summary", "") or "(a single figure)", scope=_c15_scope_line(prev) or "as answered",
        typed=collapse_ws(typed or ""))
    try:
        out = await llm.call_rewriter(prompt, max_tokens=220,
                                      timeout=getattr(settings, "LLM_REFERENCE_TIMEOUT_SECONDS", 8), role="explain")
    except Exception as e:  # noqa: BLE001 — the fallback always answers
        logger.warning("explain call failed (%s) — using the fallback", e)
        return fallback
    out = collapse_ws((out or "").split("\nExplanation:")[-1]).strip().strip('"')
    if not (40 <= len(out) <= 900) or any(c in out for c in "{}[]`<>"):
        context_budget.log_decision("meta", kind="explain", guard="shape")
        return fallback
    if not _c15_number_set(out) <= allowed:
        context_budget.log_decision("meta", kind="explain", guard="numbers")
        return fallback
    return out


_C15_MISREAD_WORDING = [
    "Sorry — I read your message as “{q}” and answered that.",
    "My mistake — I took your message to mean “{q}”.",
    "Sorry, I misread you: I answered “{q}” instead.",
]


def _c15_rotate(session, kind: str) -> int:
    if session is None:
        return 0
    mem = topic_memory._memory(session)
    replies = mem.setdefault("replies", {})
    i = int(replies.get(kind, 0))
    replies[kind] = i + 1
    return i


def _c15_misread_answer(prev, session) -> str:
    i = _c15_rotate(session, "misread")
    # Quote what was understood only when the previous turn was an answer — never
    # the bot's own apology or a greeting (live 2026-10-18: "you are not
    # understanding me" quoted "why you are not giving this thing").
    answered = prev is not None and getattr(prev, "route", None) in _ANTECEDENT_ROUTES
    q = collapse_ws(getattr(prev, "question", "") or "") if answered else ""
    if q:
        first = _C15_MISREAD_WORDING[i % len(_C15_MISREAD_WORDING)].format(q=q.rstrip(" ?."))
    else:
        first = "Sorry — I didn't get that right."
    ask = ("Tell me in your own words what you want — the scheme, the place (a district, block or village) and "
           "the financial year — and I'll get it. For example: “PMAY-G houses completed in Ri Bhoi in 2023-24”.")
    return f"{first} {ask}"


def _c15_recap_answer(prev) -> str:
    q = collapse_ws(getattr(prev, "question", "") or "").rstrip(" ?.")
    ans = (getattr(prev, "answer", "") or "").strip()
    scope = _c15_scope_line(prev)
    lines = [f"Here's what I said last, in reply to “{q}”:" if q else "Here's what I said last:", "", ans]
    if scope and getattr(prev, "route", None) == "data":
        lines += ["", f"That covers {scope}."]
    return "\n".join(lines)


# One measure per scheme for the "put it in context" chips. A chip is sent as the
# message itself, so it must be a question the pipeline answers as typed: a
# single-measure breakdown works for every scheme; MGNREGA's two-fact compare by
# block or by year does not (KI-311, live 2026-10-18).
_C15_HEADLINE_MEASURE = {
    "MGNREGA": "MGNREGA person-days", "PMAY-G": "PMAY-G houses completed",
    "Focus Plus": "Focus Plus amount disbursed", "CM Elevate": "CM Elevate applications",
    "Focus Legacy": "Focus Legacy amount paid", "CM Elevate Legacy": "CM Elevate Legacy amount disbursed",
}


def _c15_reason_chips(prev) -> list:
    resolved = getattr(prev, "resolved_entities", None) or {}
    scheme = _c15_scheme(prev)
    measure = _C15_HEADLINE_MEASURE.get(scheme or "")
    year = _c15_scope_line_year(resolved)
    items = []
    if measure:
        block, village, district = resolved.get("block"), resolved.get("village"), resolved.get("district")
        if block and not village:
            parent = district or _c15_entity_resolver.block_parent_district(str(block), scheme or "")
            if parent:
                items.append(f"{measure} by block in {str(parent).title()}{year}")
        elif village and block:
            items.append(f"{measure} by village in {str(block).title()} block{year}")
        elif district and not block:
            items.append(f"{measure} by district{year}")
        elif not any((block, village, district)):
            items.append(f"{measure} by district{year}")
    items.append("Compare with the previous financial year")
    if scheme != "MGNREGA":
        items.append("Show every financial year, year by year")
    for s in (getattr(edge, "_SCHEME_STARTERS", {}) or {}).get(scheme) or []:
        if len(items) >= 5:
            break
        if s not in items:
            items.append(s)
    return items


def _c15_scope_line_year(resolved: dict) -> str:
    try:
        y = _scope_banner_year(resolved)
    except Exception:  # noqa: BLE001
        return ""
    return f" in {y}" if y else ""


def _c15_reason_answer(prev) -> str:
    scheme = _c15_scheme(prev)
    scope = _c15_scope_line(prev)
    held = f"{scheme}'s records" if scheme else "the scheme records"
    where = f" for {scope}" if scope else ""
    return (f"I can't say why — {held} hold the figures{where}, not the reasons behind them. "
            "What I can do is put the figure in context: compare it with the other places at the same level, "
            "with other financial years, or with the state total. Pick one below, or tell me what to compare it with.")


def _c15_suggest_answer(prev) -> str:
    scheme = _c15_scheme(prev)
    items = _c15_chips(prev)
    head = f"Here are some things you could ask next about {scheme}:" if scheme else \
        "Here are some things you could ask me:"
    return "\n".join([head, ""] + [f"- {s}" for s in items] + ["", "Tap one, or ask in your own words."])


async def _conversation_meta_answer(raw_question: str, prev, session) -> "dict | None":
    """The reply to a message about the conversation itself (recap / explain / misread /
    suggest), or None. A correction or a breakdown is not answered here: the follow-up
    stage turns it into the question to run (_meta_question)."""
    kind = _meta_kind(raw_question, prev)
    if kind not in ("recap", "explain", "misread", "suggest", "reason"):
        return None
    context_budget.log_decision("meta", kind=kind, prev_route=getattr(prev, "route", None))
    if kind == "recap":
        reply = _c15_reply("recap", _c15_recap_answer(prev), prev)
    elif kind == "explain":
        reply = _c15_reply("explain", await _c15_explain(prev, raw_question), prev)
    elif kind == "misread":
        reply = _c15_reply("misread", _c15_misread_answer(prev, session), prev)
    elif kind == "reason":
        reply = _c15_reply("reason", _c15_reason_answer(prev), prev, chips=_c15_reason_chips(prev))
    else:
        reply = _c15_reply("suggest", _c15_suggest_answer(prev), prev)
    # An aside: the next message still continues the topic
    # (conversation_layer.resume_after_small_talk reads this).
    if session is not None:
        topic_memory._memory(session)["aside"] = raw_question
    return reply


# ── "What is going on in Dalu block?" — a place overview ────────────────────
# Live 2026-10-18: "tell me what is going on in my block" (+ MGNREGA) ran as free-form
# SQL that joined MGNREGA's two facts and failed every repair, then fell to the KB;
# "overview of …" / "key figures for …" went straight to the KB. A place overview is
# the scheme's headline figures for that place, asked the way the pipeline already
# answers (MGNREGA's two-CTE compare, PMAY-G's house-status facts, one query elsewhere).
_C15_OVERVIEW = [
    ("going", "on"), ("overview",), ("situation",), ("progress",), ("performance",), ("key", "figures"),
    ("summary",), ("happening",), ("update", "on"), ("how", "is"), ("how", "are"), ("doing",), ("status", "of"),
    ("report", "on"), ("picture",), ("tell", "me", "about"), ("know", "about"),
]
_C15_OVERVIEW_TEMPLATES = {
    "MGNREGA": "Compare expenditure and person-days in {place}{year}",
    "PMAY-G": "PMAY-G house status in {place}{year}",
    "Focus Plus": "Total Focus Plus amount disbursed and number of beneficiaries in {place}{year}",
    "CM Elevate": "Number of CM Elevate applications by status in {place}",
    "Focus Legacy": "Total Focus Legacy amount paid and number of producer groups in {place}{year}",
    "CM Elevate Legacy": "Total CM Elevate Legacy amount disbursed and number of beneficiaries in {place}{year}",
}


def _overview_question(question: str) -> "tuple[str, str] | None":
    """(the headline-figures question for the place, the line that opens the answer)
    when `question` asks for an overview of ONE district or block under ONE scheme
    and names no measure of its own; else None."""
    ws = _c15_words(question)
    if not _c15_has(ws, _C15_OVERVIEW):
        return None
    if _measure_labels(question) or context_policy.metric_families(question):
        return None
    places = named_places(question)
    if len(places) != 1:
        return None
    schemes = _named_or_inferred_schemes(question)
    if len(schemes) != 1 or schemes[0] not in _C15_OVERVIEW_TEMPLATES:
        return None
    (canon, dim), = places.items()
    place = f"{canon.title()} {dim}" if dim in ("block", "district") else canon.title()
    years = context_policy.extract_year_keys(question)
    year = ""
    if len(years) == 1:
        y = int(list(years)[0])
        year = f" in FY {y}-{str(y + 1)[-2:]}"
    scheme = schemes[0]
    return (_C15_OVERVIEW_TEMPLATES[scheme].format(place=place, year=year),
            f"Here's an overview of {place} under {scheme}:")


# ── "compare with last year" when no year is in play ────────────────────────
# Live 2026-10-18: after an all-years overview of Dalu block, "ok compare with last
# year" was rewritten "… for the last year", the SQL ignored it, and the same figure
# came back. With a year in play, context_manager.substitute_references turns "last
# year" into the FY before it; with none there is nothing to count back from, so ask —
# with the scheme's own financial years as chips (a typed year merges back the same
# way as any year pause).
_C15_RELATIVE_YEAR = [("last", "year"), ("previous", "year"), ("this", "year"), ("current", "year"),
                      ("last", "fy"), ("previous", "fy"), ("year", "before"), ("earlier", "year")]
_C15_COMPARE_WORDS = frozenset("compare comparison compared versus vs against difference change trend".split())


def _c15_fy(label: str) -> str:
    return f"FY {label}"


def _relative_year_clarification(raw_question: str, prev, thread_state) -> "ClarificationNeeded | None":
    ws = _c15_words(raw_question)
    if not _c15_has(ws, _C15_RELATIVE_YEAR) or len(ws) > 14:
        return None
    if context_policy.extract_year_keys(raw_question) or _mentions_scheme(raw_question) or named_places(raw_question):
        return None
    if getattr(thread_state, "year", None) is not None:
        return None     # substitute_references counts back from it
    scheme = _c15_scheme(prev)
    years = list(_SCHEME_DATA_YEARS.get(scheme or "", []) or [])
    if len(years) < 2:
        return None
    stem = _c05_statewide_stem(getattr(prev, "question", "") or "")
    if not stem:
        return None
    latest_first = list(reversed(years))
    # One year per chip. A two-year question for one MGNREGA block comes back with
    # the later year only (KI-311, live 2026-10-18), so a "FY a vs FY b" chip would
    # promise a comparison the pipeline does not give; the officer picks the year
    # they meant and asks "and the year before?" next. MGNREGA's "for each
    # financial year" fails the same way, so that chip is for the other schemes.
    options = [{"label": _c15_fy(y), "question": f"{stem} for {_c15_fy(y)}"} for y in latest_first[:3]]
    if scheme != "MGNREGA":
        options.append({"label": "Every financial year, year by year", "question": f"{stem} for each financial year"})
    place = _c15_scope_line(prev)
    covered = f" for {place}" if place else ""
    e = ClarificationNeeded(
        f"Which year do you mean by “last year”? My last answer covered all financial years{covered}. "
        f"Pick a year below, or name it (for example, \"{_c15_fy(latest_first[1])}\").",
        options=options, rule="year-not-specified")
    e.stem = stem
    return e


# ── Roll-up: "back to the district level" / "and statewide?" (E3) ───────────
# Live 2026-10-18 (superadmin): after "only Mawphlang", "back to the district level"
# and "and for the whole district?" came back with the BLOCK figure labelled as the
# district — the rewrite kept the block filter. A roll-up names no place, so it is
# resolved here from the previous turn's entities: block -> its parent district,
# village -> its block, anything -> all of Meghalaya. No model call.
_C15_ROLLUP_DISTRICT = [("district", "level"), ("whole", "district"), ("entire", "district"), ("the", "district"),
                        ("district", "total"), ("district", "as", "a", "whole"), ("back", "to", "district"),
                        ("full", "district"), ("district", "figure"), ("district", "overall")]
_C15_ROLLUP_BLOCK = [("block", "level"), ("whole", "block"), ("entire", "block"), ("the", "block"),
                     ("block", "total"), ("back", "to", "block"), ("full", "block"), ("block", "figure")]
_C15_ROLLUP_STATE = [("state", "level"), ("whole", "state"), ("entire", "state"), ("statewide",), ("state", "wide"),
                     ("all", "of", "meghalaya"), ("whole", "of", "meghalaya"), ("entire", "meghalaya"),
                     ("state", "total"), ("state", "figure"), ("for", "the", "state"), ("meghalaya", "total"),
                     ("overall", "state"), ("at", "state")]


def _c15_swap_place(question: str, old: str, new: str) -> "str | None":
    """`question` with the place `old` (any case, with or without its level word)
    replaced by `new`; None when `old` is not in it."""
    low = (question or "").lower()
    o = (old or "").lower().strip()
    if not o or o not in low:
        return None
    # Every form, longest first: "in East Khasi Hills … for East Khasi Hills
    # district" must lose both (live 2026-10-18: one was left and "statewide"
    # became a district question that the verifier refused).
    out = question
    for form in (f"{o} block", f"{o} village", f"{o} district", o):
        if form in out.lower():
            out = _c04_replace_ci(out, form, new)
    return collapse_ws(out)


_C15_PLURAL_DIMS = frozenset("villages blocks districts constituencies".split())


def _c15_is_breakdown_question(text: str) -> bool:
    """"Which villages in Mawphlang block had …", "… by block in …", "… for each
    district": a question whose answer is a list, not one figure."""
    ws = _c15_words(text)
    if _C15_PLURAL_DIMS & set(ws) or "wise" in ws:
        return True
    return any(ws[i] in ("by", "each", "every", "per") and ws[i + 1] in _C15_DIMENSION_WORDS
               for i in range(len(ws) - 1))


def _c15_rollup_plan(*levels: str) -> "context_policy.MergePlan":
    """A merge plan that CLEARs the levels rolled past, so resolve_entities does
    not inherit them from the previous turn (prior_resolved) — the mechanism
    that put the block filter back under a rolled-up question (live 2026-10-18)."""
    plan = context_policy.MergePlan(kind=context_policy.GEOGRAPHY_CHANGE)
    for lvl in levels:
        plan.actions[lvl] = context_policy.CLEAR
        plan.reasons[lvl] = "rolled up past this level"
    return plan


def _c15_earlier_data_turns(prev, turns, session) -> list:
    """The topic's earlier DATA turns, newest first. On the server a session holds
    only its last turn (session_sync rehydrates from the snapshot every request),
    so the durable topic ledger is read first; `turns` is the in-process list."""
    out: list = []
    seen: set = set()
    want = set(getattr(prev, "schemes", None) or [])

    def _add(t):
        q = getattr(t, "question", "") or ""
        if (getattr(t, "route", None) == "data" and q and q not in seen
                and set(getattr(t, "schemes", None) or []) == want):
            seen.add(q)
            out.append(t)
    try:
        if session is not None:
            entries = sorted(topic_memory._ledger_entries(topic_memory._memory(session)),
                             key=lambda ke: ke[1].get("n") or 0, reverse=True)
            for _k, e in entries:
                if e.get("route") == "data" and e.get("turn"):
                    _add(topic_memory._turn_from(e["turn"]))
    except Exception:  # noqa: BLE001 — the ledger is a bonus; the turn list still works
        logger.warning("rollup: ledger read failed — using session.turns", exc_info=True)
    for t in reversed(list(turns or [])[-8:]):
        _add(t)
    return out


def _rollup_question(raw_question: str, prev, turns=None, session=None) -> "tuple[str, str, object] | None":
    """(the topic's last aggregate question rolled up one or more levels, the level
    name, the merge plan that clears the levels rolled past) or None. A breakdown
    question ("which villages …") is not rolled up itself: the figure the officer
    wants is the aggregate, so the last aggregate question of the same scheme is."""
    ws = _c15_words(raw_question)
    if not ws or len(ws) > 10 or getattr(prev, "route", None) != "data":
        return None
    if named_places(raw_question) or _mentions_scheme(raw_question) or context_policy.extract_year_keys(raw_question):
        return None
    if _c15_breakdown_dimension(raw_question):
        return None                                  # "by block" is a breakdown, not a roll-up
    scheme = _c15_scheme(prev)
    base = prev
    if _c15_is_breakdown_question(getattr(prev, "question", "") or ""):
        for t in _c15_earlier_data_turns(prev, turns, session):
            if not _c15_is_breakdown_question(getattr(t, "question", "") or ""):
                base = t
                break
    resolved = dict(getattr(base, "resolved_entities", None) or {})
    for k, v in (getattr(prev, "resolved_entities", None) or {}).items():
        resolved.setdefault(k, v)                    # the breakdown's own block / district still count
    block, village, district = resolved.get("block"), resolved.get("village"), resolved.get("district")
    pq = getattr(base, "question", "") or ""
    if _c15_has(ws, _C15_ROLLUP_STATE):
        q = None
        for canon in named_places(pq):
            q = _c15_swap_place(q or pq, canon, "all of Meghalaya") or q
        if q is None and village:
            q = _c15_swap_place(pq, str(village), "all of Meghalaya")
        return ((q or f"{pq.rstrip(' ?.')} for all of Meghalaya"), "state",
                _c15_rollup_plan("district", "block", "village"))
    if _c15_has(ws, _C15_ROLLUP_DISTRICT) and (block or village):
        parent = district or (_c15_entity_resolver.block_parent_district(str(block), scheme or "") if block else None)
        if not parent:
            return None
        base_resolved = getattr(base, "resolved_entities", None) or {}
        if (not base_resolved.get("block") and not base_resolved.get("village")
                and str(parent).upper() in named_places(pq)):
            q = pq                                   # the base question is already the district's
        else:
            q = None
            for name in (village, block):
                if name:
                    q = _c15_swap_place(q or pq, str(name), f"{str(parent).title()} district") or q
        return ((q or f"{pq.rstrip(' ?.')} for {str(parent).title()} district"), "district",
                _c15_rollup_plan("block", "village"))
    if _c15_has(ws, _C15_ROLLUP_BLOCK) and village and block:
        q = _c15_swap_place(pq, str(village), f"{str(block).title()} block")
        return (q or f"{pq.rstrip(' ?.')} for {str(block).title()} block"), "block", _c15_rollup_plan("village")
    return None


# ── "compare with pmay" after a figure: a cross-scheme comparison in the same scope ──
# Live 2026-10-18 (user report): "Total MGNREGA person-days in FY 2023-24" then
# "compare with pmay" answered PMAY-G alone, over all financial years — the model
# rewrite swapped the scheme and lost the year. A comparison keeps the scheme the
# officer was on and adds the named one, in the previous answer's place and year, as
# the question app/cross_scheme.py answers deterministically ("Compare MGNREGA and
# PMAY-G in all of Meghalaya in FY 2023-24"), which also says when one scheme has no
# data for that year. The measure is left out on purpose: the comparison shows each
# scheme's own headline figure side by side (person-days are MGNREGA's alone).
_C15_COMPARE_CUES = frozenset("compare compared comparison comparing vs versus against alongside".split())
_C15_COMPARE_FILLERS = frozenset("ok okay so and now then please pls it this that the with to for of me us scheme "
                                 "schemes data figure figures number numbers one too also as well how does do".split())


def _compare_with_scheme_question(raw_question: str, prev) -> "str | None":
    """"compare with pmay" / "vs Focus Plus" / "and compared to CM Elevate?" right
    after a single-scheme DATA answer -> "Compare <that scheme> and <named scheme>
    in <place> in <FY>", or None (no compare cue, no or several named schemes, the
    same scheme, a bare "Focus", or anything else asked in the same breath)."""
    ws = _c15_words(raw_question)
    if not ws or len(ws) > 12 or getattr(prev, "route", None) != "data":
        return None
    if not (_C15_COMPARE_CUES & set(ws)):
        return None
    prev_schemes = list(getattr(prev, "schemes", None) or [])
    if len(prev_schemes) != 1:
        return None
    # An exact name wins; the fuzzy reading is for "pmay" / "mgnrega"-style spellings
    # only ("CM Elevate Legacy" must not also count as a fuzzy "CM Elevate").
    named = set(_exact_schemes(raw_question)) or set(_fuzzy_named_schemes(raw_question) or [])
    if len(named) != 1:
        return None
    other = named.pop()
    if other == prev_schemes[0]:
        return None
    if named_places(raw_question) or context_policy.extract_year_keys(raw_question):
        return None                                  # a new place or year: not a plain comparison
    # Nothing else may be asked: the words left after the cue, the fillers and the
    # scheme's own name must be none.
    scheme_words = set()
    for pat in _SCHEME_NAME_MATCHER.values():
        for h in pat.finditer(raw_question or ""):
            scheme_words |= set(_c15_words(h.group(0)))
    left = [w for w in ws if w not in _C15_COMPARE_CUES and w not in _C15_COMPARE_FILLERS
            and w not in scheme_words and not _is_known_scheme_word(w)]
    if left:
        return None
    resolved = getattr(prev, "resolved_entities", None) or {}
    place = _scope_banner_place(resolved)
    year = _scope_banner_year(resolved)
    scope = f" in {place if place != 'All of Meghalaya' else 'all of Meghalaya'}"
    if year:
        scope += f" in {year}"
    return f"Compare {prev_schemes[0]} and {other}{scope}"


def _is_known_scheme_word(w: str) -> bool:
    """A word that only ever spells a scheme ("pmay", "mgnrega", "elevate", "focus",
    "plus", "legacy", "cm"), so a fuzzy name leaves nothing behind."""
    return w in {"pmay", "pmayg", "pmay-g", "mgnrega", "mnrega", "nrega", "focus", "plus", "legacy", "cm",
                 "elevate", "cmelevate", "focusplus", "awaas", "awas", "g"}


# ── "pie chart" / "why are you giving a line chart?" / "give me a wide frame" ──
# Live 2026-10-19 16:00-16:02, after "How many households provided hundred days of
# work in MGNREGA ... by district as a chart":
#   "But give me only pie chart."   -> the model rewrite dropped "by district": one
#                                      statewide figure, nothing to slice
#   "So I asked about pie chart, right? But why you are giving line chart? Give me a
#    wide frame, okay."             -> routed to the scheme documents, which "do not
#                                      contain information about chart types"
# A message that only asks HOW to show the last answer (a chart type, a table, a
# bigger chart) is the previous data question again, with that view. A type named in
# a "why ... giving X" clause is the one the officer did NOT want. Read on words.
_C15_CHART_NOUNS = frozenset("graph graphs chart charts plot plots diagram visual visualise visualize "
                             "visualisation visualization graphically pictorial".split())
_C15_VIEW_TYPES = {"pie": "pie", "donut": "doughnut", "doughnut": "doughnut", "line": "line", "bar": "bar",
                   "bars": "bar", "column": "bar", "stacked": "stacked", "table": "table", "tabular": "table",
                   # written as one word ("I want only in Barchart", live 2026-10-19 16:00)
                   **{t + n: v for t, v in (("pie", "pie"), ("donut", "doughnut"), ("doughnut", "doughnut"),
                                            ("line", "line"), ("bar", "bar"), ("column", "bar"))
                      for n in ("chart", "graph", "charts", "graphs")}}
_C15_VIEW_PHRASE = {"pie": "a pie chart", "doughnut": "a donut chart", "line": "a line chart", "bar": "a bar chart",
                    "stacked": "a stacked bar chart", "table": "a table", "chart": "a chart"}
_C15_WIDE_WORDS = frozenset("wide wider widescreen big bigger large larger enlarge enlarged fullscreen expand "
                            "expanded frame full screen size".split())
_C15_VIEW_COMPLAINT = frozenset("why wrong asked told said instead not didn didnt t".split())
# Everything else such a message is made of. "only" / "above query" / "right?" carry no ask.
_C15_VIEW_FILLER = _C15_FILLERS | _C15_EMPTY_OBJECT | _C15_VIEW_COMPLAINT | frozenset(
    "i we you u are is was were be am want wanted need would like can could give giving gave given show showing "
    "shown showed make draw display convert change put see view only just same above previous last earlier query "
    "result results as in on into with using form format type kind style version one also too do did does "
    "should will okay ok right yes yeah why about told me us your you're its it's s let".split())


def _chart_view_request(raw_question: str) -> "tuple[str | None, bool, set] | None":
    """(view, wide, shown) when the message asks only how to show the last answer, else
    None. view is a _C15_VIEW_PHRASE key or None (only "wider", or only a complaint about
    the type shown); shown = the types named as the wrong ones ("why ... giving X")."""
    ws = _c15_words(raw_question)
    if not ws or len(ws) > 30:
        return None
    if any(w not in _C15_VIEW_FILLER and w not in _C15_CHART_NOUNS and w not in _C15_VIEW_TYPES
           and w not in _C15_WIDE_WORDS and w != "meghalaya" for w in ws):
        return None
    named = [(i, _C15_VIEW_TYPES[w]) for i, w in enumerate(ws) if w in _C15_VIEW_TYPES]
    # "line" / "bar" / "column" alone mean other things; they need a chart noun beside them
    named = [(i, t) for i, t in named
             if t in ("pie", "doughnut", "stacked", "table") or ws[i] not in ("line", "bar", "bars", "column")
             or any(x in _C15_CHART_NOUNS for x in ws[i + 1:i + 3])]
    wide = any(w in _C15_WIDE_WORDS for w in ws)
    noun = any(w in _C15_CHART_NOUNS for w in ws)
    if not named and not noun and not wide:
        return None
    # a type in a "why ... giving X" clause is the one shown, not the one wanted
    whys = [i for i, w in enumerate(ws) if w == "why"]
    shown = {t for i, t in named if any(j < i and "why" not in ws[j + 1:i] and i - j <= 8 for j in whys)}
    wanted = [t for _, t in named if t not in shown]
    if wanted:
        return wanted[0], wide, shown
    return ("chart" if noun and not named else None), wide, shown


def _c15_strip_view_phrase(question: str) -> str:
    """The question without its "as a pie chart" / "in a graph" / "as a table" phrase."""
    raw = (question or "").strip().split()
    low = ["".join(c for c in w.lower() if c.isalnum()) for w in raw]
    idx = next((i for i, w in enumerate(low) if w in _C15_CHART_NOUNS or w in ("table", "tabular")), None)
    if idx is None:
        return (question or "").strip()
    start = idx
    while start > 0 and (low[start - 1] in _C15_VIEW_TYPES or low[start - 1] in ("a", "an", "the", "as", "in", "only")):
        start -= 1
    out = " ".join(raw[:start] + raw[idx + 1:]).strip()
    return out.rstrip(" ,.;:!?")


def _chart_view_question(raw_question: str, prev, turns=None) -> "tuple[str, str | None, bool] | None":
    """(question, preface, wide) re-running the previous data question with the view
    asked for, or None. The type comes from this message, else from the officer's last
    view request in the conversation."""
    if prev is None or getattr(prev, "route", None) != "data" or not getattr(prev, "question", None):
        return None
    req = _chart_view_request(raw_question)
    if req is None:
        return None
    view, wide, shown = req
    if "meghalaya" in _c15_words(raw_question):
        resolved = getattr(prev, "resolved_entities", None) or {}
        if any(resolved.get(k) for k in ("district", "block", "village", "village_code", "district_list")):
            return None                              # a new scope: not a view request
    if view is None or (view == "chart" and shown):
        # the officer's last view request in this conversation, never the type complained of
        view = None
        for t in reversed(list(turns or [])):
            r = _chart_view_request(getattr(t, "raw_question", None) or getattr(t, "question", "") or "")
            if r is not None and r[0] and r[0] != "chart" and r[0] not in shown:
                view = r[0]
                break
        if view is None and shown:
            view = "bar" if "bar" not in shown else "pie"
    base = _c15_strip_view_phrase(prev.question)
    question = f"{base} as {_C15_VIEW_PHRASE[view]}" if view else prev.question
    ws = set(_c15_words(raw_question))
    preface = None
    if ws & {"why", "wrong", "asked", "told", "said"}:
        preface = f"Sorry about that — here it is as {_C15_VIEW_PHRASE[view]}." if view \
            else "Sorry about that — here it is, larger."
    return question, preface, wide


def _attach_preface(result: dict, session) -> None:
    """Open a data / knowledge answer with the apology a correction or breakdown earned
    (session.turn_context["answer_preface"], set in the follow-up stage). The preface
    carries no figures, so the numeric checks on the composed answer are unaffected."""
    ctx = getattr(session, "turn_context", None) if session is not None else None
    if (ctx or {}).get("chart_wide") and isinstance(result, dict) and result.get("route") == "data":
        result["chart_wide"] = True              # "give me a wide frame": the UI draws it larger
    preface = (ctx or {}).get("answer_preface")
    if not preface or not isinstance(result, dict) or result.get("answer_failed"):
        return      # "Sorry — here it is block-wise." must never introduce a failure text
    if result.get("route") in ("data", "knowledge") and result.get("answer"):
        result["answer"] = f"{preface}\n\n{result['answer']}"


# ── Coverage, greeting back, and referring back (Conversational Memory approach, 2026-10-19) ──
# documents/Megh_One_AI_Conversational_Memory_Approach.pdf. Facts come from rules and
# SQL; these only add wording around them, so every number below is a result value.

_C15_YEAR_WORDS = frozenset(("year", "years", "fy", "fys"))
_C15_AREA_WORDS = frozenset(("district", "districts", "area", "areas"))
_C15_HAVE_WORDS = [("do", "you", "have"), ("do", "you", "cover"), ("are", "available"), ("is", "available"),
                   ("available",), ("are", "covered"), ("is", "there", "data"), ("are", "there"),
                   ("can", "i", "see"), ("can", "i", "view"), ("can", "i", "access"), ("can", "i", "check"),
                   ("can", "i", "ask"), ("do", "i", "have"), ("have", "i", "got"), ("you", "have", "data")]
# "which district has the most job cards" is a data question, not a coverage one.
_C15_DATA_WORDS = frozenset("most highest lowest least top best worst max min more less many much total number "
                            "count sum average rank ranking compare".split())


def _coverage_kind(raw_question: str) -> "str | None":
    """"years" for "which years do you have for MGNREGA?", "areas" for "which
    districts can I see?", else None (§8.3: coverage is answered from the
    registry, not by the pipeline, which asked "which scheme?")."""
    ws = _c15_words(raw_question)
    if not ws or ws[0] not in ("which", "what", "for", "tell", "list", "show") or len(ws) > 12:
        return None
    if set(ws) & _C15_DATA_WORDS or not _c15_has(ws, _C15_HAVE_WORDS):
        return None
    if set(ws) & _C15_YEAR_WORDS:
        return "years"
    if set(ws) & _C15_AREA_WORDS:
        return "areas"
    return None


def _c15_join(items: list) -> str:
    items = [str(x) for x in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _c15_year_span(years: list) -> str:
    """"FY 2022-23 to 2025-26" when the years run without a gap, else each year."""
    starts = [_fy_start(y) for y in years]
    if len(years) > 2 and starts == list(range(starts[0], starts[0] + len(starts))):
        return f"FY {years[0]} to {years[-1]}"
    return "FY " + _c15_join(years)


def _coverage_answer(raw_question: str, prev, scope=None) -> "dict | None":
    kind = _coverage_kind(raw_question)
    if kind is None:
        return None
    named = list(_named_schemes(raw_question)) or ([_c15_scheme(prev)] if _c15_scheme(prev) else [])
    if kind == "years":
        lines = []
        for s in (named or list(_SCHEME_DATA_YEARS)):
            years = _SCHEME_DATA_YEARS.get(s)
            if years is None:
                continue
            if not years:
                lines.append(f"{s} has no financial-year split — its figures cover the whole programme")
            else:
                n = len(years)
                lines.append(f"{s} data covers {_c15_year_span(years)} "
                             f"({n} financial year{'s' if n != 1 else ''})")
        if not lines:
            return None
        if len(lines) == 1:
            answer = f"{lines[0]}. Which year would you like to look at?"
        else:
            answer = "Here's what each scheme covers:\n\n" + "\n".join(f"- {x}" for x in lines) + \
                     "\n\nWhich scheme and year would you like to look at?"
        chips = None
        if len(named) == 1 and _SCHEME_DATA_YEARS.get(named[0]):
            yrs = _SCHEME_DATA_YEARS[named[0]]
            starters = (getattr(edge, "_SCHEME_STARTERS", {}) or {}).get(named[0]) or []
            chips = [f"{named[0]} figures for {y}" for y in reversed(yrs[-2:])] + list(starters)[:2]
        return _c15_reply("coverage", answer, prev, chips=chips)
    # areas: the officer's own permitted districts / blocks, else every district
    restricted = scope is not None and bool(getattr(scope, "geo_restricted", False))
    allowed = [str(d).title() for d in (scope.allowed_districts() if restricted else [])]
    blocks = [str(b).title() for b in (scope.allowed_blocks() if restricted else [])]
    if blocks and not allowed:
        answer = f"You can view {_c15_join(blocks)} block{'s' if len(blocks) > 1 else ''}."
        places = blocks
    elif allowed:
        answer = f"You can view {_c15_join(allowed)} district{'s' if len(allowed) > 1 else ''}" + \
                 (f" ({_c15_join(blocks)} block{'s' if len(blocks) > 1 else ''})" if blocks else "") + "."
        places = allowed
    else:
        seen: dict = {}
        for s in (named or ["MGNREGA"]):
            for d in _c15_entity_resolver.all_districts(s):
                seen.setdefault(str(d).title(), None)
        places = list(seen)
        if not places:
            return None
        answer = (f"You can view all {len(places)} districts of Meghalaya: {_c15_join(places)}"
                  " — and their blocks and villages too.")
    answer += " Which one would you like to look at?"
    scheme = named[0] if len(named) == 1 else _c15_scheme(prev)
    what = f"{scheme} figures" if scheme else "Scheme figures"
    chips = [f"{what} for {p}" for p in places[:4]]
    return _c15_reply("coverage", answer, prev, chips=chips)


# A message that opens with a greeting or a thank-you and then asks something
# ("Hi, how many job cards…", "thanks. what about 2023-24?") — §4.1: the answer
# greets back / says "You're welcome" before the figure.
_C15_HELLO_WORDS = frozenset("hi hii hello hey hai hlo namaste namaskar".split())
_C15_THANKS_WORDS = frozenset("thanks thank thankyou thx tq ty dhanyavaad dhanyavad dhanyawad shukriya".split())


def _social_prefix(raw_question: str) -> "str | None":
    ws = _c15_words(raw_question)
    if len(ws) < 3:
        return None
    if ws[0] in _C15_HELLO_WORDS or ws[:2] in (["good", "morning"], ["good", "afternoon"], ["good", "evening"]):
        return "greeting"
    if ws[0] in _C15_THANKS_WORDS or ws[:2] in (["ok", "thanks"], ["okay", "thanks"], ["ok", "thank"],
                                                ["okay", "thank"]):
        return "thanks"
    return None


_C15_HEADLINES_KEPT = 8


def _c15_headline(result: dict) -> "dict | None":
    """The one figure of a single-value data answer: its column, value, scheme,
    year and the rest of its scope, or None."""
    rows = result.get("rows") or result.get("data") or []
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    metrics = [(k, v) for k, v in _row_metrics(rows[0]) if "year" not in str(k).lower()]
    if len(metrics) != 1 or len(result.get("schemes") or []) != 1:
        return None
    resolved = result.get("resolved_entities") or {}
    try:
        year = int(resolved.get("year_key"))
    except (TypeError, ValueError):
        return None
    col, value = metrics[0]
    if not isinstance(value, (int, float)):
        return None
    scope_rest = {k: str(v).upper() for k, v in resolved.items()
                  if v not in (None, "", []) and "year" not in k and isinstance(v, (str, int))}
    return {"col": col, "value": value, "scheme": result["schemes"][0], "year": year, "scope": scope_rest}


def _c15_value_words(col: str, value) -> str:
    unit = _unit_suffix(col)
    if unit:
        _name, word, rupee = unit
        return f"{rupee}{_fmt_num(value)}{word if word == '%' else (' ' + word if word else '')}"
    return _fmt_num(value)


def _callback_sentence(head: dict, earlier: dict) -> str:
    """"That's down from 3,408,697 in FY 2022-23 (about 10.2% lower)." — the change
    is computed here from the two result values, never by a model."""
    cur, old = head["value"], earlier["value"]
    fy = f"FY {earlier['year']}-{(earlier['year'] + 1) % 100:02d}"
    then = _c15_value_words(earlier["col"], old)
    if cur == old:
        return f"That's the same as in {fy} ({then})."
    tail = ""
    if old:
        pct = abs(cur - old) / abs(old) * 100
        if pct >= 0.1:
            tail = f" (about {pct:.1f}% {'higher' if cur > old else 'lower'})"
    return f"That's {'up' if cur > old else 'down'} from {then} in {fy}{tail}."


def _c15_same_figure(a: dict, b: dict) -> bool:
    return a.get("col") == b.get("col") and a.get("scheme") == b.get("scheme") and a.get("scope") == b.get("scope")


def _attach_conversational_touches(result: dict, session, raw_question: "str | None") -> None:
    """Finalize: the greeting back / "You're welcome" a mixed message earned, and a
    callback to the same figure for another year asked earlier in this chat. Both
    are wording around result values; nothing here changes a figure."""
    if isinstance(result, dict) and result.get("route") != "edge" and session is not None:
        # An answered turn ends a run of asides (conversation_replies.restyle: one
        # steer-back per run; no second "anything else?" after two thank-yous).
        replies = (getattr(session, "topics", None) or {}).get("replies")
        if isinstance(replies, dict):
            replies.pop("_last_kind", None)
    if not isinstance(result, dict) or result.get("route") != "data" or result.get("answer_failed") \
            or not result.get("answer") or session is None:
        return
    try:
        from app import topic_memory
        mem = topic_memory._memory(session)
        head = _c15_headline(result)
        if head is not None:
            heads = [h for h in (mem.get("headlines") or []) if isinstance(h, dict)]
            earlier = next((h for h in reversed(heads)
                            if _c15_same_figure(h, head) and h.get("year") != head["year"]), None)
            if earlier is not None:
                fy_old = f"{earlier['year']}-{(earlier['year'] + 1) % 100:02d}"
                if fy_old not in result["answer"]:      # a comparison answer already names it
                    result["answer"] = f"{result['answer'].rstrip()} {_callback_sentence(head, earlier)}"
                    result["context_dependent"] = True
            heads = [h for h in heads if not (_c15_same_figure(h, head) and h.get("year") == head["year"])]
            mem["headlines"] = (heads + [head])[-_C15_HEADLINES_KEPT:]
        prefix = _social_prefix(raw_question or "")
        if prefix:
            name = mem.get("user_name")
            opening = (f"Hello, {name}!" if name else "Hello!") if prefix == "greeting" else "You're welcome!"
            if name:
                result["context_dependent"] = True
            result["answer"] = f"{opening} {result['answer']}"
    except Exception:  # noqa: BLE001 — wording only; the answer stands as written
        logger.warning("_attach_conversational_touches failed (non-fatal)", exc_info=True)
