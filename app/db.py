"""
megh_db access — two pools, three when the chatbot login is set.

- The app pool (DATABASE_URL, megh_app — deploy/sql/01): the service's own
  app.* writes and our trusted, parametrised queries (fetch_rows / fetchrow /
  fetchval / execute).
- The read-only pool (READONLY_DATABASE_URL, megh_readonly — deploy/sql/03):
  model-generated SQL only (run_readonly). SELECT-only grants on curated and
  semantic, default_transaction_read_only and search_path = curated, semantic on
  every connection, and each statement inside a READ ONLY transaction.
  Also our catalog reads and, with the chatbot login, the type description of a
  generated query (parse only, never executed).
- The chatbot pool (CHATBOT_DATABASE_URL, megh_chatbot — DB team 2026-10-27,
  D-073): when set, every generated query runs as
  semantic.run_query(sql, max_rows, max_cost) — the database plans it (fact
  row joins, cost) and runs it with megh_readonly's rights; the login can do
  nothing else.

The database role is the security boundary; the SQLGlot check in
app/sql_guard.py is the layer in front of it: a generated query is untrusted
input until proven otherwise.
"""
import asyncio
import datetime
import json
import logging
from decimal import Decimal

import asyncpg

from app.config import settings
from app.sql_guard import READONLY_SCHEMAS, UnsafeSQLError, prepare_readonly

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_pool_dsn: str | None = None
_ro_pool: asyncpg.Pool | None = None
_chat_pool: asyncpg.Pool | None = None

# UnsafeSQLError lives in app/sql_guard.py (the SQLGlot check) and is
# re-exported here, where callers have always imported it from.
__all__ = ["UnsafeSQLError", "DatabaseUnavailableError", "ReadonlyRoleError"]


class DatabaseUnavailableError(RuntimeError):
    """megh_db could not be reached (VPN / network drop, connection refused or
    lost, server out of connection slots). Not a problem with the question or
    its SQL — the caller must say "try again", never repair the SQL or answer
    from the reference documents instead (KI-025)."""


class QueryTooHeavyError(TimeoutError):
    """megh_readonly's server limits stopped a generated query: statement_timeout
    (57014) or temp_file_limit (53400, the 1 GB cap) — DB team, 2026-10-27. A
    TimeoutError like our own command_timeout, so it takes the same road: one
    more repair round with the reason, then the router's 504 "try a narrower
    question" instead of the "couldn't build a working query" fallback."""


# 57014 query_canceled (statement_timeout), 53400 configuration_limit_exceeded
# (temp_file_limit) — the codes the DB team says mean "ask the user to narrow".
_TOO_HEAVY_SQLSTATES = frozenset({"57014", "53400"})


class ReadonlyRoleError(DatabaseUnavailableError):
    """The read-only pool's login is a superuser and READONLY_DB_ALLOW_SUPERUSER
    is off. A configuration fault, not the question's: like a lost connection
    it is never sent to SQL repair."""


# asyncpg's connection-class failures. A slow query's command_timeout
# (asyncio.TimeoutError) is deliberately NOT here: it keeps its own 504 path.
_CONNECTION_ERRORS: tuple[type[BaseException], ...] = (
    OSError,                       # ConnectionRefused/Reset, WinError 121 "semaphore timeout"
    asyncpg.exceptions.PostgresConnectionError,
    asyncpg.exceptions.ConnectionDoesNotExistError,
    asyncpg.exceptions.InterfaceError,
    asyncpg.exceptions.TooManyConnectionsError,
    asyncpg.exceptions.CannotConnectNowError,
)


