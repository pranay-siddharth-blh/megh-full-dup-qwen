"""
Conversation layer: the per-conversation decisions taken BEFORE a turn
reaches the caches and the LangGraph pipeline.

The pipeline already understands a conversation (followups, context_manager,
context_policy, topic_memory, the clarification pauses). Five things were
missing, and none of them belongs inside a stage:

  1. Idle expiry. The in-process Session expires after SESSION_TTL_SECONDS,
     but session_sync.sync_in brings the durable snapshot back however old
     it is, so "how many beneficiaries?" the next morning was still answered
     for yesterday's scheme and district. A conversation idle for longer than
     CONTEXT_IDLE_EXPIRY_SECONDS now starts afresh. The chat history (the
     app.conversation_turns rows the sidebar replays) is never touched: only
     what the NEXT question would inherit is dropped.
  2. Reset on request. "Start a new topic", "forget the previous question",
     "let's start again" clear the same context. On its own the message is
     answered with a short acknowledgement; with a question after it
     ("Forget that. How many MGNREGA job cards?") the question runs fresh.
  3. Returning to a topic in plain words. topic_memory restores an earlier
     topic when the message opens with "go back to" / "coming back to". "What
     was the PMAY-G information again?" did not open that way, so it ran as
     a new question with the active topic's context. It is now rewritten to
     the topic_memory form ("Go back to PMAY-G, <PMAY-G's last question>"),
     and topic_memory restores PMAY-G's place, year and last turn as for any
     other return. "What about PMAY-G?" is NOT taken: it is the existing
     scheme swap (KI-180), which re-asks the last question for PMAY-G.
  4. A measure right after a KNOWLEDGE answer. "Tell me about PMAY-G" ->
     "How many beneficiaries are there?" was asked "which scheme?" (live
     2026-10-08). The pipeline has the rewrite for it
     (pipeline._measure_after_knowledge: "... under PMAY-G?"), but only in its
     follow-up branch, which a "how many ..." question never enters
     (looks_like_followup reads "how many" as a standalone question, and
     is_scopeless_followup needs a DATA antecedent). The layer applies that
     same predicate and the same rewrite before the pipeline runs, against
     the antecedent the pipeline will see: the last turn, the restored
     topic's last turn after a bare "go back to PMAY-G", or the named topic's
     for "coming back to PMAY-G, how many beneficiaries?". No antecedent
     scheme, no rewrite: the "which scheme?" pause still asks.
  5. Small talk mid-topic. A "thanks" / "hi" between two questions no longer
     ends the topic: the answer before it stays the follow-up antecedent
     (resume_after_small_talk).

Where it runs: routers.query._answer, right after session_sync.sync_in and
before the caches (prepare_turn). The pipeline, the graph and the database
are not changed. A turn the layer answered or rewrote is never cached: it
means something only in its own conversation.

Clearing the context also deletes a paused LangGraph run for the thread
(pipeline_graph keys it on session_id). Otherwise the next message would be
fed to that run as the reply to a clarification the user abandoned.

Best-effort like the rest of the context layer: any failure leaves the turn
exactly as it would have run without this module.
"""
import dataclasses
import logging
import re
import time
from dataclasses import dataclass

from app import context_budget, topic_memory
from app.config import settings

logger = logging.getLogger(__name__)

# The edge_type of the acknowledgement a bare reset gets.
RESET_EDGE = "context_reset"


# ── Reset ───────────────────────────────────────────────────────────────────

