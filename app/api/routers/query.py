import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.core import auth
from app.conversation import conversation_memory, conversation_store
from app.orchestration import langgraph_followup
from app.clients import llm
from app.orchestration import pipeline_graph
from app.caching.cache import metrics, response_cache
from app.core.config import settings
from app.api.deps import tenant_scoped
from app.core.net import client_ip as _resolve_ip
from app.nlu import understand
from app.core import request_trace
from app.caching.semantic_cache import semantic_cache
from app.conversation.session_store import ConversationState, SessionOwnershipError, Turn, session_store
from app.database import db
from app.database.db import UnsafeSQLError
from app.clients.llm import ModelBusyError
from app.orchestration.pipeline import (
    RESUMABLE_CLARIFICATION_RULES,
    ClarificationNeeded,
    _empty_data_fields,
    answer_question,
    apply_post_answer_context,
    data_path_fallback_or_reraise,
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
    # A one-tap clarification option: which slot it fills and with what
    # (FRAME_GATES_ENABLED — see pipeline._run_pipeline_frame_mode). Sent
    # alongside `question` (the option's text), which older clients send alone.
    slot: str | None = Field(default=None, max_length=32, pattern=r"^[a-z_]+$")
    value: "int | str | dict | None" = None

    @field_validator("value")
    @classmethod
    def _small_value(cls, v):
        import json as _json
        if v is not None and len(_json.dumps(v, default=str)) > 1000:
            raise ValueError("value too large")
        return v

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


async def _identity(scope: auth.UserScope = Depends(tenant_scoped)) -> auth.UserScope:
    """Require a real user when AUTH_ENABLED; allow anonymous in dev mode.
    Depends on tenant_scoped (not current_scope directly) so this route's
    RLS tenant context (openspec/changes/multi-tenant-rls-scheme-scaleout)
    is set for its whole duration — see that dependency's own docstring."""
    if settings.AUTH_ENABLED and scope.db_user_id is None:
        raise HTTPException(401, "authentication required — POST /api/auth/login")
    return scope


@dataclass
class _TurnCtx:
    """Per-request state shared by /api/query and /api/query/stream: who is
    asking, which conversation, and what the caches already hold."""
    started: float
    ip: str
    session_id: str
    session: object
    scope: auth.UserScope
    scope_key: str
    cacheable: bool
    sem_vec: object = None
    result: "dict | None" = None      # a cache hit, when served_from is set
    served_from: "str | None" = None  # metrics route tag when the answer came from a cache


async def _prepare_turn(req: QueryRequest, request: Request, scope: auth.UserScope) -> _TurnCtx:
    """Validation, trace, session resolution + rehydration, and the cache
    lookup — everything before the pipeline runs. Raises HTTPException 400/403,
    so a streaming caller gets a real status before any event is sent."""
    # openspec/changes/multi-tenant-rls-scheme-scaleout: this request's RLS
    # tenant context (app.database.db.set_tenant_context) is already set for the
    # whole duration of this call by _identity's dependency on
    # app.api.deps.tenant_scoped — every DB call made anywhere below,
    # including the curated-data query app.orchestration.pipeline.answer_question
    # eventually issues via app.database.db.run_readonly(), carries it. No explicit
    # wrapper needed here (an earlier version of this function had one
    # before tenant_scoped existed — see app/api/deps.py for why that approach
    # doesn't scale to every router).
    if not req.question or not req.question.strip():
        raise HTTPException(400, "question must not be empty")

    started = time.monotonic()
    # This request's diagnostic trace (stage latencies, rules fired, verifier,
    # repairs, fallbacks, frame before/after) -> app.query_audit.trace and the
    # JSONL mirror. Lives in this request's own task context, so it cannot
    # leak into another request; see app/core/request_trace.py.
    request_trace.start(req.question)
    ip = _client_ip(request)
    client_session = req.session_id or request.headers.get("x-session-id")
    # The client owns conversation identity: the chat UI mints a session_id per
    # "New chat" so each thread is its own row in app.conversations. Only a
    # caller that sends none falls back to the per-day bucket, which keeps API
    # scripts and older clients from creating a thread per one-off question.
    if client_session:
        session_id = client_session
    elif scope.db_user_id is not None:
        session_id = f"day-{scope.db_user_id}-{date.today().isoformat()}"
    else:
        session_id = f"one-{uuid.uuid4().hex[:16]}"
    try:
        session = session_store.ensure(session_id, scope.user_id)
    except SessionOwnershipError as e:
        # A session_id belonging to a different user — e.g. the guessable
        # `day-{user_id}-{date}` bucket for a known other user_id, or a
        # client-supplied id that collides with someone else's live session.
        # Reject outright: never resume, read, or reassign it.
        logger.warning("session ownership denied: session_id=%s requester=%s",
                       session_id, scope.user_id)
        raise HTTPException(403, "This session belongs to a different account.") from e
    session.scope = scope
    # Rehydrate the L1 structured state from its L2 (Postgres) mirror when this
    # is a fresh in-process session resuming an existing, client-named thread —
    # a worker restart, a session that TTL'd out of session_store, or a request
    # landing on a different worker. Only on a session with no turns yet, so a
    # live conversation's in-process state (the source of truth while it's
    # active) is never clobbered mid-thread. Best-effort: any failure just
    # means this turn starts with blank state, same as before this layer existed.
    if not session.turns and client_session:
        try:
            durable = await conversation_store.load_context_state(session_id)
            if durable.get("context_state"):
                session.state = ConversationState.from_dict(durable["context_state"])
            if durable.get("summary"):
                session.summary = durable["summary"]
                session.summary_turn_count = session.state.turn_count
        except Exception as e:  # noqa: BLE001
            logger.warning("context state rehydration failed (non-fatal): %s", e)

    # Response + semantic caches are keyed on (question + authorization
    # fingerprint): safe to share across users who resolve to the same scope,
    # since the auth outcome is a pure function of scope + query. Genuine
    # follow-up fragments ("what about EGH?") are never cached — they only mean
    # something against their own conversation.
    ctx = _TurnCtx(started=started, ip=ip, session_id=session_id, session=session, scope=scope,
                   scope_key=scope.cache_fingerprint(),
                   cacheable=not looks_like_followup(req.question) and not req.slot)

    if ctx.cacheable:
        cached = await response_cache.get(req.question, ctx.scope_key)
        if cached is not None:
            ctx.result = {**cached, "session_id": session_id}
            ctx.served_from = f"{cached.get('route', 'data')}:cache"
        else:
            sem_hit, ctx.sem_vec = await semantic_cache.lookup(req.question, ctx.scope_key)
            if sem_hit is not None:
                ctx.result = {**sem_hit, "session_id": session_id}
                ctx.served_from = f"{sem_hit.get('route', 'data')}:semcache"
    return ctx


def _paused_result(ctx: _TurnCtx, req: QueryRequest, clar: dict) -> dict:
    """A checkpointer-owned pause (langgraph_followup / pipeline_graph resume):
    shape it for the frontend clarification renderer and record the turn."""
    out = {
        "route": "clarification",
        "intent": "CLARIFY",
        "confidence": "high",
        "answer": clar["question"],
        "needs_clarification": True,
        "question": clar["question"],
        "clarification": {"options": clar.get("options"), "rule": clar.get("rule")},
        "session_id": ctx.session_id,
        "denied_by": clar.get("rule"),
        **_empty_data_fields(),
    }
    clarify_latency_ms = (time.monotonic() - ctx.started) * 1000
    conversation_store.persist_turn(
        tenant_id=ctx.scope.tenant_id, user_id=ctx.scope.db_user_id, session_id=ctx.session_id,
        result=out, question=req.question, latency_ms=clarify_latency_ms,
        username=ctx.scope.username or None, ip=ctx.ip, trace=request_trace.snapshot(),
    )
    # Mirrors session.state durably (e.g. pending_village_hint,
    # set internally by the graph node for entity-ambiguous) —
    # symmetric with the bespoke path's own save_context_state
    # call, even though this path's resume signal lives in the
    # checkpointer, not in this blob.
    conversation_store.save_context_state(
        session_id=ctx.session_id, context_state=ctx.session.state.to_dict())
    _mirror_audit(ctx.scope, ctx.session_id, req.question, out, ctx.started, ctx.ip)
    return out


async def _answer_turn(ctx: _TurnCtx, req: QueryRequest,
                       on_event=None) -> "tuple[dict, bool]":
    """Run the turn through whichever pipeline owns it. Returns (result,
    recorded): recorded=True for a checkpointer pause that _paused_result
    already persisted — the caller returns it as-is, without _finalize.
    Raises ClarificationNeeded (see _clarification_result) and the pipeline's
    own errors (see _error_response). `on_event` (streaming only) reaches the
    answer_question path; the two checkpointer-resume paths run unchanged
    and simply produce no live events."""
    session, scope, session_id = ctx.session, ctx.scope, ctx.session_id
    # FRAME_GATES_ENABLED owns clarification resume itself (slot filling
    # on ConversationState.pending_frame, inside answer_question), so the
    # two checkpointer-based resume owners below stand aside — the same
    # one-owner-per-pause rule they already follow between themselves.
    if settings.LANGGRAPH_FOLLOWUP_ENABLED and not settings.FRAME_GATES_ENABLED:
        # Alternative pause/resume path (openspec/changes/phase-2-
        # orchestration-durability) — app/orchestration/langgraph_followup.py owns its
        # own durable resume signal via its checkpointer (is_paused
        # below reads it), never via session.state.pending_scope_q, so
        # this branch and the bespoke except-block below can coexist on
        # the same session without either corrupting the other's merge
        # logic. See app/orchestration/langgraph_followup.py's module docstring.
        paused = await langgraph_followup.is_paused(session_id)
        lf_result = await asyncio.wait_for(
            langgraph_followup.run_with_pause(
                session_id=session_id, question=req.question, scope=scope,
                resume=req.question if paused else None,
            ),
            timeout=settings.REQUEST_TIMEOUT_SECONDS,
        )
        if lf_result.get("paused"):
            # Deliberately does NOT set session.state.pending_scope_q/
            # pending_village_hint the way the bespoke except-block
            # below does for its own pauses — this path's resume state
            # already lives durably in the LangGraph checkpointer
            # (is_paused above reads it back on the next call).
            return _paused_result(ctx, req, lf_result["clarification"]), True
        return lf_result, False
    if (
        not settings.LANGGRAPH_FOLLOWUP_ENABLED
        and not settings.FRAME_GATES_ENABLED
        and (settings.PIPELINE_GRAPH_ENABLED or settings.PIPELINE_GRAPH_CANARY_PERCENT > 0)
        # should_resume, not is_paused: the thread must be suspended at
        # a REAL interrupt(), and this reply must actually be an answer
        # to it rather than "thanks" or a brand-new question. Either way
        # a False here clears the dead thread, so falling through to the
        # normal answer_question path below is safe.
        and await pipeline_graph.should_resume(session_id, req.question)
    ):
        # Task 5.4 — real cross-request resume via
        # app/orchestration/pipeline_graph.py's own checkpointer. Mirrors the
        # LANGGRAPH_FOLLOWUP_ENABLED branch above exactly (same
        # is_paused-then-resume shape, same reasoning for why this
        # bypasses answer_question/_run_pipeline's routing maze
        # entirely rather than re-entering it): a paused graph
        # thread must resume at the exact node it paused at, not
        # restart the whole pipeline from node 5.1. `is_paused` is
        # only even checked when LANGGRAPH_FOLLOWUP_ENABLED is off
        # — see app/orchestration/pipeline.py::_run_pipeline's mutual-exclusivity
        # comment at the call site that sets thread_id, the flip
        # side of this same design decision.
        # Wrapped in the same DATA-path except-ladder _run_pipeline
        # applies, because this branch bypasses _run_pipeline entirely.
        # Without it, a resumed turn whose SQL repair budget is spent
        # (e.g. the semantic verifier rejecting the repaired SQL too)
        # escaped as a raw 502 in the chat UI, where the bespoke path
        # and the non-resume graph path both answer from the KB or ask
        # the user to rephrase. Transient gateway errors and
        # ClarificationNeeded still propagate untouched.
        try:
            pg_result = await asyncio.wait_for(
                pipeline_graph.resume_via_graph(session_id, req.question),
                timeout=settings.REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as _e:  # noqa: BLE001 — sorted by the helper
            _fallback = await data_path_fallback_or_reraise(
                _e, req.question, req.question)
            if _fallback is None:
                raise
            pg_result = _fallback
        if pg_result.get("paused"):
            return _paused_result(ctx, req, pg_result["clarification"]), True
        # This branch deliberately bypasses answer_question/_run_pipeline
        # (see the comment above), so the post-answer half of
        # answer_question — 'Next steps' suggestions + the Context
        # Updater — has to be applied explicitly here. Without it a
        # graph-resumed turn never reached context_manager.update_state,
        # so ConversationState kept none of that turn's scheme/district/
        # year and the save_context_state call further down mirrored the
        # stale pre-turn blob to L2. See
        # tests/unit/test_graph_resume_context_layer.py.
        return await apply_post_answer_context(pg_result, req.question, session=session), False
    _choice = understand.incoming_choice.set(
        {"slot": req.slot, "value": req.value} if req.slot else None)
    try:
        result = await asyncio.wait_for(
            answer_question(req.question, session=session, scope=scope,
                            **({"on_event": on_event} if on_event is not None else {})),
            timeout=settings.REQUEST_TIMEOUT_SECONDS,
        )
    finally:
        understand.incoming_choice.reset(_choice)
    return result, False


def _clarification_result(ctx: _TurnCtx, req: QueryRequest, e: ClarificationNeeded) -> dict:
    """A ClarificationNeeded pause: remember what it asked, record the turn,
    and return the clarification response.

    Reached either for the bespoke path's own pause (flag off), or a
    non-pause-eligible (terminal) rule propagated by run_with_pause
    (flag on) — a pause-eligible rule under the flag never reaches
    here, it's handled by the lf_result.get("paused") branch in
    _answer_turn instead, so `e.rule in (...)` below is naturally False
    whenever the flag is on and this still runs.

    A scope pause ("which area / year?"), a year pause ("which FY?"), or
    an entity-ambiguity pause ("which of these villages/districts/blocks?")
    carries one-tap options where they exist, but the user may still type
    the answer as free text ("West Garo Hills 2023-24", "East Khasi
    Hills"). Remember the question so the pipeline merges that reply back
    into it next turn instead of treating it as a brand-new question.
    graph_resumable (task 5.4): this pause's resume state already
    lives durably in pipeline_graph's own checkpointer (the elif
    branch in _answer_turn resumes it via resume_via_graph next turn) —
    setting the bespoke fields too would make BOTH mechanisms
    think they own the resume, and the next request would hit
    the graph-resume branch first anyway, never reading
    these fields — same reasoning app/orchestration/langgraph_followup.py's
    own pause branch already documents for its separate case."""
    session = ctx.session
    request_trace.note("clarification", {
        "asked": e.question, "rule": e.rule,
        "slot": understand.SLOT_FOR_RULE.get(e.rule or ""),
        "options": [o.get("label") for o in (e.options or []) if isinstance(o, dict)]})
    if settings.FRAME_GATES_ENABLED and getattr(e, "pending_frame", None) is not None:
        # Frame mode: the paused frame + the slot it asks — the next turn
        # fills that slot (see pipeline._run_pipeline_frame_mode). Saved
        # with the state below, so any worker can resume it.
        session.state.pending_frame = e.pending_frame
    elif e.rule in RESUMABLE_CLARIFICATION_RULES and not e.graph_resumable:
        session.state.pending_scope_q = req.question
        session.state.pending_village_hint = e.village_hint
        # The chips offered, and what the turn had already resolved
        # when it paused — so the next turn can recognise a tapped chip
        # exactly and doesn't re-derive the earlier rounds' answers
        # from the merged text alone. See ConversationState's own
        # doc-comments for both fields.
        session.state.pending_options = list(e.options or [])
        session.state.pending_resolved = dict(e.resolved_so_far or {})
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
        "session_id": ctx.session_id,
        # Surfaces which rule paused the turn (e.g. "pii-column-blocked")
        # on the same queryable column app.conversation_turns/
        # app.query_audit already use for a hard authorization denial —
        # conversation_store.persist_turn reads this key unchanged, no
        # schema change needed. Without it a PII block was previously
        # visible only in the application log, not the durable audit
        # trail. Never the blocklisted column name itself — just the rule.
        "denied_by": e.rule,
        **_empty_data_fields(),
    }
    # A clarification pause is still a turn the user should see when they
    # reopen the thread — persist it durably (L2) exactly like an answered
    # turn, so the conversation appears in the sidebar and replays the
    # clarifying question + its option chips.
    clarify_latency_ms = (time.monotonic() - ctx.started) * 1000
    conversation_store.persist_turn(
        tenant_id=ctx.scope.tenant_id, user_id=ctx.scope.db_user_id, session_id=ctx.session_id,
        result=out, question=req.question, latency_ms=clarify_latency_ms,
        username=ctx.scope.username or None, ip=ctx.ip, trace=request_trace.snapshot(),
    )
    # Mirror the pause fields (session.state.pending_scope_q/
    # pending_village_hint) to app.conversations.context_state now, not
    # just on a successful turn — otherwise a worker restart, a
    # session-TTL eviction, or the next request landing on a different
    # worker (routine at this deployment's 2-VM/4-worker scale) silently
    # loses the resume context and the pause can never be answered.
    # See openspec/changes/phase-2-orchestration-durability/design.md.
    conversation_store.save_context_state(
        session_id=ctx.session_id, context_state=session.state.to_dict())
    _mirror_audit(ctx.scope, ctx.session_id, req.question, out, ctx.started, ctx.ip)
    return out


def _error_response(e: Exception) -> "tuple[int, str, dict | None]":
    """(status, detail, headers) for a failed turn, with the metrics and
    logging /api/query has always done. Call from inside the `except` block
    (logger.exception reads the active exception)."""
    if isinstance(e, ModelBusyError):
        metrics.busy_rejections += 1
        return 503, "The service is busy right now. Please retry in a few seconds.", {"Retry-After": "5"}
    if isinstance(e, asyncio.TimeoutError):
        metrics.errors += 1
        return 504, "The request took too long. Please try a narrower question.", None
    if isinstance(e, UnsafeSQLError):
        metrics.errors += 1
        logger.error("Blocked unsafe SQL: %s", e)
        return 500, "the generated query failed a safety check", None
    metrics.errors += 1
    metrics.model_errors += 1
    logger.exception("query failed")
    return 502, "upstream error while answering the question", None


async def _finalize(ctx: _TurnCtx, req: QueryRequest, result: dict) -> dict:
    """Post-answer bookkeeping for an answered (or cache-served) turn."""
    session_id = ctx.session_id
    scope = ctx.scope
    latency_ms = (time.monotonic() - ctx.started) * 1000
    result["session_id"] = session_id
    # Surface the real end-to-end time to the UI meta line. On a cache hit this
    # is recomputed here (the fast path), overwriting whatever was cached.
    result["execution_time_ms"] = round(latency_ms)

    # L1 follow-up context — recorded even on a cache hit, so the next turn's
    # follow-up rewrite still has this question as its antecedent.
    session_store.add_turn(session_id, Turn(
        question=result.get("rewritten_question") or req.question,
        raw_question=req.question,
        route=result.get("route", "data"),
        schemes=result.get("schemes", []),
        resolved_entities=result.get("resolved_entities", {}),
        answer=result.get("answer", ""),
    ))
    # L2 durable — conversation + turn + audit (fire-and-forget)
    conversation_store.persist_turn(
        tenant_id=scope.tenant_id, user_id=scope.db_user_id, session_id=session_id,
        result=result, question=req.question, latency_ms=latency_ms,
        username=scope.username or None, ip=ctx.ip, trace=request_trace.snapshot(),
    )
    # Semantic conversation memory — indexes this turn for later "relevant
    # older turns" retrieval (see app.conversation.context_manager.build_followup_context).
    # Fire-and-forget, scoped to this tenant/user/session; never blocks or
    # fails the response (app.conversation.conversation_memory.index_turn degrades silently).
    conversation_memory.index_turn(
        tenant_id=scope.tenant_id, user_id=scope.db_user_id, session_id=session_id,
        question=req.question, standalone_question=result.get("rewritten_question") or req.question,
        answer=result.get("answer", ""), schemes=result.get("schemes"),
    )
    # L2 mirror of the structured conversation state (context_manager.update_state
    # already ran, in-process, inside answer_question). Runs after persist_turn
    # above so the app.conversations row it needs is guaranteed to exist,
    # including on this session's very first turn.
    conversation_store.save_context_state(
        session_id=session_id, context_state=ctx.session.state.to_dict())
    _mirror_audit(scope, session_id, req.question, result, ctx.started, ctx.ip)

    # Only write back a freshly computed answer, and only under this caller's scope.
    if ctx.cacheable and ctx.served_from is None:
        await response_cache.put(req.question, result, ctx.scope_key)
        await semantic_cache.put(req.question, result, vec=ctx.sem_vec, scope_key=ctx.scope_key)

    metrics.record(ctx.served_from or result.get("route", "data"), latency_ms)
    return result


@router.post("/api/query")
async def query(req: QueryRequest, request: Request,
                scope: auth.UserScope = Depends(_identity)):
    ctx = await _prepare_turn(req, request, scope)
    result = ctx.result
    if result is None:
        try:
            result, recorded = await _answer_turn(ctx, req)
            if recorded:
                return result
        except ClarificationNeeded as e:
            return _clarification_result(ctx, req, e)
        except Exception as e:
            status, detail, headers = _error_response(e)
            raise HTTPException(status, detail, headers=headers) from e
    return await _finalize(ctx, req, result)


# ── /api/query/stream — the same turn as Server-Sent Events ─────────────────
# Events: "token" {"t"} / "replace" {"answer"} while the answer is written
# (app/response/answer_stream.py), then exactly one "done" (the dict /api/query
# would have returned — an answer or a clarification) or "error" {"status",
# "detail"}. Validation / auth / session-ownership failures happen before the
# stream opens and come back as ordinary HTTP errors.
_SSE_PING_SECONDS = 15
_TURN_DONE = object()


def _sse(name: str, data) -> str:
    return f"event: {name}\ndata: {json.dumps(data, default=str)}\n\n"


@router.post("/api/query/stream")
async def query_stream(req: QueryRequest, request: Request,
                       scope: auth.UserScope = Depends(_identity)):
    ctx = await _prepare_turn(req, request, scope)

    async def gen():
        # The body runs after this handler returns; set the RLS tenant context
        # here too, exactly as tenant_scoped does, so every DB call the
        # pipeline makes carries it regardless of when that dependency's
        # own teardown runs relative to the stream.
        tenant_token = db.set_tenant_context(scope.tenant_id, bypass=(scope.role == "super_admin"))
        task: "asyncio.Task | None" = None
        try:
            if ctx.result is not None:
                yield _sse("done", await _finalize(ctx, req, ctx.result))
                return

            queue: asyncio.Queue = asyncio.Queue()

            # Synchronous on purpose: "stage" events fire from a plain context
            # manager (request_trace.stage), and a sync sink keeps every event —
            # stage, token, replace — in the exact order it happened.
            def on_event(kind: str, data: dict) -> None:
                queue.put_nowait((kind, data))

            task = asyncio.create_task(_answer_turn(ctx, req, on_event=on_event))
            task.add_done_callback(lambda _t: queue.put_nowait(_TURN_DONE))
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), _SSE_PING_SECONDS)
                except asyncio.TimeoutError:
                    if await request.is_disconnected():
                        logger.info("query_stream: client disconnected — cancelling turn")
                        task.cancel()
                        return
                    yield ": ping\n\n"
                    continue
                if item is _TURN_DONE:
                    break
                yield _sse(*item)

            try:
                result, recorded = task.result()
            except ClarificationNeeded as e:
                yield _sse("done", _clarification_result(ctx, req, e))
                return
            except Exception as e:  # noqa: BLE001 — mapped exactly as /api/query maps it
                status, detail, _headers = _error_response(e)
                yield _sse("error", {"status": status, "detail": detail})
                return
            if not recorded:
                result = await _finalize(ctx, req, result)
            yield _sse("done", result)
        except (GeneratorExit, asyncio.CancelledError):
            # The client went away mid-stream (the server closed the generator
            # or cancelled its task): stop spending model/DB time on it.
            if task is not None and not task.done():
                logger.info("query_stream: stream closed — cancelling turn")
                task.cancel()
            raise
        finally:
            try:
                db.reset_tenant_context(tenant_token)
            except ValueError:
                # Finalised from another context (a generator closed by GC):
                # that context never held this token, so there is nothing to undo.
                pass

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _shadow_frame_for(session_id, question) -> "dict | None":
    """This turn's shadow QueryFrame, or None if the session holds a frame for
    a different message (e.g. this turn was a cache hit and never ran)."""
    shadow = getattr(session_store.get(session_id), "understand_frame", None)
    return shadow if shadow and shadow.get("question") == question else None


