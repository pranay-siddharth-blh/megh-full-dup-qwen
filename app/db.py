"""
megh_db access — read-only, pooled.

The connection itself should already be a SELECT-only role (megh_readonly, per
data/schema/schema_for_developers.md), but that is a second layer, not a substitute
for checking here: a generated query is untrusted input until proven otherwise.
"""
import contextvars
import logging
import time

import asyncpg
import sqlglot
from sqlglot import exp

from app.config import settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_pool_dsn: str | None = None

# openspec/changes/multi-tenant-rls-scheme-scaleout: the tenant context for
# the current request, if any. Set via set_tenant_context() (called once,
# at the top of a request handler — see app/routers/query.py) and consulted
# by every low-level helper below (fetch_rows/fetchrow/fetchval/execute/
# run_readonly) so a request's tenant identity reaches Postgres RLS
# policies without threading a parameter through every call site in
# app/pipeline.py, app/appdb.py, app/conversation_store.py, etc. A
# contextvar (not a global) so concurrent requests on the same event loop
# never see each other's tenant. None (the default, and always the value
# when TENANT_SCHEME_RLS_ENABLED is off) means "behave exactly as before
# this mechanism existed" — no transaction wrapping, no set_config call.
_current_tenant_ctx: "contextvars.ContextVar[tuple[int | None, bool] | None]" = (
    contextvars.ContextVar("current_tenant_ctx", default=None)
)


def set_tenant_context(tenant_id: int | None, *, bypass: bool = False):
    """Call once per request, before any DB work, with the caller's
    UserScope.tenant_id. Every fetch_rows/fetchrow/fetchval/execute/
    run_readonly call made anywhere during this request (any depth of
    function call, as long as it's on the same asyncio task) will then run
    inside a short transaction that first sets the `app.current_tenant_id`/
    `app.tenant_bypass` session GUCs the RLS policies in
    deploy/sql/03_tenant_scheme_rls.sql read — one connection acquired and
    released per query, never held across a request's non-DB work (LLM
    calls), unlike holding one connection open for the whole request would.
    `bypass=True` is for a verified super_admin only (resolved server-side
    — never pass a client-suppliable flag here) and should NOT be set for
    tenant_admin, which stays tenant-scoped on curated data by design (see
    proposal.md's "Why" section on the previous all-query-checks bypass).
    Returns a token for reset_tenant_context(); a no-op token (None) when
    TENANT_SCHEME_RLS_ENABLED is off, so callers don't need to branch on
    the flag themselves."""
    if not settings.TENANT_SCHEME_RLS_ENABLED:
        return None
    return _current_tenant_ctx.set((tenant_id, bypass))


def reset_tenant_context(token) -> None:
    """Always call in a `finally`, with whatever set_tenant_context()
    returned (including None) — resetting a None token is a no-op."""
    if token is not None:
        _current_tenant_ctx.reset(token)
# monotonic() timestamp before which ensure_pool() fast-fails instead of
# re-attempting a connect — set on any failed attempt (startup or lazy). Without
# this, every DB-touching call (including /health) pays the full
# DB_POOL_TIMEOUT on its own fresh asyncpg.create_pool() while megh_db is down.
_pool_retry_after: float = 0.0


class DBUnavailableError(ConnectionError):
    """megh_db is known-down and still within its retry cooldown."""

# Node types that mean "this touches something other than reading rows" —
# checked anywhere in the parsed tree, not just at the root. A root-type
# check alone ("is the statement a Select?") is not enough: Postgres allows
# data-modifying CTEs — "WITH deleted AS (DELETE FROM t RETURNING *) SELECT
# * FROM deleted" parses with root type Select but contains a real DELETE.
# Command is sqlglot's catch-all for syntax it doesn't have a dedicated node
# for (e.g. VACUUM, EXPLAIN) — treated as unsafe by default rather than
# silently passed through, since an unrecognised construct can't be proven
# read-only.
_WRITE_NODE_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create,
    exp.TruncateTable, exp.Grant, exp.Revoke, exp.Merge, exp.Command,
)


class UnsafeSQLError(ValueError):
    """Raised when generated SQL fails the read-only / single-statement check."""


async def _connect_pool() -> asyncpg.Pool:
    dsn = _pool_dsn or settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.create_pool(
        dsn,
        min_size=settings.DB_POOL_MIN_SIZE,
        max_size=settings.DB_POOL_MAX_SIZE,
        timeout=settings.DB_POOL_TIMEOUT,
        command_timeout=settings.SQL_EXECUTION_TIMEOUT_MS / 1000,
    )


