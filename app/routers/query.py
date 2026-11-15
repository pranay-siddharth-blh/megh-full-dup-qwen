import asyncio
import json
import logging
import time
import uuid

from fastapi import (APIRouter, Depends, File, Form, HTTPException,
                     Request, UploadFile)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app import (asr_guard, auth, context_manager, conversation_layer, conversation_memory,
                 context_budget, conversation_replies, conversation_store, llm, pipeline, session_sync,
                 topic_memory, translate, turn_events, turn_trace)
from app.cache import metrics, response_cache
from app.config import settings
from app.deps import current_scope, require_user
from app.net import client_ip as _resolve_ip
from app.semantic_cache import semantic_cache
from app.session_store import Turn, session_store
from app.db import DatabaseUnavailableError, UnsafeSQLError
from app.llm import ModelBusyError
from app.pipeline import (
    SCHEME_PAUSE_RULES,
    SCOPE_MERGE_RULES,
    is_scheme_substitution,
    is_scopeless_followup,
    ClarificationNeeded,
    _empty_data_fields,
    answer_question,
    looks_like_followup,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10 MB — a minute or so of WAV


class QueryRequest(BaseModel):
    # A03 — bound the free-text field. 2000 chars is far above any real question
    # and well below anything that would bloat a prompt or an audit row.
    question: str = Field(min_length=1, max_length=settings.MAX_QUESTION_CHARS)
    session_id: str | None = Field(
        default=None, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )  # continue an existing conversation
    # Regenerate (the ↻ under an answer): answer afresh instead of from the
    # response / semantic caches. The fresh answer is written back as usual,
    # so it replaces the cached one for everyone in the same scope.
    skip_cache: bool = False
    # The chat's language button (en / kha / gar). Sent by the UI all along but
    # ignored until the RAG upgrade Phase 4: a Khasi or Garo question is now
    # translated to English first (app/translate.py).
    language: str = Field(default="en", max_length=8)
    # K-6 (chat UI audit 2026-10-29): Regenerate / Edit replace a question and what
    # followed it. The number of this conversation's saved turns to keep; the rest
    # are deleted and the context goes back to what it was before them.
    keep_turns: int | None = Field(default=None, ge=0, le=500)

    @field_validator("question")
    @classmethod
    def _strip_control_chars(cls, v: str) -> str:
        # Drop C0 control characters except tab/newline/carriage-return.
        cleaned = "".join(c for c in v if c in "\t\n\r" or ord(c) >= 0x20)
        if not cleaned.strip():
            raise ValueError("question must not be empty")
        return cleaned


def _client_ip(request: Request) -> str:
    return _resolve_ip(request)


async def _identity(scope: auth.UserScope = Depends(current_scope)) -> auth.UserScope:
    """Require a real user when AUTH_ENABLED; allow anonymous in dev mode."""
    if settings.AUTH_ENABLED and scope.db_user_id is None:
        raise HTTPException(401, "authentication required — POST /api/auth/login")
    return scope


@router.post("/api/query")
async def query(req: QueryRequest, request: Request,
                scope: auth.UserScope = Depends(_identity)):
    # The plain request has no pings, so nginx cuts it at 120 s: its total
    # deadline is capped below that (REL-02b). The stream keeps its own.
    request.state.megh_nonstream = True
    return await _answer(req, request, scope)


@router.post("/api/query/stream")
async def query_stream(req: QueryRequest, request: Request,
                       scope: auth.UserScope = Depends(_identity)):
    """The same turn as POST /api/query, as Server-Sent Events (D-039):
      data: {"type": "step", "node": "entities"}     a graph node started
      data: {"type": "draft_reset"}                  the composer starts (again)
      data: {"type": "token", "text": "..."}         the composer's text, as written
      data: {"type": "done", "result": {...}}        exactly what /api/query returns
      data: {"type": "error", "status": 503, "detail": "..."}   what it would raise
    A ": ping" comment every STREAM_PING_SECONDS keeps proxies from closing a
    quiet stream. The draft is never the answer: `done` carries the checked
    text. A client that disconnects (the Stop button) cancels the turn."""
    if not req.question or not req.question.strip():
        raise HTTPException(400, "question must not be empty")
    queue: asyncio.Queue = asyncio.Queue()

    async def run() -> None:
        token = turn_events.bind(queue.put_nowait)
        try:
            result = await _answer(req, request, scope)
            queue.put_nowait({"type": "done", "result": result})
        except HTTPException as e:
            queue.put_nowait({"type": "error", "status": e.status_code, "detail": e.detail})
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — _answer maps its own; this is the last net
            logger.exception("query stream failed")
            queue.put_nowait({"type": "error", "status": 502,
                              "detail": "upstream error while answering the question"})
        finally:
            turn_events.unbind(token)

    async def events():
        task = asyncio.create_task(run())
        try:
            while True:
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=settings.STREAM_PING_SECONDS)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        break
                    yield ": ping\n\n"
                    continue
                yield "data: " + json.dumps(jsonable_encoder(ev), ensure_ascii=False) + "\n\n"
                if ev.get("type") in ("done", "error"):
                    break
        finally:
            if not task.done():
                # The client went away (Stop, closed tab): nothing will read
                # this answer, so stop spending model and DB time on it.
                task.cancel()
                logger.info("query stream: client disconnected, turn cancelled")
                # "continue" afterwards answers it (conversation_layer).
                _remember_stopped(req, request, scope)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _session_id(req: QueryRequest, request: Request, scope: auth.UserScope) -> str:
    """The conversation this request belongs to. Computed once per request and
    reused (the stream's stop handler asks again; a fresh id would differ)."""
    cached = getattr(request.state, "megh_session_id", None)
    if cached:
        return cached
    client_session = req.session_id or request.headers.get("x-session-id")
    # The client owns conversation identity: the chat UI mints a session_id per
    # "New chat" so each thread is its own row in app.conversations.
    # A caller that sends none gets a conversation of its OWN (RAG plan E3,
    # 2026-10-26). It used to share one per-day bucket per user
    # ("day-<user>-<date>"), so every session-less API call that day was a
    # "follow-up" of the last one: unrelated questions inherited each other's
    # scheme, place and year. The id is returned in the response (session_id);
    # sending it back continues that conversation, on any worker. "api-" threads
    # are kept for audit but left out of the user's own history list
    # (conversation_store.list_my_conversations), so scripts do not flood it.
    if client_session:
        sid = client_session
    elif scope.db_user_id is not None:
        sid = f"api-{uuid.uuid4().hex[:16]}"
    else:
        sid = f"one-{uuid.uuid4().hex[:16]}"
    try:
        request.state.megh_session_id = sid
    except Exception:  # noqa: BLE001 — a request without state: just not cached
        pass
    return sid


