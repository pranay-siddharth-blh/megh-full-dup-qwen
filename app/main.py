import asyncio
import logging

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import appdb, pipeline, schema_introspect
from app.annotations import load_all as load_annotations
from app.config import insecure_secrets, reranker_problem, settings
from app.db import close_pool, init_pool
from app.deps import current_scope
from app.entity_resolver import load_all as load_entity_resolver
from app.kb_ingest import ingest_kb
from app.llm import close_client, init_client
from app.middleware.limits import BodyLimitMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware, apply_security_headers
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.feedback import router as feedback_router
from app.routers.history import router as history_router
from app.routers.query import router as query_router
from app.routers.rag import router as rag_router
from app.routers.stats import router as stats_router
from app.vectorstore import close_qdrant, collection_count, init_qdrant

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("nlp_service")

# app/main.py -> repo root -> web/
_FRONTEND = Path(__file__).resolve().parents[1] / "web"


async def _ingest_kb_bg():
    """KB ingest runs in the background so a cold Qdrant / slow embed batch
    never blocks the service from accepting traffic."""
    try:
        result = await ingest_kb()
        logger.info("scheme KB: %s", result)
    except Exception as e:  # noqa: BLE001
        logger.warning("scheme KB ingest failed (RAG path degraded): %s", e)


async def _warm_up() -> None:
    """RAG fix report 2026-10-29, Issue 14: the UI's first /api/query/stream after a start
    came back 503 — the read-only pool, the embedding model and the graph's checkpointer
    were all opened by that first question. Opened here, in the background, instead; each
    step is best-effort (the first question still opens what failed)."""
    from app import db, llm, pipeline_graph
    await _try("warm_readonly_pool", db.fetch_rows_readonly("SELECT 1 AS ok"))
    await _try("warm_embedding", llm.call_embedding(["warm up"]))
    await _try("warm_checkpointer", pipeline_graph._runtime())


async def _try(label: str, coro):
    """Run one startup step; log and continue if the remote box (10.48.242.4)
    is unreachable, so the server always comes up (degraded, see /health)."""
    try:
        await coro
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("startup step %r failed — continuing degraded: %s", label, e)
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    bad = insecure_secrets()
    if bad:
        msg = ("insecure configuration — rotate before real traffic: "
               + "; ".join(bad) + " (see docs/SECURITY.md)")
        # Loud, but never blocks boot — the deploy checklist owns enforcement.
        (logger.critical if settings.ENV != "dev" else logger.warning)(msg)
    # The re-ranker is always on (D-083); a missing key would quietly turn every
    # knowledge question back into vector order only, so say it loudly.
    if problem := reranker_problem():
        logger.error("qwen3-reranker not usable: %s — knowledge answers fall back to vector order "
                     "(set it in .env; see docs/AI_PIPELINE.md)", problem)

    await init_pool()                     # best-effort; rebuilds lazily on first query
    await init_client()
    await _try("qdrant", init_qdrant())
    load_annotations()                    # local YAML, no network
    load_entity_resolver()                # local YAML, no network
    from app.entity_resolver import load_village_names, load_geography_constituencies
    await _try("village_names", load_village_names())  # bare village names -> a place (2026-10-21)
    await _try("ac_names", load_geography_constituencies())  # urban constituencies no catalogue has (2026-10-30)
    from app import spelling
    spelling.warm()                       # misspelt names: build the gazetteer now, not on a user's turn
    await _try("app_schema", appdb.ensure_schema())     # app.* tables + seed users
    await _try("schema_catalog", schema_introspect.load())  # semantic.* -> SQL prompt
    from app import metric_catalog
    await _try("metric_catalog", metric_catalog.load())  # semantic.metric_definitions (D-071)
    await _try("scheme_years", pipeline.refresh_scheme_years())  # per-scheme FY coverage from megh_db
    asyncio.create_task(_ingest_kb_bg())
    _warm = asyncio.create_task(_warm_up())
    # LangGraph orchestrator (D-032, D-036), the only one. The checkpointer
    # opens lazily on the first request; this sweeps paused threads nobody
    # answered (the Session's own pending pause expires anyway).
    from app import pipeline_graph
    _sweep = asyncio.create_task(pipeline_graph.sweep_loop())
    # Conversation memory older than CONTEXT_MEMORY_RETENTION_DAYS: deleted now
    # and then once a day (RAG upgrade Phase 7).
    from app import conversation_memory
    _purge = asyncio.create_task(conversation_memory.purge_loop())
    # The SQL prompt's data figures (row counts, NULL counts, shares), live from megh_db
    # now and every 10 min; the typed defaults until the first read (2026-10-29).
    from app import data_facts
    _facts = asyncio.create_task(data_facts.refresh_loop())

    # KI-027: scheme years and the live schema / metric catalogues were read only at
    # startup, so a data load during the day (a new financial year, a new column, a
    # new measure) stayed invisible until a restart. Re-read every 30 min with the
    # same loaders; a failed read keeps the last good copy (each loader is best-effort).
    async def _catalog_refresh_loop() -> None:
        while True:
            await asyncio.sleep(1800)
            await _try("scheme_years", pipeline.refresh_scheme_years())
            await _try("schema_catalog", schema_introspect.load())
            await _try("metric_catalog", metric_catalog.load())
    _catalogs = asyncio.create_task(_catalog_refresh_loop())
    logger.info("nlp-service startup complete (see /health for component status)")
    yield
    _warm.cancel()
    _catalogs.cancel()
    _facts.cancel()
    _purge.cancel()
    _sweep.cancel()
    await pipeline_graph.close()
    await close_pool()
    await close_client()
    await close_qdrant()


