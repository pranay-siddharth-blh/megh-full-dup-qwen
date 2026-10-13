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
  4. Anything else is the existing behaviour, unchanged: a follow-up continues
     the active topic, a question naming a new scheme starts a new topic (the
     scheme-change reset), "what about PMAY?" is the existing scheme swap.
Every decision is logged as pipeline_decision stage "topic".

Best-effort like the rest of the context layer: any failure in the
bookkeeping leaves the turn exactly as it would have run without this module.
"""
import logging
import re
from dataclasses import dataclass

from app import context_budget
from app.config import settings

logger = logging.getLogger(__name__)

# The rule tag of our own "which topic?" pause (ClarificationNeeded.rule).
TOPIC_PAUSE_RULE = "topic-ambiguous"
# The edge_type of the acknowledgement a bare "go back to MGNREGA" gets.
TOPIC_SWITCH_EDGE = "topic_switch"

MAX_TOPICS = 8               # six schemes + a couple of comparison topics
_TOPIC_QUESTIONS = 5         # recent questions kept per topic
_ANSWER_CHARS = 2000         # the same cap Session.to_snapshot uses
_TOPIC_ROUTES = ("data", "knowledge")   # pipeline._ANTECEDENT_ROUTES
_FOCUS_TOPICS = ("Focus Plus", "Focus Legacy")


# ── Detecting a topic switch ────────────────────────────────────────────────

# The opening of an explicit return: "go back to", "coming back to", "back
# to", "return to", "switch back to", "let's continue (with)", "resume",
# "now regarding". Anchored at the start: a switch is what the message opens
# with. Fillers before it ("ok, now", "so") are allowed.
_SWITCH_LEAD = re.compile(
    r"^\s*(?:(?:ok(?:ay)?|now|so|and|alright|right|fine|then|well)\b[\s,]*)*"
    r"(?:(?:let'?s|let\s+us|can\s+we|could\s+we|please|i\s+want\s+to|i'?d\s+like\s+to)\s+)?"
    r"(?:"
    r"(?:go(?:ing)?|get(?:ting)?|come|coming|came|turn(?:ing)?|jump(?:ing)?|head(?:ing)?|switch(?:ing)?|move|moving)"
    r"\s+back\s+(?:to|on)"
    r"|back\s+to|return(?:ing)?\s+to|revisit(?:ing)?"
    r"|switch(?:ing)?\s+(?:over\s+)?to"
    r"|continu(?:e|ing)(?:\s+(?:with|on))?|resum(?:e|ing)"
    r"|(?:now\s+)?regarding|now\s+about|now\s+for|again\s+(?:on|about)"
    r")\b[\s,:-]*",
    re.IGNORECASE,
)
# The topic part ends at the first clause break; what follows is the question.
_CLAUSE_BREAK = re.compile(r"\s*(?:[,.:;?!]|\s-\s|\s+and\s+(?=(?:what|how|which|who|when|where|show|give|tell|list)\b))\s*",
                           re.IGNORECASE)
# "the previous topic / question / scheme", "the earlier one", "where we were".
_UNNAMED_TOPIC = re.compile(
    r"^(?:the\s+|that\s+|our\s+)?(?:previous|earlier|last|other|old(?:er)?|first|before)\s+"
    r"(?:topic|question|scheme|one|discussion|subject|conversation|thing)s?$"
    r"|^(?:where\s+we\s+(?:were|left\s+off)|what\s+we\s+were\s+(?:discussing|talking\s+about))$",
    re.IGNORECASE,
)
# Words that may sit around a named topic: "the previous MGNREGA question",
# "the MGNREGA one", "MGNREGA scheme please".
_TOPIC_FILLER = re.compile(
    r"\b(?:the|that|our|previous|earlier|last|old(?:er)?|question|questions|topic|discussion|"
    r"scheme|schemes|one|data|please|pls|again|thing|conversation|subject)\b",
    re.IGNORECASE,
)


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
    rest = q[m.end():]
    brk = _CLAUSE_BREAK.search(rest)
    target, remainder = (rest[:brk.start()], rest[brk.end():]) if brk else (rest, "")
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
            " ", re.sub(r"\bfocus\b", " ", target, flags=re.I)).strip(" ,.-"):
        return TopicSwitch(names=[], bare_focus=True, remainder=remainder)
    if _UNNAMED_TOPIC.match(target):
        return TopicSwitch(names=[], bare_focus=False, remainder=remainder)
    return None


def _strip_scheme_words(text: str) -> str:
    from app import pipeline
    out = text
    for pattern in pipeline._SCHEME_NAME_PATTERN.values():
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
        return parse_switch(question) is not None
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
        mem["active"] = key
        _touch(mem, key)
    # The state belongs to the topic it names, which is not always the last
    # turn's: a KNOWLEDGE digression into PMAY-G leaves the MGNREGA data state
    # in place (update_state), and that state is MGNREGA's, not PMAY-G's.
    skey = _state_topic(session.state)
    if skey is not None and skey in mem["items"]:
        mem["items"][skey]["state"] = session.state.to_dict()
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
        return (key if key in items else None), []
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
        sw = parse_switch(question)
        if sw is None:
            return TopicTurn(question=question, action="continue" if mem.get("active") else "none",
                             topic=mem.get("active"))
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