def is_connection_error(e: BaseException) -> bool:
    """True for a failure to reach / stay connected to megh_db, anywhere in the
    exception's cause chain."""
    seen = 0
    while e is not None and seen < 6:
        # TimeoutError is an OSError subclass (and IS asyncio.TimeoutError on
        # 3.11): a slow query's timeout keeps its own 504 path, so it is excluded.
        if isinstance(e, DatabaseUnavailableError) or (
                isinstance(e, _CONNECTION_ERRORS) and not isinstance(e, (UnsafeSQLError, TimeoutError))):
            return True
        e = e.__cause__ or e.__context__
        seen += 1
    return False


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def application_name(pool: str) -> str | None:
    """'megh-chatbot-v2:readonly' — which build and which pool a megh_db session
    belongs to, for the DB team (pg_stat_activity). None when unset."""
    base = (settings.DB_APPLICATION_NAME or "").strip()
    return f"{base}:{pool}"[:63] if base else None  # PostgreSQL keeps 63 bytes


def _named(pool: str, server_settings: dict | None = None) -> dict:
    out = dict(server_settings or {})
    name = application_name(pool)
    if name:
        out["application_name"] = name
    return out


async def _create_app_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn,
        min_size=settings.DB_POOL_MIN_SIZE,
        max_size=settings.DB_POOL_MAX_SIZE,
        timeout=settings.DB_POOL_TIMEOUT,
        max_inactive_connection_lifetime=settings.DB_POOL_IDLE_SECONDS,
        command_timeout=settings.SQL_EXECUTION_TIMEOUT_MS / 1000,
        server_settings=_named("app"),
    )


# Set on every read-only connection at login, so even a statement that somehow
# ran outside run_readonly's READ ONLY transaction could not write, and an
# unqualified table name resolves only in curated / semantic.
_READONLY_SERVER_SETTINGS = {
    "default_transaction_read_only": "on",
    "search_path": ", ".join(READONLY_SCHEMAS),
}

# Objects in curated/semantic the login could still write — expected 0.
_WRITABLE_SQL = """
SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY($1::text[]) AND c.relkind IN ('r', 'v', 'm', 'p', 'f')
  AND (has_table_privilege(c.oid, 'INSERT') OR has_table_privilege(c.oid, 'UPDATE')
       OR has_table_privilege(c.oid, 'DELETE') OR has_table_privilege(c.oid, 'TRUNCATE'))
"""


async def _check_readonly_login(pool: asyncpg.Pool, label: str = "read-only",
                                min_size: int | None = None, max_size: int | None = None) -> None:
    """Refuse a superuser login on the read-only pool (unless explicitly allowed
    for dev); warn when the role has write grants on the scheme data."""
    async with pool.acquire() as conn:
        role = await conn.fetchrow(
            "SELECT current_user AS who, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")
        writable = await conn.fetchval(_WRITABLE_SQL, list(READONLY_SCHEMAS))
    who = role["who"] if role else "?"
    if role and (role["rolsuper"] or role["rolbypassrls"]):
        if not settings.READONLY_DB_ALLOW_SUPERUSER:
            raise ReadonlyRoleError(
                f"{label} pool logged in as '{who}', a superuser — refusing to run generated SQL. "
                "Set READONLY_DATABASE_URL to the megh_readonly role (deploy/sql/03_readonly_role.sql).")
        logger.critical("read-only pool logged in as superuser '%s' (READONLY_DB_ALLOW_SUPERUSER) — "
                        "dev only; generated SQL is held only by READ ONLY transactions", who)
    if writable:
        logger.warning("read-only pool role '%s' holds write grants on %d curated/semantic object(s) — "
                       "READ ONLY transactions still block them; revoke them (deploy/sql/03)", who, writable)
    logger.info("megh_db %s pool ready as '%s' (min=%d max=%d)", label, who,
                settings.READONLY_DB_POOL_MIN_SIZE if min_size is None else min_size,
                settings.READONLY_DB_POOL_MAX_SIZE if max_size is None else max_size)


