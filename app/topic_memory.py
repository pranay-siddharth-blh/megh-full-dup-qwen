"""
Topic memory: several topics in one conversation, each with its own context.

The context layer (context_manager, context_policy, D-022..D-024) keeps ONE
rolling context: session.state and the last turn. That is right inside one
topic, and it is why a topic switch drops the old topic's filters
(update_state's scheme-change reset): they must not leak into the new scheme.
The cost was that the old topic was gone for good. After

    MGNREGA beneficiaries in East Khasi Hills, 2024-25
    -> PMAY-G houses sanctioned in West Garo Hills
    -> "Go back to MGNREGA"  -> "What about 2023-24?"

nothing remembered East Khasi Hills any more, and the last turn the follow-up
was rewritten against was the PMAY-G one.

This module keeps one compact record per topic and, when the user asks to go
back to a topic, puts that topic's context back in place. Nothing downstream
changes: the existing stages read session.state and session.last_turn exactly
as before, they just read the right topic's.

A topic is keyed by its scheme set ("MGNREGA", or "MGNREGA + PMAY-G" for a
comparison turn). Each record holds what continuing the topic needs and
nothing else: the ConversationState as the topic left it (scheme, place,
year, metric, provenance), the topic's last turn (the follow-up antecedent),
its last few questions, and a one-line summary. Execution state (SQL, rows,
repairs, errors) is never kept here.

Where it runs: pipeline._turn_context_stage, first thing (graph: context),
calls resolve_turn. No graph node was added or changed.

Where it lives: `session.topics`, part of the durable snapshot
(Session.to_snapshot, D-023) since 2026-10-08, so a return works on whichever
worker serves it. If a worker still sees a revision jump (the durable write
failed, so another worker's turns never reached the snapshot), checkpoint()
starts the topic record afresh instead of restoring an out-of-date topic.
The LangGraph checkpoint is not involved: it holds a paused run only.

Caching: the acknowledgement of a bare switch is marked confidence "low",
which the answer caches never store. A switch WITH a question ("go back to
MGNREGA, what about 2023?") is kept out of the caches by
routers.query.is_cacheable (is_topic_command).

Plain-words returns ("what was the PMAY-G information again?") and context
reset / idle expiry belong to app/conversation_layer.py, which hands a return
to this module in the "Go back to <topic>, <question>" form.

How a message is placed in a topic (resolve_turn):
  1. Bookkeeping first (checkpoint): the turn that just finished is filed
     under its topic, and the state under the state's own scheme. It runs at
     the START of the next turn because the router appends the finished turn
     only after the graph returns.
  2. A reply to our own "which topic?" pause picks that topic.
  3. An explicit return ("go back to MGNREGA", "coming back to PMAY, ...",
     "back to the previous topic") to a topic this conversation already has
     restores it. With a question after it, the question runs in that topic;
     on its own, a short acknowledgement is the answer.
     Unnamed ("the previous topic") with two or more topics to go back to:
     ask which one (a pause with one chip per topic), never guess.
  2b. A reply to our own "which earlier question?" pause picks that question.
  2c. "What did we discuss?" is answered with the conversation's questions,
     numbered (2026-10-18, see "The topic ledger" below).
  3b. A reference to an earlier QUESTION ("go back to the East Khasi Hills
     one", "the first question", "MGNREGA ka 2022 wala figure") restores that
     question's own scope from its topic's ledger; several matches: ask with
     one chip per question, never guess (2026-10-18, D-050).
  4. Anything else is the existing behaviour, unchanged: a follow-up continues
     the active topic, a question naming a new scheme starts a new topic (the
     scheme-change reset), "what about PMAY?" is the existing scheme swap.
Every decision is logged as pipeline_decision stage "topic".

Best-effort like the rest of the context layer: any failure in the
bookkeeping leaves the turn exactly as it would have run without this module.
"""
import asyncio
import logging
import time
from dataclasses import dataclass

from app import context_budget
from app.config import settings
from app.context_policy import _CpEnd, _CpSep, _CpStart, _cp_end_punct, _cp_ws
from app.text_match import Alt, Matcher, Opt, Pred, Rep, Seq, W, words

logger = logging.getLogger(__name__)

# The rule tag of our own "which topic?" pause (ClarificationNeeded.rule).
TOPIC_PAUSE_RULE = "topic-ambiguous"
# The rule tag of our own "which earlier question?" pause (the topic ledger).
LEDGER_PAUSE_RULE = "ledger-ambiguous"
# The edge_type of the acknowledgement a bare "go back to MGNREGA" gets.
TOPIC_SWITCH_EDGE = "topic_switch"
# The edge_type of the answer to "what did we discuss?".
HISTORY_EDGE = "conversation_history"

MAX_TOPICS = 8               # six schemes + a couple of comparison topics
_TOPIC_QUESTIONS = 5         # recent questions kept per topic
_ANSWER_CHARS = 2000         # the same cap Session.to_snapshot uses
_TOPIC_ROUTES = ("data", "knowledge")   # pipeline._ANTECEDENT_ROUTES
_FOCUS_TOPICS = ("Focus Plus", "Focus Legacy")
# "Go back to CM Elevate" while the conversation's topic is CM Elevate Legacy
# (a bare "CM Elevate" data question goes there by the 2026-10-12 decision,
# D-009): the one CM Elevate-family topic this conversation holds is meant;
# with both, ask (live matrix 2026-10-18, CM Elevate F7: it ran as a new
# question and was answered from the documents).
_CME_TOPICS = ("CM Elevate", "CM Elevate Legacy")


def same_scheme_family(a, b) -> bool:
    """The two CM Elevate datasets count as one scheme for topic continuity
    (a bare "CM Elevate" data question goes to Legacy by the 2026-10-12
    decision, and "who is eligible for CM Elevate?" is about both): a
    knowledge aside about one, or "and in West Garo Hills?" after it, continues
    the other's figure (live matrix 2026-10-18, CM Elevate F4)."""
    return a == b or (a in _CME_TOPICS and b in _CME_TOPICS)


# ── Detecting a topic switch ────────────────────────────────────────────────

# The opening of an explicit return: "go back to", "coming back to", "back
# to", "return to", "switch back to", "let's continue (with)", "resume",
# "now regarding". Anchored at the start: a switch is what the message opens
# with. Fillers before it ("ok, now", "so") are allowed.
def _tm_filler_gap(g: str) -> bool:
    """Whitespace and commas only (or nothing)."""
    return g.replace(",", " ").strip() == ""


_TM_GO = ("go", "going", "get", "getting", "come", "coming", "came", "turn", "turning", "jump", "jumping",
          "head", "heading", "switch", "switching", "move", "moving")
_SWITCH_LEAD = Matcher(Seq(
    _CpStart(_cp_ws),
    Rep(Seq(W("ok", "okay", "now", "so", "and", "alright", "right", "fine", "then", "well"),
            _CpSep(_tm_filler_gap))),
    Opt(Alt(W("lets"), Seq("let", "s"), "let us", "can we", "could we", W("please"), "i want to",
            Seq("id", "like", "to"), Seq("i", "d", "like", "to"))),
    Alt(Seq(W(*_TM_GO), "back", W("to", "on")),
        "back to",
        Seq(W("return", "returning"), "to"),
        W("revisit", "revisiting"),
        Seq(W("switch", "switching"), Opt("over"), "to"),
        Seq(W("continue", "continuing"), Opt(W("with", "on"))),
        W("resume", "resuming"),
        Seq(Opt("now"), "regarding"),
        "now about", "now for",
        Seq("again", W("on", "about")))))