# The reset itself, at the start of the message. Fillers before it ("ok",
# "now", "please") and a "let's" / "can we" opener are allowed.
_RESET_LEAD = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|now|so|alright|right|fine|then|well|please|hey|hi)\b[\s,!.]*)*"
    r"(?:(?:let'?s|let\s+us|can\s+we|could\s+we|shall\s+we|i\s+want\s+to|i'?d\s+like\s+to|please)\s+)?"
    r"(?:"
    r"start\s+(?:a\s+)?(?:new|fresh|another)\s+(?:topic|conversation|chat|discussion|session|subject)"
    r"|start\s+(?:over|again|afresh|fresh|anew|from\s+(?:scratch|the\s+beginning))"
    r"|begin\s+(?:again|afresh|anew)"
    r"|(?:a\s+)?(?:new|fresh)\s+(?:topic|subject|start)"
    r"|change\s+(?:the\s+)?(?:topic|subject)"
    r"|forget\s+(?:about\s+)?(?:"
    r"that|this|it|everything|all(?:\s+(?:of\s+)?(?:that|this|it))?"
    r"|what\s+(?:i|we)\s+(?:said|asked|discussed)(?:\s+(?:before|earlier))?"
    r"|(?:the|my|our|that|this)\s+(?:previous|earlier|last|old|above|current)?\s*"
    r"(?:question|questions|topic|conversation|context|discussion|one|query|chat)"
    r")"
    r"|clear\s+(?:the\s+|my\s+)?(?:context|conversation|history|chat|topic|memory)"
    r"|reset(?:\s+(?:the\s+|my\s+)?(?:context|conversation|chat|topic|memory))?"
    r")"
    r"(?=$|[\s,.:;!?-])",
    re.IGNORECASE,
)
# What may sit after the reset without being a question of its own.
_RESET_TAIL = re.compile(
    r"^(?:please|pls|now|then|ok(?:ay)?|thanks?|thank\s+you|and|so|"
    r"(?:and\s+)?start\s+(?:over|again|afresh|fresh)|(?:and\s+)?start\s+(?:a\s+)?new\s+(?:topic|one|conversation))?$",
    re.IGNORECASE,
)


def parse_reset(question: str) -> "str | None":
    """None when `question` is not a reset; otherwise the question that came
    after it ("" for a bare reset)."""
    q = (question or "").strip()
    m = _RESET_LEAD.match(q)
    if not m:
        return None
    rest = _lead_trim(q[m.end():])
    # "start a new topic and forget the previous one" is still a bare reset.
    while (m2 := _RESET_LEAD.match(rest)) is not None:
        rest = _lead_trim(rest[m2.end():])
    if _RESET_TAIL.match(rest.rstrip(" \t\r\n.!?")):
        return ""
    return rest.strip()


def _lead_trim(text: str) -> str:
    """Drop the punctuation and connective ("and", "then") between a reset
    and what follows it. The end of the text, a question mark included, stays."""
    return re.sub(r"^[\s,.:;!?-]*(?:(?:and|then|so)\b[\s,]*)?", "", text, flags=re.IGNORECASE)


# ── Return to a topic in plain words ────────────────────────────────────────

# The message asks for something seen before: "… again", "remind me …",
# "recap …".
_RECALL_CUE = re.compile(r"\bagain\b|^\s*(?:can\s+you\s+|could\s+you\s+|please\s+)?remind\s+me\b|\brecap\b",
                         re.IGNORECASE)
# Everything that may sit around the scheme name in such a message. What is
# left after removing these and the scheme name must be nothing, so a real
# question ("PMAY-G houses in Ri Bhoi again?") is never taken.
_RECALL_FILLER = re.compile(
    r"\b(?:what|whats|was|were|is|are|the|that|those|this|these|it|info|information|answer|answers|"
    r"details?|data|figures?|numbers?|results?|again|remind|me|about|of|on|for|regarding|show|tell|"
    r"give|repeat|recap|say|can|could|would|will|you|please|pls|once|more|one|time|we|discussed|"
    r"talked|had|got|us|i|asked|question|questions|scheme|topic|discussion|so|ok|okay|and|then|"
    r"now|go|over|summary|summarise|summarize|status|thing|stuff|did|said|earlier|previous|before|"
    r"there|bit|a|an|quick|quickly|briefly)\b",
    re.IGNORECASE,
)


def recall_target(session, question: str) -> "str | None":
    """The earlier topic a plain-words recall ("what was the PMAY-G
    information again?") asks for, or None. Only a topic this conversation
    already holds, and never the one in progress."""
    from app import pipeline  # lazy: pipeline imports topic_memory
    q = (question or "").strip()
    if not q or not _RECALL_CUE.search(q):
        return None
    if topic_memory.parse_switch(q) is not None:
        return None   # already topic_memory's own form
    key = topic_memory.topic_key(pipeline._named_schemes(q))
    if key is None:
        return None
    if _RECALL_FILLER.sub(" ", topic_memory._strip_scheme_words(q)).strip(" \t,.:;!?'\"-()"):
        return None
    mem = topic_memory._memory(session)
    if key not in mem["items"]:
        return None
    # The topic in progress is the last answered turn's (topic_memory files
    # it only when the next turn starts, which is after this).
    active = topic_memory._turn_topic(session.last_turn) or mem.get("active")
    if key == active:
        return None
    return key