async def _create_readonly_pool() -> asyncpg.Pool:
    url = settings.READONLY_DATABASE_URL
    if not url:
        logger.critical("READONLY_DATABASE_URL is not set — generated SQL shares the app login "
                        "(DATABASE_URL); set it to the megh_readonly role (deploy/sql/03_readonly_role.sql)")
        url = settings.DATABASE_URL
    pool = await asyncpg.create_pool(
        _dsn(url),
        min_size=settings.READONLY_DB_POOL_MIN_SIZE,
        max_size=settings.READONLY_DB_POOL_MAX_SIZE,
        timeout=settings.DB_POOL_TIMEOUT,
        max_inactive_connection_lifetime=settings.DB_POOL_IDLE_SECONDS,
        command_timeout=settings.SQL_EXECUTION_TIMEOUT_MS / 1000,
        server_settings=_named("readonly", _READONLY_SERVER_SETTINGS),
    )
    try:
        await _check_readonly_login(pool)
    except BaseException:
        await pool.close()
        raise
    return pool


async def _create_chatbot_pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(
        _dsn(settings.CHATBOT_DATABASE_URL),
        min_size=settings.CHATBOT_DB_POOL_MIN_SIZE,
        max_size=settings.CHATBOT_DB_POOL_MAX_SIZE,
        timeout=settings.DB_POOL_TIMEOUT,
        max_inactive_connection_lifetime=settings.DB_POOL_IDLE_SECONDS,
        command_timeout=settings.SQL_EXECUTION_TIMEOUT_MS / 1000,
        server_settings=_named("chatbot", _READONLY_SERVER_SETTINGS),
    )
    try:
        await _check_readonly_login(pool, "chatbot", settings.CHATBOT_DB_POOL_MIN_SIZE,
                                    settings.CHATBOT_DB_POOL_MAX_SIZE)
    except BaseException:
        await pool.close()
        raise
    return pool


async def init_pool() -> None:
    """Build both megh_db pools. Best-effort: if the DB host is unreachable at
    startup (the 10.48.242.4 box flaps), log and carry on with the pool None —
    the server still boots (degraded), and ensure_pool() / ensure_readonly_pool()
    rebuild it lazily on the first query once the host is back."""
    global _pool, _pool_dsn, _ro_pool, _chat_pool
    _pool_dsn = _dsn(settings.DATABASE_URL)
    try:
        _pool = await _create_app_pool(_pool_dsn)
        logger.info(
            "megh_db pool ready (min=%d max=%d)",
            settings.DB_POOL_MIN_SIZE, settings.DB_POOL_MAX_SIZE,
        )
    except Exception as e:  # noqa: BLE001
        _pool = None
        logger.warning("megh_db pool init failed — starting degraded, will retry on first query: %s", e)
    try:
        _ro_pool = await _create_readonly_pool()
    except ReadonlyRoleError as e:
        _ro_pool = None
        logger.critical("%s", e)
    except Exception as e:  # noqa: BLE001
        _ro_pool = None
        logger.warning("megh_db read-only pool init failed — will retry on first generated query: %s", e)
    if settings.CHATBOT_DATABASE_URL:
        try:
            _chat_pool = await _create_chatbot_pool()
        except ReadonlyRoleError as e:
            _chat_pool = None
            logger.critical("%s", e)
        except Exception as e:  # noqa: BLE001
            _chat_pool = None
            logger.warning("megh_db chatbot pool init failed — will retry on first generated query: %s", e)


async def ensure_pool() -> asyncpg.Pool:
    """Return the live app pool, building it now if startup couldn't. Raises if
    the DB is still unreachable."""
    global _pool
    if _pool is not None:
        return _pool
    _pool = await _create_app_pool(_pool_dsn or _dsn(settings.DATABASE_URL))
    logger.info("megh_db pool ready (lazy) (min=%d max=%d)",
                settings.DB_POOL_MIN_SIZE, settings.DB_POOL_MAX_SIZE)
    return _pool