# What the lead may be followed by before the topic: spaces, commas, colons, dashes.
_TM_LEAD_TAIL = " \t\n\r\f\v,:-"
_TM_BREAK_WORDS = ("what", "how", "which", "who", "when", "where", "show", "give", "tell", "list")


def _tm_is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _tm_clause_break(text: str) -> "tuple[int, int] | None":
    """(start, end) of the first clause break in `text`: a , . : ; ? ! mark, a
    spaced dash " - ", or " and " before a question word ("and what …"), with
    the whitespace around it. None when there is none."""
    n = len(text)

    def ws_back(k):
        while k > 0 and text[k - 1].isspace():
            k -= 1
        return k

    def ws_fwd(k):
        while k < n and text[k].isspace():
            k += 1
        return k

    for k, ch in enumerate(text):
        if ch in ",.:;?!":
            return ws_back(k), ws_fwd(k + 1)
        if ch == "-" and 0 < k < n - 1 and text[k - 1].isspace() and text[k + 1].isspace():
            return ws_back(k - 1), ws_fwd(k + 2)
        if (text[k:k + 3].lower() == "and" and k > 0 and text[k - 1].isspace()
                and k + 3 < n and text[k + 3].isspace()):
            after = ws_fwd(k + 3)
            j = after
            while j < n and _tm_is_word_char(text[j]):
                j += 1
            if text[after:j].lower() in _TM_BREAK_WORDS:
                return ws_back(k - 1), after
    return None


# "the previous topic / question / scheme", "the earlier one", "where we were".
# Matched on the whole (stripped) topic part, which must hold words and
# spaces only.
_TM_UNNAMED_NOUNS = ("topic", "question", "scheme", "one", "discussion", "subject", "conversation", "thing")
_UNNAMED_TOPIC = Matcher(Alt(
    Seq(Opt(W("the", "that", "our")), W("previous", "earlier", "last", "other", "old", "older", "first", "before"),
        W(*_TM_UNNAMED_NOUNS, *(w + "s" for w in _TM_UNNAMED_NOUNS)), sep="space"),
    Seq("where", "we", Alt("were", Seq("left", "off", sep="space")), sep="space"),
    Seq("what", "we", "were", Alt("discussing", Seq("talking", "about", sep="space")), sep="space")))


def _tm_unnamed_topic(target: str) -> bool:
    return (all(_tm_is_word_char(c) or c.isspace() for c in target)
            and _UNNAMED_TOPIC.fullmatch(target) is not None)


# Words that may sit around a named topic: "the previous MGNREGA question",
# "the MGNREGA one", "MGNREGA scheme please".
_TOPIC_FILLER = Matcher(W(
    "the", "that", "our", "previous", "earlier", "last", "old", "older", "question", "questions", "topic",
    "discussion", "scheme", "schemes", "one", "data", "please", "pls", "again", "thing", "conversation",
    "subject"))
_TM_FOCUS = Matcher(W("focus"))


@dataclass
class TopicSwitch:
    """What an explicit return asked for. `names` are the schemes named
    (empty for "the previous topic"); `bare_focus` is a bare "Focus";
    `remainder` is the question that came after it ("" for a bare switch)."""
    names: list
    bare_focus: bool
    remainder: str


def parse_switch(question: str) -> "TopicSwitch | None":
    """The explicit return in `question`, or None when it is not one."""
    from app import pipeline  # lazy: pipeline imports this module
    q = (question or "").strip()
    m = _SWITCH_LEAD.match(q)
    if not m:
        return None
    rest = q[m.end():].lstrip(_TM_LEAD_TAIL)
    brk = _tm_clause_break(rest)
    target, remainder = (rest[:brk[0]], rest[brk[1]:]) if brk else (rest, "")
    target = target.strip()
    remainder = remainder.strip()
    if not target:
        return None
    names = pipeline._named_schemes(target)
    if names:
        # Only the topic may sit in the topic part: "continue with MGNREGA
        # beneficiaries in East Khasi Hills" is a question, not a switch.
        if _TOPIC_FILLER.sub(" ", _strip_scheme_words(target)).strip(" ,.-"):
            return None
        return TopicSwitch(names=list(names), bare_focus=False, remainder=remainder)
    if pipeline._is_ambiguous_focus(target) and not _TOPIC_FILLER.sub(
            " ", _TM_FOCUS.sub(" ", target)).strip(" ,.-"):
        return TopicSwitch(names=[], bare_focus=True, remainder=remainder)
    if _tm_unnamed_topic(target):
        return TopicSwitch(names=[], bare_focus=False, remainder=remainder)
    return None


def _strip_scheme_words(text: str) -> str:
    from app import pipeline
    out = text
    for pattern in pipeline._SCHEME_NAME_MATCHER.values():
        out = pattern.sub(" ", out)
    # Misspelled names (_named_schemes' fuzzy fallback) leave one short word.
    words = [w for w in out.split() if w.strip(" ,.-")]
    if len(words) == 1 and pipeline._named_schemes(words[0]):
        return ""
    return out


def is_topic_command(question: str) -> bool:
    """True for an explicit topic switch. Such a message means something only
    in its own conversation, so it must never be served from or written to the
    shared answer caches (routers.query.is_cacheable)."""
    try:
        if parse_switch(question) is not None:
            return True
        # A reference to an earlier question ("go back to the East Khasi Hills
        # one") or "what did we discuss?" likewise (the topic ledger).
        return _ledger_on() and (parse_backward(question) is not None or parse_history(question))
    except Exception:  # noqa: BLE001
        return False


# ── The per-session record ──────────────────────────────────────────────────
# session.topics (persisted in the Session snapshot):
#   {"active": "MGNREGA", "order": ["PMAY-G", "MGNREGA"],   # least recent first
#    "ack": None | "<the raw text of a bare switch awaiting its next question>",
#    "items": {"MGNREGA": {"schemes": [...], "state": {...}, "last_turn": {...},
#                          "last_fp": "...", "questions": [...], "turns": 3,
#                          "summary": "..."}}}

def _memory(session) -> dict:
    mem = getattr(session, "topics", None)
    if not isinstance(mem, dict):
        mem = {}
        session.topics = mem
    mem.setdefault("active", None)
    mem.setdefault("order", [])
    mem.setdefault("items", {})
    mem.setdefault("ack", None)
    return mem


def topic_key(schemes) -> "str | None":
    """The topic a scheme list belongs to: the scheme, or the comparison."""
    from app import pipeline
    names = [s for s in (schemes or []) if s]
    if not names:
        return None
    ordered = [s for s in pipeline.SCHEME_CATALOG if s in names] + \
              sorted(s for s in names if s not in pipeline.SCHEME_CATALOG)
    return " + ".join(dict.fromkeys(ordered))


def _key_schemes(key: str) -> list:
    return [s for s in key.split(" + ") if s]