def _recall_question(session, key: str) -> str:
    """topic_memory's return form, re-asking the topic's last question so the
    officer sees that information again in the restored context."""
    item = topic_memory._memory(session)["items"].get(key) or {}
    last = ((item.get("last_turn") or {}).get("question") or "").strip()
    return f"Go back to {key}, {last}" if last else f"Go back to {key}"


# ── A measure right after a knowledge answer ────────────────────────────────

def _effective_prev(session):
    """The turn the pipeline will treat as this message's antecedent. After a
    bare "go back to PMAY-G" the last turn is the acknowledgement, and
    topic_memory.checkpoint puts PMAY-G's own last turn back in its place."""
    last = session.last_turn
    mem = topic_memory._memory(session)
    ack = mem.get("ack")
    if ack and last is not None and last.route == "edge" and last.raw_question == ack:
        item = mem["items"].get(mem.get("active") or "") or {}
        if item.get("last_turn"):
            return topic_memory._turn_from(item["last_turn"])
    return last


def _with_scheme(question: str, prev) -> "str | None":
    """pipeline._measure_after_knowledge's own rewrite, for a question its
    follow-up branch would not reach. None when it does not apply."""
    from app import pipeline
    if not question or pipeline.looks_like_followup(question):
        return None   # the pipeline's follow-up branch already does this
    if not pipeline._measure_after_knowledge(question, prev):
        return None
    return f"{question.strip().rstrip(' ?.')} under {prev.schemes[0]}?"


def knowledge_measure_question(session, question: str) -> "str | None":
    """'How many beneficiaries are there?' after a knowledge answer about one
    scheme, as the pipeline would have rewritten it ('… under PMAY-G?'); also
    inside a return ('Coming back to PMAY-G, how many beneficiaries are
    there?'). None when nothing applies."""
    sw = topic_memory.parse_switch(question)
    if sw is not None:
        if not (sw.names and sw.remainder):
            return None
        key = topic_memory.topic_key(sw.names)
        item = topic_memory._memory(session)["items"].get(key or "") or {}
        if not item.get("last_turn"):
            return None   # not a topic of this conversation: runs as it is
        rewritten = _with_scheme(sw.remainder, topic_memory._turn_from(item["last_turn"]))
        return f"Go back to {key}, {rewritten}" if rewritten else None
    return _with_scheme(question, _effective_prev(session))


# ── "What about X?" swaps X's counterpart, not the measure ──────────────────
# Live 2026-10-09: "How many villages are there under MGNREGA in employment for
# West Khasi Hills across all financial years" (530) -> "what about expenditure"
# was rewritten "What is the expenditure under MGNREGA in West Khasi Hills…"
# and answered ₹131.54 crore. "Expenditure" is also a money measure, so the
# follow-up plan replaced the MEASURE; but the previous question named its
# counterpart ("employment" — MGNREGA's other dataset), and "what about X"
# means: put X where its counterpart was, keep everything else (the measure,
# scheme, place, years). When the previous question holds a counterpart of X,
# that word alone is swapped; otherwise the message runs as before.
#
# Each group lists values of ONE kind; each value lists its word forms, aligned
# by position, so "female employees" + "what about men" -> "male employees".
_COUNTERPARTS = [
    [["employment"], ["expenditure"]],
    [["female", "women", "woman"], ["male", "men", "man"]],
    [["sanctioned"], ["completed"], ["incomplete"]],
]
_SWAP_ASK = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|so|and|then|now|also)[\s,]+)*"
    r"(?:(?:what|how)\s+about|same\s+for|now\s+for|and\s+for|for|in)?\s*"
    r"(?:the\s+|in\s+|for\s+|on\s+)?(?P<term>[a-z-]+)"
    r"(?:\s+(?:data|records?|side|one|ones|too|also|instead|please|pls))*\s*[?.!]*\s*$",
    re.IGNORECASE,
)


