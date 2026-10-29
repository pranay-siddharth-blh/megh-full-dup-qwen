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
import copy
import dataclasses
import logging
import time
from dataclasses import dataclass

from app import context_budget, topic_memory
from app.config import settings
from app.context_policy import (_CpEnd, _CpNextChar, _CpSep, _CpStart, _cp_end_punct, _cp_ends, _cp_glued,
                                _cp_has, _cp_starts, _cp_ws)
from app.text_match import Alt, Cap, Joined, Matcher, Opt, Pred, Rep, Seq, W

logger = logging.getLogger(__name__)

# The edge_type of the acknowledgement a bare reset gets.
RESET_EDGE = "context_reset"


# ── Reset ───────────────────────────────────────────────────────────────────

# The reset itself, at the start of the message. Fillers before it ("ok",
# "now", "please") and a "let's" / "can we" opener are allowed.
def _cl_filler_gap(g: str) -> bool:
    """Only spaces, commas, "!" and "." (or nothing) after a filler word."""
    return all(c.isspace() or c in ",!." for c in g)


_CL_RESET_NOUN = W("question", "questions", "topic", "conversation", "context", "discussion", "one", "query", "chat")
_RESET_LEAD = Matcher(Seq(
    _CpStart(_cp_ws),
    Rep(Seq(W("ok", "okay", "now", "so", "alright", "right", "fine", "then", "well", "please", "hey", "hi"),
            _CpSep(_cl_filler_gap))),
    Opt(Alt(W("lets"), Seq("let", "s"), "let us", "can we", "could we", "shall we", "i want to",
            Seq("id", "like", "to"), Seq("i", "d", "like", "to"), W("please"))),
    Alt(
        Seq("start", Opt("a"), W("new", "fresh", "another"),
            W("topic", "conversation", "chat", "discussion", "session", "subject")),
        Seq("start", Alt(W("over", "again", "afresh", "fresh", "anew"), Seq("from", Alt("scratch", "the beginning")))),
        Seq("begin", W("again", "afresh", "anew")),
        Seq(Opt("a"), W("new", "fresh"), W("topic", "subject", "start")),
        Seq("change", Opt("the"), W("topic", "subject")),
        Seq("forget", Opt("about"), Alt(
            W("that", "this", "it", "everything"),
            Seq("all", Opt(Seq(Opt("of"), W("that", "this", "it")))),
            Seq("what", W("i", "we"), W("said", "asked", "discussed"), Opt(W("before", "earlier"))),
            Seq(W("the", "my", "our", "that", "this"),
                Opt(W("previous", "earlier", "last", "old", "above", "current")), _CL_RESET_NOUN))),
        Seq("clear", Opt(W("the", "my")), W("context", "conversation", "history", "chat", "topic", "memory")),
        Seq("reset", Opt(Seq(Opt(W("the", "my")), W("context", "conversation", "chat", "topic", "memory"))))),
    _CpNextChar(lambda c: c.isspace() or c in ",.:;!?-")))
# What may sit after the reset without being a question of its own.
_RESET_TAIL = Matcher(Seq(
    _CpStart(lambda p: p == ""),
    Opt(Alt(W("please", "pls", "now", "then", "ok", "okay", "thank", "thanks", "and", "so"), "thank you",
            Seq(Opt("and"), "start", W("over", "again", "afresh", "fresh")),
            Seq(Opt("and"), "start", Opt("a"), "new", W("topic", "one", "conversation")))),
    _CpEnd(lambda t: t == ""), sep="space"))


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
    text = text or ""
    i, n = 0, len(text)
    while i < n and (text[i].isspace() or text[i] in ",.:;!?-"):
        i += 1
    for w in ("and", "then", "so"):
        j = i + len(w)
        if text[i:j].lower() == w and (j == n or not (text[j].isalnum() or text[j] == "_")):
            while j < n and (text[j].isspace() or text[j] == ","):
                j += 1
            i = j
            break
    return text[i:]


# ── Return to a topic in plain words ────────────────────────────────────────

# The message asks for something seen before: "… again", "remind me …",
# "recap …".
_RECALL_CUE = Matcher(Alt(
    W("again", "recap"),
    Seq(_CpStart(_cp_ws), Opt(Alt("can you", "could you", "please")), "remind", "me")))
# Everything that may sit around the scheme name in such a message. What is
# left after removing these and the scheme name must be nothing, so a real
# question ("PMAY-G houses in Ri Bhoi again?") is never taken.
_RECALL_FILLER = Matcher(W(
    "what", "whats", "was", "were", "is", "are", "the", "that", "those", "this", "these", "it", "info",
    "information", "answer", "answers", "detail", "details", "data", "figure", "figures", "number", "numbers",
    "result", "results", "again", "remind", "me", "about", "of", "on", "for", "regarding", "show", "tell",
    "give", "repeat", "recap", "say", "can", "could", "would", "will", "you", "please", "pls", "once", "more",
    "one", "time", "we", "discussed", "talked", "had", "got", "us", "i", "asked", "question", "questions",
    "scheme", "topic", "discussion", "so", "ok", "okay", "and", "then", "now", "go", "over", "summary",
    "summarise", "summarize", "status", "thing", "stuff", "did", "said", "earlier", "previous", "before",
    "there", "bit", "a", "an", "quick", "quickly", "briefly"))


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
_SWAP_ASK = Matcher(Seq(
    _CpStart(_cp_ws),
    Rep(W("ok", "okay", "so", "and", "then", "now", "also")),
    Opt(Alt(Seq(W("what", "how"), "about"), "same for", "now for", "and for", W("for", "in"))),
    Opt(W("the", "in", "for", "on")),
    Cap(Pred(lambda w: w.isascii() and w.isalpha()), "term"),
    Rep(W("data", "record", "records", "side", "one", "ones", "too", "also", "instead", "please", "pls")),
    _CpEnd(_cp_end_punct)))


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
            word_matcher = Matcher(W(form))
            if word_matcher.search(base):
                # the new value in the SAME form as the word it replaces
                new_forms = group[new_vi]
                word = new_forms[fi] if fi < len(new_forms) else new_forms[0]
                return word_matcher.sub(lambda mm: word.capitalize() if mm.group(0)[:1].isupper() else word, base, count=1)
    return None