async def ensure_readonly_pool() -> asyncpg.Pool:
    """Return the live read-only pool, building it now if startup couldn't.
    Raises if the DB is unreachable or the login is refused (ReadonlyRoleError)."""
    global _ro_pool
    if _ro_pool is None:
        _ro_pool = await _create_readonly_pool()
    return _ro_pool


async def ensure_chatbot_pool() -> asyncpg.Pool:
    """Return the live megh_chatbot pool, building it now if startup couldn't."""
    global _chat_pool
    if _chat_pool is None:
        _chat_pool = await _create_chatbot_pool()
    return _chat_pool


async def close_pool() -> None:
    global _pool, _ro_pool, _chat_pool
    for pool in (_pool, _ro_pool, _chat_pool):
        if pool is not None:
            await pool.close()
    _pool = _ro_pool = _chat_pool = None


async def fetch_rows(sql: str, params: list | None = None) -> list[dict]:
    """For our own hardcoded, parametrized queries (entity resolution) — trusted
    SQL text, untrusted values only, safe via asyncpg's parameter binding. Not
    for LLM-generated SQL — use run_readonly() for that."""
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *(params or []))
    return [dict(r) for r in rows]


async def fetchrow(sql: str, params: list | None = None) -> dict | None:
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, *(params or []))
    return dict(row) if row else None


async def fetchval(sql: str, params: list | None = None):
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(sql, *(params or []))


async def execute(sql: str, params: list | None = None) -> str:
    """Run one trusted, parametrised write/DDL statement (our own `app.*` SQL —
    NEVER model-generated text). Values are still bound, never interpolated."""
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        return await conn.execute(sql, *(params or []))


async def execute_script(sql: str) -> None:
    """Run a multi-statement DDL script (schema bootstrap only, no parameters)."""
    pool = await ensure_pool()
    async with pool.acquire() as conn:
        await conn.execute(sql)


async def fetch_rows_readonly(sql: str, params: list | None = None) -> list[dict]:
    """Our own trusted, parameter-bound catalog reads (schema_introspect) on the
    read-only pool, in a READ ONLY transaction — so the SQL prompt is built from
    what megh_readonly can see: information_schema hides the columns it may not
    select (member_id, account_no, scheme_specific). Ingestion team, 2026-10-26.
    Not for model text (use run_readonly)."""
    pool = await ensure_readonly_pool()
    async with pool.acquire() as conn:
        async with conn.transaction(readonly=True):
            rows = await conn.fetch(sql, *(params or []))
    return [dict(r) for r in rows]


async def precheck_readonly(sql: str) -> str | None:
    """semantic.check_query's verdict on a generated query, BEFORE it runs: the
    'row_join' detail when the plan joins two fact tables row by row (the join
    that inflated person-days 456 times), else None. Fail-open — never builds a
    pool (offline / before startup: no check), and any failure of the check
    itself (missing function, timeout, lost connection) returns None so the
    query runs exactly as it would have. Planning errors are left to the real
    execution, whose error goes to repair."""
    if not settings.SQL_DB_PRECHECK or _ro_pool is None or settings.CHATBOT_DATABASE_URL:
        return None  # run_query (chatbot login) makes the same check itself
    try:
        limited = prepare_readonly(sql, settings.SQL_MAX_RESULT_ROWS)
        async with _ro_pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                rows = await conn.fetch(
                    "SELECT check_name, detail FROM semantic.check_query($1)", limited, timeout=5)
    except Exception as e:  # noqa: BLE001 — advisory check only
        logger.info("semantic.check_query skipped (%s: %s)", type(e).__name__, str(e)[:160])
        return None
    for r in rows:
        if r["check_name"] == "row_join":
            return str(r["detail"] or "two fact tables joined row by row")
    return None


