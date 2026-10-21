"""Generated SQL runs on its own pool (app/db.py): logged in as the SELECT-only
megh_readonly role (READONLY_DATABASE_URL), default_transaction_read_only and
search_path = curated, semantic on every connection, each statement inside a
READ ONLY transaction — and a superuser login on that pool is refused. Before,
everything ran on one pool logged in as the `postgres` superuser."""
import asyncio

import pytest

from app import db
from app.config import settings


class _Txn:
    def __init__(self, conn, readonly):
        self.conn, self.readonly = conn, readonly

    async def __aenter__(self):
        self.conn.log.append(("begin", self.readonly))

    async def __aexit__(self, *exc):
        self.conn.log.append(("end",))


class _Conn:
    def __init__(self, role):
        self.role, self.log = role, []

    def transaction(self, readonly=False):
        return _Txn(self, readonly)

    async def fetch(self, sql, *args):
        self.log.append(("fetch", sql))
        return [{"n": 1}]

    async def fetchrow(self, sql, *args):
        return self.role

    async def fetchval(self, sql, *args):
        return 0


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        pass


class _Pool:
    def __init__(self, dsn, role, **kw):
        self.dsn, self.kw, self.conn, self.closed = dsn, kw, _Conn(role), False

    def acquire(self):
        return _Acquire(self.conn)

    async def close(self):
        self.closed = True


@pytest.fixture
def pools(monkeypatch):
    """Fake asyncpg.create_pool; `role` is what the login reports."""
    made = []
    state = {"role": {"who": "megh_readonly", "rolsuper": False, "rolbypassrls": False}}

    async def create_pool(dsn, **kw):
        pool = _Pool(dsn, state["role"], **kw)
        made.append(pool)
        return pool

    monkeypatch.setattr(db.asyncpg, "create_pool", create_pool)
    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(db, "_ro_pool", None)
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://megh_app:x@h/megh_db")
    monkeypatch.setattr(settings, "READONLY_DATABASE_URL", "postgresql+asyncpg://megh_readonly:y@h/megh_db")
    monkeypatch.setattr(settings, "READONLY_DB_ALLOW_SUPERUSER", False)
    return made, state


def test_generated_sql_uses_the_readonly_login_in_a_read_only_transaction(pools):
    made, _ = pools
    rows = asyncio.run(db.run_readonly("SELECT COUNT(*) AS n FROM curated.v_cm_elevate"))
    assert rows == [{"n": 1}]
    (ro,) = made
    assert ro.dsn == "postgresql://megh_readonly:y@h/megh_db"
    assert ro.kw["server_settings"] == {"default_transaction_read_only": "on",
                                        "search_path": "curated, semantic"}
    assert ro.kw["max_size"] == settings.READONLY_DB_POOL_MAX_SIZE
    begin, fetch, end = ro.conn.log
    assert begin == ("begin", True)
    assert fetch[1].startswith("SELECT COUNT(*) AS n FROM curated.v_cm_elevate")
    assert end == ("end",)


def test_trusted_queries_stay_on_the_app_pool(pools):
    made, _ = pools
    asyncio.run(db.fetch_rows("SELECT 1"))
    (app,) = made
    assert app.dsn == "postgresql://megh_app:x@h/megh_db"
    assert "server_settings" not in app.kw


def test_both_pools_are_separate(pools):
    made, _ = pools
    asyncio.run(db.init_pool())
    assert [p.dsn for p in made] == ["postgresql://megh_app:x@h/megh_db",
                                     "postgresql://megh_readonly:y@h/megh_db"]
    asyncio.run(db.close_pool())
    assert all(p.closed for p in made)


def test_unsafe_sql_never_reaches_the_pool(pools):
    made, _ = pools
    with pytest.raises(db.UnsafeSQLError):
        asyncio.run(db.run_readonly("SELECT * FROM app.users"))
    assert made == []


def test_superuser_login_is_refused_and_not_repaired(pools):
    made, state = pools
    state["role"] = {"who": "postgres", "rolsuper": True, "rolbypassrls": True}
    with pytest.raises(db.ReadonlyRoleError) as e:
        asyncio.run(db.run_readonly("SELECT 1 FROM curated.v_focus_plus"))
    assert "superuser" in str(e.value)
    assert made[0].closed and db._ro_pool is None
    # a configuration fault, not the SQL's: never sent to the repair loop
    assert db.is_connection_error(e.value)


def test_superuser_allowed_only_when_opted_in(pools, monkeypatch, caplog):
    made, state = pools
    state["role"] = {"who": "postgres", "rolsuper": True, "rolbypassrls": True}
    monkeypatch.setattr(settings, "READONLY_DB_ALLOW_SUPERUSER", True)
    asyncio.run(db.run_readonly("SELECT 1 FROM curated.v_focus_plus"))
    assert any(r.levelname == "CRITICAL" and "superuser" in r.getMessage() for r in caplog.records)
    assert made[0].conn.log[0] == ("begin", True)


def test_blank_readonly_url_falls_back_loudly(pools, monkeypatch, caplog):
    made, _ = pools
    monkeypatch.setattr(settings, "READONLY_DATABASE_URL", "")
    asyncio.run(db.run_readonly("SELECT 1 FROM curated.v_focus_plus"))
    assert made[0].dsn == "postgresql://megh_app:x@h/megh_db"
    assert made[0].kw["server_settings"]["default_transaction_read_only"] == "on"
    assert any(r.levelname == "CRITICAL" and "READONLY_DATABASE_URL" in r.getMessage()
               for r in caplog.records)


def test_startup_survives_a_refused_readonly_login(pools):
    made, state = pools
    state["role"] = {"who": "postgres", "rolsuper": True, "rolbypassrls": False}
    asyncio.run(db.init_pool())      # must not raise: the app pool still serves logins
    assert db._pool is not None and db._ro_pool is None