async def init_pool() -> None:
    """Build the megh_db pool. Best-effort: if the DB host is unreachable at
    startup (the 10.48.242.4 box flaps), log and carry on with `_pool = None` —
    the server still boots (degraded), and `ensure_pool()` rebuilds it lazily on
    the first query once the host is back (subject to the same retry cooldown)."""
    global _pool, _pool_dsn, _pool_retry_after
    _pool_dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
    try:
        _pool = await _connect_pool()
        logger.info(
            "megh_db pool ready (min=%d max=%d)",
            settings.DB_POOL_MIN_SIZE, settings.DB_POOL_MAX_SIZE,
        )
    except Exception as e:  # noqa: BLE001
        _pool = None
        _pool_retry_after = time.monotonic() + settings.DB_POOL_RETRY_COOLDOWN_SECONDS
        logger.warning("megh_db pool init failed — starting degraded, will retry on first query: %s", e)


async def ensure_pool() -> asyncpg.Pool:
    """Return the live pool, building it now if startup couldn't. Raises
    DBUnavailableError immediately (no connection attempt) if a prior attempt
    failed within the last DB_POOL_RETRY_COOLDOWN_SECONDS — otherwise every
    caller (including /health, once per request) would each pay the full
    DB_POOL_TIMEOUT trying to reach a host already known to be down."""
    global _pool, _pool_retry_after
    if _pool is not None:
        return _pool
    now = time.monotonic()
    if now < _pool_retry_after:
        raise DBUnavailableError(
            f"megh_db unreachable — retrying in {_pool_retry_after - now:.1f}s"
        )
    try:
        _pool = await _connect_pool()
    except Exception as e:
        _pool_retry_after = time.monotonic() + settings.DB_POOL_RETRY_COOLDOWN_SECONDS
        # Found+fixed 2026-09-18, live-tested against a real running server:
        # a genuinely fresh connection attempt that fails here (the common
        # case — most callers arrive well after any prior cooldown expired,
        # not within the fast-fail window above) used to re-raise the raw
        # underlying exception (OSError, an asyncpg connect error, ...) —
        # a different type every time depending on exactly how the network
        # failed, which app/main.py's DBUnavailableError-specific exception
        # handler could never catch. Normalizing to DBUnavailableError here
        # too (not just the fast-fail branch above) means EVERY DB-
        # unreachable failure, fast-failed or freshly attempted, presents
        # the same type to callers — a graceful 503 instead of a bare 500,
        # regardless of which of the two paths produced it.
        raise DBUnavailableError(f"megh_db unreachable: {e}") from e
    logger.info("megh_db pool ready (lazy) (min=%d max=%d)",
                settings.DB_POOL_MIN_SIZE, settings.DB_POOL_MAX_SIZE)
    return _pool


async def close_pool() -> None:
    if _pool is not None:
        await _pool.close()