def _counterpart_forms(term: str):
    """(group, value index, form index) of a word, or None."""
    t = term.lower()
    for group in _COUNTERPARTS:
        for vi, forms in enumerate(group):
            if t in forms:
                return group, vi, forms.index(t)
    return None


def counterpart_swap(session, question: str) -> "str | None":
    """The previous question with X's counterpart replaced by X, for a bare
    "what about X?" — or None when the message is not one, or the previous
    question names no counterpart of X (then the follow-up rewrite decides)."""
    m = _SWAP_ASK.match(question or "")
    if not m:
        return None
    hit = _counterpart_forms(m.group("term"))
    if hit is None:
        return None
    group, new_vi, new_fi = hit
    prev = _effective_prev(session)
    if prev is None or prev.route not in ("data", "knowledge"):
        return None
    base = (prev.question or "").strip()
    if not base:
        return None
    for vi, forms in enumerate(group):
        if vi == new_vi:
            continue
        for fi, form in enumerate(forms):
            rx = re.compile(rf"\b{re.escape(form)}\b", re.IGNORECASE)
            if rx.search(base):
                # the new value in the SAME form as the word it replaces
                new_forms = group[new_vi]
                word = new_forms[fi] if fi < len(new_forms) else new_forms[0]
                return rx.sub(lambda mm: word.capitalize() if mm.group(0)[:1].isupper() else word, base, count=1)
    return None


# ── "Each year, for these schemes" / "why only one year?" ───────────────────
# UI 2026-10-12: "total beneficiaries in MGNREGA, PMAY-G, CM Elevate and Focus
# Plus … in which financial years" got MGNREGA's LATEST year only; "for that
# query, how many beneficiaries in each year for all schemes" failed (the SQL
# model joined the scheme views, the verifier rejected it 3 times, the KB
# answered "no single published list"); and "MGNREGA in the above query …
# only one year … cross verify" was refused by the guardrail model. Asked one
# scheme at a time ("How many MGNREGA beneficiaries were there in each
# financial year?") every scheme answers correctly. So such a follow-up is
# turned into exactly those questions: one per scheme, run one after another,
# their answers merged into one reply and one scheme x year table.
_PER_YEAR_CUE = re.compile(
    r"\b(?:each|every|all|per)\s+(?:the\s+)?(?:particular\s+)?(?:financial\s+)?years?\b|\byear[\s-]?wise\b"
    r"|\bin\s+which\s+(?:financial\s+)?years?\b|\bfinancial\s+years\b"
    r"|\bonly\s+(?:one|1|a\s+single|single)\s+(?:financial\s+)?year\b|\bnot\s+in\s+(?:a\s+)?single\s+year\b"
    r"|\b(?:two|three|four|five|six|seven|2|3|4|5|6|7)\s+(?:financial\s+)?years\b|\bby\s+(?:financial\s+)?year\b",
    re.IGNORECASE)
_ALL_SCHEMES_CUE = re.compile(r"\b(?:all|every|each)\s+(?:the\s+)?schemes?\b|\ball\s+of\s+them\b", re.IGNORECASE)
_REFERS_BACK = re.compile(
    r"\b(?:above|previous|last|earlier|that|this|same)\s+(?:query|queries|question|answer|result|results|data|output)\b"
    r"|\byou\s+(?:have\s+|had\s+)?(?:gave|given|give|showed|shown|said|told|provided)\b"
    r"|\bcross[\s-]?(?:verify|check)\w*|\bre[\s-]?(?:check|verify)\w*|\bverify\b"
    r"|\bwhy\s+(?:are\s+|is\s+)?(?:you\s+)?(?:giving|showing|only)\b",
    re.IGNORECASE)
# (label in the question, pattern, "how many" or "total")
_YEAR_METRICS = [
    ("person-days", r"person[\s-]?days?", "count"),
    ("households", r"households?", "count"),
    ("job cards", r"job\s*cards?", "count"),
    ("houses sanctioned", r"houses?\s+sanction\w*|sanctioned\s+houses?", "count"),
    ("houses completed", r"houses?\s+complet\w*|completed\s+houses?", "count"),
    ("applications", r"applications?|applicants?", "count"),
    ("payments", r"payments?|disbursements?", "count"),
    ("expenditure", r"expenditure|amount\s+spent|\bspen[dt]\b", "money"),
    ("beneficiaries", r"beneficiar\w*", "count"),
]