_BACKGROUND: set = set()   # strong refs to fire-and-forget tasks


def _remember_stopped(req: QueryRequest, request: Request, scope: auth.UserScope) -> None:
    """The officer stopped this question while it ran: keep it on the session
    so a following "continue" answers it (conversation_layer). Recorded at
    once on this worker; the durable save runs in the background, because the
    caller is a stream being torn down by the disconnect."""
    try:
        if getattr(request.state, "megh_foreign", False):
            return    # another user's conversation: refused, nothing to keep (CTX-01)
        session_id = _session_id(req, request, scope)
        if session_id.startswith("one-"):
            return    # no thread to continue in
        session = session_store.ensure(session_id, scope.user_id)
        # The turn may have been stopped half way (its state changed, its
        # answer never delivered): put the session back as the turn found it,
        # then record the stopped question on top (CTX-01, 2026-10-29).
        _restore_turn_start(request, session)
        conversation_layer.remember_stopped(session, req.question)

        async def save() -> None:
            try:
                await session_sync.sync_out(session, session_id, tenant_id=scope.tenant_id,
                                            user_id=scope.db_user_id, title=req.question)
            except Exception:  # noqa: BLE001
                logger.warning("query stream: could not save the stopped question", exc_info=True)
        task = asyncio.get_running_loop().create_task(save())
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)
    except Exception:  # noqa: BLE001 — a stopped turn must never raise
        logger.warning("query stream: could not remember the stopped question", exc_info=True)


# One turn at a time per conversation on this worker (CTX-01, 2026-10-29). Two
# requests on one session (a double click, two tabs) used to interleave their
# reads and writes of the same Session; only the graph run itself was locked
# (pipeline_graph), and that lock is not re-entrant, so it is not reused here.
# Entries are counted and removed when the last waiter leaves, so the dict holds
# only conversations with a turn in flight. Across workers the durable revision
# guard (conversation_store.save_session_state) already refuses the second write.
_TURN_LOCKS: dict = {}


async def _answer(req: QueryRequest, request: Request, scope: auth.UserScope) -> dict:
    """One turn, for both endpoints, run after any other turn of the same
    conversation on this worker has finished (see _TURN_LOCKS)."""
    if not req.question or not req.question.strip():
        raise HTTPException(400, "question must not be empty")
    sid = _session_id(req, request, scope)
    entry = _TURN_LOCKS.get(sid)
    if entry is None:
        entry = _TURN_LOCKS[sid] = [asyncio.Lock(), 0]
    entry[1] += 1
    try:
        async with entry[0]:
            return await _answer_turn(req, request, scope)
    finally:
        entry[1] -= 1
        if entry[1] <= 0 and _TURN_LOCKS.get(sid) is entry:
            del _TURN_LOCKS[sid]