# ── "Compare this with the MGNREGA figure you showed" ───────────────────────
# Context Memory proposal §9.3 "mid-sentence" (live probe V4, 2026-10-18: it
# was answered for the active scheme alone). "This" is the active topic's
# scope; the named scheme is the other side. The pipeline already answers a
# two-scheme comparison for one place and year (app/cross_scheme.py, D-044),
# so the message becomes that question — deterministically, from the state.
_CMP_REF = W("this", "that", "it", "these", "those")
_CMP_FILLER = Rep(W("the", "figure", "figures", "number", "numbers", "one", "ones", "data", "value", "values",
                    "result", "results", "you", "showed", "shown", "gave", "given", "said", "mentioned", "earlier",
                    "before", "previously", "above", "from", "of", "for", "under", "please", "pls", "again"))
_COMPARE_ASK = Matcher(Seq(
    _CpStart(_cp_ws),
    Rep(W("ok", "okay", "so", "and", "now", "then", "please", "can", "could", "you")),
    Alt(Seq(W("compare", "comparing", "comparison"), Opt("of"), _CMP_REF, _CMP_FILLER,
            W("with", "to", "against", "and", "vs", "versus")),
        Seq("how", W("does", "do", "did"), _CMP_REF, _CMP_FILLER, "compare", W("with", "to", "against")),
        Seq(_CMP_REF, _CMP_FILLER, W("vs", "versus", "against", "compared"), Opt(W("with", "to")))),
    _CMP_FILLER,
    Cap(Rep(Pred(lambda w: True), 1, 6), "other"),
    _CpEnd(_cp_end_punct)))


def comparison_with_earlier(session, question: str) -> "str | None":
    """'Compare this with the MGNREGA figure you showed' as the two-scheme
    comparison question for the active scope, or None when the message is not
    one, names no other single scheme, or there is no active scheme."""
    from app import pipeline
    m = _COMPARE_ASK.match(question or "")
    if not m:
        return None
    other = m.group("other")
    named = list(pipeline._named_schemes(other))
    if len(named) != 1 or pipeline._named_schemes(question[:m.start("other")]):
        return None
    st = session.state
    active = st.scheme or (topic_memory._memory(session).get("active") or "")
    if not active or " + " in active or topic_memory.same_scheme_family(active, named[0]):
        return None
    place = topic_memory.place_words(st)
    where = f" in {place}" if place else " in Meghalaya"
    if st.year is not None:
        when = f" in {topic_memory._fy(st.year)}"
    elif st.year_all:
        when = " across all financial years"
    else:
        when = ""
    return f"Compare {active} and {named[0]}{where}{when}"


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
_CL_YEARS = W("year", "years")
_PER_YEAR_CUE = Matcher(Alt(
    Seq(W("each", "every", "all", "per"), Opt("the"), Opt("particular"), Opt("financial"), _CL_YEARS),
    Joined("year", "wise"),
    Seq("in", "which", Opt("financial"), _CL_YEARS),
    "financial years",
    Seq("only", Alt(W("one", "1", "single"), "a single"), Opt("financial"), "year"),
    Seq("not", "in", Opt("a"), "single", "year"),
    Seq(W("two", "three", "four", "five", "six", "seven", "2", "3", "4", "5", "6", "7"), Opt("financial"), "years"),
    Seq("by", Opt("financial"), "year"),
    # A-15: the same per-year words as cross_figures' (annually / yearly / year-wise trend)
    W("annually", "yearly", "annual", "yearwise", "trend", "trends"),
    Seq("over", "the", "years"), Seq("year", "on", "year")))
_ALL_SCHEMES_CUE = Matcher(Alt(Seq(W("all", "every", "each"), Opt("the"), W("scheme", "schemes")), "all of them"))
_REFERS_BACK = Matcher(Alt(
    Seq(W("above", "previous", "last", "earlier", "that", "this", "same"),
        W("query", "queries", "question", "answer", "result", "results", "data", "output")),
    Seq("you", Opt(W("have", "had")), W("gave", "given", "give", "showed", "shown", "said", "told", "provided")),
    W("crossverify", "crosscheck", "recheck", "reverify", prefix=True),
    Seq(W("cross", "re"), _CpSep(lambda g: g == "-" or (len(g) == 1 and g.isspace())),
        W("verify", "check", prefix=True)),
    W("verify"),
    Seq("why", Opt(W("are", "is")), Opt("you"), W("giving", "showing", "only"))))


def _cl_ws_gap(g: str) -> bool:
    return g.strip() == ""


def _cl_pair(a: tuple, b: tuple) -> Seq:
    """Anywhere in the text: a word ending in an `a` form, spaces, a word starting with `b`."""
    return Seq(_cp_ends(*a), _CpSep(_cl_ws_gap), _cp_starts(*b))


