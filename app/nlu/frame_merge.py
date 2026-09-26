"""
app/nlu/frame_merge.py — one message's QueryFrame in its conversation.

frame_for_turn() is the ONE owner of clarification resume and follow-up
merge for pipeline._run_pipeline (a LangGraph checkpointer owns a pause only
when LANGGRAPH_FOLLOWUP_ENABLED / the graph's own resume is on — see
app/api/routers/query.py). Nothing here glues reply text onto a paused
question:

  - a one-tap option ({slot, value} from the client, understand.incoming_choice)
    fills that slot on the paused frame (ConversationState.pending_frame) —
    no model call;
  - a typed reply goes through Understand with the pause as context and, if
    it answers the pause (answers_pending / is_followup), is merged into the
    paused frame; a brand-new question drops the pause;
  - otherwise the message's own frame is used, merged onto the previous
    answer's frame when it is a follow-up (below).

on_pause() records the frame + the slot a pause asks; after_answer() adds
the "Understood as / Assumed" lines, remembers the answered frame and offers
"Change area" chips when the statewide default was applied.

Whether a message continues the previous turn is decided by the Understand
node (frame.is_followup), which sees the recent turns — not by
pipeline.looks_like_followup's patterns, which miss phrasings like "now show
it block wise" or "same thing for last year". A follow-up's frame is then
merged onto the previous answered turn's frame:

  - it inherits every previous slot; the new message's NON-EMPTY slots win
    ("same for 2022-23" replaces only the year);
  - a scheme change clears metric and tranche (a PMAY-G question has no
    MGNREGA "expenditure" and no Focus Plus tranche to carry over);
  - "compare with EGH" adds EGH to the inherited place instead of replacing it;
  - a new question (is_followup false) starts fresh — no merge at all.

The merged frame's standalone question is the Understand node's own
rewritten_question (it saw the history) — there is no separate follow-up
rewrite call.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from app.core import request_trace
from app.core.config import settings
from app.nlu import understand
from app.nlu.understand import LLM_FIELDS, GeoMention, QueryFrame

logger = logging.getLogger(__name__)

# Slots a follow-up inherits and may override. schemes/geo handled separately.
_SLOTS = ("metric", "year_text", "tranche", "query_type", "group_by", "top_n")


def remember(frame: QueryFrame) -> dict:
    """What ConversationState.last_frame keeps of an answered turn's frame:
    the model-filled slots plus the normalised schemes (JSON-safe)."""
    d = frame.model_dump(include=set(LLM_FIELDS))
    d["resolved_schemes"] = list(frame.resolved_schemes)
    return d


def _geo_key(g: GeoMention) -> str:
    return (g.text or "").strip().casefold()


def merge_followup(previous: dict, current: QueryFrame) -> QueryFrame:
    """The follow-up `current` laid over the previous turn's frame."""
    prev = QueryFrame.model_validate({k: v for k, v in previous.items() if k in LLM_FIELDS})
    prev_schemes = list(previous.get("resolved_schemes") or prev.schemes)
    merged = prev.model_copy(deep=True)
    merged.schemes = prev_schemes

    scheme_changed = bool(current.schemes) and sorted(current.schemes) != sorted(prev_schemes)
    if current.schemes:
        merged.schemes = list(current.schemes)
    if scheme_changed:
        merged.metric = None
        merged.tranche = None

    if current.geo_mentions:
        if current.query_type == "comparison":
            seen = {_geo_key(g) for g in merged.geo_mentions}
            merged.geo_mentions = list(merged.geo_mentions) + [
                g for g in current.geo_mentions if _geo_key(g) not in seen]
        else:
            merged.geo_mentions = list(current.geo_mentions)

    for slot in _SLOTS:
        value = getattr(current, slot)
        if value not in (None, "", []):
            setattr(merged, slot, value)

    merged.rewritten_question = current.rewritten_question or prev.rewritten_question
    merged.intent = current.intent
    merged.unclear = current.unclear
    merged.is_followup = True          # decided by Understand; kept for the audit trail
    merged.answers_pending = False
    return merged


# ── one turn ───────────────────────────────────────────────────────────────
@dataclass
class TurnFrame:
    """What frame_for_turn decided for one message."""
    frame: "QueryFrame | None"          # None => the Understand model gave no frame
    question: str                       # the standalone question the pipeline answers
    followup: bool = False              # continues the previous answer (merged onto it)
    meta: dict = field(default_factory=dict)

    @property
    def intent(self) -> "str | None":
        """The frame's DATA / KNOWLEDGE routing, or None (classify as before)."""
        f = self.frame
        return f.intent if f is not None and f.source == "model" else None