def _refuse_foreign(request: Request, session_id: str, scope: auth.UserScope, where: str) -> None:
    """403 for a conversation another user owns (CTX-01). Its context is never
    loaded, used or overwritten, and a Stop of this request records nothing."""
    try:
        request.state.megh_foreign = True
    except Exception:  # noqa: BLE001
        pass
    logger.warning("query: session %s refused for user %s: the %s owner differs",
                   session_id, scope.username or scope.user_id, where)
    raise HTTPException(403, "This conversation belongs to another account. Please start a new chat.")


def _turn_start_copy(session) -> tuple:
    """The session as this turn found it: the durable snapshot (deep, through
    JSON as the database stores it, so later in-place edits of topics or state
    cannot reach it) plus the summary, which travels beside the snapshot."""
    return (json.loads(json.dumps(session.to_snapshot(), default=str)),
            session.summary, session.summary_turn_count)


def _restore_turn_start(request: Request, session) -> None:
    """Put the session back as the turn found it: the turn failed (503 / 504 /
    5xx) or was stopped before its answer was delivered. Without this the
    worker kept a half-changed copy (the pending clarification already cleared,
    say), and the next reply behaved differently on this worker than on the
    others (CTX-10, 2026-10-29). The revision is left alone: nothing was saved."""
    start = getattr(request.state, "megh_turn_start", None)
    if not start or session is None:
        return
    snap, summary, summary_turn_count = start
    try:
        session.apply_snapshot(snap)
        session.summary, session.summary_turn_count = summary, summary_turn_count
        session.turn_context = {}
    except Exception:  # noqa: BLE001 — a failed restore must not hide the turn's own error
        logger.warning("query: could not restore the session after a failed turn", exc_info=True)