def _turn_topic(turn) -> "str | None":
    if turn is None or getattr(turn, "route", None) not in _TOPIC_ROUTES:
        return None
    return topic_key(getattr(turn, "schemes", None))


def _state_topic(state) -> "str | None":
    if state is None:
        return None
    if state.scheme:
        return state.scheme
    if state.comparison_kind == "scheme" and len(state.comparison_entities or []) >= 2:
        return topic_key(state.comparison_entities)
    return None


def _turn_dict(turn) -> dict:
    return {"question": turn.question, "raw_question": turn.raw_question, "route": turn.route,
            "schemes": list(turn.schemes or []), "resolved_entities": dict(turn.resolved_entities or {}),
            "answer": (turn.answer or "")[:_ANSWER_CHARS], "result_summary": turn.result_summary or ""}


def _turn_from(d: dict):
    from app.session_store import Turn
    return Turn(question=d.get("question") or "", raw_question=d.get("raw_question") or "",
                route=d.get("route") or "data", schemes=list(d.get("schemes") or []),
                resolved_entities=dict(d.get("resolved_entities") or {}),
                answer=d.get("answer") or "", result_summary=d.get("result_summary") or "")


def _fingerprint(turn) -> str:
    return "\x1f".join([turn.raw_question or "", turn.question or "", (turn.answer or "")[:200]])


def _touch(mem: dict, key: str) -> None:
    order = [k for k in mem["order"] if k != key]
    order.append(key)
    mem["order"] = order
    # Bounded: the least recently used topic goes first.
    while len(order) > MAX_TOPICS:
        gone = order.pop(0)
        mem["items"].pop(gone, None)
        if mem.get("active") == gone:
            mem["active"] = None


def _fy(year) -> str:
    try:
        y = int(year)
    except (TypeError, ValueError):
        return ""
    return f"FY {y}-{str(y + 1)[-2:]}"


def _summary(key: str, item: dict) -> str:
    """One deterministic line: what this topic was about where it was left."""
    st = item.get("state") or {}
    bits = [b for b in (st.get("metric"),
                        st.get("village") or st.get("block") or st.get("district"),
                        _fy(st.get("year")) if st.get("year") is not None else
                        ("all financial years" if st.get("year_all") else None)) if b]
    line = key + (": " + " · ".join(str(b) for b in bits) if bits else "")
    last = (item.get("last_turn") or {}).get("question")
    return f"{line} — last asked: {last}" if last else line


def checkpoint(session) -> None:
    """File the turn that just finished under its topic, and the current
    state under the state's own topic. Runs at the start of the next turn."""
    mem = _memory(session)
    # Each request on this worker moves the durable revision on by one
    # (session_sync.sync_out). A bigger jump means turns were served by another
    # worker, whose topic records this copy never saw: drop them rather than
    # ever restore an out-of-date topic. The conversation itself is unaffected.
    rev, seen = int(getattr(session, "rev", 0) or 0), mem.get("rev")
    if seen is not None and rev > int(seen) + 1 and mem["items"]:
        context_budget.log_decision("topic", action="reset-stale", topics=len(mem["items"]))
        mem.update(active=None, order=[], items={}, ack=None)
    mem["rev"] = rev
    last = session.last_turn
    ack, mem["ack"] = mem.get("ack"), None
    if ack and last is not None and last.route == "edge" and last.raw_question == ack:
        # The previous message was a bare switch ("go back to MGNREGA"). Its
        # acknowledgement is not something to follow up on: the topic's own
        # last turn is (otherwise "what about 2023-24?" has no antecedent).
        item = mem["items"].get(mem.get("active") or "")
        if item and item.get("last_turn"):
            session.turns.append(_turn_from(item["last_turn"]))
        return
    key = _turn_topic(last)
    filed = False
    if key is not None:
        item = mem["items"].setdefault(key, {"schemes": _key_schemes(key), "state": None,
                                             "last_turn": None, "last_fp": None,
                                             "questions": [], "turns": 0, "summary": key})
        fp = _fingerprint(last)
        if item.get("last_fp") != fp:
            item["last_turn"] = _turn_dict(last)
            item["last_fp"] = fp
            item["questions"] = (item.get("questions") or [])[-(_TOPIC_QUESTIONS - 1):] + [last.question]
            item["turns"] = int(item.get("turns") or 0) + 1
            filed = True
        mem["active"] = key
        _touch(mem, key)
    # The state belongs to the topic it names, which is not always the last
    # turn's: a KNOWLEDGE digression into PMAY-G leaves the MGNREGA data state
    # in place (update_state), and that state is MGNREGA's, not PMAY-G's.
    skey = _state_topic(session.state)
    if skey is not None and skey in mem["items"]:
        mem["items"][skey]["state"] = session.state.to_dict()
    if filed and key in mem["items"]:
        _file_ledger(mem, key, last, session.state)
    for k in ({key, skey} - {None}):
        if k in mem["items"]:
            mem["items"][k]["summary"] = _summary(k, mem["items"][k])


def describe(session) -> dict:
    """The global view: which topics this conversation has and which is active
    (most recent last). For logs and the acknowledgement text."""
    mem = _memory(session)
    return {"active": mem.get("active"),
            "topics": [{"topic": k, "turns": (mem["items"].get(k) or {}).get("turns", 0),
                        "summary": (mem["items"].get(k) or {}).get("summary") or k}
                       for k in mem["order"] if k in mem["items"]]}


# ── The topic ledger: going back to an earlier QUESTION ─────────────────────
# A topic record holds the topic's LAST turn, so after
#
#    1 MGNREGA person-days, East Khasi Hills, 2022-23
#    2 Who is eligible for PMAY-G?
#    3 MGNREGA job cards, West Garo Hills, 2023-24
#    4 "Go back to the East Khasi Hills one"
#
# "go back to MGNREGA" could only restore question 3: question 1's scope was
# gone. Each topic now also keeps a ledger of its last CONTEXT_LEDGER_PER_TOPIC
# questions, each with the scope it ran in (Context Memory proposal, Phase 3,
# 2026-10-18). A ledger entry holds the scope and the question, never a figure
# to repeat: going back RE-RUNS the question in its restored scope, so a data
# refresh in between can never show a stale number. The answer is kept only
# (cut short) as the follow-up antecedent.
#
# A message is read as a reference to an earlier question only with a clear
# cue (parse_backward), and only an entry it matches is restored:
#   by order    "the first question", "question 3", "the last question"
#   by content  "the East Khasi Hills one", "the job cards question",
#               "MGNREGA ka 2023 wala figure" (place, year and words of the
#               entry's own question; a named scheme narrows to its topic)
# One match: restore it. Several: ask with one chip per entry (never guess).
# None: the message runs exactly as it did before the ledger existed.
#
# A ledger entry (item["ledger"], least recent last; persisted with the topics):
#   {"n": 3, "question": <standalone question run>, "raw": <as typed>,
#    "route": "data", "state": {...ConversationState...} | None,
#    "turn": {...the turn, answer cut to _LEDGER_ANSWER_CHARS...}, "ts": ...}
# "n" is the question's number in the conversation (mem["seq"]); it is what
# "the first question" and the chips ("Go back to question 3") refer to.

_LEDGER_ANSWER_CHARS = 300   # the snapshot carries up to 8 x 6 entries