# /docs, /redoc and /openapi.json are dev-only — they enumerate every route and
# schema for an attacker (A05). ENV=dev re-enables them.
_docs_kw = {} if settings.ENV == "dev" else dict(docs_url=None, redoc_url=None, openapi_url=None)
app = FastAPI(title=settings.APP_NAME, lifespan=lifespan, **_docs_kw)

# Middleware runs bottom-up on the way in: rate limit first, then (going out)
# body limit, then security headers outermost so every response — errors
# included — carries them.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(BodyLimitMiddleware)
if settings.CORS_ALLOW_ORIGINS.strip():
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ALLOW_ORIGINS.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Session-Id", "X-Request-ID"],
        max_age=600,
    )
app.add_middleware(SecurityHeadersMiddleware)


@app.exception_handler(RequestValidationError)
async def _invalid_request(request: Request, exc: RequestValidationError):
    """RAG fix report 2026-10-29, Issue 15: a 5,000-character question came back as a 422
    whose detail[].input held the whole question. The body never echoes the input (nor
    pydantic's ctx / url); an over-long question gets one plain sentence."""
    errors = exc.errors()
    if any(e.get("type") == "string_too_long" and tuple(e.get("loc") or ())[-1:] == ("question",) for e in errors):
        detail = f"Question is too long (max {settings.MAX_QUESTION_CHARS} characters)."
    else:
        detail = [{"loc": list(e.get("loc") or ()), "msg": e.get("msg"), "type": e.get("type")} for e in errors]
    resp = JSONResponse(status_code=422, content={"detail": detail})
    apply_security_headers(resp.headers, request.url.path)
    return resp


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    """Last resort: log the trace server-side, return a generic body with the
    request id so support can correlate without the client ever seeing internals
    (A05 — no stack traces / DB errors in responses)."""
    rid = getattr(request.state, "request_id", "-")
    logger.exception("unhandled error (request_id=%s) on %s", rid, request.url.path)
    resp = JSONResponse(status_code=500, content={"detail": "internal error", "request_id": rid})
    resp.headers["X-Request-ID"] = rid
    apply_security_headers(resp.headers, request.url.path)
    return resp


app.include_router(auth_router)
app.include_router(query_router)
app.include_router(rag_router)
app.include_router(history_router)
app.include_router(admin_router)
app.include_router(stats_router)
app.include_router(feedback_router)
# Full-duplex voice (2026-11-02): /ws/voice only; the pipeline is not touched (app/voice/__init__.py).
from app.voice.relay import router as voice_router  # noqa: E402
app.include_router(voice_router)


async def _privileged_view(authorization: str | None, x_metrics_token: str | None) -> bool:
    """True when the caller may see internal detail on /health and /metrics —
    a valid X-Metrics-Token, or an admin JWT."""
    if settings.METRICS_TOKEN and x_metrics_token == settings.METRICS_TOKEN:
        return True
    try:
        scope = await current_scope(authorization)
        return bool(scope.is_admin)
    except HTTPException:
        return False