def _year_metric(*texts) -> "tuple[str, str]":
    for t in texts:
        for label, rx, kind in _YEAR_METRICS:
            if t and re.search(rx, t, re.IGNORECASE):
                return label, kind
    return "beneficiaries", "count"


def per_year_plan(session, question: str) -> "list[str] | None":
    """The per-scheme, per-year questions a follow-up asks for, or None."""
    from app import pipeline
    q = question or ""
    if not _PER_YEAR_CUE.search(q):
        return None
    named = list(pipeline._named_schemes(q))
    prev = _effective_prev(session)
    prev_schemes = list(prev.schemes or []) if prev is not None and prev.route in ("data", "knowledge") else []
    refers = bool(_REFERS_BACK.search(q) or _ALL_SCHEMES_CUE.search(q))
    if not (refers or len(named) >= 2):
        return None   # a plain one-scheme question: the pipeline answers it as it is
    schemes = named
    if _ALL_SCHEMES_CUE.search(q):
        # "all schemes" = every scheme this conversation has discussed, not only
        # the last answer's (which may have narrowed to one).
        seen = []
        for t in list(session.turns)[-8:]:
            if getattr(t, "route", None) in ("data", "knowledge"):
                seen += [s for s in (t.schemes or []) if s not in seen]
        seen += [k for k in (topic_memory._memory(session).get("order") or []) if " + " not in k and k not in seen]
        schemes = named + [s for s in prev_schemes + seen if s not in named]
    elif not named:
        schemes = prev_schemes
    order = list(getattr(pipeline, "SCHEME_CATALOG", []))
    schemes = sorted(dict.fromkeys(schemes), key=lambda s: order.index(s) if s in order else len(order))
    if not schemes:
        return None
    label, kind = _year_metric(q, getattr(prev, "raw_question", "") if prev else "",
                               getattr(prev, "question", "") if prev else "")
    # CM Elevate's applications data has no year; per-year beneficiaries / money
    # are CM Elevate Legacy's (the pipeline pins the same way). Never both.
    if "CM Elevate" in schemes and label != "applications":
        schemes = [s for s in schemes if s != "CM Elevate"]
        if "CM Elevate Legacy" not in schemes:
            schemes.append("CM Elevate Legacy")
        schemes = sorted(schemes, key=lambda s: order.index(s) if s in order else len(order))
    if kind == "money":
        return [f"What was the total {s} {label} in each financial year?" for s in schemes]
    return [f"How many {s} {label} were there in each financial year?" for s in schemes]


_YEARISH_COL = re.compile(r"(?:^|_)(?:year|fy)(?:_|$)|financial", re.IGNORECASE)


def _year_and_value(row: dict) -> "tuple[object, object] | None":
    """(financial year, figure) of one result row; None when the row has no figure."""
    year = next((v for k, v in row.items() if _YEARISH_COL.search(str(k)) and not str(k).endswith("_key")), None)
    if year is None:
        year = next((v for k, v in row.items() if _YEARISH_COL.search(str(k))), None)
    value = None
    for k, v in row.items():
        if _YEARISH_COL.search(str(k)):
            continue
        try:
            float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            continue
        value = v
        break
    return None if value is None else (year, value)