# (label in the question, pattern, "how many" / "total" / "villages", the schemes that hold
# it — None: every scheme). A-9 / A-11 (audit 2026-10-29): money words other than
# "expenditure / spent" (money, amount, released, disbursed, funds) and "villages"
# were not here, so "… amount released each year" was answered with beneficiaries;
# and the first measure found was asked of every scheme ("PMAY-G person-days").
_YEAR_METRICS = [
    ("person-days", Matcher(_cp_glued("person", "day")), "count", ("MGNREGA",)),
    ("households", Matcher(_cp_has("household")), "count", ("MGNREGA",)),
    ("job cards", Matcher(_cp_glued("job", "card", gap=_cl_ws_gap)), "count", ("MGNREGA",)),
    ("houses sanctioned", Matcher(Alt(_cl_pair(("house", "houses"), ("sanction",)),
                                      _cl_pair(("sanctioned",), ("house",)))), "count", ("PMAY-G",)),
    ("houses completed", Matcher(Alt(_cl_pair(("house", "houses"), ("complet",)),
                                     _cl_pair(("completed",), ("house",)))), "count", ("PMAY-G",)),
    # "houses" alone is PMAY-G's houses sanctioned ("person days and houses each year")
    ("houses sanctioned", Matcher(W("house", "houses")), "count", ("PMAY-G",)),
    ("applications", Matcher(_cp_has("application", "applicant")), "count", ("CM Elevate",)),
    ("payments", Matcher(_cp_has("payment", "disbursement")), "count", ("Focus Plus", "Focus Legacy")),
    ("expenditure", Matcher(Alt(_cp_has("expenditure"), _cl_pair(("amount",), ("spent",)), W("spend", "spent"),
                                W("money", "amount", "amounts", "fund", "funds", "funding", "released", "disbursed",
                                  "spending", "crore", "lakh", "rupees"),
                                W("releas", "disburs", prefix=True))), "money", None),
    ("villages", Matcher(W("village", "villages")), "villages", ("MGNREGA", "PMAY-G", "Focus Plus", "Focus Legacy")),
    ("beneficiaries", Matcher(_cp_has("beneficiar")), "count", None),
]
# what each scheme's money is (the money measure is asked in the scheme's own kind)
_MONEY_LABEL = {"MGNREGA": "expenditure", "PMAY-G": "amount released", "Focus Plus": "amount disbursed",
                "Focus Legacy": "amount disbursed", "CM Elevate Legacy": "amount disbursed",
                "CM Elevate": "amount disbursed"}


def _year_measures(*texts) -> list:
    """[(label, kind, holders), ...]: every measure the first text that names one
    names, in table order; [] when none does."""
    for t in texts:
        found = []
        for label, word_matcher, kind, held in _YEAR_METRICS:
            if t and word_matcher.search(t) and all(f[0] != label for f in found):
                found.append((label, kind, held))
        if found:
            return found
    return []


def _year_metric(*texts) -> "tuple[str, str]":
    found = _year_measures(*texts)
    return (found[0][0], found[0][1]) if found else ("beneficiaries", "count")


_CL_LEVEL_WORDS = frozenset({"district", "districts", "block", "blocks", "village", "villages",
                              "constituency", "constituencies"})
_CL_JOINERS = frozenset({"and", "or", "vs", "versus", "with", "plus"})
_CL_NOT_PLACES = frozenset({"fy", "meghalaya", "financial", "each", "every", "all", "the", "which", "year", "years"})


def _cl_carries_scope(q: str, scheme_spans: list) -> bool:
    """The question names more than a measure: a place, a place level, a top /
    bottom N or a rank word (I-2: "top 5 districts in MGNREGA and PMAY-G year wise",
    "… in East Khasi Hills year wise" were rewritten to statewide per-year totals)."""
    from app import cross_figures
    from app.text_match import tokens
    if cross_figures.rank_ask(q) or cross_figures._top_n(q):
        return True
    toks = tokens(q)
    inside = lambda t: any(a <= t.start < b for a, b in scheme_spans)  # noqa: E731
    for i, t in enumerate(toks):
        # a level of breakdown ("district wise", "each block", "by village"), not the
        # villages MEASURE ("villages covered each year")
        if t.low in _CL_LEVEL_WORDS and ((i and toks[i - 1].low in ("each", "every", "per", "by", "which", "what"))
                                         or (i + 1 < len(toks) and toks[i + 1].low == "wise")):
            return True
        # "in East Khasi Hills", "for Ri Bhoi": a capitalised name after a preposition
        if t.low in ("in", "for", "at", "of") and i + 1 < len(toks):
            nxt = toks[i + 1]
            if nxt.raw[:1].isupper() and not inside(nxt) and nxt.low not in _CL_NOT_PLACES \
                    and not nxt.raw[:1].isdigit():
                return True
    return False


def _cl_one_scheme_question(q: str, keep: str, spans: list) -> str:
    """The question with every scheme but `keep` taken out, with the joining word
    ("MGNREGA and PMAY-G" -> "MGNREGA")."""
    from app.text_match import tokens
    out = q
    for a, b, s in sorted(spans, reverse=True):
        if s == keep:
            continue
        before = out[:a].rstrip()
        after = out[b:]
        toks = tokens(before)
        if toks and toks[-1].low in _CL_JOINERS and toks[-1].end == len(before):
            before = before[:toks[-1].start].rstrip()
        elif before.endswith((",", "&", "/")):
            before = before[:-1].rstrip()
        else:
            nxt = tokens(after)
            if nxt and nxt[0].low in _CL_JOINERS and after[:nxt[0].start].strip(" ,") == "":
                after = after[nxt[0].end:]
            elif after.lstrip().startswith((",", "&", "/")):
                after = after.lstrip()[1:]
        out = (before + " " + after.lstrip()).strip()
    return " ".join(out.split())