async def frame_for_turn(question: str, session) -> TurnFrame:
    """Build this message's normalised frame (see the module docstring).
    Consumes any pending pause. Raises ClarificationNeeded only for a pause of
    its own ("Change area: District" -> "which district?", or an ambiguous
    reference); a frame failure never fails the turn — the frame is then None
    and the gates read understand.fallback_frame(question)."""
    from app.conversation import context_manager
    from app.orchestration.pipeline import ClarificationNeeded

    choice = understand.incoming_choice.get()
    ctx = understand.snapshot_context(session)          # before the pause is consumed
    pending = session.state.pending_frame if session is not None else None
    last_frame = session.state.last_frame if session is not None else None
    if session is not None:
        session.state.pending_frame = None              # consumed, whatever the reply
    is_pause = bool(pending) and pending.get("kind", "pause") == "pause"
    frame = None
    body_question = question
    meta: dict = {}
    followup = False
    try:
        if pending and choice and choice.get("slot") == "area_level" \
                and choice.get("value") in understand.AREA_LEVELS:
            # "Change area: District" under an answer (or a level pick): ask for
            # the name, keeping the frame — the typed name fills the area slot.
            level = choice["value"]
            pf = QueryFrame.model_validate(pending["frame"])
            asked = understand.area_level_question(level)
            e = ClarificationNeeded(asked, rule="area-level-name")
            e.pending_frame = understand.pending_record(
                pf, "area-level-name", asked, [], pending.get("base_question") or pf.rewritten_question,
                level=level)
            if session is not None:
                session.understand_frame = {"frame": pf.model_dump(), "question": question,
                                            "meta": {"resume": "area_level", "level": level}}
            raise e
        if is_pause and choice and choice.get("slot") == pending.get("slot"):
            frame, body_question = understand.fill_slot(pending, choice["slot"], choice.get("value"))
            meta = {"resume": "click", "slot": choice["slot"]}
        else:
            # Deterministic reference resolution ("the previous year", "the
            # other one") against the conversation state stays a PRE-step —
            # Understand then reads the already-substituted message.
            message = question
            if session is not None and settings.CONTEXT_LAYER_ENABLED and settings.CONTEXT_STATE_ENABLED:
                try:
                    message = context_manager.substitute_references(question, session.state)
                except context_manager.AmbiguousReference as ex:
                    raise ClarificationNeeded(ex.question, options=ex.options, rule="entity-ambiguous")
                except Exception:  # noqa: BLE001
                    message = question
            with request_trace.stage("understand"):
                built = await asyncio.wait_for(understand.build_frame(message, ctx),
                                               settings.UNDERSTAND_TIMEOUT_SECONDS + 5)
            request_trace.note("frame_before", built.get("frame"))
            meta = built.get("meta") or {}
            reply = QueryFrame.model_validate(built["frame"]) if built.get("frame") else None
            if reply is not None and is_pause and (reply.answers_pending or reply.is_followup):
                frame = understand.merge_reply(pending, reply)
                body_question = frame.rewritten_question or question
                meta["resume"] = "typed"
            else:
                if is_pause:
                    meta["resume"] = "dropped"          # a new message: the pause is dropped
                followup = bool(reply is not None and reply.is_followup)
                if followup and last_frame:
                    # Continues the previous answer: inherit its slots, the new
                    # message's non-empty slots win.
                    frame = merge_followup(last_frame, reply)
                    body_question = frame.rewritten_question or question
                    meta["followup"] = "merged"
                elif followup:
                    frame = reply
                    body_question = reply.rewritten_question or question
                    meta["followup"] = "no previous frame"
                else:
                    frame = reply                       # a new question starts fresh
        if frame is not None:
            with request_trace.stage("normalise"):
                frame = await understand.normalise_frame(frame, body_question)
            request_trace.note("frame_after", understand.frame_for_audit(frame))
            request_trace.note("frame_meta", meta)
    except ClarificationNeeded:
        raise
    except Exception as e:  # noqa: BLE001 — never fail the turn on the frame
        logger.warning("frame unavailable this turn (%s) — fallback frame", e)
        frame, meta = None, {"error": f"{type(e).__name__}: {e}"[:200]}
        body_question, followup = question, False
    if frame is None:
        followup = False
    if session is not None:
        session.understand_frame = {"frame": frame.model_dump() if frame is not None else None,
                                    "meta": meta, "question": question}
    return TurnFrame(frame=frame, question=body_question, followup=followup, meta=meta)


def on_pause(e, turn: TurnFrame) -> None:
    """A gate / resolver pause on this turn: stamp {slot, value} on its options
    and remember the frame + the slot it asks (e.pending_frame — the router
    persists it as ConversationState.pending_frame), so the reply fills that
    slot. A turn with no model frame pauses on its fallback frame."""
    if not understand.SLOT_FOR_RULE.get(e.rule or ""):
        return
    frame = turn.frame if turn.frame is not None else understand.fallback_frame(turn.question)
    e.options = understand.annotate_options(e.rule, e.options)
    e.pending_frame = understand.pending_record(
        frame, e.rule, e.question, e.options,
        base_question=frame.rewritten_question or turn.question)


def after_answer(result: dict, typed: str, turn: TurnFrame, session) -> None:
    """Post-answer frame work: the "Understood as / Assumed" lines, the
    answered frame remembered for the next follow-up, and "Change area" chips
    (with a correction pause) when the statewide default was applied."""
    if turn.question != typed and not result.get("rewritten_question"):
        result["rewritten_question"] = turn.question
    if result.get("route") not in ("data", "knowledge"):
        return
    frame = turn.frame if turn.frame is not None else understand.fallback_frame(turn.question)
    understand.prepend_understanding(result, typed, frame)
    if session is None:
        return
    if turn.frame is not None:
        session.state.last_frame = remember(turn.frame)
    if "area:default:statewide" in (result.get("gate_trace") or []):
        base = frame.rewritten_question or turn.question
        result["correction_options"] = understand.correction_options(base)
        session.state.pending_frame = understand.pending_record(
            frame, None, "", result["correction_options"], base_question=base, kind="correction")