def _ledger_on() -> bool:
    return bool(getattr(settings, "BACKWARD_RESOLVER_ENABLED", True))


def _file_ledger(mem: dict, key: str, turn, state) -> None:
    """Append the turn that just finished to its topic's ledger, with the
    scope it ran in. Asking the same question again keeps its number."""
    if not _ledger_on():
        return
    # A pure "go back to the East Khasi Hills one" / "go back to MGNREGA"
    # re-runs an earlier question and asks nothing new: it is not a question
    # of its own (browser check 2026-10-18: it was listed as "3. Go back to
    # the East Khasi Hills one" and offered as a chip). A return WITH a
    # question ("go back to the first one, what about Ri Bhoi?") runs that
    # question, which differs from the typed text, and is filed as usual.
    raw = (turn.raw_question or "").strip()
    if raw and raw == (turn.question or "").strip() and (parse_switch(raw) or parse_backward(raw)):
        return
    item = mem["items"][key]
    st = state.to_dict() if state is not None and _state_topic(state) == key else None
    if st is None and len(item.get("schemes") or []) == 1:
        st = {"scheme": item["schemes"][0]}
    old = [e for e in item.get("ledger") or [] if e.get("question") == turn.question]
    if old:
        n = old[0]["n"]
    else:
        mem["seq"] = int(mem.get("seq") or 0) + 1
        n = mem["seq"]
    d = _turn_dict(turn)
    d["answer"] = d["answer"][:_LEDGER_ANSWER_CHARS]
    ledger = [e for e in item.get("ledger") or [] if e.get("question") != turn.question]
    ledger.append({"n": n, "question": turn.question, "raw": turn.raw_question, "route": turn.route,
                   "state": st, "turn": d, "ts": time.time()})
    item["ledger"] = ledger[-max(1, int(getattr(settings, "CONTEXT_LEDGER_PER_TOPIC", 6) or 6)):]


def _ledger_entries(mem: dict) -> list:
    """Every (topic, entry) this conversation holds, oldest question first."""
    out = [(k, e) for k in mem["order"] if k in mem["items"]
           for e in (mem["items"][k].get("ledger") or [])]
    return sorted(out, key=lambda ke: ke[1].get("n") or 0)


def recent_data_turn(session, schemes=None, within: int = 4):
    """The latest DATA question among the conversation's last `within`
    questions, as a Turn, from the durable ledger — for a worker rehydrated
    from the snapshot, whose session.turns holds only the last turn (live
    2026-10-18, scenario H on 3 workers: "And in West Garo Hills?" after
    "Who is eligible for PMAY-G?" lost the PMAY-G figure it continues).
    With `schemes`, None unless that latest DATA question is about one of them."""
    try:
        if session is None or not _ledger_on():
            return None
        entries = _ledger_entries(_memory(session))
        if not entries:
            return None
        newest = entries[-1][1].get("n") or 0
        for _k, e in reversed(entries):
            if (e.get("n") or 0) <= newest - within:
                break
            if e.get("route") == "data" and e.get("turn"):
                turn = _turn_from(e["turn"])
                if schemes and not any(same_scheme_family(a, b) for a in schemes for b in (turn.schemes or [])):
                    return None
                return turn
    except Exception:  # noqa: BLE001 — a fallback must never break the turn
        logger.warning("topic memory: recent_data_turn failed (non-fatal)", exc_info=True)
    return None


# Words for "the Nth question". "previous" / "latest" mean the last one.
_ORDINALS = {"first": 1, "1st": 1, "initial": 1, "original": 1, "opening": 1, "second": 2, "2nd": 2,
             "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "sixth": 6, "6th": 6,
             "seventh": 7, "7th": 7, "eighth": 8, "8th": 8, "ninth": 9, "9th": 9, "tenth": 10, "10th": 10,
             "last": "last", "latest": "last", "previous": "last", "recent": "last"}
_QUESTION_NOUNS = ("question", "questions", "query", "queries")
# Nouns that make "the East Khasi Hills one" a reference to something said.
_REF_NOUNS = frozenset(("one", "question", "questions", "query", "queries", "figure", "figures", "number",
                        "numbers", "answer", "answers", "result", "results", "discussion", "data",
                        "wala", "wali", "wale", "vala", "vali", "vale"))
_HINDI_BACK = ("pehle", "pehla", "pehli", "pahle", "pichla", "pichle", "pichli", "pichhla", "pichhle",
               "dobara", "dubara", "wapas", "vapas", "wala", "wali", "wale")
# A cue anywhere in the message that it refers to something said earlier.
# "the last one" / "the first one" are NOT cues: they point into a result
# ("which one had the highest?" -> "the last one"), which the follow-up layer
# handles.
_BACK_CUE = Matcher(Alt(
    Seq(W(*_ORDINALS), W(*_QUESTION_NOUNS)),
    Seq(W("question", "query"), Opt(W("number", "no")), Pred(str.isdigit)),
    Seq(W("you", "u"), Opt(W("have", "had", "just", "already")),
        W("said", "showed", "shown", "told", "gave", "given", "mentioned", "shared", "answered", "reported")),
    Seq(W("we", "i"), Opt(W("have", "had", "just", "already")),
        W("discussed", "asked", "talked", "saw", "seen", "looked", "checked", "covered")),
    Seq("remind", "me"),
    Seq(W("the", "that"), W("earlier", "previous", "older", "first", "initial", "original"),
        W("one", "question", "query", "figure", "number", "answer", "result", "data")),
    W(*_HINDI_BACK),
    Seq("phir", "se")))
# Words that carry no content of their own in a reference ("go back to the
# ... one", "what was the ... figure you showed again?"); what is left is
# matched against the ledger.
_BACK_FILLER = frozenset((
    "go", "going", "get", "come", "coming", "came", "back", "to", "return", "returning", "revisit", "switch",
    "continue", "resume", "regarding", "now", "ok", "okay", "so", "and", "please", "pls", "the", "that",
    "this", "those", "these", "a", "an", "one", "ones", "what", "whats", "was", "were", "is", "are", "again",
    "remind", "me", "you", "u", "said", "showed", "shown", "told", "gave", "given", "mentioned", "shared",
    "answered", "reported", "we", "i", "have", "had", "just", "already", "discussed", "asked", "talked",
    "saw", "seen", "looked", "checked", "covered", "about", "for", "of", "on", "in", "figure", "figures",
    "number", "numbers", "no", "answer", "answers", "result", "results", "data", "info", "information",
    "earlier", "previously", "before", "older", "tell", "show", "give", "repeat", "can", "could", "would",
    "will", "once", "more", "there", "it", "its", "let", "lets", "us", "question", "questions", "query",
    "queries", "discussion", "topic", "scheme", "one", "phir", "se", "ka", "ki", "ke", "ko", "batao",
    "bataiye", "bataye", "dikhao", "do", "dena", "hai", "tha", "thi", "fy", "year", "financial", "with",
    *_ORDINALS, *_HINDI_BACK, "vala", "vali", "vale"))


@dataclass
class BackRef:
    """A reference to an earlier question. `ordinal` is 1, 2, ... or "last"
    (None: by content); `target` is the referring part; `remainder` is a
    question that came after it ("go back to the first one, what about
    2023-24?")."""
    ordinal: "int | str | None"
    target: str
    remainder: str
    lead: bool