async def _answer_turn(req: QueryRequest, request: Request, scope: auth.UserScope) -> dict:
    """One turn, for both endpoints: caches, the pipeline, the pause, and the
    bookkeeping (L1/L2 context, memory, audit, cache write-back). Raises the
    HTTPException the endpoint returns."""

    started = time.monotonic()
    ip = _client_ip(request)
    # What the DATA path did this turn (few-shot ids, repaired errors, the final
    # error) — recorded by the pipeline stages, written to the audit below.
    trace = turn_trace.start(context_budget.request_id_var.get())
    # Khasi / Garo (KHA / GAR selected): everything after this reads English —
    # the caches, the conversation layer, routing, retrieval and SQL. The words
    # the officer typed go back on the result as `translated_from`.
    translated_from = None
    _lang = (req.language or "en").lower() if (req.language or "en").lower() in translate.LANGUAGE_NAMES \
        else translate.script_language(req.question)       # Devanagari, whatever the button (Issue 9)
    if _lang:
        english = await translate.to_english(req.question, _lang)
        if english.strip() and english.strip() != req.question.strip():
            translated_from, req.question = req.question, english.strip()
    # KI-399 is closed by CTX-01 below (a 403, "start a new chat"). The open-bug sweep's
    # silent swap to a new "own-…" id (merged beside it, 2026-10-29) ran first, so the 403
    # was never reached and the officer's chat changed id unseen: removed (pipeline #87).
    session_id = _session_id(req, request, scope)
    session = session_store.ensure(session_id, scope.user_id)
    # Ownership (CTX-01, 2026-10-29): a session id is not a secret the caller
    # can be trusted with. This worker's copy names its owner by login; the
    # durable row (sync_in below) by app.users id. Either unknown: no check.
    # K-2: covers the next officer on a shared computer reusing the previous
    # officer's session id after a sign-out.
    if session.user_id and scope.user_id and str(session.user_id) != str(scope.user_id):
        _refuse_foreign(request, session_id, scope, "in-memory")
    session.scope = scope
    # Shared conversation state (app/session_sync.py, KI-028): bring this
    # worker's copy up to the durable revision before answering. The previous
    # request may have been served by another worker (2 workers on each of 2 VMs,
    # no stickiness), and its turn, state and pending clarification are only
    # current in app.conversations. Bounded and non-raising: if the DB is
    # unreachable the local copy is used, as before. A one-off "one-..." id has
    # no durable thread to read.
    durable_session = not session_id.startswith("one-")
    if durable_session:
        if await session_sync.sync_in(session, session_id, user_id=scope.db_user_id) == "foreign":
            if not session.turns:
                # the empty copy ensure() just made for this caller: left in
                # place, it would refuse the real owner on this worker
                session_store.drop(session_id)
            _refuse_foreign(request, session_id, scope, "durable")
    if req.keep_turns is not None and durable_session and scope.db_user_id is not None:
        await _replace_turns(session, session_id, scope, req.keep_turns)
    # K-6: the context as it is before this turn, saved with it so a later Edit /
    # Regenerate of this question can put it back
    context_before = {"snapshot": session.to_snapshot(), "summary": session.summary}
    # The session as this turn found it, restored if the turn fails or is
    # stopped (CTX-10). Taken here, after sync_in (and K-6's replace, which is
    # already saved) and before the conversation layer: the layer's idle expiry
    # must not be undone by a restore.
    request.state.megh_turn_start = _turn_start_copy(session)
    # Conversation layer (app/conversation_layer.py): an idle conversation
    # starts afresh, "start a new topic" clears the context, and "what was the
    # PMAY-G information again?" becomes a return to that topic. Before the
    # caches: such a turn only means something in its own conversation.
    layer = await conversation_layer.prepare_turn(session, req.question)
    question = layer.question
    if layer.action == "continue-expired":
        # The "Continue with …" tap brings back the set-aside topic. A pause
        # asked since the expiry ("which scheme?") belongs to the fresh start
        # the officer just left: the next question must not merge into it
        # (CTX-13, 2026-10-29).
        topic_memory._clear_pending(session)

    # Response + semantic caches are keyed on (question + authorization
    # fingerprint): safe to share across users who resolve to the same scope,
    # since the auth outcome is a pure function of scope + query. Genuine
    # follow-up fragments ("what about EGH?") are never cached — they only mean
    # something against their own conversation.
    scope_key = scope.cache_fingerprint()
    # A reply to a pending clarification ("Focus Plus", "West Garo Hills
    # 2023-24") only means something against the question it resumes. Served
    # from the shared cache it would return whatever was cached for those bare
    # words, and written back it would poison the cache for everyone else. A
    # scope fragment usually already looked like a follow-up; a bare scheme
    # name does not.
    cacheable = is_cacheable(req.question, session) and not layer.changed
    sem_vec = None
    result = None
    served_from = None  # metrics route tag when the answer came from a cache

    if layer.response is not None:
        result = {**layer.response, "session_id": session_id}
    elif cacheable and not req.skip_cache:
        cached = await response_cache.get(req.question, scope_key)
        if cached is not None:
            result = {**cached, "session_id": session_id}
            served_from = f"{cached.get('route', 'data')}:cache"
        else:
            sem_hit, sem_vec = await semantic_cache.lookup(req.question, scope_key)
            if sem_hit is not None:
                result = {**sem_hit, "session_id": session_id}
                served_from = f"{sem_hit.get('route', 'data')}:semcache"

    if result is None:
        deadline: float = settings.REQUEST_TIMEOUT_SECONDS * (len(layer.multi) if layer.multi else 1)
        if getattr(request.state, "megh_nonstream", False):
            # REL-02b: one part per scheme could run past the proxy's own cut-off,
            # which the officer would see as a bare gateway error.
            deadline = min(deadline, settings.QUERY_NONSTREAM_MAX_SECONDS)
        try:
            # "Each year, for all schemes": one question per scheme, answered
            # one after another and merged (conversation_layer.answer_many).
            result = await asyncio.wait_for(
                conversation_layer.answer_many(
                    layer.multi, lambda q: answer_question(q, session=session, scope=scope),
                    notes=layer.multi_notes)
                if layer.multi else answer_question(question, session=session, scope=scope),
                timeout=deadline,
            )
        except ClarificationNeeded as e:
            # A scope pause ("which area / year?"), a year pause ("which FY?"), or
            # an entity-ambiguity pause ("which of these villages/districts/blocks?")
            # carries one-tap options where they exist, but the user may still type
            # the answer as free text ("West Garo Hills 2023-24", "East Khasi
            # Hills"). Remember the question so the pipeline merges that reply back
            # into it next turn instead of treating it as a brand-new question.
            remember_pause(session, pause_question(session, question), e)
            # Shape it for the frontend clarification renderer (intent CLARIFY +
            # clarification.options), and keep the flat keys older callers read.
            out = {
                "route": "clarification",
                "intent": "CLARIFY",
                "confidence": "high",
                "answer": e.question,
                "needs_clarification": True,
                "question": e.question,
                "clarification": {"options": e.options, "rule": e.rule},
                "session_id": session_id,
                **_empty_data_fields(),
            }
            # After an idle expiry the first reply carries the "Continue with …"
            # chip, a pause included: it returned before the offer was attached,
            # and the next message dropped the set-aside context (CTX-13).
            out = conversation_layer.attach_continue_offer(session, out)
            # A clarification pause is still a turn the user should see when they
            # reopen the thread — persist it durably (L2) exactly like an answered
            # turn, so the conversation appears in the sidebar and replays the
            # clarifying question + its option chips. L1 follow-up context is left
            # untouched: the resume already runs off session.pending_scope_q.
            clarify_latency_ms = (time.monotonic() - started) * 1000
            conversation_store.persist_turn(
                tenant_id=scope.tenant_id, user_id=scope.db_user_id, session_id=session_id,
                result=out, question=translated_from or req.question, latency_ms=clarify_latency_ms,
                context_before=context_before,
                username=scope.username or None, ip=ip,
                audit=turn_trace.audit_fields(trace, out),
            )
            _mirror_audit(scope, session_id, req.question, {"route": "clarification"}, started, ip, trace)
            turn_trace.finish(trace, out)
            # The pending clarification must reach whichever worker receives the
            # reply (KI-001): it is part of the durable snapshot.
            if durable_session:
                await session_sync.sync_out(session, session_id, tenant_id=scope.tenant_id,
                                            user_id=scope.db_user_id, title=translated_from or req.question)
            return out
        # Every failure below leaves the session as the turn found it (CTX-10),
        # so the retry behaves the same on whichever worker gets it.
        except ModelBusyError as e:
            metrics.busy_rejections += 1
            _restore_turn_start(request, session)
            raise HTTPException(503, "The service is busy right now. Please retry in a few seconds.",
                                headers={"Retry-After": "5"}) from e
        except DatabaseUnavailableError as e:
            # megh_db unreachable mid-question (VPN / network drop). Say so, so
            # the officer retries — never a "not in the data" answer (KI-025).
            metrics.errors += 1
            logger.warning("database unreachable: %s", e)
            _restore_turn_start(request, session)
            raise HTTPException(503, "Couldn't reach the Megh One data service just now (network or "
                                     "VPN interruption). Please retry in a few seconds.",
                                headers={"Retry-After": "5"}) from e
        except asyncio.TimeoutError as e:
            metrics.errors += 1
            _restore_turn_start(request, session)
            raise HTTPException(504, "The request took too long. Please try a narrower question.") from e
        except UnsafeSQLError as e:
            metrics.errors += 1
            logger.error("Blocked unsafe SQL: %s", e)
            _restore_turn_start(request, session)
            raise HTTPException(500, "the generated query failed a safety check") from e
        except Exception as e:
            metrics.errors += 1
            metrics.model_errors += 1
            logger.exception("query failed")
            _restore_turn_start(request, session)
            raise HTTPException(502, "upstream error while answering the question") from e

    # A refusal said conversationally (app/conversation_replies.py): its kind,
    # the current topic, a fresh wording each time. It depends on this chat,
    # so it is never written to the shared answer caches.
    styled = conversation_replies.restyle(session, req.question, result)
    if styled is not None:
        result = styled
        cacheable = False
    # After an idle expiry the first reply offers "Continue with MGNREGA (…)"
    # (conversation_layer, Context Memory S3); such a reply is this chat's alone.
    offered = conversation_layer.attach_continue_offer(session, result)
    if offered is not result:
        result = offered
        cacheable = False
    if translated_from:
        result = {**result, "translated_from": translated_from, "translated_question": req.question}

    latency_ms = (time.monotonic() - started) * 1000
    result["session_id"] = session_id
    # Surface the real end-to-end time to the UI meta line. On a cache hit this
    # is recomputed here (the fast path), overwriting whatever was cached.
    result["execution_time_ms"] = round(latency_ms)

    # L1 follow-up context — recorded even on a cache hit, so the next turn's
    # follow-up rewrite still has this question as its antecedent.
    # The question the pipeline ran (the conversation layer's), so a reset's
    # "Forget that." or a recall's wording never becomes the antecedent.
    if served_from is not None and layer.response is None:
        # A cached answer skips the graph, and with it the context stage, which
        # first files the previous turn under its topic (topic_memory.checkpoint).
        # Without this the turn before a cache hit was never filed: after
        # MGNREGA -> PMAY-G -> a cached MGNREGA answer the PMAY-G topic was gone
        # (CTX-02, 2026-10-29). Filing twice is harmless (a fingerprint skips it).
        try:
            topic_memory.checkpoint(session)
        except Exception:  # noqa: BLE001 — bookkeeping must never fail the answer
            logger.warning("topic memory: checkpoint before a cache hit failed (non-fatal)", exc_info=True)
    if layer.action != "stop":
        session_store.add_turn(session_id, build_turn(question, result))
    # else: a typed "stop" with nothing running is not a turn of the topic. Recorded
    # as the last turn, it became the follow-up antecedent and its topic filing
    # skipped the answer before it: "What about FY 2023-24?" then reached the data
    # path with no scheme (CTX-13, 2026-10-29). persist_turn still keeps it in the
    # chat's history.
    if served_from is not None and layer.response is None:
        # KI-319 (2026-10-18): a cached answer skips the graph, so its
        # context_update node never ran — the structured state (scheme, place,
        # year), the topic ledger's scope, the idle "continue?" chip and the
        # scope banner were all missing after a cache hit. Fold the cached
        # answer in exactly as the graph does for a computed one. A cache hit
        # is always a standalone question (follow-ups are never cached), so the
        # per-request turn_context is reset first: no merge plan from the
        # previous turn may decide what this one keeps.
        session.turn_context = {}
        await pipeline._update_context(session, question, result)
        if "scope_banner" not in result:
            pipeline._attach_scope_banner(result, session)
    # L2 durable — conversation + turn + audit (fire-and-forget)
    conversation_store.persist_turn(
        tenant_id=scope.tenant_id, user_id=scope.db_user_id, session_id=session_id,
        result=result, question=translated_from or req.question, latency_ms=latency_ms,
        context_before=context_before,
        username=scope.username or None, ip=ip,
        audit=turn_trace.audit_fields(trace, result),
    )
    # live accuracy / repair counters (/metrics) — computed answers only, not cache hits
    if served_from is None:
        turn_trace.finish(trace, result)
    # Semantic conversation memory — indexes this turn for later "relevant
    # older turns" retrieval (see app.context_manager.build_followup_context).
    # Fire-and-forget, scoped to this tenant/user/session; never blocks or
    # fails the response (app.conversation_memory.index_turn degrades silently).
    conversation_memory.index_turn(
        tenant_id=scope.tenant_id, user_id=scope.db_user_id, session_id=session_id,
        question=req.question, standalone_question=result.get("rewritten_question") or req.question,
        answer=result.get("answer", ""), schemes=result.get("schemes"),
    )
    # Durable snapshot of this turn: structured state, this turn as the next
    # follow-up's antecedent, the summary. AWAITED, because the next request can
    # land on another worker immediately (session_sync.sync_out upserts the row
    # itself, so it no longer races persist_turn's insert).
    if durable_session:
        await session_sync.sync_out(session, session_id, tenant_id=scope.tenant_id,
                                    user_id=scope.db_user_id, title=translated_from or req.question)
    _mirror_audit(scope, session_id, req.question, result, started, ip, trace)

    # Only write back a freshly computed answer, and only under this caller's scope —
    # never one the pipeline built from this conversation's context (WI-5,
    # node_finalize's context_dependent): cached under the raw words, another user
    # typing them would get an answer scoped by someone else's conversation.
    if cacheable and served_from is None and not result.get("context_dependent"):
        # Never the officer's own Khasi / Garo words: a later asker in the same
        # scope would receive them in the JSON (CTX-14, 2026-10-29).
        shared = {k: v for k, v in result.items() if k != "translated_from"}
        await response_cache.put(req.question, shared, scope_key)
        await semantic_cache.put(req.question, shared, vec=sem_vec, scope_key=scope_key)

    metrics.record(served_from or result.get("route", "data"), latency_ms)
    return result