def _cl_year_phrase(q: str, scheme: str) -> str:
    """The asked years, written out for a per-scheme question (A-3: the range was
    dropped and every year held came back): " from FY 2022-23 to FY 2024-25",
    " in FY 2023-24 and FY 2024-25", or the relative period read for this scheme."""
    from app import cross_scheme, pipeline
    ys = cross_scheme.years_in_text(q)
    span = pipeline._c09_stated_year_span(q)
    if span:
        ys = list(range(span[0], span[1] + 1))
    if not ys:
        rel = pipeline._relative_years(q, [scheme])
        if rel is None:
            return ""
        ys = rel[0]
    fy = lambda y: f"FY {y}-{(y + 1) % 100:02d}"  # noqa: E731
    if len(ys) == 1:
        return f" in {fy(ys[0])}"
    if ys == list(range(ys[0], ys[-1] + 1)):
        return f" from {fy(ys[0])} to {fy(ys[-1])}"
    return " in " + ", ".join(fy(y) for y in ys[:-1]) + f" and {fy(ys[-1])}"


def per_year_parts(session, question: str) -> "dict | None":
    """{"questions": the per-scheme, per-year questions a follow-up asks for,
    "notes": what the answer must say (a scheme that holds none of the measures),
    "ask": a "which figure?" pause when no measure is named}, or None."""
    from app import pipeline
    # a misspelt scheme ("mgnerga and pmayg") is read as at turn start (I-17)
    q = pipeline._correct_scheme_spelling(question or "")
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
    measures = _year_measures(q, getattr(prev, "raw_question", "") if prev else "",
                              getattr(prev, "question", "") if prev else "")
    labels = [m[0] for m in measures]
    # CM Elevate's applications data has no year; per-year beneficiaries / money
    # are CM Elevate Legacy's (the pipeline pins the same way). Never both.
    if "CM Elevate" in schemes and labels != ["applications"]:
        schemes = [s for s in schemes if s != "CM Elevate"]
        if "CM Elevate Legacy" not in schemes:
            schemes.append("CM Elevate Legacy")
        schemes = sorted(schemes, key=lambda s: order.index(s) if s in order else len(order))
    spans = [(h.start(), h.end(), s) for s, pat in pipeline._SCHEME_NAME_MATCHER.items() for h in pat.finditer(q)]
    if len(named) >= 2 and set(schemes) <= set(named) and _cl_carries_scope(q, [(a, b) for a, b, _ in spans]):
        # I-2: the officer's own question, one scheme at a time, keeps its place,
        # its top / bottom N, its level and its years
        return {"questions": [_cl_one_scheme_question(q, s, spans) for s in schemes], "notes": [], "ask": None}
    if not measures:
        # A-9: no measure named here or in the last answer — ask which one,
        # never default to beneficiaries
        return {"questions": None, "notes": [], "ask": _cl_measure_ask(schemes, q)}
    questions, notes = [], []
    for s in schemes:
        held = [m for m in measures if m[2] is None or s in m[2]]
        if not held:
            # A-11: "PMAY-G person-days" was asked; PMAY-G records none
            notes.append(f"{s} records no {' or '.join(m[0] for m in measures)}")
            continue
        yp = _cl_year_phrase(q, s)
        for label, kind, _held in held:
            if kind == "money":
                questions.append(f"What was the total {s} {_MONEY_LABEL.get(s, label)} in each financial year{yp}?")
            elif kind == "villages":
                questions.append(f"How many villages did {s} cover in each financial year{yp}?")
            else:
                questions.append(f"How many {s} {label} were there in each financial year{yp}?")
    if not questions:
        return None
    return {"questions": questions, "notes": notes, "ask": None}


def _cl_measure_ask(schemes: list, q: str) -> dict:
    """The "which figure?" pause for a per-year question that names no measure (A-9)."""
    from app import pipeline
    who = " and ".join(schemes) if len(schemes) <= 2 else ", ".join(schemes[:-1]) + " and " + schemes[-1]
    opts = [{"label": lab, "question": f"{lab} of {who} in each financial year"}
            for lab in ("Beneficiaries", "Money spent", "Villages covered")]
    text = f"Which figure do you want for {who}, year by year?"
    return {"route": "clarification", "intent": "CLARIFY", "confidence": "high", "answer": text,
            "needs_clarification": True, "question": text,
            "clarification": {"options": opts, "rule": "per-year-measure"}, **pipeline._empty_data_fields()}


def per_year_plan(session, question: str) -> "list[str] | None":
    """The per-scheme, per-year questions a follow-up asks for, or None."""
    parts = per_year_parts(session, question)
    return parts["questions"] if parts else None


# ── merging the per-scheme answers into one scheme x year table ─────────────
# A-1 / A-2 / A-10 / A-12 (audit 2026-10-29): each scheme's answer names its
# year column its own way (year_key 2023, financial_year_short "2023-24",
# "2023-2024"), its first number may be a code or another figure, and MGNREGA
# money is in ₹ lakh while PMAY-G's and Focus's is in rupees. Merged as they
# came, the chart lost the year, zig-zagged between "2022-23" and "2022-2023",
# charted an LGD code, and drew PMAY-G 11,000 times bigger than MGNREGA.

def _cl_yearish_col(name: str) -> bool:
    """A column naming the financial year: a 'year' / 'fy' part between
    underscores, or 'financial' anywhere."""
    low = name.lower()
    return "financial" in low or any(part in ("year", "fy") for part in low.split("_"))