def _mirror_audit(scope, session_id, question, result, started, ip):
    """JSONL mirror of the DB audit trail — offline grep / belt-and-braces."""
    auth.audit({
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
        # Kept in parity with app.query_audit's columns of the same name
        # (openspec/changes/phase-2-audit-trail-enrichment) — same bounded
        # preview size, settings.AUDIT_RESULT_PREVIEW_ROWS.
        "sql": result.get("sql"),
        "result_preview": (result.get("data") or [])[:settings.AUDIT_RESULT_PREVIEW_ROWS],
        "findings": result.get("findings") or [],
        "chart_type": result.get("chart_type"),
        "answer": result.get("answer"),
        # Kept in parity with app.query_audit's columns of the same name
        # (openspec/changes/query-analyzer-consolidation).
        "analysis": result.get("analysis"),
        "scope": result.get("scope"),
        # Step 9 diagnostic trace — same object as app.query_audit.trace.
        "trace": request_trace.snapshot(),
        # Shadow Understand node (settings.UNDERSTAND_SHADOW) — the QueryFrame
        # computed alongside this turn; key present only while shadowing.
        # With FRAME_GATES_ENABLED the same frame DROVE the gates; the answer
        # then also carries the defaults applied and the rule trace.
        **({"understand_frame": _shadow_frame_for(session_id, question)}
           if (settings.UNDERSTAND_SHADOW or settings.FRAME_GATES_ENABLED) else {}),
        **({"assumptions": result.get("assumptions"), "gate_trace": result.get("gate_trace")}
           if settings.FRAME_GATES_ENABLED else {}),
    })


@router.post("/api/query/transcribe")
async def transcribe(file: UploadFile = File(...), scope: auth.UserScope = Depends(_identity)):
    """Voice input -> text, via qwen3-asr on the model gateway."""
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "empty audio upload")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio too large (max 10 MB)")
    try:
        text = await llm.call_asr(audio, file.filename or "audio.wav")
    except ModelBusyError as e:
        raise HTTPException(503, "The service is busy right now. Please retry in a few seconds.",
                            headers={"Retry-After": "5"}) from e
    except Exception as e:
        logger.exception("transcription failed")
        raise HTTPException(502, "transcription upstream error") from e
    return {"text": text}
