"""
Conversation frames and the window resolver (D-100, 2026-11-03).

Why: context was decided by phrase checks (turn_kind cue words, looks_like_followup,
comparison_with_earlier, _data_thread_antecedent, ...), each covering one wording
and reading only the PREVIOUS turn; the snapshot kept only that one turn, so a
worker could not see the rest of the chat at all. Every new wording broke again
(user chat 2026-11-03: "compare this with spend on Focus Legacy scheme" lost the
district breakdown, "include focus plus also" went to the documents, "i mean
compare focus plus also" lost Focus Legacy because the turn before was that
documents answer).

What:
  1. A FRAME per answered turn — the question the pipeline actually ran and its
     scope (schemes, breakdown level, place, years), read with the pipeline's own
     readers. Every frame of the window is in the durable snapshot (D-023), so any
     worker sees the whole chat.
  2. RESOLVE: a follow-up message (context_policy.turn_kind = FOLLOWUP) gets one
     guided-JSON call to the rewrite model with the window's frames. It picks the
     turn the message continues — any turn in the window, not only the last — and
     writes that turn's question with the message's change applied.
  3. CHECKS (deterministic, no word lists): every scheme / place / year / measure in
     the written question comes from the message or the chosen turn
     (context_policy.rewrite_violation, D-024, applied to the chosen turn); nothing
     of that turn the message did not change is lost (its schemes, breakdown level,
     place, years, measure); the result is a complete question (turn_kind STANDALONE).
  4. Any skip, failure, timeout or failed check returns None: the existing path
     runs exactly as before. So the worst case is the old behaviour.

What it never does: resolve a bare "Focus" (CLAUDE.md §4 — the which-Focus pause
still asks), touch a self-sufficient new question (D-061), or answer a reply that
an open pause already understands (D-065 / D-098).
"""
from __future__ import annotations

import logging

from app import context_budget, context_policy, scheme_registry, topic_memory
from app.config import settings

logger = logging.getLogger(__name__)

_WINDOW = 10            # frames shown to the model (the snapshot keeps SESSION_MAX_TURNS)
_ROUTES = ("data", "knowledge")


# ── Frames ───────────────────────────────────────────────────────────────────

def _frame_scope(q: str, route: str, schemes: list, resolved: dict) -> dict:
    years = resolved.get("year_key_list") or (
        [resolved["year_key"]] if resolved.get("year_key") is not None else [])
    place = {k: resolved.get(k) for k in ("district", "block", "village", "assembly_constituency")
             if isinstance(resolved.get(k), str) and resolved.get(k)}
    return {"route": route, "schemes": [s for s in schemes if s in scheme_registry.NAMES],
            "by": list(context_policy.asked_levels(q)), "place": place,
            "years": sorted(int(y) for y in years if isinstance(y, int))}


def record(session, raw_question: str, result: dict) -> None:
    """Add this answered turn's frame to the session (best-effort, never raises)."""
    if session is None or not settings.CONTEXT_FRAMES_ENABLED:
        return
    try:
        route = result.get("route")
        if route not in _ROUTES or result.get("needs_clarification"):
            return
        q = (result.get("rewritten_question") or raw_question or "").strip()
        if not q:
            return
        frames = list(getattr(session, "frames", None) or [])
        fid = (frames[-1].get("id", 0) + 1) if frames else 1
        frames.append({"id": fid, "q": q, **_frame_scope(q, route, list(result.get("schemes") or []),
                                                         result.get("resolved_entities") or {})})
        session.frames = frames[-max(1, settings.SESSION_MAX_TURNS):]
    except Exception:  # noqa: BLE001 — frames must never break an answer
        logger.debug("context frame not recorded", exc_info=True)


def _describe(f: dict) -> str:
    bits = [f["route"]]
    if f.get("schemes"):
        bits.append("schemes: " + ", ".join(f["schemes"]))
    bits.append("by: " + (", ".join(f["by"]) if f.get("by") else "-"))
    if f.get("place"):
        bits.append("place: " + ", ".join(f"{k} {v}" for k, v in f["place"].items()))
    if f.get("years"):
        from app import context_manager
        bits.append("years: " + ", ".join(context_manager._fy_text(y) for y in f["years"]))
    return f'T{f["id"]}: "{f["q"]}" [{"; ".join(bits)}]'


# ── Resolve ──────────────────────────────────────────────────────────────────

_SCHEMA = {
    "type": "object",
    "properties": {
        "relation": {"enum": ["followup", "new"]},
        "question": {"type": "string", "maxLength": 300},
    },
    "required": ["relation", "question"],
}


def _prompt(frames: "list[dict]", base: dict, message: str) -> str:
    window = "\n".join(_describe(f) for f in frames)
    b = f"T{base['id']}"
    return f"""You track the context of a conversation about Meghalaya government scheme data.

Turns answered so far in this conversation, oldest first (id, the exact question answered, its scope):
{window}

The figure the conversation is on now: {b}.
New message: "{message}"

relation:
- "followup": the message continues {b} — it refers to it, repeats or charts it, compares it with
  something, adds or removes a scheme, place, year or breakdown, or changes its measure.
- "new": the message is a complete question that does not depend on the conversation.
question (followup only): {b}'s question rewritten as ONE complete standalone question that KEEPS
  everything of it the message does not change — every scheme, the measure, the place, the years and
  the breakdown (for example "district-wise" / "by district") — and applies what the message changes
  or adds. To compare with another scheme, keep {b}'s scheme(s) AND add the other one, naming each
  scheme once. Use only names from the message and the turns above; add nothing else. No pronouns
  like "this" or "that".

Return ONLY JSON."""


