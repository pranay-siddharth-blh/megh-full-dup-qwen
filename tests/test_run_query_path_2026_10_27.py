"""Generated SQL through semantic.run_query on the megh_chatbot login (D-073,
DB team 2026-10-27). run_readonly must return exactly what it returned from
the read-only pool — dicts in the query's column order, values in asyncpg's
Python types — and turn run_query's refusals into the errors the pipeline
already handles. Every test calls the real db functions with a faked pool."""
import asyncio
import datetime
import json
from decimal import Decimal

import pytest

from app import db
from app.config import settings
from app.sql_guard import UnsafeSQLError


class _Txn:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return _Acquire(self.conn)


class _ChatConn:
    """megh_chatbot: answers run_query with the queued JSON replies (or raises)."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def transaction(self, readonly=False):
        return _Txn()

    async def fetchval(self, sql, *args):
        self.calls.append((sql, args))
        r = self.replies.pop(0)
        if isinstance(r, BaseException):
            raise r
        return json.dumps(r) if isinstance(r, dict) else r


class _Attr:
    def __init__(self, name, type_name):
        self.name = name
        self.type = type("T", (), {"name": type_name})()


class _Stmt:
    def __init__(self, attrs):
        self.attrs = attrs

    def get_attributes(self):
        return self.attrs


class _RoConn:
    """megh_readonly: only describes (prepare); must never fetch generated SQL."""

    def __init__(self, types):
        self.types, self.prepared = types, []

    def transaction(self, readonly=False):
        return _Txn()

    async def prepare(self, sql):
        self.prepared.append(sql)
        return _Stmt([_Attr(n, t) for n, t in self.types])

    async def fetch(self, sql, *args):
        raise AssertionError("generated SQL must not execute on megh_readonly")


@pytest.fixture
def chat(monkeypatch):
    """Point run_readonly at a fake megh_chatbot + read-only pair."""
    state = {}

    def setup(replies, types=()):
        chat_conn, ro_conn = _ChatConn(replies), _RoConn(list(types))
        monkeypatch.setattr(settings, "CHATBOT_DATABASE_URL", "postgresql://megh_chatbot:x@h/megh_db")
        monkeypatch.setattr(db, "_chat_pool", _Pool(chat_conn))
        monkeypatch.setattr(db, "_ro_pool", _Pool(ro_conn))

        async def no_sleep(_s):
            state["slept"] = state.get("slept", 0) + 1
        monkeypatch.setattr(db.asyncio, "sleep", no_sleep)
        state.update(chat=chat_conn, ro=ro_conn)
        return state
    return setup


SQL = "SELECT lgd_district, SUM(person_days) AS pd FROM curated.v_employment GROUP BY 1"


def _run(sql=SQL):
    return asyncio.run(db.run_readonly(sql))


def test_rows_keep_column_order_and_asyncpg_types(chat):
    # the server's own text (live 2026-10-27): numeric scale kept, "82.90"
    st = chat(['{"ok": true, "columns": ["lgd_district", "pd", "share", "n", "b", "d", "ts", "arr", "z"], '
               '"rows": [{"z": null, "pd": 677731, "share": 0.25, "n": 82.90, "b": 7, "d": "2026-10-27", '
               '"ts": "2026-10-27T13:13:37.113084+05:30", "arr": [1, 2.5], "lgd_district": "EAST GARO HILLS"}], '
               '"row_count": 1, "truncated": false, "estimated_cost": 10}'],
               types=[("lgd_district", "text"), ("pd", "numeric"), ("share", "float8"), ("n", "numeric"),
                      ("b", "int8"), ("d", "date"), ("ts", "timestamptz"), ("arr", "_numeric"), ("z", "numeric")])
    rows = _run()
    assert list(rows[0]) == ["lgd_district", "pd", "share", "n", "b", "d", "ts", "arr", "z"]
    r = rows[0]
    assert r["pd"] == Decimal("677731") and isinstance(r["pd"], Decimal)      # SUM(bigint) is numeric
    assert r["n"] == Decimal("82.90") and str(r["n"]) == "82.90"              # scale kept
    assert isinstance(r["share"], float) and r["share"] == 0.25
    assert isinstance(r["b"], int) and r["b"] == 7
    assert r["d"] == datetime.date(2026, 10, 27)
    assert r["ts"].tzinfo is not None and r["ts"].year == 2026
    assert r["arr"] == [Decimal("1"), Decimal("2.5")]
    assert r["z"] is None
    # the statement sent is the guarded one (LIMIT added), with the row and cost caps
    sql_sent, args = st["chat"].calls[0]
    assert "semantic.run_query" in sql_sent
    assert args[1] == settings.SQL_MAX_RESULT_ROWS and args[2] == settings.SQL_MAX_COST
    assert "LIMIT" in args[0].upper()
    assert st["ro"].prepared == [args[0]]                                     # described, never executed


def test_run_query_types_list_is_used_without_describing(chat):
    st = chat([{"ok": True, "columns": ["pd"], "types": ["numeric"], "rows": [{"pd": 5}]}])
    assert _run() == [{"pd": Decimal("5")}]
    assert st["ro"].prepared == []


def test_empty_result_needs_no_description(chat):
    st = chat([{"ok": True, "columns": ["lgd_district"], "rows": [], "row_count": 0}])
    assert _run() == []
    assert st["ro"].prepared == []


def test_row_join_goes_to_repair_with_the_reason(chat):
    chat([{"ok": False, "reason": "row_join", "detail": ["fact_mgnrega_employment x fact_pmay_house (Hash Join)"]}])
    with pytest.raises(ValueError, match="fact_mgnrega_employment x fact_pmay_house"):
        _run()


def test_rejected_is_unsafe_sql(chat):
    chat([{"ok": False, "reason": "rejected", "detail": ["more than one statement"]}])
    with pytest.raises(UnsafeSQLError):
        _run()


@pytest.mark.parametrize("reply", [
    {"ok": False, "reason": "too_expensive"},
    {"ok": False, "reason": "error", "sqlstate": "57014", "message": "canceling statement due to statement timeout"},
    {"ok": False, "reason": "error", "sqlstate": "53400", "message": "temporary file size exceeds temp_file_limit"},
])
def test_heavy_queries_end_as_narrower_question(chat, reply):
    chat([reply])
    with pytest.raises(db.QueryTooHeavyError) as got:
        _run()
    assert isinstance(got.value, asyncio.TimeoutError) and not db.is_connection_error(got.value)


def test_query_mistake_reaches_repair_with_postgres_message(chat):
    chat([{"ok": False, "reason": "error", "sqlstate": "42703", "message": 'column "x" does not exist'}])
    with pytest.raises(db.RunQueryError) as got:
        _run()
    assert str(got.value) == 'column "x" does not exist' and got.value.sqlstate == "42703"
    assert not db.is_connection_error(got.value)


def test_server_full_is_retried_once_then_unavailable(chat):
    full = {"ok": False, "reason": "error", "sqlstate": "53300", "message": "too many connections"}
    st = chat([full, {"ok": True, "columns": ["n"], "types": ["int8"], "rows": [{"n": 1}]}])
    assert _run() == [{"n": 1}] and st["slept"] == 1
    chat([full, full])
    with pytest.raises(db.DatabaseUnavailableError):
        _run()


def test_lost_connection_is_retried_once(chat):
    st = chat([ConnectionResetError("reset"), {"ok": True, "columns": ["n"], "types": ["int8"], "rows": [{"n": 2}]}])
    assert _run() == [{"n": 2}] and st["slept"] == 1
    chat([ConnectionResetError("reset"), ConnectionResetError("reset")])
    with pytest.raises(ConnectionResetError) as got:
        _run()
    assert db.is_connection_error(got.value)


def test_unsafe_sql_never_reaches_run_query(chat):
    st = chat([])
    with pytest.raises(UnsafeSQLError):
        _run("DELETE FROM curated.v_employment")
    assert st["chat"].calls == []


def test_blank_url_keeps_the_read_only_pool_path(monkeypatch):
    seen = []

    class _Conn(_RoConn):
        async def fetch(self, sql, *args):
            seen.append(sql)
            return [{"n": 1}]
    monkeypatch.setattr(settings, "CHATBOT_DATABASE_URL", "")
    monkeypatch.setattr(db, "_ro_pool", _Pool(_Conn([])))

    async def ensure():
        return db._ro_pool
    monkeypatch.setattr(db, "ensure_readonly_pool", ensure)
    assert _run() == [{"n": 1}] and seen


def test_precheck_is_skipped_when_run_query_checks(chat):
    chat([])
    assert asyncio.run(db.precheck_readonly(SQL)) is None


def test_run_query_types_as_the_server_names_them(chat):
    # live reply 2026-10-27: base type names, arrays as "numeric[]", sent with no rows too
    st = chat(['{"ok": true, "rows": [{"f": 1.5, "n": 82.90, "b": 7, "i": 3, "v": "x", "d": "2026-10-27", '
               '"ts": "2026-10-27T13:32:34.789007+05:30", "narr": [1.5], "arr": ["a"], "t": true}], '
               '"types": ["double precision", "numeric", "bigint", "integer", "character varying", "date", '
               '"timestamp with time zone", "numeric[]", "text[]", "boolean"], '
               '"columns": ["f", "n", "b", "i", "v", "d", "ts", "narr", "arr", "t"], "row_count": 1}'])
    (r,) = _run()
    assert isinstance(r["f"], float) and str(r["n"]) == "82.90" and isinstance(r["n"], Decimal)
    assert type(r["b"]) is int and type(r["i"]) is int and r["v"] == "x" and r["t"] is True
    assert r["d"] == datetime.date(2026, 10, 27) and r["ts"].tzinfo is not None
    assert r["narr"] == [Decimal("1.5")] and r["arr"] == ["a"]
    assert st["ro"].prepared == []                              # no describe when types are sent


def test_every_pool_names_its_build(monkeypatch):
    monkeypatch.setattr(settings, "DB_APPLICATION_NAME", "megh-chatbot-v2")
    assert db.application_name("chatbot") == "megh-chatbot-v2:chatbot"
    assert len(db.application_name("x" * 80)) == 63
    monkeypatch.setattr(settings, "DB_APPLICATION_NAME", "")
    assert db.application_name("app") is None