async def answer_many(questions: list, ask) -> dict:
    """Run each question through the pipeline (`ask`), one after another, and
    merge the answers: the text scheme by scheme, one scheme x year table.
    A question that pauses or fails is reported in the text, never guessed."""
    from app import pipeline
    sections, rows, schemes, sqls, notes = [], [], [], [], []
    label = None
    for q in questions:
        scheme = next(iter(pipeline._named_schemes(q)), q)
        label = label or _year_metric(q)[0]
        try:
            r = await ask(q)
        except pipeline.ClarificationNeeded as e:
            notes.append(f"**{scheme}** — needs one more detail: {e.question}")
            continue
        except Exception:  # noqa: BLE001 — one scheme failing must not lose the others
            logger.warning("conversation layer: per-year sub-question failed: %s", q, exc_info=True)
            notes.append(f"**{scheme}** — this figure could not be fetched just now; please ask for it on its own.")
            continue
        text = (r.get("answer") or "").strip()
        if text:
            sections.append(f"**{scheme}** — {text}")
        for s in r.get("schemes") or [scheme]:
            if s not in schemes:
                schemes.append(s)
        if r.get("sql_query"):
            sqls.append(f"-- {scheme}\n{r['sql_query']}")
        for row in r.get("data") or []:
            yv = _year_and_value(row)
            if yv is not None:
                rows.append({"scheme": scheme, "financial_year": yv[0] if yv[0] is not None else "(no year)",
                             (label or "value").replace(" ", "_").replace("-", "_"): yv[1]})
    head = f"{(label or 'Figures').capitalize()} in each financial year, scheme by scheme:"
    answer = "\n\n".join([head] + sections + notes) if (sections or notes) else \
        "I couldn't fetch these figures just now. Please try again in a moment."
    out = {"route": "data", "intent": "DATA", "confidence": "high", "answer": answer,
           **pipeline._empty_data_fields()}
    out.update({"schemes": schemes, "data": rows, "rows": rows, "row_count": len(rows),
                "sql_query": "\n\n".join(sqls),
                "rewritten_question": f"{(label or 'beneficiaries').capitalize()} in each financial year for "
                                      + ", ".join(schemes or [])})
    return out


# ── "What schemes are there?" in any wording ────────────────────────────────
# The pipeline answers the scheme list deterministically
# (pipeline._scheme_listing_answer), but only for the wordings its
# _SCHEME_LISTING_CUE knows. "what schemes are present" got the "which
# scheme?" pause, and "what schmes are present" (typed in the UI, 2026-10-09)
# the off-topic refusal: the misspelt word is no scheme vocabulary, so the
# edge whitelist gate bounced it. Such a request is handed to the pipeline in
# the one wording it answers.
LISTING_QUESTION = "What schemes are available?"

# "scheme(s)" and its usual misspellings, plus "programmes" / "yojanas".
_SCHEME_W = (r"(?:s[ck]?h?e{1,2}m[ae]?s?|sc?hm[ae]?s?|schems?|shcemes?|scemes?|skeems?|scheams?|"
             r"programm?e?s?|yojanas?)")
_PLEASE = r"(?:\s*(?:please|pls|plz|now|currently|here|in\s+(?:this|the)\s+(?:app|system|bot|chat(?:bot)?|portal|data(?:base)?)))*"
_LISTING_ASK = re.compile(
    r"^\s*(?:(?:hi|hello|ok(?:ay)?|so|and|then|tell\s+me|can\s+you\s+tell\s+me|please)[\s,]+)*(?:"
    # what / which (all) schemes are there / present / available / covered ...
    rf"(?:what|which|wat|wht|wich)\s+(?:all\s+|are\s+the\s+|are\s+)?(?:the\s+)?{_SCHEME_W}"
    r"(?:\s+(?:are|r|is|do\s+(?:you|u)|can\s+(?:you|u)|does\s+(?:it|this)|you))?"
    r"(?:\s+(?:there|present|available|avail|avaliable|covered|supported|included|offered|listed|"
    r"have|cover|support|know|handle|answer|provide|show))*"
    # list / show / tell me / give me (all) (the) (available) schemes
    r"|(?:list|show|tell|give|name)\s+(?:me\s+|us\s+)?(?:out\s+)?(?:all\s+)?(?:of\s+)?(?:the\s+)?(?:full\s+)?(?:list\s+of\s+(?:all\s+)?(?:the\s+)?)?"
    rf"(?:available\s+|supported\s+|covered\s+)?{_SCHEME_W}(?:\s+(?:available|covered|supported|you\s+(?:have|cover)))?"
    # available / supported / all schemes; scheme list
    rf"|(?:available|supported|all|list\s+of)\s+{_SCHEME_W}"
    rf"|{_SCHEME_W}\s+(?:list|available|present|covered)"
    # how many schemes (are there / do you cover)
    rf"|how\s+many\s+{_SCHEME_W}(?:\s+(?:are|r|do\s+(?:you|u)))?(?:\s+(?:there|present|available|covered|have|cover))?"
    r")" + _PLEASE + r"\s*[?.!]*\s*$",
    re.IGNORECASE,
)