def _skip(reason: str) -> None:
    context_budget.log_decision("frame", outcome="skip", reason=reason)
    return None


def _pause_owns_reply(session, message: str) -> bool:
    """True when an open pause understands this reply itself (left to it)."""
    from app import pipeline as p
    pending = getattr(session, "pending_scope_q", None)
    if not pending:
        return False
    rule = getattr(session, "pending_scope_rule", None)
    if rule not in p.SCHEME_PAUSE_RULES:
        return True          # scope / option pauses: their own merge rules (D-065)
    options = getattr(session, "pending_scope_options", None)
    return bool(p._resume_scheme_pause(message, options)
                or p._resume_scheme_pause_typed(message, pending, options))


def check(question: str, message: str, base: dict) -> "str | None":
    """Why the written `question` cannot stand for `message` continuing `base`,
    or None when it can. Deterministic; the pipeline's own readers only."""
    from app import pipeline as p
    from app.entity_resolver import place_mentions
    q_schemes = p._exact_schemes(question)
    if not q_schemes:
        return "no-scheme"
    if p._names_bare_focus_scheme(question):
        return "bare-focus"
    allowed = set(base.get("schemes") or []) | p._exact_schemes(message)
    if q_schemes - allowed:
        return "scheme-not-permitted"
    viol = context_policy.rewrite_violation(question, question=message, allowed_text=f"{message}\n{base['q']}",
                                            denied_text="", allowed_schemes=sorted(allowed))
    if viol:
        return f"provenance:{viol}"
    # Nothing of the base turn the message leaves alone may be lost. A comparison
    # naming one side ("compare this with Focus Legacy", turn_kind's
    # compare-one-side cue) keeps the base turn's schemes as the other side: it
    # came back as Focus Legacy alone (replay 2026-11-03).
    msg_schemes = p._exact_schemes(message)
    compares = "cue:compare-one-side" in context_policy.turn_kind(message).reasons
    if (not msg_schemes or compares) and set(base.get("schemes") or []) - q_schemes:
        return "lost-scheme"
    if not context_policy.asked_levels(message) and not place_mentions(message):
        # 2026-11-14: "now by financial year" after a by-district answer names its own grouping (c02's dimensions,
        # not only the place levels asked_levels reads); the new grouping replaces the old one, nothing is lost
        if not p._c02_breakdowns(message) \
                and set(base.get("by") or []) - set(context_policy.asked_levels(question)):
            return "lost-breakdown"
        if set(context_policy._places(base["q"])) - set(context_policy._places(question)):
            return "lost-place"
    if not context_policy.extract_year_keys(message) and \
            context_policy.extract_year_keys(base["q"]) - context_policy.extract_year_keys(question):
        return "lost-year"
    if not context_policy.metric_families(message) and \
            context_policy.metric_families(base["q"]) - context_policy.metric_families(question):
        return "lost-measure"
    if context_policy.turn_kind(question).kind != context_policy.TURN_STANDALONE:
        return "not-standalone"
    return None


async def resolve(session, message: str) -> "str | None":
    """The standalone question a follow-up `message` stands for, resolved over
    the whole window, or None (the existing path then runs unchanged)."""
    if session is None or not settings.CONTEXT_FRAMES_ENABLED:
        return None
    try:
        from app import llm
        from app import pipeline as p
        frames = [f for f in (getattr(session, "frames", None) or []) if f.get("route") in _ROUTES][-_WINDOW:]
        if not any(f["route"] == "data" for f in frames):
            return _skip("no-data-turn")
        tk = context_policy.turn_kind(message)
        if tk.kind != context_policy.TURN_FOLLOWUP:
            return _skip(tk.kind)                     # D-061: a new question inherits nothing
        if p._names_bare_focus_scheme(message):
            return _skip("bare-focus")              # CLAUDE.md §4: asked, never guessed
        if _pause_owns_reply(session, message):
            return _skip("pause-reply")
        # The turn a follow-up continues: the latest ANSWERED figure. Pauses, greetings
        # and how-it-works asides in between are not it ("i mean compare focus plus also"
        # after a documents answer lost Focus Legacy, 2026-11-03). Deterministic: the
        # model choosing among turns picked an older one for "this" (replay 2026-11-03).
        # A return to an older topic is topic memory's ("go back to …", recall above).
        base = next(f for f in reversed(frames) if f["route"] == "data")
        last = frames[-1]
        if last["route"] == "knowledge" and last.get("schemes") and not any(
                topic_memory.same_scheme_family(k, s) for k in last["schemes"] for s in base.get("schemes") or []):
            # An aside about ANOTHER scheme than the figure: which one the message
            # continues is the existing rules' call (_data_thread_antecedent).
            return _skip("aside-other-scheme")
        raw =await llm.call_rewriter(_prompt(frames, base, message), max_tokens=200, role="frame",
                                      guided={"guided_json": _SCHEMA})
        out = p._extract_json(raw)
        if not isinstance(out, dict):
            return _skip("unusable")
        if out.get("relation") != "followup":
            return _skip(f"model:{out.get('relation')}")
        question = " ".join(str(out.get("question") or "").split())
        why = check(question, message, base)
        if why:
            context_budget.log_decision("frame", outcome="rejected", reason=why, base=base["id"])
            logger.info("context frame: rejected (%s) %r -> %r", why, message, question)
            return None
        context_budget.log_decision("frame", outcome="resolved", base=base["id"],
                                    back=frames[-1]["id"] - base["id"])
        logger.info("context frame: %r continues T%s -> %r", message, base["id"], question)
        return question
    except Exception:  # noqa: BLE001 — the resolver must never break a turn
        logger.warning("context frame resolver failed — existing path", exc_info=True)
        return None