def _ordinal(text: str) -> "int | str | None":
    ws = words(text)
    for i, w in enumerate(ws):
        nxt = ws[i + 1] if i + 1 < len(ws) else ""
        # "the second question", also "the first PMAY-G question" (a scheme
        # name, up to three words, in between)
        if w in _ORDINALS and any(x in _QUESTION_NOUNS for x in ws[i + 1:i + 5]):
            return _ORDINALS[w]
        if w in ("question", "query"):
            j = i + 2 if nxt in ("number", "no") else i + 1
            if j < len(ws) and ws[j].isdigit():
                return int(ws[j])
    return None


def _again_cue(text: str) -> bool:
    """"again" as a reference: "what was that figure again?", "show me the
    East Khasi Hills data again" — not "show it again by block" alone."""
    ws = words(text)
    return "again" in ws and (ws[0] in ("what", "whats", "repeat", "say")
                              or any(w in _REF_NOUNS for w in ws))


def parse_backward(question: str) -> "BackRef | None":
    """The reference to an earlier question in `question`, or None. Read only
    when parse_switch found no topic return (resolve_turn)."""
    q = (question or "").strip()
    if not q:
        return None
    m = _SWITCH_LEAD.match(q)
    if m:
        # "go back to the East Khasi Hills one", "back to question 3, what
        # about 2024?". The target must refer to something said: "continue
        # with MGNREGA beneficiaries in East Khasi Hills" is a new question.
        rest = q[m.end():].lstrip(_TM_LEAD_TAIL)
        brk = _tm_clause_break(rest)
        target, remainder = (rest[:brk[0]], rest[brk[1]:]) if brk else (rest, "")
        target = target.strip()
        if not target:
            return None
        ordinal = _ordinal(target)
        # "go back to the first one" / "back to the second": after a "go back
        # to" lead the bare ordinal is the question's number (live 2026-10-19:
        # it had no ordinal, matched no content and fell to the knowledge base,
        # which explained that MGNREGA has no "first one"). Without the lead,
        # "the first one" still points into a result (see _BACK_CUE).
        if ordinal is None:
            bare = [w for w in words(target) if w not in ("the", "that", "my", "our", "very")]
            if bare and bare[0] in _ORDINALS and bare[1:] in ([], ["one"]):
                ordinal = _ORDINALS[bare[0]]
        if ordinal is None and not (_REF_NOUNS & set(words(target))):
            return None
        return BackRef(ordinal, target, remainder.strip(), True)
    # A cue anywhere. The clause holding it is the reference; a clause after
    # it is the question to run there ("you said 1.8 lakh for East Khasi
    # Hills, what about Ri Bhoi?"). A cue only in a later clause ("what about
    # Ri Bhoi, like you said?") is left to the follow-up layer.
    brk = _tm_clause_break(q)
    first, rest = (q[:brk[0]], q[brk[1]:]) if brk else (q, "")
    if not (_BACK_CUE.search(first) or _again_cue(first)):
        return None
    return BackRef(_ordinal(first), first.strip(), rest.strip(), False)