def _cl_fy(v) -> "str | None":
    """One financial-year label, "2023-24": from 2023, "2023", "2023-2024",
    "FY 2023-24", "2023-24"; None when `v` is not a year."""
    s = str(v if v is not None else "").strip()
    if s.lower().startswith("fy"):
        s = s[2:].strip()
    head = s[:4]
    if len(head) == 4 and head.isdigit() and head[:2] in ("19", "20"):
        rest = s[4:]
        if rest == "" or (rest.startswith("-") and rest[1:].isdigit() and len(rest[1:]) in (2, 4)):
            y = int(head)
            return f"{y}-{(y + 1) % 100:02d}"
    return None


_CL_ID_PARTS = frozenset({"code", "id", "lgd", "key", "rank", "sl", "serial", "pin", "pincode", "no"})
# column-name stems of each measure (A-12: the column that matches the asked measure)
_CL_MEASURE_STEMS = {
    "person-days": ("person", "day", "persondays", "mandays"),
    "households": ("household", "hh"),
    "job cards": ("job", "card", "jobcard"),
    "houses sanctioned": ("house", "sanction"),
    "houses completed": ("complet",),
    "applications": ("application", "applicant"),
    "payments": ("payment", "disbursement", "transaction"),
    "expenditure": ("exp", "amount", "amt", "money", "releas", "disburs", "spent", "fund", "crore", "lakh",
                    "rupee", "rs", "cost"),
    "villages": ("village",),
    "beneficiaries": ("beneficiar", "member", "household", "house", "count", "total"),
}
_CL_PLACE_COLS = (("district", "district"), ("block", "block"), ("village", "village"),
                  ("constituency", "constituency"), ("panchayat", "gram_panchayat"))


def _cl_parts(col) -> list:
    return [x for x in str(col).lower().replace("(", "_").replace(")", "_").replace(" ", "_").split("_") if x]


def _cl_is_number(v) -> bool:
    if isinstance(v, bool) or v is None:
        return False
    try:
        float(str(v).replace(",", ""))
        return True
    except (TypeError, ValueError):
        return False


def _cl_money_crore(col: str, scheme: str, v) -> float:
    """A money figure in ₹ crore, from its column's unit (or the scheme's own:
    MGNREGA money is in ₹ lakh, every other scheme's in rupees)."""
    parts = _cl_parts(col)
    n = float(str(v).replace(",", ""))
    if any(x in ("crore", "crores", "cr") for x in parts):
        return n
    if any(x in ("lakh", "lakhs") for x in parts):
        return n / 100
    if any(x in ("rupees", "rs", "inr") for x in parts):
        return n / 1e7
    return n / 100 if scheme == "MGNREGA" else n / 1e7


def _year_row(row: dict, scheme: str, label: str, kind: str) -> "dict | None":
    """One merged row {scheme, [place columns], financial_year, <measure>} from a
    sub-answer's row; None when it has no figure."""
    years = [k for k in row if _cl_yearish_col(str(k))]
    fy = next((_cl_fy(row[k]) for k in sorted(years, key=lambda k: str(k).endswith("_key")) if _cl_fy(row[k])),
              None)
    cands = [k for k, v in row.items() if k not in years and k != "scheme" and _cl_is_number(v)
             and not any(x in _CL_ID_PARTS for x in _cl_parts(k))]
    if not cands:
        return None
    stems = _CL_MEASURE_STEMS.get(label, ())
    col = next((k for k in cands if any(x.startswith(st) for x in _cl_parts(k) for st in stems)), cands[0])
    out = {"scheme": scheme}
    for k, v in row.items():
        if k in years or k == "scheme" or _cl_is_number(v):
            continue
        low = str(k).lower()
        out[next((canon for word, canon in _CL_PLACE_COLS if word in low), str(k))] = v
    out["financial_year"] = fy
    if kind == "money":
        out["money_crore"] = round(_cl_money_crore(str(col), scheme, row[col]), 4)
    else:
        v = float(str(row[col]).replace(",", ""))
        out[(label or "value").replace(" ", "_").replace("-", "_")] = int(v) if v.is_integer() else v
    return out


def _year_and_value(row: dict) -> "tuple[object, object] | None":
    """(financial year, figure) of one result row; None when the row has no figure."""
    r = _year_row(row, "", "", "count")
    if r is None:
        return None
    return r["financial_year"], r["value"]


_CL_LEGACY_NOTE = ("CM Elevate's applications carry no financial year, so its per-year figures are CM Elevate "
                   "Legacy's: the sanction and disbursement records of the same scheme")