async def run_readonly(sql: str) -> list[dict]:
    """Validate (SQLGlot — app/sql_guard.py: one SELECT, curated/semantic only),
    bound at SQL_MAX_RESULT_ROWS, then execute on the read-only pool inside a
    READ ONLY transaction (BEGIN READ ONLY, the same as SET TRANSACTION READ ONLY)."""
    limited = prepare_readonly(sql, settings.SQL_MAX_RESULT_ROWS)
    if settings.CHATBOT_DATABASE_URL:
        return await _run_via_run_query(limited)
    pool = await ensure_readonly_pool()

    try:
        async with pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                rows = await conn.fetch(limited)
    except asyncpg.exceptions.PostgresError as e:
        if getattr(e, "sqlstate", None) in _TOO_HEAVY_SQLSTATES:
            raise QueryTooHeavyError(
                f"the database stopped this query as too heavy ({e.sqlstate}: {e}); "
                "make it cheaper — aggregate earlier, filter by year / place, fewer joins") from e
        raise
    return [dict(r) for r in rows]


# ── Generated SQL through semantic.run_query (megh_chatbot, D-073) ────────────

class RowJoinRefusedError(ValueError):
    """run_query refused the plan: two fact tables (or one with itself) joined
    row by row — the join that multiplied person-days 456 times. A ValueError,
    so it goes to repair with the reason, like our own fan-out guard."""


class RunQueryError(RuntimeError):
    """run_query reported a planning / execution error. str() is PostgreSQL's
    own message, exactly what the repair prompt saw from asyncpg before."""

    def __init__(self, message: str, sqlstate: str | None = None):
        super().__init__(message)
        self.sqlstate = sqlstate


# run_query sends rows as JSON, so every value loses its PostgreSQL type (a
# SUM(bigint) is numeric -> Decimal through asyncpg, but a bare JSON 677731).
# The answer checks treat Decimal, int and float differently (c12 number forms,
# c13 rounding), so each value is given back the Python type asyncpg returns
# for its column: the types come from describing the statement on the
# read-only login (parse only — it never runs), or from run_query's own
# "types" list if the DB team adds one.
_INT_TYPES = frozenset({"int2", "int4", "int8", "oid", "smallint", "integer", "bigint"})
_FLOAT_TYPES = frozenset({"float4", "float8", "real", "double precision"})
_NUMERIC_TYPES = frozenset({"numeric", "decimal"})
_JSON_TYPES = frozenset({"json", "jsonb"})


def _scalar(type_name: str, v):
    if v is None:
        return None
    if type_name in _NUMERIC_TYPES:
        return v if isinstance(v, Decimal) else Decimal(str(v))
    if type_name in _INT_TYPES:
        return int(v)
    if type_name in _FLOAT_TYPES:
        return float(v)
    if type_name == "date":
        return datetime.date.fromisoformat(v)
    if type_name in ("timestamp", "timestamptz", "timestamp without time zone",
                     "timestamp with time zone"):
        return datetime.datetime.fromisoformat(v)
    if type_name in _JSON_TYPES:
        return json.dumps(v)  # asyncpg hands json columns over as text
    return v


def _typed(type_name: str | None, v):
    if type_name is None or v is None:
        return v
    if isinstance(v, list):
        # arrays: run_query's "types" say numeric[] / text[]; asyncpg's describe says _numeric
        if type_name.endswith("[]"):
            return [_typed(type_name[:-2], x) for x in v]
        if type_name.startswith("_"):
            return [_typed(type_name[1:], x) for x in v]
    return _scalar(type_name, v)


async def _describe_types(limited: str) -> list[str] | None:
    """The result columns' PostgreSQL type names, by parsing the statement on the
    read-only login (prepare = parse + describe; nothing is executed). None if
    it can't be described — the values are then left as JSON gave them."""
    try:
        pool = await ensure_readonly_pool()
        async with pool.acquire() as conn:
            async with conn.transaction(readonly=True):
                stmt = await conn.prepare(limited)
                return [a.type.name for a in stmt.get_attributes()]
    except Exception as e:  # noqa: BLE001
        logger.warning("run_query: could not describe the result types (%s: %s) — values kept as JSON gave them",
                       type(e).__name__, str(e)[:160])
        return None