def listing_question(question: str) -> "str | None":
    """LISTING_QUESTION for a request to list the schemes that the pipeline's
    own listing cue does not recognise; None otherwise (also when a scheme is
    named: "what schemes are like PMAY-G" is not a listing)."""
    from app import pipeline
    q = (question or "").strip()
    if not q or not _LISTING_ASK.match(q):
        return None
    if pipeline._SCHEME_LISTING_CUE.search(q):
        return None   # already answered as the list
    if pipeline._named_schemes(re.sub(_SCHEME_W, " ", q, flags=re.IGNORECASE)):
        return None
    return LISTING_QUESTION


# ── Small talk does not end a topic ─────────────────────────────────────────
# "PMAY-G houses in West Garo Hills, 2023-24" -> "Thanks!" -> "What about
# 2022-23?" was asked "which scheme?" (live 2026-10-08, reproduced with the
# layer off): the thanks reply became the last turn, and an edge turn is no
# follow-up antecedent. A greeting or a thanks says nothing about the topic,
# so the answer before it is put back as the last turn, the way
# topic_memory.checkpoint does after a bare "go back to …".

_SMALL_TALK_BANKS = ("_GREETINGS", "_THANKS")


def _is_small_talk(text: str) -> bool:
    from app import edge
    ql = (text or "").strip().lower()
    return bool(ql) and any(re.search(p, ql) for bank in _SMALL_TALK_BANKS
                            for p in getattr(edge, bank, ()))


def resume_after_small_talk(session) -> bool:
    """Put the last answered turn back after a greeting / thanks. True when
    it did. The structured state was never changed by the edge reply."""
    last = session.last_turn
    if last is None or last.route != "edge" or not _is_small_talk(last.raw_question):
        return False
    prev = next((t for t in reversed(session.turns[:-1]) if t.route in ("data", "knowledge")), None)
    if prev is None:
        # Rehydrated from the snapshot on another worker: only the last turn
        # came back, but the active topic's own last turn is durable.
        mem = topic_memory._memory(session)
        item = mem["items"].get(mem.get("active") or "") or {}
        if item.get("last_turn"):
            prev = topic_memory._turn_from(item["last_turn"])
    if prev is None:
        return False
    session.turns.append(dataclasses.replace(prev))
    context_budget.log_decision("conversation", action="resume-after-small-talk",
                                schemes=list(prev.schemes or []))
    return True


# ── Clearing the context ────────────────────────────────────────────────────

def has_context(session) -> bool:
    """Whether the next question would inherit anything from this one."""
    st = session.state
    return bool(session.turns or session.pending_scope_q or session.summary
                or (getattr(session, "topics", None) or {}).get("items")
                or st.scheme or st.district or st.block or st.village or st.year is not None
                or st.metric or st.comparison_entities)


def clear_context(session) -> None:
    """Forget what the next question would inherit: the structured state, the
    turns a follow-up is rewritten against, the rolling summary, a pending
    clarification and every topic. The revision (session_sync) is kept, so
    the cleared state is written as the next durable revision."""
    from app.session_store import ConversationState
    session.state = ConversationState()
    session.turns = []
    session.summary = None
    session.summary_turn_count = 0
    session.pending_scope_q = None
    session.pending_village_hint = None
    session.pending_scope_rule = None
    session.pending_scope_options = None
    session.topics = {}
    session.turn_context = {}


async def _drop_paused_run(session_id: str) -> None:
    """Delete a paused LangGraph run for this thread, so the next message is
    a fresh turn and not the reply to an abandoned clarification."""
    try:
        from app import pipeline_graph
        if await pipeline_graph.pending_pause(session_id) is None:
            return
        rt = await pipeline_graph._runtime()
        async with rt.lock(session_id):
            await rt.saver.adelete_thread(session_id)
        context_budget.log_decision("conversation", action="drop-paused-run")
    except Exception:  # noqa: BLE001 — the pause sweep removes it later
        logger.warning("conversation layer: could not drop the paused run (non-fatal)", exc_info=True)


def _reset_answer(expired: bool) -> dict:
    from app import pipeline
    answer = ("Okay, starting fresh. I've set aside what we were discussing, so your next question "
              "won't carry over any scheme, place or year from before. What would you like to know?")
    # confidence "low": the answer caches never store such a reply
    # (cache.ResponseCache.put); the router does not offer it to them either.
    return {"route": "edge", "intent": "EDGE", "confidence": "low", "answer": answer,
            "edge_type": RESET_EDGE, "context_expired": expired, "suggestions": [],
            **pipeline._empty_data_fields()}