async def answer_many(questions: list, ask, notes: "list | None" = None) -> dict:
    """Run each question through the pipeline (`ask`), one after another, and
    merge the answers: the text scheme by scheme, one scheme x year table.
    A question that pauses or fails is reported in the text, never guessed.
    `notes`: lines the answer must carry (a scheme that holds none of the measures)."""
    from app import pipeline
    sections, rows, schemes, sqls = [], [], [], []
    notes = [f"{n}." for n in (notes or [])]
    labels: list = []
    no_year: list = []
    for q in questions:
        scheme = next(iter(pipeline._named_schemes(q)), q)
        label, kind = _year_metric(q)
        if label not in labels:
            labels.append(label)
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
            yr = _year_row(dict(row), scheme, label, kind)
            if yr is None:
                continue
            if yr["financial_year"] is None:
                # H-2: a figure with no year is not a year on the chart
                if scheme not in no_year:
                    no_year.append(scheme)
                continue
            rows.append(yr)
    if no_year:
        notes.append(f"{' and '.join(no_year)} {'has' if len(no_year) == 1 else 'have'} figures with no financial "
                     "year; they are in the text above, not in the year table.")
    if "CM Elevate Legacy" in schemes:
        notes.append(f"{_CL_LEGACY_NOTE}.")                   # A-17
    measure_cols = {k for r in rows for k, v in r.items() if k not in ("scheme", "financial_year")
                    and not isinstance(v, str)}
    if len(measure_cols) > 1:
        # different measures per scheme (person-days, houses): one value column
        # and what it counts, so every scheme's figure is in the same column (I-9)
        for r in rows:
            k = next(k for k in list(r) if k in measure_cols)
            r["measure"] = k.replace("_", " ")
            r["value"] = r.pop(k)
    one = labels[0] if len(labels) == 1 else None
    head = f"{(one or 'Figures').capitalize()} in each financial year, scheme by scheme:"
    failed = not sections and not rows
    if failed:
        answer = "\n\n".join(["I couldn't fetch these figures just now. Please try again in a moment."] + notes)
    else:
        answer = "\n\n".join([head] + sections + notes)
    out = {"route": "data", "intent": "DATA", "confidence": "low" if failed else "high", "answer": answer,
           **pipeline._empty_data_fields()}
    out.update({"schemes": schemes, "data": rows, "rows": rows, "row_count": len(rows),
                "sql_query": "\n\n".join(sqls),
                "rewritten_question": f"{(one or 'figures').capitalize()} in each financial year for "
                                      + ", ".join(schemes or [])})
    if failed:
        out["answer_failed"] = True       # H-2: the UI shows it as failed, with Retry
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
def _cl_scheme_forms() -> frozenset:
    """Every spelling the old s[ck]?h?e{1,2}m[ae]?s?|sc?hm[ae]?s?|schems?|
    shcemes?|scemes?|skeems?|scheams?|programm?e?s?|yojanas? accepted."""
    out = set()
    for c in ("", "c", "k"):
        for h in ("", "h"):
            for e in ("e", "ee"):
                for v in ("", "a", "e"):
                    for pl in ("", "s"):
                        out.add(f"s{c}{h}{e}m{v}{pl}")
    for c in ("", "c"):
        for v in ("", "a", "e"):
            for pl in ("", "s"):
                out.add(f"s{c}hm{v}{pl}")
    for stem in ("schem", "shceme", "sceme", "skeem", "scheam", "yojana"):
        out |= {stem, stem + "s"}
    for m in ("", "m"):
        for e in ("", "e"):
            for pl in ("", "s"):
                out.add(f"program{m}{e}{pl}")
    return frozenset(out)


# "scheme(s)" and its usual misspellings, plus "programmes" / "yojanas".
_SCHEME_W = W(*_cl_scheme_forms())
_CL_SCHEME_WORD = Matcher(_SCHEME_W)
_PLEASE = Rep(Alt(W("please", "pls", "plz", "now", "currently", "here"),
                  Seq("in", W("this", "the"), W("app", "system", "bot", "chat", "chatbot", "portal", "data", "database"))))
_CL_YOU = W("you", "u")
_LISTING_ASK = Matcher(Seq(
    _CpStart(_cp_ws),
    Rep(Alt(W("hi", "hello", "ok", "okay", "so", "and", "then", "please"), "tell me", "can you tell me")),
    Alt(
        # what / which (all) schemes are there / present / available / covered ...
        Seq(W("what", "which", "wat", "wht", "wich"), Opt(Alt(W("all"), Seq("are", "the"), W("are"))), Opt("the"),
            _SCHEME_W,
            Opt(Alt(W("are", "r", "is"), Seq("do", _CL_YOU), Seq("can", _CL_YOU), Seq("does", W("it", "this")),
                    W("you"))),
            Rep(W("there", "present", "available", "avail", "avaliable", "covered", "supported", "included",
                  "offered", "listed", "have", "cover", "support", "know", "handle", "answer", "provide", "show"))),
        # list / show / tell me / give me (all) (the) (available) schemes
        Seq(W("list", "show", "tell", "give", "name"), Opt(W("me", "us")), Opt("out"), Opt("all"), Opt("of"),
            Opt("the"), Opt("full"), Opt(Seq("list", "of", Opt("all"), Opt("the"))),
            Opt(W("available", "supported", "covered")), _SCHEME_W,
            Opt(Alt(W("available", "covered", "supported"), Seq("you", W("have", "cover"))))),
        # available / supported / all schemes; scheme list
        Seq(Alt(W("available", "supported", "all"), "list of"), _SCHEME_W),
        Seq(_SCHEME_W, W("list", "available", "present", "covered")),
        # how many schemes (are there / do you cover)
        Seq("how", "many", _SCHEME_W, Opt(Alt(W("are", "r"), Seq("do", _CL_YOU))),
            Opt(W("there", "present", "available", "covered", "have", "cover")))),
    _PLEASE,
    _CpEnd(_cp_end_punct)))


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
    if pipeline._named_schemes(_CL_SCHEME_WORD.sub(" ", q)):
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
    return bool(ql) and any(_cl_bank_hit(getattr(edge, bank, ()), ql) for bank in _SMALL_TALK_BANKS)


def _cl_bank_hit(bank, text: str) -> bool:
    """Does any pattern of an edge bank (a Matcher, a list of Matchers, or
    plain predicates) match `text`?"""
    items = bank if isinstance(bank, (list, tuple)) else [bank]
    for p in items:
        search = getattr(p, "search", None)
        if search is not None:
            if search(text):
                return True
        elif callable(p) and p(text):
            return True
    return False