def _sing(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _content_words(text: str) -> set:
    return {_sing(w) for w in words(text)
            if w not in _BACK_FILLER and not w.isdigit() and len(w) >= 3}


def _years_in(text: str) -> set:
    """The four-digit years in `text` ("2022-23" -> {"2022"})."""
    return {w for w in words(text) if len(w) == 4 and w.isdigit() and w.startswith("20")}


def _entry_text(e: dict) -> str:
    st = e.get("state") or {}
    return " ".join(str(x) for x in (e.get("raw"), e.get("question"), st.get("metric")) if x)


def _score(e: dict, target: str, content: set, years: set) -> int:
    """How well `target` describes ledger entry `e`: a place it ran for
    counts 3, its year 2, each word of its own question 1. A year the
    entry did not run for rules it out."""
    st = e.get("state") or {}
    score = 0
    for place in (st.get("village"), st.get("block"), st.get("district")):
        if place and words(place) and Matcher(Seq(*words(place))).search(target):
            score += 3
            # counted once, as the place, not again as words of the question
            content = content - {_sing(w) for w in words(place)}
    if years:
        held = ({str(st["year"])} if st.get("year") is not None else set()) | _years_in(e.get("question") or "")
        if not held & years:
            return 0
        score += 2
    return score + len(content & _content_words(_entry_text(e)))


def _match_entries(mem: dict, ref: BackRef, question: str) -> "tuple[list, str]":
    """((topic, entry) candidates, "order" | "content")."""
    from app import pipeline
    entries = _ledger_entries(mem)
    named = list(pipeline._named_schemes(ref.target))
    if named:
        entries = [(k, e) for k, e in entries if set(named) <= set(_key_schemes(k))]
    if not entries:
        return [], "none"
    if ref.ordinal is not None:
        if ref.ordinal == "last":
            return [entries[-1]], "order"
        if named:
            # "the second MGNREGA question": the second within that topic
            return ([entries[ref.ordinal - 1]] if 0 < ref.ordinal <= len(entries) else []), "order"
        return [ke for ke in entries if ke[1].get("n") == ref.ordinal], "order"
    try:
        target = pipeline._correct_place_spelling(ref.target)
    except Exception:  # noqa: BLE001 — the typed text still matches exact names
        target = ref.target
    content = _content_words(target) - {_sing(w) for s in named for w in words(s)}
    years = _years_in(target)
    scored = [(s + (1 if named and s else 0), k, e)
              for k, e in entries for s in (_score(e, target, content, years),)]
    best = max((s for s, _, _ in scored), default=0)
    if best < 2:
        return [], "none"
    picked = [(k, e) for s, k, e in scored if s >= 0.8 * best]
    return sorted(picked, key=lambda ke: ke[1].get("n") or 0, reverse=True), "content"


def _entry_label(key: str, e: dict) -> str:
    """A chip label: '#1 MGNREGA · East Khasi Hills · FY 2022-23 · person-days'."""
    st = e.get("state") or {}
    place = st.get("village") or st.get("block") or st.get("district")
    bits = [key] + [b for b in (str(place).title() if place else None,
                                _fy(st.get("year")) if st.get("year") is not None else None,
                                st.get("metric")) if b]
    if len(bits) == 1:
        q = (e.get("question") or e.get("raw") or "").strip()
        bits.append(q[:60] + ("…" if len(q) > 60 else ""))
    return f"#{e.get('n')} " + " · ".join(str(b) for b in bits)


def _ask_which_entry(candidates: list, remainder: str):
    from app import pipeline
    tail = f", {remainder}" if remainder else ""
    return pipeline.ClarificationNeeded(
        "Which earlier question do you mean?",
        options=[{"label": _entry_label(k, e), "question": f"Go back to question {e.get('n')}{tail}"}
                 for k, e in candidates[:4]],
        rule=LEDGER_PAUSE_RULE)


def _asks_more(target: str, e: dict) -> bool:
    """Whether the reference asks for something the entry did not hold: a
    word that is neither in the entry's question nor its scheme or place."""
    st = e.get("state") or {}
    known = _content_words(_entry_text(e))
    for name in list((e.get("turn") or {}).get("schemes") or []) + [st.get(f) for f in ("district", "block", "village")]:
        if name:
            known |= {_sing(w) for w in words(name)}
    return bool(_content_words(target) - known)


# Words after "the first question" that change nothing ("repeat my first
# question again please").
_TAIL_FILLER = frozenset(("again", "please", "pls", "once", "more", "now", "too", "also", "same", "the", "that",
                          "this", "it", "one", "i", "asked", "had", "my", "of", "ok", "okay", "kindly", "but",
                          "and", "with", "just", "instead"))


def _ordinal_tail(target: str) -> str:
    """What follows "the Nth question" in the same clause, when it changes the
    question: "repeat my first question for West Garo Hills" -> "for West Garo
    Hills". Empty when nothing (or only filler) follows. Audit 2026-10-19: the
    tail had no clause break, so the first question re-ran unchanged."""
    toks = (target or "").split()
    low = [t.lower().strip(",.?!:;") for t in toks]
    for i, w in enumerate(low):
        if w in _ORDINALS and any(x in _QUESTION_NOUNS for x in low[i + 1:i + 4]):
            j = next(k for k in range(i + 1, min(i + 4, len(low))) if low[k] in _QUESTION_NOUNS)
            tail = toks[j + 1:]
            while tail and tail[0].lower().strip(",.?!:;") in _TAIL_FILLER - {"for", "in"}:
                tail = tail[1:]
            if any(t.lower().strip(",.?!:;") not in _TAIL_FILLER for t in tail):
                return " ".join(tail).strip(" ,.?!:;")
            return ""
    return ""


def _restore_entry(session, mem: dict, key: str, e: dict, ref: BackRef, how: str) -> "TopicTurn":
    """Put an earlier question's scope and turn back in place. The question
    that runs is the one after the reference, else the user's own words when
    they ask for more than the entry held ("show the East Khasi Hills data
    again by block"), else the entry's question, re-run."""
    from app.session_store import ConversationState
    restored = ConversationState.from_dict(e.get("state") or {})
    restored.turn_count = session.state.turn_count
    session.state = restored
    if e.get("turn"):
        session.turns.append(_turn_from(e["turn"]))
    before = mem.get("active")
    mem["active"] = key
    _touch(mem, key)
    if getattr(session, "pending_scope_q", None):
        _clear_pending(session)
    _tail = "" if ref.remainder or ref.ordinal is None else _ordinal_tail(ref.target)
    if ref.remainder:
        question = ref.remainder
    elif _tail:
        # The restored question is the antecedent; the tail is its follow-up
        # ("for West Garo Hills"), rewritten against it like any other.
        question = _tail
    elif how == "content" and not ref.lead and _asks_more(ref.target, e):
        question = ref.target
    else:
        question = e.get("question") or ref.target
    context_budget.log_decision("topic", action="restore-question", n=e.get("n"), topic=key, previous=before,
                                by=how, rerun=question == e.get("question"))
    logger.info("topic memory: restored question #%s (%s, by %s)", e.get("n"), key, how)
    return TopicTurn(question=question, action="restore", topic=key)


def _backward(session, mem: dict, question: str) -> "TopicTurn | None":
    """Restore the earlier question `question` refers to; ask when several
    match; None when it refers to none (the message then runs as before)."""
    if not _ledger_on() or not _ledger_entries(mem):
        return None
    ref = parse_backward(question)
    if ref is None:
        return None
    picked, how = _match_entries(mem, ref, question)
    if len(picked) == 1:
        return _restore_entry(session, mem, picked[0][0], picked[0][1], ref, how)
    if len(picked) >= 2:
        context_budget.log_decision("topic", action="ask-question", candidates=[e.get("n") for _, e in picked])
        session.turn_context = {}
        raise _ask_which_entry(picked, ref.remainder)
    context_budget.log_decision("topic", action="no-such-question")
    return None


# ── Phase 4: a reference the rules cannot place, picked by the model ────────
# "is that figure you gave for the housing scheme still right?", "the
# district one from before": a backward cue, but no place, year, number or
# question words that match one ledger entry. The rewrite model (9B; follow-up
# resolution in the fixed role map) reads the last turns and a NUMBERED list
# of this conversation's questions and answers with one id, NONE or ASK. It
# cannot output a scheme, place or year: anything but a listed id / NONE /
# ASK is discarded and treated as ASK (or as NONE when there is only one
# question, which would make a pointless chip). A failed or slow call leaves
# the turn exactly as it ran before.

# What each scheme is about, as the "which scheme?" chips say it
# (pipeline c04_scheme_listing): live 2026-10-18 the model answered NONE for
# "that employment figure you gave earlier" with an MGNREGA person-days
# question in the list — it needs to know MGNREGA IS employment.
_SCHEME_ABOUT = {"MGNREGA": "rural employment, person-days, job cards, wages",
                 "PMAY-G": "rural housing, houses sanctioned / completed",
                 "Focus Plus": "farmer cash benefit", "CM Elevate": "livelihood / enterprise applications",
                 "Focus Legacy": "producer group payments", "CM Elevate Legacy": "sanctions & disbursements"}


def _reference_prompt(session, question: str, entries: list) -> str:
    recent = [t for t in list(getattr(session, "turns", []) or [])[-3:] if t.route in _TOPIC_ROUTES]
    lines = [f'- User: "{t.raw_question}" -> answered as: "{t.question}"' for t in recent]
    cands = []
    for k, e in entries:
        about = "; ".join(f"{s} = {_SCHEME_ABOUT[s]}" for s in _key_schemes(k) if s in _SCHEME_ABOUT)
        answer = " ".join(((e.get("turn") or {}).get("answer") or "").split())[:160]
        cands.append(f"q{e.get('n')}: {e.get('question')}\n    scope: {_entry_label(k, e)}"
                     + (f"\n    scheme: {about}" if about else "") + (f'\n    answer was: "{answer}"' if answer else ""))
    return ("You decide which EARLIER question of this conversation the user's new message refers to.\n"
            "Recent turns:\n" + ("\n".join(lines) or "- (none)") + "\n\n"
            "Earlier questions:\n" + "\n".join(cands) + "\n\n"
            f'New message: "{question}"\n\n'
            "Match by MEANING, not only by the same words: 'employment' points to a question about person-days "
            "or job cards, 'housing' to one about houses, 'that figure' to the question whose answer gave it.\n"
            "Answer with exactly ONE token: the id of the earlier question the message refers to (for example "
            "q2), or NONE if it refers to none of them, or ASK if two or more fit equally well. "
            "Do not explain. Do not write anything else.")


def _parse_pick(text: str, ids: set) -> str:
    """'q3' (a listed id), 'NONE' or 'ASK'. Anything else is ASK."""
    ws = words(text)
    for w in ws[:3]:
        if w in ids:
            return w
        if w in ("none", "ask"):
            return w.upper()
    return "ASK"


async def resolve_reference(session, question: str) -> "TopicTurn | None":
    """The constrained model pick for a backward reference the rules left
    unplaced (see above). None: nothing to do, the turn runs as before.
    Raises ClarificationNeeded for ASK."""
    from app import llm, pipeline
    if not (_enabled(session) and _ledger_on() and getattr(settings, "LLM_REFERENCE_ENABLED", True)):
        return None
    try:
        mem = _memory(session)
        entries = _ledger_entries(mem)
        if not entries or getattr(session, "pending_scope_q", None):
            return None
        if parse_switch(question) is not None or parse_history(question):
            return None
        # "So I asked about pie chart, right? But why you are giving line chart?" is
        # about how the LAST answer is drawn, not a pointer to an earlier question:
        # read as one, "I asked about pie chart" was cut off and the redraw lost the
        # pie (live 2026-10-19 16:12, KI-333; c15 _chart_view_question)
        if pipeline._chart_view_request(question) is not None:
            return None
        ref = parse_backward(question)
        if ref is None:
            return None
        # the rules found nothing to restore (else resolve_turn would have)
        if _match_entries(mem, ref, question)[0]:
            return None
        entries = entries[-8:]
        by_id = {f"q{e.get('n')}": (k, e) for k, e in entries}
        try:
            raw = await asyncio.wait_for(
                llm.call_rewriter(_reference_prompt(session, question, entries), max_tokens=8,
                                  role="reference"),
                timeout=float(getattr(settings, "LLM_REFERENCE_TIMEOUT_SECONDS", 8) or 8))
        except Exception:  # noqa: BLE001 — a slow / failed call: run the turn as before
            logger.warning("topic memory: reference model call failed (non-fatal)", exc_info=True)
            context_budget.log_decision("topic", action="reference-model-failed")
            return None
        pick = _parse_pick(raw or "", set(by_id))
        context_budget.log_decision("topic", action="reference-model", pick=pick, candidates=list(by_id))
        if pick in by_id:
            k, e = by_id[pick]
            return _restore_entry(session, mem, k, e, ref, "model")
        if pick == "ASK" and len(entries) >= 2:
            session.turn_context = {}
            raise _ask_which_entry(list(reversed(entries)), ref.remainder)
        return None
    except Exception as e:  # noqa: BLE001
        if isinstance(e, pipeline.ClarificationNeeded):
            raise
        logger.warning("topic memory: reference resolve failed (non-fatal)", exc_info=True)
        return None


# ── "What did we discuss?" ──────────────────────────────────────────────────
_HISTORY_ASK = Matcher(Seq(
    _CpStart(_cp_ws),
    Rep(Alt(W("ok", "okay", "so", "and", "now", "hi", "hello", "please", "pls"), "can you tell me", "tell me",
            "remind me", "remind me of")),
    Alt(
        Seq("what", Opt(W("all", "else")), Opt(W("did", "have", "had")), "we", Opt("been"),
            W("discuss", "discussed", "discussing", "talk", "talked", "talking", "cover", "covered", "covering"),
            Opt("about")),
        Seq("what", Opt("all"), Opt(W("questions", "queries", "things")), Opt(W("did", "have", "had")),
            W("i", "we"), W("ask", "asked")),
        Seq(W("list", "show", "give", "repeat"), Opt(W("me", "us")), Opt("all"), Opt(W("my", "the", "our")),
            Opt(W("previous", "earlier", "past", "old")), W("questions", "queries", "history", "topics")),
        Seq(W("summarise", "summarize", "recap"), Opt("of"), Opt(W("our", "this", "the")),
            W("conversation", "chat", "discussion", "session")),
        Seq(Opt(W("my", "our", "the")), W("conversation", "chat", "question", "questions", "query"), "history")),
    Rep(W("so", "till", "until", "now", "far", "yet", "here", "today", "please", "pls", "in", "this",
          "conversation", "chat", "session")),
    _CpEnd(_cp_end_punct)))


def parse_history(question: str) -> bool:
    """True for "what did we discuss?" / "list my questions"."""
    return bool(question) and _HISTORY_ASK.match(question.strip()) is not None


def _history_answer(mem: dict) -> dict:
    """The questions of this conversation, topic by topic, numbered as
    "go back to question N" refers to them; the latest few as chips."""
    from app import pipeline
    lines = []
    for k in mem["order"]:
        ledger = sorted((mem["items"].get(k) or {}).get("ledger") or [], key=lambda e: e.get("n") or 0)
        if not ledger:
            continue
        lines.append(f"**{k}**")
        lines += [f"{e.get('n')}. {e.get('question') or e.get('raw')}" for e in ledger]
        lines.append("")
    if lines:
        answer = ("Here is what we have covered so far:\n\n" + "\n".join(lines)
                  + "\nTo go back to one, tap it below or say, for example, \"go back to question 1\".")
    else:
        answer = ("We haven't looked at any scheme yet in this conversation. Ask me about MGNREGA, PMAY-G, "
                  "Focus Plus, CM Elevate, Focus Legacy or CM Elevate Legacy to get started.")
    recent = [e for _, e in reversed(_ledger_entries(mem))][:4]
    # confidence "low": the answer caches never store such a reply.
    return {"route": "edge", "intent": "EDGE", "confidence": "low", "answer": answer,
            "edge_type": HISTORY_EDGE, **pipeline._empty_data_fields(),
            "suggestions": [e.get("question") for e in recent if e.get("question")]}


# ── Resolving a message to a topic ──────────────────────────────────────────

@dataclass
class TopicTurn:
    """resolve_turn's verdict: the question the turn runs on, or a finished
    `response` (the acknowledgement of a bare switch)."""
    question: str
    action: str = "none"           # none | continue | switch
    topic: "str | None" = None
    response: "dict | None" = None


def _enabled(session) -> bool:
    return (session is not None and settings.CONTEXT_LAYER_ENABLED and settings.CONTEXT_STATE_ENABLED
            and getattr(settings, "TOPIC_MEMORY_ENABLED", True))


def _clear_pending(session) -> None:
    session.pending_scope_q = None
    session.pending_village_hint = None
    session.pending_scope_rule = None
    session.pending_scope_options = None


def _match(mem: dict, sw: TopicSwitch) -> "tuple[str | None, list]":
    """(the existing topic the switch names, or None; the candidates when it
    is ambiguous). Only topics this conversation already has match."""
    items = mem["items"]
    if sw.names:
        key = topic_key(sw.names)
        if key in items:
            return key, []
        if sw.names == ["CM Elevate"]:
            have = [k for k in _CME_TOPICS if k in items]
            return (have[0], []) if len(have) == 1 else (None, have)
        return None, []
    if sw.bare_focus:
        # "Focus" is never guessed between the two datasets (CLAUDE.md §4).
        # Going back to the one Focus topic this conversation had is not a
        # guess; with both, ask.
        have = [k for k in _FOCUS_TOPICS if k in items]
        return (have[0], []) if len(have) == 1 else (None, have)
    # "the previous topic": the topics other than the active one, most recent first.
    others = [k for k in reversed(mem["order"]) if k != mem.get("active") and k in items]
    return (others[0], []) if len(others) == 1 else (None, others)


def _ask_which(candidates: list, remainder: str):
    from app import pipeline
    tail = f": {remainder}" if remainder else ""
    names = ", ".join(candidates[:-1]) + f" or {candidates[-1]}"
    return pipeline.ClarificationNeeded(
        f"Which topic would you like to go back to — {names}?",
        options=[{"label": k, "question": f"Go back to {k}{tail}"} for k in candidates],
        rule=TOPIC_PAUSE_RULE)


def _acknowledge(key: str, item: dict) -> dict:
    from app import pipeline
    st = item.get("state") or {}
    where = [b for b in (st.get("village") or st.get("block") or st.get("district"),
                         _fy(st.get("year")) if st.get("year") is not None else None) if b]
    last = (item.get("last_turn") or {}).get("question")
    answer = f"Back to {key}."
    if last:
        answer += f" We were on: \"{last}\""
        answer += f" ({', '.join(where)})." if where else ""
    answer += " Ask your next question about it — for example \"What about another year?\" — and I'll continue from there."
    # confidence "low": the answer caches never store such a reply
    # (cache.ResponseCache.put). This one names THIS conversation's last
    # question, and served from the cache to anyone else it would also skip
    # their switch. (The UI reads only a numeric confidence.)
    return {"route": "edge", "intent": "EDGE", "confidence": "low", "answer": answer,
            "edge_type": TOPIC_SWITCH_EDGE, "topic": key, "suggestions": [],
            **pipeline._empty_data_fields()}


def _switch(session, mem: dict, key: str, remainder: str, raw: str) -> TopicTurn:
    """Make `key` the active topic and put its context back in place."""
    from app.session_store import ConversationState
    item = mem["items"][key]
    before = mem.get("active")
    restored = ConversationState.from_dict(item.get("state") or {})
    if not item.get("state") and len(item.get("schemes") or []) == 1:
        restored.scheme = item["schemes"][0]
    # The turn counter is the conversation's, not the topic's (the rolling
    # summary is paced by it).
    restored.turn_count = session.state.turn_count
    session.state = restored
    if item.get("last_turn"):
        session.turns.append(_turn_from(item["last_turn"]))
    mem["active"] = key
    _touch(mem, key)
    context_budget.log_decision("topic", action="switch", topic=key, previous=before,
                                bare=not remainder, topics=len(mem["items"]))
    logger.info("topic memory: switched %s -> %s", before, key)
    if not remainder:
        mem["ack"] = raw
        return TopicTurn(question=raw, action="switch", topic=key, response=_acknowledge(key, item))
    return TopicTurn(question=remainder, action="switch", topic=key)


def _pick_reply(reply: str, options: "list | None", mem: dict) -> "str | None":
    """The topic a reply to our own pause picks: a chip, or a typed name."""
    from app import pipeline
    keys = [o.get("label") for o in (options or []) if o.get("label") in mem["items"]]
    text = (reply or "").strip()
    for o in options or []:
        if text.lower() == str(o.get("question") or "").strip().lower() and o.get("label") in keys:
            return o["label"]
    named = topic_key(pipeline._named_schemes(text))
    if named in keys:
        return named
    low = text.lower()
    hits = [k for k in keys if k.lower() in low]
    return hits[0] if len(hits) == 1 else None


def resolve_turn(session, question: str) -> TopicTurn:
    """Which topic this message belongs to, with that topic's context put in
    place (see the module docstring). Raises ClarificationNeeded for an
    unnamed return with several topics to go back to. Never raises otherwise."""
    if not _enabled(session):
        return TopicTurn(question=question)
    try:
        checkpoint(session)
    except Exception:  # noqa: BLE001 — bookkeeping must never break a turn
        logger.warning("topic memory: checkpoint failed (non-fatal)", exc_info=True)
        return TopicTurn(question=question)
    try:
        mem = _memory(session)
        # 2. A reply to our own "which topic?" pause.
        if getattr(session, "pending_scope_rule", None) == TOPIC_PAUSE_RULE:
            paused, options = session.pending_scope_q or "", session.pending_scope_options
            _clear_pending(session)
            picked = _pick_reply(question, options, mem)
            if picked is not None:
                sw = parse_switch(question) or parse_switch(paused)
                return _switch(session, mem, picked, sw.remainder if sw else "", question)
            context_budget.log_decision("topic", action="pause-abandoned")
            # Not a pick: the reply is a message of its own (handled below).
        # 2b. A reply to our own "which earlier question?" pause: a chip (or
        #     its label typed) becomes the chip's "Go back to question N".
        if getattr(session, "pending_scope_rule", None) == LEDGER_PAUSE_RULE:
            options = session.pending_scope_options
            _clear_pending(session)
            text = (question or "").strip().lower()
            hit = next((o for o in options or []
                        if text in (str(o.get("question") or "").strip().lower(),
                                    str(o.get("label") or "").strip().lower())), None)
            if hit is not None:
                question = hit["question"]
            else:
                context_budget.log_decision("topic", action="pause-abandoned")
        # 2c. "What did we discuss?": the conversation's questions, answered
        #     here. Like a "thanks", it does not end the topic: the answer
        #     before it stays the follow-up antecedent (aside, see
        #     conversation_layer.resume_after_small_talk).
        if _ledger_on() and parse_history(question):
            mem["aside"] = question
            context_budget.log_decision("topic", action="history", questions=len(_ledger_entries(mem)))
            return TopicTurn(question=question, action="history", topic=mem.get("active"),
                             response=_history_answer(mem))
        sw = parse_switch(question)
        if sw is None:
            # 3b. A reference to an earlier QUESTION (the topic ledger).
            back = _backward(session, mem, question)
            if back is not None:
                return back
            return TopicTurn(question=question, action="continue" if mem.get("active") else "none",
                             topic=mem.get("active"))
        if not sw.names and not sw.bare_focus:
            # "Go back to the first / second question" is a numbered QUESTION,
            # not "the previous topic" (which "the previous / earlier
            # question" still means).
            ref = parse_backward(question) if _ledger_on() else None
            if ref is not None and isinstance(ref.ordinal, int):
                back = _backward(session, mem, question)
                if back is not None:
                    return back
        key, candidates = _match(mem, sw)
        if key is None and len(candidates) >= 2:
            context_budget.log_decision("topic", action="ask", candidates=candidates)
            # The router remembers the pause's question from turn_context
            # (routers.query.pause_question); the stage that resets it per
            # request has not run yet, so clear the previous turn's values.
            session.turn_context = {}
            raise _ask_which(candidates, sw.remainder)
        if key is None:
            # Nothing in this conversation to go back to (a scheme never
            # discussed, or no other topic): the message runs as it always did.
            context_budget.log_decision("topic", action="no-such-topic", names=sw.names)
            return TopicTurn(question=question, action="continue" if mem.get("active") else "none",
                             topic=mem.get("active"))
        if key == mem.get("active") and sw.remainder:
            # "Regarding MGNREGA, how many job cards?" while on MGNREGA: there
            # is nothing to switch, and the question runs exactly as before.
            return TopicTurn(question=question, action="continue", topic=key)
        if getattr(session, "pending_scope_q", None):
            # An explicit switch while another pause waits abandons that pause.
            _clear_pending(session)
            context_budget.log_decision("topic", action="pause-abandoned")
        return _switch(session, mem, key, sw.remainder, question)
    except Exception as e:  # noqa: BLE001
        from app import pipeline
        if isinstance(e, pipeline.ClarificationNeeded):
            raise
        logger.warning("topic memory: resolve failed (non-fatal)", exc_info=True)
        return TopicTurn(question=question)