# ── Per-request conversation bookkeeping ────────────────────────────────────
# Module-level so the live validation harness (tests/live_context_validation.py)
# runs exactly this logic rather than a copy of it.

async def _replace_turns(session, session_id: str, scope: auth.UserScope, keep: int) -> None:
    """K-6: delete the saved turns after the first `keep` and restore the context
    saved before the first of them. Never fails the question: if the store is
    unreachable the turns stay (as before) and the question is answered."""
    try:
        ctx = await conversation_store.truncate_turns(session_id=session_id, user_id=scope.db_user_id, keep=keep)
    except Exception as e:  # noqa: BLE001
        logger.warning("keep_turns: could not remove replaced turns (%s)", e)
        return
    if not ctx or not isinstance(ctx.get("snapshot"), dict):
        return
    session.apply_snapshot(ctx["snapshot"], ctx.get("summary"))
    await session_sync.sync_out(session, session_id, tenant_id=scope.tenant_id, user_id=scope.db_user_id)


def is_cacheable(question: str, session) -> bool:
    """Whether this request may be served from, and written to, the shared
    answer caches. Follow-up fragments only mean something within their own
    conversation. So does a reply to a pending clarification ("Focus Plus",
    "West Garo Hills 2023-24"): served from the cache it would return whatever
    was cached for those words, and written back it would poison the cache
    for everyone else. A bare "Focus Plus" or "West Garo Hills 2023-24"
    already looked like a follow-up. "focus plus please" or "for the district
    of West Garo Hills in the year 2023-24" did not, and were cacheable
    (checked 2026-09-26)."""
    if getattr(session, "pending_scope_q", None) or looks_like_followup(question):
        return False
    # A measure-only question right after a data answer ("How many beneficiaries
    # were there?") is answered in that turn's scope, so it must not be cached
    # for anyone else (pipeline.is_scopeless_followup).
    prev = getattr(session, "last_turn", None)
    # Likewise a scheme substitution ("give me the same for MGNREGA in 2023-24"):
    # its scope is the previous turn's (pipeline.is_scheme_substitution).
    if is_scopeless_followup(question, prev) or is_scheme_substitution(question, prev):
        return False
    # D-056 (2026-10-21): a new question that will inherit the chat's place or
    # year ("how many households for PMAY-G" after a West Garo Hills FY 2022-23
    # answer) is answered in THIS chat's scope; a cached answer for the same
    # words was computed in another scope.
    _state = getattr(session, "state", None)
    if _state is not None and getattr(_state, "scheme", None):
        from app import pipeline as _p
        try:
            if _p._same_scheme_context_year(question, question, _state):
                return False
        except Exception:  # noqa: BLE001 — undecidable: do not share
            return False
    # Live 2026-10-21 (harness F3 with the caches on): "show me for south garo
    # hills district" after an MGNREGA FY 2023-24 answer was served another
    # chat's cached KNOWLEDGE answer ("application steps … South Garo Hills"):
    # it opens like no follow-up, so it read as standalone. Inside a chat with
    # an active scheme, words that name no scheme take THAT scheme (D-056), so
    # the answer is this chat's alone (MAIN_Contex 8.6: only standalone turns
    # are shared).
    if _state is not None and getattr(_state, "scheme", None):
        from app import pipeline as _p
        if not _p._mentions_scheme(question):
            return False
    # An explicit topic switch ("go back to MGNREGA, what about 2023-24?") runs
    # in the restored topic's context (app/topic_memory.py), so it is this
    # conversation's alone.
    return not topic_memory.is_topic_command(question)