def resume_after_small_talk(session) -> bool:
    """Put the last answered turn back after a greeting / thanks. True when
    it did. The structured state was never changed by the edge reply."""
    last = session.last_turn
    # a greeting / thanks, or any other aside the refusal styler noted
    # (conversation_replies.restyle: "who is the PM?" mid-topic)
    aside = topic_memory._memory(session).get("aside")
    if last is None:
        return False
    # A denied follow-up ("by block" for an account authorised up to district
    # level) is an aside too: the refusal is about that one question, and the
    # topic the officer was on must survive it (live 2026-10-18: "only
    # Mawphlang" / "and statewide?" after a denial lost the topic; proposal F2).
    denied = last.route == "denied"
    if not denied and (last.route != "edge" or not (_is_small_talk(last.raw_question)
                                                    or (aside and last.raw_question == aside))):
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
    # The older turns of this chat stay in semantic memory (Qdrant); from now
    # on only turns after this moment may come back as context (KI-224).
    session.memory_since = time.time()


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


# ── "Continue with MGNREGA (East Khasi Hills, FY 2022-23)?" after an expiry ──
# Context Memory proposal S3 (2026-10-18): an idle expiry no longer forgets
# silently. What it clears is set aside (session.expired_ctx, durable) and the
# first reply after it offers one chip naming it. Tapping the chip puts the
# state, the topics and the last turn back; any other message drops it, so
# ignoring the chip starts fresh exactly as before.
CONTINUE_EDGE = "context_continued"


def _continue_chip(session) -> "str | None":
    st = session.state
    scheme = st.scheme or (getattr(session, "topics", None) or {}).get("active")
    if not scheme:
        return None
    place = topic_memory.place_words(st)
    bits = [b for b in (place,
                        topic_memory._fy(st.year) if st.year is not None else None) if b]
    return f"Continue with {scheme}" + (f" ({', '.join(bits)})" if bits else "")


def _set_aside(session) -> "str | None":
    """Keep what an expiry is about to clear; the chip text, or None when
    there is no topic worth offering."""
    chip = _continue_chip(session)
    if chip is None:
        return None
    prev = next((t for t in reversed(session.turns) if t.route in ("data", "knowledge")), None)
    if prev is None:
        mem = topic_memory._memory(session)
        item = mem["items"].get(mem.get("active") or "") or {}
        prev = topic_memory._turn_from(item["last_turn"]) if item.get("last_turn") else None
    session.expired_ctx = {"chip": chip, "state": session.state.to_dict(),
                           "topics": copy.deepcopy(getattr(session, "topics", None) or {}),
                           "summary": session.summary,
                           "last_turn": topic_memory._turn_dict(prev) if prev is not None else None}
    return chip


def _is_continue_tap(session, question: str) -> bool:
    exp = getattr(session, "expired_ctx", None) or {}
    chip = str(exp.get("chip") or "").strip().lower()
    return bool(chip) and (question or "").strip().rstrip(" ?.!").lower() == chip


def _continue_expired(session, question: str = "") -> dict:
    """Put the set-aside context back; the acknowledgement."""
    from app import pipeline
    from app.session_store import ConversationState
    exp = session.expired_ctx or {}
    session.expired_ctx = None
    restored = ConversationState.from_dict(exp.get("state") or {})
    restored.turn_count = session.state.turn_count
    session.state = restored
    session.topics = exp.get("topics") or {}
    session.summary = exp.get("summary")
    if exp.get("last_turn"):
        session.turns.append(topic_memory._turn_from(exp["last_turn"]))
    # The acknowledgement is an aside, like "thanks": the restored data turn
    # stays the follow-up antecedent (browser check 2026-10-18: "What about FY
    # 2023-24?" right after the tap asked "which scheme?").
    topic_memory._memory(session)["aside"] = question
    what = str(exp.get("chip") or "").replace("Continue with ", "", 1)
    answer = (f"Picking up where we left off: {what}. Ask your next question about it — for example "
              "\"What about another year?\" — and I'll continue from there.")
    # confidence "low": the answer caches never store such a reply.
    return {"route": "edge", "intent": "EDGE", "confidence": "low", "answer": answer,
            "edge_type": CONTINUE_EDGE, "suggestions": [], **pipeline._empty_data_fields()}


def attach_continue_offer(session, result: dict) -> dict:
    """The first reply after an expiry carries the "Continue with …" chip as
    `continue_offer`, shown under any kind of answer (the router calls this
    before saving)."""
    exp = getattr(session, "expired_ctx", None) if session is not None else None
    if not exp or not exp.pop("offer_pending", False):
        return result
    return {**result, "continue_offer": exp["chip"]}


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
    # what the merged answer must say ("PMAY-G records no person-days", A-11)
    multi_notes: "list | None" = None


def _enabled(session) -> bool:
    return session is not None and getattr(settings, "CONVERSATION_LAYER_ENABLED", True)


# ── "stop" … "continue" ─────────────────────────────────────────────────────
# User request 2026-10-18: a question stopped while it ran (the Stop button,
# or "stop" typed in the box) is answered when the officer then says
# "continue". The router records the stopped question on the session when it
# cancels the streamed turn (remember_stopped); the next message, if it is a
# continue request, runs that question through this layer as if it had just
# been typed. Any other message drops it.
# A stopped question lives as long as the idle window (CONTEXT_IDLE_EXPIRY_SECONDS).
STOPPED_MAX_AGE_SECONDS = 1800   # fallback when the idle window is 0 (never expire)
NOTHING_RUNNING_EDGE = "nothing_running"

_CL_POLITE = W("ok", "okay", "yes", "yeah", "yep", "sure", "please", "pls", "plz", "now", "so", "then", "haan", "ha")
_CONTINUE_ASK = Matcher(Seq(
    _CpStart(_cp_ws),
    Rep(_CL_POLITE),
    Alt(W("continue", "resume", "proceed", "contiue", "contnue", "continu"),
        Seq("go", W("on", "ahead")), Seq("carry", "on"), Seq(W("keep", "kepp"), "going")),
    Opt(Alt(Seq(Opt(W("with", "from")), Opt(W("the", "my", "that")),
                Opt(W("previous", "last", "stopped", "earlier", "same", "old")),
                W("query", "question", "answer", "one", "request", "search")),
            Seq(Opt("where"), "you", W("stopped", "left"), Opt("off")))),
    Rep(_CL_POLITE),
    _CpEnd(_cp_end_punct)))