# ── The turn ────────────────────────────────────────────────────────────────

@dataclass
class LayerTurn:
    """prepare_turn's verdict: the question the pipeline runs on, or a
    finished `response`. `changed` is True when the turn depends on this
    conversation in a way the caches cannot see (never cache it)."""
    question: str
    action: str = "none"           # none | expired | reset | recall | inject | swap | per-year
    response: "dict | None" = None
    changed: bool = False
    # Several questions to run and merge (answer_many): "each year, for all schemes".
    multi: "list | None" = None


def _enabled(session) -> bool:
    return session is not None and getattr(settings, "CONVERSATION_LAYER_ENABLED", True)


async def prepare_turn(session, question: str) -> LayerTurn:
    """Expiry, reset and plain-words recall for this message (see the module
    docstring). Never raises."""
    if not _enabled(session):
        return LayerTurn(question=question)
    try:
        from app import pipeline  # lazy: pipeline imports topic_memory
        now = time.time()
        expired = False
        ttl = int(getattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 0) or 0)
        last = float(getattr(session, "context_at", 0.0) or 0.0)
        # context_at 0: a snapshot written before this layer existed. Its age
        # is unknown, so it is not expired; it is stamped from now on.
        if ttl > 0 and last > 0 and now - last > ttl and has_context(session):
            clear_context(session)
            await _drop_paused_run(session.session_id)
            expired = True
            context_budget.log_decision("conversation", action="expired", idle_s=round(now - last))
            logger.info("conversation layer: context expired after %ds idle", round(now - last))
        session.context_at = now

        remainder = parse_reset(question)
        if remainder is not None:
            if has_context(session):
                clear_context(session)
                await _drop_paused_run(session.session_id)
            context_budget.log_decision("conversation", action="reset", bare=not remainder)
            if not remainder:
                return LayerTurn(question=question, action="reset", response=_reset_answer(expired),
                                 changed=True)
            return LayerTurn(question=remainder, action="reset", changed=True)

        listing = listing_question(question) or (
            pipeline._SCHEME_LISTING_CUE.search(question or "") and LISTING_QUESTION
            if getattr(session, "pending_scope_q", None) else None)
        if listing is not None:
            if getattr(session, "pending_scope_q", None):
                # Not a reply to the waiting "which area / year?": asked then,
                # it was merged into the paused question (KI-223) and answered
                # with that question's year pause. The pause is abandoned.
                session.pending_scope_q = None
                session.pending_village_hint = None
                session.pending_scope_rule = None
                session.pending_scope_options = None
                await _drop_paused_run(session.session_id)
            context_budget.log_decision("conversation", action="scheme-listing")
            return LayerTurn(question=listing, action="listing", changed=True)

        # After the reset (which clears it) and before the recall / measure
        # checks, which read the last turn.
        resume_after_small_talk(session)

        plan = per_year_plan(session, question)
        if plan:
            context_budget.log_decision("conversation", action="per-year", questions=len(plan))
            if len(plan) == 1:
                return LayerTurn(question=plan[0], action="per-year", changed=True)
            return LayerTurn(question=question, action="per-year", changed=True, multi=plan)

        swapped = counterpart_swap(session, question)
        if swapped is not None:
            context_budget.log_decision("conversation", action="counterpart-swap", question=swapped)
            return LayerTurn(question=swapped, action="swap", changed=True)

        key = recall_target(session, question)
        if key is not None:
            rewritten = _recall_question(session, key)
            context_budget.log_decision("conversation", action="recall", topic=key)
            return LayerTurn(question=rewritten, action="recall", changed=True)

        injected = knowledge_measure_question(session, question)
        if injected is not None:
            context_budget.log_decision("conversation", action="measure-after-knowledge",
                                        question=injected)
            return LayerTurn(question=injected, action="inject", changed=True)

        # After an expiry the question runs as a fresh one: nothing it inherits
        # is left, so it may be cached like any other.
        return LayerTurn(question=question, action="expired" if expired else "none")
    except Exception:  # noqa: BLE001 — the layer must never break a turn
        logger.warning("conversation layer: prepare failed (non-fatal)", exc_info=True)
        return LayerTurn(question=question)