def pause_question(session, raw_question: str) -> str:
    """The question to remember for a pause. A reply that resumed an earlier
    pause and then paused AGAIN is remembered as the full resumed question
    (pipeline turn_context["resumed_question"]), never the bare reply: a typed
    "Focus Plus" resumed the bank question, the area pause that followed was
    remembered as just "Focus Plus", and the typed "All of Meghalaya" then ran
    as "Focus Plus, All of Meghalaya" (Focus Plus use-case QA 2026-09-27).
    A follow-up that paused is remembered as its standalone form
    (turn_context["standalone_question"]): "give me beneficiaries" rewritten
    "…under CM Elevate Legacy" and paused for the year; remembered as the bare
    fragment, the typed "2024-25" resumed without the scheme (2026-09-29)."""
    ctx = getattr(session, "turn_context", None) or {}
    return ctx.get("standalone_question") or ctx.get("resumed_question") or raw_question


def remember_pause(session, question: str, e: ClarificationNeeded) -> None:
    """Remember a clarification pause so the next turn's reply resumes it.
    The pending fields are part of the durable snapshot (session_sync), so
    the reply may land on any worker."""
    # D-065: the paused question's kind travels with it (a resumed pause keeps
    # the kind it resumed with, so a chain of pauses keeps the typed one).
    session.pending_turn_kind = (getattr(session, "turn_context", None) or {}).get("turn_kind")
    if e.rule in SCOPE_MERGE_RULES:
        # A scope pause ("which area / year?"), a year pause ("which FY?"), or
        # an entity-ambiguity pause ("which of these villages/districts/blocks?")
        # carries one-tap options where they exist, but the user may still type
        # the answer as free text ("West Garo Hills 2023-24", "East Khasi
        # Hills"). Remember the question so the pipeline merges that reply back
        # into it next turn instead of treating it as a brand-new question.
        session.pending_scope_q = question
        session.pending_village_hint = e.village_hint
        session.pending_scope_rule = e.rule
        session.pending_scope_options = None
    elif e.rule in SCHEME_PAUSE_RULES:
        # "Which scheme?" / "which Focus?": remember the options too, so a
        # TYPED scheme name resumes the paused question as its chip would
        # (pipeline._resume_scheme_pause). Any other reply is unaffected.
        session.pending_scope_q = question
        session.pending_village_hint = None
        session.pending_scope_rule = e.rule
        session.pending_scope_options = list(e.options or [])
    elif e.rule and e.options:
        # Any other pause that offers chips ("PMAY-G doesn't record person-days
        # — which of its measures?", "which FY?", "which tranche?", "which
        # Sericulture scheme?"): remember the options, so a TYPED pick ("houses
        # sanctioned", "2022-23", "the second one") resumes it as its chip
        # would, and an unmatched reply continues the paused scheme's thread
        # (pipeline._resume_option_pause / _paused_thread_antecedent). Before
        # 2026-09-29 these pauses were forgotten and a typed reply continued the
        # last ANSWERED turn instead.
        session.pending_scope_q = question
        session.pending_village_hint = None
        session.pending_scope_rule = e.rule
        session.pending_scope_options = list(e.options)