_STOP_ASK = Matcher(Seq(
    _CpStart(_cp_ws),
    Rep(_CL_POLITE),
    W("stop", "cancel", "abort", "halt", "ruko", "band"),
    Opt(W("it", "this", "that", "now", "please", "pls", "karo")),
    Rep(_CL_POLITE),
    _CpEnd(_cp_end_punct)))


def is_continue_request(question: str) -> bool:
    return bool(question) and _CONTINUE_ASK.match(question.strip()) is not None


def is_stop_request(question: str) -> bool:
    return bool(question) and _STOP_ASK.match(question.strip()) is not None


def remember_stopped(session, question: str) -> None:
    """The router cancelled this question while it ran (Stop)."""
    if session is None or not (question or "").strip() or is_continue_request(question):
        return
    session.stopped_ctx = {"question": question.strip(), "at": time.time()}
    context_budget.log_decision("conversation", action="stopped")


def _take_stopped(session, question: str) -> "str | None":
    """The stopped question a "continue" asks for (and forget it); None
    otherwise. Any message drops a stopped question."""
    stopped = getattr(session, "stopped_ctx", None) or {}
    session.stopped_ctx = None
    if not stopped.get("question") or not is_continue_request(question):
        return None
    max_age = int(getattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 0) or 0) or STOPPED_MAX_AGE_SECONDS
    if time.time() - float(stopped.get("at") or 0) > max_age:
        return None
    return stopped["question"]


def _nothing_running_answer() -> dict:
    from app import pipeline
    # confidence "low": the answer caches never store such a reply.
    return {"route": "edge", "intent": "EDGE", "confidence": "low",
            "answer": "Okay — nothing is running right now. Ask me your next question whenever you're ready.",
            "edge_type": NOTHING_RUNNING_EDGE, "suggestions": [], **pipeline._empty_data_fields()}


async def prepare_turn(session, question: str) -> LayerTurn:
    """Stop / continue, then expiry, reset and plain-words recall for this
    message (see the module docstring). Never raises."""
    if not _enabled(session):
        return LayerTurn(question=question)
    try:
        resumed = _take_stopped(session, question)
        if resumed is not None:
            context_budget.log_decision("conversation", action="continue-stopped")
            logger.info("conversation layer: continuing the stopped question %r", resumed)
            lt = await _prepare(session, resumed)
            # "continue" means something only in this chat: never cached
            return dataclasses.replace(lt, changed=True,
                                       action="continue-stopped" if lt.action == "none" else lt.action)
        if is_stop_request(question):
            # A typed "stop" with nothing running (a running answer is stopped
            # by the chat box itself). Not a question; the topic carries on.
            return LayerTurn(question=question, action="stop", response=_nothing_running_answer(), changed=True)
    except Exception:  # noqa: BLE001 — the layer must never break a turn
        logger.warning("conversation layer: stop / continue failed (non-fatal)", exc_info=True)
    return await _prepare(session, question)


async def _prepare(session, question: str) -> LayerTurn:
    """Expiry, reset and plain-words recall for this message. Never raises."""
    try:
        from app import pipeline  # lazy: pipeline imports topic_memory
        now = time.time()
        expired = False
        ttl = int(getattr(settings, "CONTEXT_IDLE_EXPIRY_SECONDS", 0) or 0)
        last = float(getattr(session, "context_at", 0.0) or 0.0)
        # The "Continue with …" chip offered after an expiry: tapped, the
        # set-aside context comes back; any other message drops it.
        if _is_continue_tap(session, question):
            session.context_at = now
            context_budget.log_decision("conversation", action="continue-expired")
            return LayerTurn(question=question, action="continue-expired",
                             response=_continue_expired(session, question), changed=True)
        session.expired_ctx = None
        # context_at 0: a snapshot written before this layer existed. Its age
        # is unknown, so it is not expired; it is stamped from now on.
        if ttl > 0 and last > 0 and now - last > ttl and has_context(session):
            if _set_aside(session) is not None:
                session.expired_ctx["offer_pending"] = True
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

        # "How are you?" mid-topic was read by the pipeline as a follow-up and
        # re-answered the last figure (live 2026-10-13): a pure pleasantry is
        # answered here, and the topic carries on after it.
        from app import conversation_replies
        chat = conversation_replies.small_talk_reply(session, question)
        if chat is not None:
            context_budget.log_decision("conversation", action="small-talk")
            return LayerTurn(question=question, action="small-talk", response=chat, changed=True)

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

        parts = per_year_parts(session, question)
        if parts and parts.get("ask"):
            context_budget.log_decision("conversation", action="per-year-ask")
            return LayerTurn(question=question, action="per-year", changed=True, response=parts["ask"])
        plan = parts["questions"] if parts else None
        if plan:
            context_budget.log_decision("conversation", action="per-year", questions=len(plan))
            if len(plan) == 1 and not parts["notes"]:
                return LayerTurn(question=plan[0], action="per-year", changed=True)
            return LayerTurn(question=question, action="per-year", changed=True, multi=plan,
                             multi_notes=parts["notes"])

        compared = comparison_with_earlier(session, question)
        if compared is not None:
            context_budget.log_decision("conversation", action="compare-earlier", question=compared)
            return LayerTurn(question=compared, action="compare", changed=True)

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
