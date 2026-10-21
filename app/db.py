"""
megh_db access — two pools.

- The app pool (DATABASE_URL, megh_app — deploy/sql/01): the service's own
  app.* writes and our trusted, parametrised queries (fetch_rows / fetchrow /
  fetchval / execute).
- The read-only pool (READONLY_DATABASE_URL, megh_readonly — deploy/sql/03):
  model-generated SQL only (run_readonly). SELECT-only grants on curated and
  semantic, default_transaction_read_only and search_path = curated, semantic on
  every connection, and each statement inside a READ ONLY transaction.

The database role is the security boundary; the SQLGlot check in
app/sql_guard.py is the layer in front of it: a generated query is untrusted
input until proven otherwise.
"""
import logging

import asyncpg

from app.config import settings
from app.sql_guard import READONLY_SCHEMAS, UnsafeSQLError, prepare_readonly

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_pool_dsn: str | None = None
_ro_pool: asyncpg.Pool | None = None

# UnsafeSQLError lives in app/sql_guard.py (the SQLGlot check) and is
# re-exported here, where callers have always imported it from.
__all__ = ["UnsafeSQLError", "DatabaseUnavailableError", "ReadonlyRoleError"]


class DatabaseUnavailableError(RuntimeError):
    """megh_db could not be reached (VPN / network drop, connection refused or
    lost, server out of connection slots). Not a problem with the question or
    its SQL — the caller must say "try again", never repair the SQL or answer
    from the reference documents instead (KI-025)."""


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


async def _create_app_pool(dsn: str) -> asyncpg.Pool:
    return await asyncpg.create_pool(
        dsn,
        min_size=settings.DB_POOL_MIN_SIZE,
        max_size=settings.DB_POOL_MAX_SIZE,
        timeout=settings.DB_POOL_TIMEOUT,
        max_inactive_connection_lifetime=settings.DB_POOL_IDLE_SECONDS,
        command_timeout=settings.SQL_EXECUTION_TIMEOUT_MS / 1000,
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


async def _check_readonly_login(pool: asyncpg.Pool) -> None:
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
                f"read-only pool logged in as '{who}', a superuser — refusing to run generated SQL. "
                "Set READONLY_DATABASE_URL to the megh_readonly role (deploy/sql/03_readonly_role.sql).")
        logger.critical("read-only pool logged in as superuser '%s' (READONLY_DB_ALLOW_SUPERUSER) — "
                        "dev only; generated SQL is held only by READ ONLY transactions", who)
    if writable:
        logger.warning("read-only pool role '%s' holds write grants on %d curated/semantic object(s) — "
                       "READ ONLY transactions still block them; revoke them (deploy/sql/03)", who, writable)
    logger.info("megh_db read-only pool ready as '%s' (min=%d max=%d)", who,
                settings.READONLY_DB_POOL_MIN_SIZE, settings.READONLY_DB_POOL_MAX_SIZE)


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
        server_settings=_READONLY_SERVER_SETTINGS,
    )
    try:
        await _check_readonly_login(pool)
    except BaseException:
        await pool.close()
        raise
    return pool


async def init_pool() -> None:
    """Build both megh_db pools. Best-effort: if the DB host is unreachable at
    startup (the 10.48.242.4 box flaps), log and carry on with the pool None —
    the server still boots (degraded), and ensure_pool() / ensure_readonly_pool()
    rebuild it lazily on the first query once the host is back."""
    global _pool, _pool_dsn, _ro_pool
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


async def close_pool() -> None:
    global _pool, _ro_pool
    for pool in (_pool, _ro_pool):
        if pool is not None:
            await pool.close()
    _pool = _ro_pool = None


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


async def run_readonly(sql: str) -> list[dict]:
    """Validate (SQLGlot — app/sql_guard.py: one SELECT, curated/semantic only),
    bound at SQL_MAX_RESULT_ROWS, then execute on the read-only pool inside a
    READ ONLY transaction (BEGIN READ ONLY, the same as SET TRANSACTION READ ONLY)."""
    limited = prepare_readonly(sql, settings.SQL_MAX_RESULT_ROWS)
    pool = await ensure_readonly_pool()

    async with pool.acquire() as conn:
        async with conn.transaction(readonly=True):
            rows = await conn.fetch(limited)
    return [dict(r) for r in rows]