def _is_retryable_sqlstate(state: str | None) -> bool:
    # class 08 (connection lost) and 53300 (server full): the DB team's "retry
    # the same query once after a short wait".
    return bool(state) and (state.startswith("08") or state == "53300")


async def _call_run_query(limited: str) -> dict:
    pool = await ensure_chatbot_pool()
    async with pool.acquire() as conn:
        async with conn.transaction(readonly=True):
            raw = await conn.fetchval("SELECT semantic.run_query($1, $2, $3)::text", limited,
                                      settings.SQL_MAX_RESULT_ROWS, settings.SQL_MAX_COST)
    return json.loads(raw, parse_float=Decimal)


async def _run_via_run_query(limited: str) -> list[dict]:
    """Run one already-guarded statement through semantic.run_query and return
    rows exactly as run_readonly always has: dicts in the query's column order,
    values in asyncpg's Python types. A lost connection or a full server is
    retried once after a short wait; run_query's refusals become the errors the
    pipeline already handles."""
    for attempt in (1, 2):
        try:
            res = await _call_run_query(limited)
        except Exception as e:  # noqa: BLE001
            if attempt == 1 and is_connection_error(e):
                logger.warning("run_query: connection lost (%s) — retrying once", e)
                await asyncio.sleep(1.0)
                continue
            raise
        if res.get("ok"):
            break
        reason = res.get("reason")
        if reason == "error" and attempt == 1 and _is_retryable_sqlstate(res.get("sqlstate")):
            logger.warning("run_query: %s %s — retrying once", res.get("sqlstate"), res.get("message"))
            await asyncio.sleep(1.0)
            continue
        _raise_refusal(res)
    else:  # pragma: no cover — both attempts 'continue'd
        raise DatabaseUnavailableError("run_query: the database stayed unreachable")

    columns = list(res.get("columns") or [])
    rows = res.get("rows") or []
    types = res.get("types")
    if not (isinstance(types, list) and len(types) == len(columns)):
        types = await _describe_types(limited) if rows else None
        if types is not None and len(types) != len(columns):
            logger.warning("run_query: %d described types for %d columns — values kept as JSON gave them",
                           len(types), len(columns))
            types = None
    typed = list(zip(columns, types)) if types else [(c, None) for c in columns]
    return [{c: _typed(t, r.get(c)) for c, t in typed} for r in rows]


def _raise_refusal(res: dict) -> None:
    reason = res.get("reason")
    detail = res.get("detail")
    if isinstance(detail, list):
        detail = "; ".join(str(d) for d in detail)
    if reason == "row_join":
        raise RowJoinRefusedError(
            f"the database's plan check found two fact tables joined row by row ({str(detail or '')[:200]}), "
            "which multiplies the figures. Aggregate each fact table to a shared grain "
            "(district / block / year) in its own CTE first, then join the aggregates. "
            "Keep every filter exactly as it was.")
    if reason == "rejected":
        raise UnsafeSQLError(f"the database refused the statement: {detail or 'not a single query'}", "rejected")
    if reason == "too_expensive":
        raise QueryTooHeavyError(
            f"the database estimated this query above its cost limit ({settings.SQL_MAX_COST:,}); "
            "make it cheaper — aggregate earlier, filter by year / place, fewer joins")
    state = res.get("sqlstate")
    message = str(res.get("message") or res)
    if state in _TOO_HEAVY_SQLSTATES:
        raise QueryTooHeavyError(
            f"the database stopped this query as too heavy ({state}: {message}); "
            "make it cheaper — aggregate earlier, filter by year / place, fewer joins")
    if _is_retryable_sqlstate(state):
        raise DatabaseUnavailableError(f"run_query: {state} {message}")
    raise RunQueryError(message, state)
