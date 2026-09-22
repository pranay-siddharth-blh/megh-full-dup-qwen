import asyncio
import logging

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import appdb, join_graph, pipeline, schema_introspect
from app.annotations import load_all as load_annotations
from app.config import insecure_secrets, settings
from app.db import DBUnavailableError, close_pool, init_pool, reset_tenant_context, set_tenant_context
from app.deps import current_scope
from app.entity_resolver import load_all as load_entity_resolver
from app.entity_resolver import load_embeddings as load_entity_resolver_embeddings
from app.kb_ingest import ingest_kb
from app.scheme_registry import load_all as load_scheme_registry
from app.scheme_registry import sync_to_db as sync_scheme_registry_to_db
from app.scheme_registry import warn_if_scheme_count_high
from app.llm import close_client, init_client
from app.middleware.limits import BodyLimitMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware, apply_security_headers
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.history import router as history_router
from app.routers.query import router as query_router
from app.routers.rag import router as rag_router
from app.vectorstore import close_pgvector, collection_count, init_pgvector

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("nlp_service")

# app/main.py -> repo root -> web/
_FRONTEND = Path(__file__).resolve().parents[1] / "web"


async def _ingest_kb_bg():
    """KB ingest runs in the background so a cold pgvector connection / slow
    embed batch never blocks the service from accepting traffic."""
    try:
        result = await ingest_kb()
        logger.info("scheme KB: %s", result)
    except Exception as e:  # noqa: BLE001
        logger.warning("scheme KB ingest failed (RAG path degraded): %s", e)


async def _build_join_graph():
    join_graph.build()  # curated YAML + schema_introspect.live_fks() cache


async def _sync_scheme_entitlements():
    """openspec/changes/multi-tenant-rls-scheme-scaleout: upsert
    app.schemes from the just-loaded registry, and (only on a tenant with
    zero existing grants) seed the default tenant with every currently
    registered scheme — keeps today's single-tenant deployment's effective
    permissions unchanged the first time this runs. Must run after both
    load_scheme_registry() (in-memory registry) and appdb.ensure_schema()
    (app.schemes/app.tenant_schemes tables exist)."""
    tid = await appdb.get_default_tenant_id()
    await sync_scheme_registry_to_db(default_tenant_id=tid)


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

    await init_pool()                     # best-effort; rebuilds lazily on first query
    await init_client()
    await _try("vectorstore", init_pgvector())
    load_annotations()                    # local YAML, no network
    load_entity_resolver()                # local YAML, no network
    # First run downloads the ONNX model (~130 MB); on a box with restricted
    # egress the HuggingFace Hub metadata check hangs rather than failing
    # fast (confirmed: >45s with no error), so this is the one _try step
    # that needs its own timeout to actually honor "never blocks boot".
    await _try(
        "entity_resolver_embeddings",
        asyncio.wait_for(load_entity_resolver_embeddings(),
                          timeout=settings.ENTITY_RESOLVER_EMBEDDING_LOAD_TIMEOUT_SECONDS),
    )
    load_scheme_registry()                # local YAML, no network
    warn_if_scheme_count_high()           # openspec/changes/multi-tenant-rls-scheme-scaleout
    # openspec/changes/multi-tenant-rls-scheme-scaleout group 2.2: startup has
    # no request/scope, so there is no tenant to derive app.db.set_tenant_context()
    # from — but ensure_schema()'s user-seed and _sync_scheme_entitlements()'s
    # default-tenant grant-seed both write real tenant_id rows into app.users /
    # app.tenant_schemes. Same bypass reasoning as app/routers/auth.py's
    # login()/bootstrap(): server-side bookkeeping with no client input, not a
    # tenant-scoped read. Without this, once Section B RLS is enabled, first-run
    # seeding would silently insert nothing (or raise) instead of seeding.
    _startup_tenant_tok = set_tenant_context(None, bypass=True)
    try:
        await _try("app_schema", appdb.ensure_schema())     # app.* tables + seed users
        await _try("scheme_entitlements", _sync_scheme_entitlements())
    finally:
        reset_tenant_context(_startup_tenant_tok)
    await _try("schema_catalog", schema_introspect.load())  # semantic.* -> SQL prompt
    await _try("join_graph", _build_join_graph())
    await _try("scheme_years", pipeline.refresh_scheme_years())  # per-scheme FY coverage from megh_db
    asyncio.create_task(_ingest_kb_bg())
    logger.info("nlp-service startup complete (see /health for component status)")
    yield
    await close_pool()
    await close_client()
    await close_pgvector()


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


@app.exception_handler(DBUnavailableError)
async def _db_unavailable(request: Request, exc: DBUnavailableError):
    """Found+fixed 2026-09-18, live-tested by actually running the server
    against the real (intermittently unreachable) DATABASE_URL: this is a
    KNOWN, gracefully-detected condition — app/db.py's retry-cooldown
    mechanism already knows exactly why the request failed and how long
    until it's worth retrying — but without this handler it fell through
    to the generic `_unhandled` handler below and looked identical to a
    genuine crash: a bare 500 with no Retry-After, indistinguishable from
    an actual bug. Registering a handler for this specific exception type
    takes precedence over the generic `Exception` one below regardless of
    definition order (Starlette resolves by exact type first, then MRO),
    so this fires whenever DBUnavailableError is the exception — including
    when it's raised during dependency resolution (e.g.
    app/deps.py::current_scope's DB lookup), which never reaches an
    individual route's own try/except at all, only a registered handler."""
    rid = getattr(request.state, "request_id", "-")
    logger.warning("DB unavailable (request_id=%s) on %s: %s", rid, request.url.path, exc)
    resp = JSONResponse(
        status_code=503,
        content={"detail": "The database is temporarily unreachable. Please retry shortly.",
                 "request_id": rid},
        headers={"Retry-After": str(settings.DB_POOL_RETRY_COOLDOWN_SECONDS)},
    )
    resp.headers["X-Request-ID"] = rid
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
        components["vectorstore"] = "ok" if qcount >= 0 else "table missing"
    except Exception as e:  # noqa: BLE001 — health must never 500
        components["vectorstore"] = f"error: {e}"

    # Core dependencies decide the status; the Redis L2 cache is best-effort and
    # reported for visibility only (in-process cache covers a Redis outage).
    status = "ok" if all(v == "ok" for v in components.values()) else "degraded"

    from app.cache import redis_healthy

    rh = await redis_healthy()
    if rh is not None:
        components["redis_cache"] = "ok" if rh else "unreachable (in-process cache active)"

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

    return {
        **metrics.snapshot(),
        "response_cache": response_cache.stats(),
        "semantic_cache": semantic_cache.stats(),
        "sessions": session_store.stats(),
    }


# ── Static UI — the one service also serves the portal + chat console ─────────
if _FRONTEND.is_dir():
    app.mount("/static", StaticFiles(directory=str(_FRONTEND)), name="static")

    @app.get("/", include_in_schema=False)
    async def portal():
        f = _FRONTEND / "Meghalaya_UnifiedPortal_UI.html"
        return FileResponse(f) if f.exists() else JSONResponse({"app": settings.APP_NAME})

    @app.get("/ai-query", include_in_schema=False)
    async def ai_query():
        f = _FRONTEND / "ai_query.html"
        return FileResponse(f) if f.exists() else JSONResponse({"app": settings.APP_NAME})

    @app.get("/admin-ui", include_in_schema=False)
    async def admin_ui():
        f = _FRONTEND / "admin.html"
        return FileResponse(f) if f.exists() else JSONResponse({"error": "admin.html missing"})
else:
    logger.warning("web/ not found at %s — API-only mode", _FRONTEND)