@app.get("/health")
async def health(authorization: str | None = Header(default=None),
                 x_metrics_token: str | None = Header(default=None)):
    """ok when every dependency answers; degraded (with the failing component
    named) otherwise. Kept cheap — no model call.

    Anonymous callers get only {"status": ...} — which dependency is down, and
    whether secrets are unrotated, is internal detail (A01/A05). An admin JWT or
    the metrics token unlocks the full breakdown."""
    privileged = await _privileged_view(authorization, x_metrics_token)
    components: dict[str, str] = {}

    try:
        from app.db import fetch_rows

        await fetch_rows("SELECT 1")
        components["db"] = "ok"
    except Exception as e:  # noqa: BLE001
        components["db"] = f"error: {e}"

    try:
        qcount = await collection_count()
        components["qdrant"] = "ok" if qcount >= 0 else "collection missing"
    except Exception as e:  # noqa: BLE001 — health must never 500
        components["qdrant"] = f"error: {e}"

    # Core dependencies decide the status; the Redis L2 cache is best-effort and
    # reported for visibility only (in-process cache covers a Redis outage).
    status = "ok" if all(v == "ok" for v in components.values()) else "degraded"

    from app.cache import redis_healthy

    rh = await redis_healthy()
    if rh is not None:
        components["redis_cache"] = "ok" if rh else "unreachable (in-process cache active)"

    from app import pipeline_graph
    components["pipeline_graph"] = pipeline_graph.status()["checkpointer"]

    # Visibility only, like Redis: the guardrail model's recent failures (E2).
    from app import guardrails
    _recent = guardrails.outage_monitor.recent()
    components["guardrail_model"] = (f"failing ({_recent} in the last "
                                     f"{int(settings.GUARDRAIL_ALERT_WINDOW_SECONDS)}s)"
                                     if _recent else "ok")

    if not privileged:
        return {"status": status}

    payload = {"status": status, "components": components}
    bad = insecure_secrets()
    if bad:
        payload["insecure_config"] = bad
    return payload


@app.get("/metrics")
async def metrics_endpoint(authorization: str | None = Header(default=None),
                           x_metrics_token: str | None = Header(default=None)):
    """Plain-JSON operational counters — request volume by route, error counts,
    busy rejections, latency percentiles, and cache hit rate. Poll this to
    confirm the service is inside the 20-40 concurrent / 200 DAU budget.

    Gated (A01): send X-Metrics-Token (when METRICS_TOKEN is set) or an admin JWT."""
    if not await _privileged_view(authorization, x_metrics_token):
        raise HTTPException(401, "metrics require X-Metrics-Token or an admin token")
    from app.cache import metrics, response_cache
    from app.semantic_cache import semantic_cache
    from app.session_store import session_store

    from app import data_facts, guardrails, turn_trace

    return {
        **metrics.snapshot(),
        "response_cache": response_cache.stats(),
        "semantic_cache": semantic_cache.stats(),
        "sessions": session_store.stats(),
        # when the SQL prompt's data figures were last read from megh_db (app/data_facts.py)
        "data_facts": data_facts.status(),
        # live SQL outcomes and repairs on this worker, and the latest held-out
        # NL->SQL accuracy run (tests/nl2sql_eval)
        "accuracy": turn_trace.metrics(),
        # guardrail model failures on this worker: let through vs refused,
        # and the ALERT count (E2, 2026-10-29)
        "guardrail": guardrails.outage_monitor.snapshot(),
    }


# ── Static UI — the one service also serves the chat console and admin UI ─────
# Both are a React app (frontend/, D-038), built by `npm run build` into web/app:
# web/app/index.html is the chat console, web/app/admin.html the admin console,
# and their bundles load from /static/app/assets/ (content-hashed file names).
# The pages are served with no-cache (revalidate every load; the ETag keeps it a
# cheap 304), so a new build is picked up on the next load.
_NO_CACHE = {"Cache-Control": "no-cache"}
_UI_BUILD = _FRONTEND / "app"

if _FRONTEND.is_dir():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")

    # The portal landing page was removed on 2026-10-07; the bare address opens the chat.
    @app.get("/", include_in_schema=False)
    async def root():
        return RedirectResponse("/megh-chat", status_code=302)

    # Renamed /ai-query -> /megh-chat on 2026-10-04. The old path stays as a
    # redirect for officers' bookmarks.
    @app.get("/megh-chat", include_in_schema=False)
    async def megh_chat():
        f = _UI_BUILD / "index.html"
        return FileResponse(f, headers=_NO_CACHE) if f.exists() else JSONResponse(
            {"app": settings.APP_NAME, "error": "UI not built: run `npm run build` in frontend/"})

    @app.get("/ai-query", include_in_schema=False)
    async def ai_query():
        return RedirectResponse("/megh-chat", status_code=301)

    @app.get("/admin-ui", include_in_schema=False)
    async def admin_ui():
        f = _UI_BUILD / "admin.html"
        return FileResponse(f, headers=_NO_CACHE) if f.exists() else JSONResponse(
            {"error": "admin UI not built: run `npm run build` in frontend/"})
else:
    logger.warning("web/ not found at %s — API-only mode", _FRONTEND)