def build_turn(question: str, result: dict) -> Turn:
    """The L1 follow-up context for an answered request. It is recorded even on
    a cache hit, so the next turn's follow-up rewrite still has this question
    as its antecedent."""
    return Turn(
        question=result.get("rewritten_question") or question,
        raw_question=question,
        route=result.get("route", "data"),
        schemes=result.get("schemes", []),
        resolved_entities=result.get("resolved_entities", {}),
        answer=result.get("answer", ""),
        # Structured evidence for a later "what about the top one?" —
        # see context_manager.build_rewrite_evidence (never raises).
        result_summary=context_manager.summarize_result(result),
        subsets=result.get("subsets") or context_manager.result_subsets(result),     # D-098
        answer_frame=_answer_frame_of(question, result),                             # D-110
    )


def _answer_frame_of(question: str, result: dict) -> dict:
    """The answer frame the graph attached (finalize), else one read from the result now (a cached or older
    result); {} for anything but a data answer. Never raises."""
    frame = result.get("answer_frame")
    if isinstance(frame, dict) and frame:
        return dict(frame)
    try:
        return pipeline._c18_fill_frame(question, result) if result.get("route") == "data" else {}
    except Exception:  # noqa: BLE001 — bookkeeping must never fail the answer
        return {}


def _mirror_audit(scope, session_id, question, result, started, ip, trace=None):
    """JSONL mirror of the DB audit trail — offline grep / belt-and-braces. Carries
    the SQL that ran, the error, the few-shot ids and repair counts (turn_trace)."""
    auth.audit({
        **turn_trace.audit_fields(trace, result),
        "tenant_id": scope.tenant_id,
        "user_id": scope.db_user_id,
        "username": scope.username or "(anonymous)",
        "role": scope.role,
        "session_id": session_id,
        "question": question,
        "rewritten_question": result.get("rewritten_question"),
        "route": result.get("route"),
        "schemes": result.get("schemes"),
        "granularity": auth.infer_granularity(result.get("resolved_entities", {}), result.get("sql")),
        "allowed": result.get("route") != "denied",
        "deny_check": result.get("denied_by"),
        "row_count": result.get("row_count"),
        "ip": ip,
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
    })