def _assert_safe(sql: str) -> exp.Select:
    """PRD §5.11: parse to an AST (sqlglot, not a regex — a keyword-substring
    check flags a village or column merely named "Grantville"/"Dropati", and
    misses a write hidden inside a CTE) and enforce read-only, single-
    statement. Returns the parsed statement so run_readonly() can reuse it
    for the LIMIT check below instead of parsing twice."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise UnsafeSQLError(f"query failed to parse: {e}") from e
    if not statements:
        raise UnsafeSQLError("empty query")
    if len(statements) != 1:
        raise UnsafeSQLError("multiple statements are not allowed")

    stmt = statements[0]
    if not isinstance(stmt, exp.Select):
        raise UnsafeSQLError(f"query must be a read-only SELECT, got {type(stmt).__name__}")
    written = stmt.find_all(*_WRITE_NODE_TYPES)
    hit = next(written, None)
    if hit is not None:
        raise UnsafeSQLError(
            f"query contains a write/DDL construct ({type(hit).__name__}), "
            "including one nested inside a CTE"
        )
    if stmt.args.get("into"):
        raise UnsafeSQLError("SELECT INTO is not allowed — it creates a table")
    if any(sel.args.get("locks") for sel in stmt.find_all(exp.Select)):
        raise UnsafeSQLError("row-locking clauses (FOR UPDATE / FOR SHARE) are not allowed")
    return stmt


async def _apply_tenant_ctx(conn: asyncpg.Connection) -> None:
    """Set this request's tenant GUCs on `conn` — must run inside the same
    transaction as the query that follows, since both set_config() calls
    use is_local=true (transaction-scoped, auto-reverts) so a pooled
    connection never leaks one request's tenant identity to the next
    borrower. tenant_id="" (unset/anonymous) reads back as NULL via
    current_setting(..., true) in the RLS policy, which denies every
    tenant-owned row — correct default-deny for a request with no
    resolved tenant, rather than accidentally matching tenant_id=NULL rows."""
    tenant_id, bypass = _current_tenant_ctx.get()
    await conn.execute(
        "SELECT set_config('app.current_tenant_id', $1, true), "
        "set_config('app.tenant_bypass', $2, true)",
        "" if tenant_id is None else str(tenant_id),
        "on" if bypass else "off",
    )


async def fetch_rows(sql: str, params: list | None = None) -> list[dict]:
    """For our own hardcoded, parametrized queries (entity resolution) — trusted
    SQL text, untrusted values only, safe via asyncpg's parameter binding. Not
    for LLM-generated SQL — use run_readonly() for that."""
    pool = await ensure_pool()
    ctx = _current_tenant_ctx.get()
    async with pool.acquire() as conn:
        if ctx is not None:
            async with conn.transaction():
                await _apply_tenant_ctx(conn)
                rows = await conn.fetch(sql, *(params or []))
        else:
            rows = await conn.fetch(sql, *(params or []))
    return [dict(r) for r in rows]


async def fetchrow(sql: str, params: list | None = None) -> dict | None:
    pool = await ensure_pool()
    ctx = _current_tenant_ctx.get()
    async with pool.acquire() as conn:
        if ctx is not None:
            async with conn.transaction():
                await _apply_tenant_ctx(conn)
                row = await conn.fetchrow(sql, *(params or []))
        else:
            row = await conn.fetchrow(sql, *(params or []))
    return dict(row) if row else None


async def fetchval(sql: str, params: list | None = None):
    pool = await ensure_pool()
    ctx = _current_tenant_ctx.get()
    async with pool.acquire() as conn:
        if ctx is not None:
            async with conn.transaction():
                await _apply_tenant_ctx(conn)
                return await conn.fetchval(sql, *(params or []))
        return await conn.fetchval(sql, *(params or []))


async def execute(sql: str, params: list | None = None) -> str:
    """Run one trusted, parametrised write/DDL statement (our own `app.*` SQL —
    NEVER model-generated text). Values are still bound, never interpolated."""
    pool = await ensure_pool()
    ctx = _current_tenant_ctx.get()
    async with pool.acquire() as conn:
        if ctx is not None:
            async with conn.transaction():
                await _apply_tenant_ctx(conn)
                return await conn.execute(sql, *(params or []))
        return await conn.execute(sql, *(params or []))


async def execute_script(sql: str) -> None:
    """Run a multi-statement DDL script (schema bootstrap only, no parameters)."""
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        await conn.execute(sql)


async def run_readonly(sql: str) -> list[dict]:
    """Validate, then execute a single read-only statement against megh_db.

    This is the LLM-generated-SQL execution point — the actual surface
    curated-data RLS (deploy/sql/03_tenant_scheme_rls.sql) is meant to
    guard, so it's the one place besides the app-schema helpers above where
    the tenant GUCs must be set before the query runs, in the same
    transaction (see _apply_tenant_ctx's is_local=true note)."""
    stmt = _assert_safe(sql)
    pool = await ensure_pool()
    ctx = _current_tenant_ctx.get()

    # AST-based presence check, not a substring scan: a naive `"limit" in
    # sql.lower()` false-negatives on a query with no real LIMIT clause that
    # merely mentions the word elsewhere (a column alias, a WHERE literal —
    # e.g. a village or scheme name containing "limit"), skipping the
    # safety cap entirely. `stmt.args["limit"]` reflects only the outermost
    # SELECT's own clause, ignoring anything inside a CTE/subquery.
    limited = sql.strip().rstrip(";")
    if stmt.args.get("limit") is None:
        limited = f"{limited} LIMIT {settings.SQL_MAX_RESULT_ROWS}"

    async with pool.acquire() as conn:
        if ctx is not None:
            async with conn.transaction():
                await _apply_tenant_ctx(conn)
                rows = await conn.fetch(limited)
        else:
            rows = await conn.fetch(limited)
    return [dict(r) for r in rows]
