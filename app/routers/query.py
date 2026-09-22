import asyncio
import logging
import time
import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, field_validator

from app import auth, conversation_memory, conversation_store, langgraph_followup, llm, pipeline_graph
from app.cache import metrics, response_cache
from app.config import settings
from app.deps import tenant_scoped
from app.net import client_ip as _resolve_ip
from app.semantic_cache import semantic_cache
from app.session_store import ConversationState, SessionOwnershipError, Turn, session_store
from app.db import UnsafeSQLError
from app.llm import ModelBusyError
from app.pipeline import (
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


@router.post("/api/query")
async def query(req: QueryRequest, request: Request,
                scope: auth.UserScope = Depends(_identity)):
    # openspec/changes/multi-tenant-rls-scheme-scaleout: this request's RLS
    # tenant context (app.db.set_tenant_context) is already set for the
    # whole duration of this call by _identity's dependency on
    # app.deps.tenant_scoped — every DB call made anywhere below,
    # including the curated-data query app.pipeline.answer_question
    # eventually issues via app.db.run_readonly(), carries it. No explicit
    # wrapper needed here (an earlier version of this function had one
    # before tenant_scoped existed — see app/deps.py for why that approach
    # doesn't scale to every router).
    if not req.question or not req.question.strip():
        raise HTTPException(400, "question must not be empty")

    started = time.monotonic()
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
    scope_key = scope.cache_fingerprint()
    cacheable = not looks_like_followup(req.question)
    sem_vec = None
    result = None
    served_from = None  # metrics route tag when the answer came from a cache

    if cacheable:
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
        try:
            if settings.LANGGRAPH_FOLLOWUP_ENABLED:
                # Alternative pause/resume path (openspec/changes/phase-2-
                # orchestration-durability) — app/langgraph_followup.py owns its
                # own durable resume signal via its checkpointer (is_paused
                # below reads it), never via session.state.pending_scope_q, so
                # this branch and the bespoke except-block below can coexist on
                # the same session without either corrupting the other's merge
                # logic. See app/langgraph_followup.py's module docstring.
                paused = await langgraph_followup.is_paused(session_id)
                lf_result = await asyncio.wait_for(
                    langgraph_followup.run_with_pause(
                        session_id=session_id, question=req.question, scope=scope,
                        resume=req.question if paused else None,
                    ),
                    timeout=settings.REQUEST_TIMEOUT_SECONDS,
                )
                if lf_result.get("paused"):
                    clar = lf_result["clarification"]
                    # Deliberately does NOT set session.state.pending_scope_q/
                    # pending_village_hint the way the bespoke except-block
                    # below does for its own pauses — this path's resume state
                    # already lives durably in the LangGraph checkpointer
                    # (is_paused above reads it back on the next call).
                    out = {
                        "route": "clarification",
                        "intent": "CLARIFY",
                        "confidence": "high",
                        "answer": clar["question"],
                        "needs_clarification": True,
                        "question": clar["question"],
                        "clarification": {"options": clar.get("options"), "rule": clar.get("rule")},
                        "session_id": session_id,
                        "denied_by": clar.get("rule"),
                        **_empty_data_fields(),
                    }
                    clarify_latency_ms = (time.monotonic() - started) * 1000
                    conversation_store.persist_turn(
                        tenant_id=scope.tenant_id, user_id=scope.db_user_id, session_id=session_id,
                        result=out, question=req.question, latency_ms=clarify_latency_ms,
                        username=scope.username or None, ip=ip,
                    )
                    # Mirrors session.state durably (e.g. pending_village_hint,
                    # set internally by the graph node for entity-ambiguous) —
                    # symmetric with the bespoke path's own save_context_state
                    # call, even though this path's resume signal lives in the
                    # checkpointer, not in this blob.
                    conversation_store.save_context_state(
                        session_id=session_id, context_state=session.state.to_dict())
                    _mirror_audit(scope, session_id, req.question, out, started, ip)
                    return out
                result = lf_result
            elif (
                not settings.LANGGRAPH_FOLLOWUP_ENABLED
                and (settings.PIPELINE_GRAPH_ENABLED or settings.PIPELINE_GRAPH_CANARY_PERCENT > 0)
                # should_resume, not is_paused: the thread must be suspended at
                # a REAL interrupt(), and this reply must actually be an answer
                # to it rather than "thanks" or a brand-new question. Either way
                # a False here clears the dead thread, so falling through to the
                # normal answer_question path below is safe.
                and await pipeline_graph.should_resume(session_id, req.question)
            ):
                # Task 5.4 — real cross-request resume via
                # app/pipeline_graph.py's own checkpointer. Mirrors the
                # LANGGRAPH_FOLLOWUP_ENABLED branch above exactly (same
                # is_paused-then-resume shape, same reasoning for why this
                # bypasses answer_question/_run_pipeline's routing maze
                # entirely rather than re-entering it): a paused graph
                # thread must resume at the exact node it paused at, not
                # restart the whole pipeline from node 5.1. `is_paused` is
                # only even checked when LANGGRAPH_FOLLOWUP_ENABLED is off
                # — see app/pipeline.py::_run_pipeline's mutual-exclusivity
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
                    clar = pg_result["clarification"]
                    out = {
                        "route": "clarification",
                        "intent": "CLARIFY",
                        "confidence": "high",
                        "answer": clar["question"],
                        "needs_clarification": True,
                        "question": clar["question"],
                        "clarification": {"options": clar.get("options"), "rule": clar.get("rule")},
                        "session_id": session_id,
                        "denied_by": clar.get("rule"),
                        **_empty_data_fields(),
                    }
                    clarify_latency_ms = (time.monotonic() - started) * 1000
                    conversation_store.persist_turn(
                        tenant_id=scope.tenant_id, user_id=scope.db_user_id, session_id=session_id,
                        result=out, question=req.question, latency_ms=clarify_latency_ms,
                        username=scope.username or None, ip=ip,
                    )
                    conversation_store.save_context_state(
                        session_id=session_id, context_state=session.state.to_dict())
                    _mirror_audit(scope, session_id, req.question, out, started, ip)
                    return out
                # This branch deliberately bypasses answer_question/_run_pipeline
                # (see the comment above), so the post-answer half of
                # answer_question — 'Next steps' suggestions + the Context
                # Updater — has to be applied explicitly here. Without it a
                # graph-resumed turn never reached context_manager.update_state,
                # so ConversationState kept none of that turn's scheme/district/
                # year and the save_context_state call further down mirrored the
                # stale pre-turn blob to L2. See
                # tests/test_graph_resume_context_layer.py.
                result = await apply_post_answer_context(
                    pg_result, req.question, session=session)
            else:
                result = await asyncio.wait_for(
                    answer_question(req.question, session=session, scope=scope),
                    timeout=settings.REQUEST_TIMEOUT_SECONDS,
                )
        except ClarificationNeeded as e:
            # Reached either for the bespoke path's own pause (flag off), or a
            # non-pause-eligible (terminal) rule propagated by run_with_pause
            # (flag on) — a pause-eligible rule under the flag never reaches
            # here, it's handled by the lf_result.get("paused") branch above
            # instead, so `e.rule in (...)` below is naturally False whenever
            # the flag is on and this except block still runs.
            #
            # A scope pause ("which area / year?"), a year pause ("which FY?"), or
            # an entity-ambiguity pause ("which of these villages/districts/blocks?")
            # carries one-tap options where they exist, but the user may still type
            # the answer as free text ("West Garo Hills 2023-24", "East Khasi
            # Hills"). Remember the question so the pipeline merges that reply back
            # into it next turn instead of treating it as a brand-new question.
            # graph_resumable (task 5.4): this pause's resume state already
            # lives durably in pipeline_graph's own checkpointer (the elif
            # branch above resumes it via resume_via_graph next turn) —
            # setting the bespoke fields too would make BOTH mechanisms
            # think they own the resume, and the next request would hit
            # the graph-resume branch above first anyway, never reading
            # these fields — same reasoning app/langgraph_followup.py's
            # own pause branch already documents for its separate case.
            if e.rule in RESUMABLE_CLARIFICATION_RULES and not e.graph_resumable:
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
                "session_id": session_id,
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
            clarify_latency_ms = (time.monotonic() - started) * 1000
            conversation_store.persist_turn(
                tenant_id=scope.tenant_id, user_id=scope.db_user_id, session_id=session_id,
                result=out, question=req.question, latency_ms=clarify_latency_ms,
                username=scope.username or None, ip=ip,
            )
            # Mirror the pause fields (session.state.pending_scope_q/
            # pending_village_hint) to app.conversations.context_state now, not
            # just on a successful turn — otherwise a worker restart, a
            # session-TTL eviction, or the next request landing on a different
            # worker (routine at this deployment's 2-VM/4-worker scale) silently
            # loses the resume context and the pause can never be answered.
            # See openspec/changes/phase-2-orchestration-durability/design.md.
            conversation_store.save_context_state(
                session_id=session_id, context_state=session.state.to_dict())
            _mirror_audit(scope, session_id, req.question, out, started, ip)
            return out
        except ModelBusyError as e:
            metrics.busy_rejections += 1
            raise HTTPException(503, "The service is busy right now. Please retry in a few seconds.",
                                headers={"Retry-After": "5"}) from e
        except asyncio.TimeoutError as e:
            metrics.errors += 1
            raise HTTPException(504, "The request took too long. Please try a narrower question.") from e
        except UnsafeSQLError as e:
            metrics.errors += 1
            logger.error("Blocked unsafe SQL: %s", e)
            raise HTTPException(500, "the generated query failed a safety check") from e
        except Exception as e:
            metrics.errors += 1
            metrics.model_errors += 1
            logger.exception("query failed")
            raise HTTPException(502, "upstream error while answering the question") from e

    latency_ms = (time.monotonic() - started) * 1000
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
        username=scope.username or None, ip=ip,
    )
    # Semantic conversation memory — indexes this turn for later "relevant
    # older turns" retrieval (see app.context_manager.build_followup_context).
    # Fire-and-forget, scoped to this tenant/user/session; never blocks or
    # fails the response (app.conversation_memory.index_turn degrades silently).
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
        session_id=session_id, context_state=session.state.to_dict())
    _mirror_audit(scope, session_id, req.question, result, started, ip)

    # Only write back a freshly computed answer, and only under this caller's scope.
    if cacheable and served_from is None:
        await response_cache.put(req.question, result, scope_key)
        await semantic_cache.put(req.question, result, vec=sem_vec, scope_key=scope_key)

    metrics.record(served_from or result.get("route", "data"), latency_ms)
    return result


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