@router.post("/api/query/transcribe")
async def transcribe(file: UploadFile = File(...),
                     language: str = Form("en"),
                     device: str = Form(""),
                     scope: auth.UserScope = Depends(_identity)):
    """Voice input -> text, via qwen3-asr on the model gateway.

    `language` is already sent by the web UI (ai_query.html appends it to the
    same FormData) and was previously discarded here, because FastAPI drops an
    undeclared form field. Accepting it closes that contract mismatch; the
    value is validated in llm._asr_language before it reaches the gateway,
    which rejects unknown codes with a 400. Defaulted so any client that omits
    the field keeps working.

    Note this was NOT the cause of the "ASR can't convert" failure — that was
    the AudioContext lifecycle bug in ai_query.html's blobToWav()."""
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "empty audio upload")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio too large (max 10 MB)")
    try:
        text = await llm.call_asr(audio, file.filename or "audio.wav",
                                  language=language or "en")
    except ModelBusyError as e:
        raise HTTPException(503, "The service is busy right now. Please retry in a few seconds.",
                            headers={"Retry-After": "5"}) from e
    except Exception as e:
        logger.exception("transcription failed")
        raise HTTPException(502, "transcription upstream error") from e
    # The ASR answers audio with no speech in it with a stock phrase ("Okay.",
    # "I'm not sure.") rather than an empty string. Returning that as the
    # transcript typed it into the composer as if the user had said it.
    # With the vocabulary prompt on, the same audio comes back as the prompt
    # itself, verbatim — the cleaner of the two signals.
    no_speech = (asr_guard.is_no_speech(text)
                 or asr_guard.is_prompt_echo(text, settings.ASR_PROMPT))
    _save_asr_sample(audio, text, no_speech, device)
    if no_speech:
        logger.info("transcribe: no speech (asr said %r, %d bytes)", text[:80], len(audio))
        return {"text": "", "no_speech": True}
    return {"text": text}


def _save_asr_sample(audio: bytes, text: str, no_speech: bool, device: str) -> None:
    """settings.ASR_DEBUG_DIR only: keep the upload and the ASR's answer so a
    bad transcript can be replayed and measured instead of guessed at."""
    if not settings.ASR_DEBUG_DIR:
        return
    try:
        import json
        from pathlib import Path
        d = Path(settings.ASR_DEBUG_DIR)
        d.mkdir(parents=True, exist_ok=True)
        stem = time.strftime("%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:6]}"
        (d / f"{stem}.wav").write_bytes(audio)
        (d / f"{stem}.json").write_text(json.dumps(
            {"text": text, "no_speech": no_speech, "device": device, "bytes": len(audio)},
            ensure_ascii=False), encoding="utf-8")
    except Exception:
        logger.warning("could not save ASR debug sample", exc_info=True)
