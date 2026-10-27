"""The DB team's changes of 2026-10-27 (new_docs/DB_Changes_Impact_Report_2026-10-27.md):
- KI-428: CMSS / Home Stay glossary terms stay out of our six schemes' SQL prompts;
- the role limits' codes 57014 / 53400 end like our own timeout ("narrower question");
- semantic.check_query is asked before a generated query runs (fail-open);
- system-information functions are refused by the SQL guard;
- KI-429: a block officer with no block assigned no longer sees the whole district.
Every test calls the real function."""
import asyncio

import asyncpg
import pytest

from app import auth, db, schema_introspect as si
from app import pipeline as p
from app.config import settings
from app.sql_guard import UnsafeSQLError, prepare_readonly

SIX = ["MGNREGA", "PMAY-G", "Focus Plus", "CM Elevate", "Focus Legacy", "CM Elevate Legacy"]


# ── KI-428: glossary scope ──────────────────────────────────────────────────

@pytest.mark.parametrize("area", ["cmss", "homestay_legacy", "homestay", "nrlm"])
def test_other_programmes_glossary_is_scoped_out_of_every_scheme(area):
    for s in SIX:
        assert not si._matches_scheme(area, [s])


def test_own_and_shared_terms_still_reach_the_prompt():
    assert si._matches_scheme("focus_plus", ["Focus Plus"])
    assert si._matches_scheme("cm_elevate_disbursement", ["CM Elevate Legacy"])
    assert si._matches_scheme("shared", ["MGNREGA"])
    assert si._matches_scheme(None, ["PMAY-G"])


@pytest.mark.parametrize("table", ["v_cmss", "fact_cmss_application", "v_homestay_legacy", "v_nrlm_shg"])
def test_other_programmes_column_notes_are_scoped_out(table):
    for s in SIX:
        assert not si._table_matches_scheme(table, [s])


def test_own_and_shared_column_notes_still_match():
    assert si._table_matches_scheme("v_focus_plus", ["Focus Plus"])
    assert si._table_matches_scheme("v_cm_elevate_disbursement", ["CM Elevate Legacy"])
    assert si._table_matches_scheme("dim_scheme", ["MGNREGA"])          # shared dimension
    assert si._table_matches_scheme("v_data_coverage", ["PMAY-G"])


def test_catalog_block_leaves_out_the_cmss_and_home_stay_terms(monkeypatch):
    cache = dict(si._cache, loaded=True, tables=[], metrics=[], columns=[], glossary=[
        {"term": "combining CMSS with Focus+", "definition": "x", "subject_area": "cmss",
         "maps_to_object": "curated.v_cmss"},
        {"term": "combining Home Stay Legacy with the new Home Stay feed", "definition": "x",
         "subject_area": "homestay_legacy", "maps_to_object": "curated.v_homestay_legacy"},
        {"term": "combining Focus+ with Focus Legacy", "definition": "x", "subject_area": "focus_plus",
         "maps_to_object": "curated.v_focus_plus"},
        {"term": "combining facts", "definition": "x", "subject_area": "shared",
         "maps_to_object": "semantic.v_join_rules"},
    ])
    monkeypatch.setattr(si, "_cache", cache)
    block = si.catalog_block(["Focus Plus"])
    assert "combining Focus+ with Focus Legacy" in block and "combining facts" in block
    assert "CMSS" not in block and "Home Stay" not in block


# ── Fake read-only pool ─────────────────────────────────────────────────────

class _Txn:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *exc):
        return False


class _Conn:
    def __init__(self, fetch):
        self._fetch = fetch

    def transaction(self, readonly=False):
        return _Txn()

    async def fetch(self, sql, *args, **kw):
        return await self._fetch(sql, *args)


class _Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *exc):
        return False


class _Pool:
    def __init__(self, fetch):
        self.conn = _Conn(fetch)

    def acquire(self):
        return _Acquire(self.conn)


def _raising(exc):
    async def fetch(sql, *args):
        raise exc
    return fetch


def _use_pool(monkeypatch, fetch):
    pool = _Pool(fetch)

    async def ensure():
        return pool
    monkeypatch.setattr(db, "ensure_readonly_pool", ensure)
    monkeypatch.setattr(db, "_ro_pool", pool)
    return pool


# ── 57014 / 53400 -> the timeout road ───────────────────────────────────────

@pytest.mark.parametrize("exc", [
    asyncpg.exceptions.QueryCanceledError("canceling statement due to statement timeout"),
    asyncpg.exceptions.ConfigurationLimitExceededError("temporary file size exceeds temp_file_limit"),
])
def test_server_limits_become_query_too_heavy(monkeypatch, exc):
    _use_pool(monkeypatch, _raising(exc))
    with pytest.raises(db.QueryTooHeavyError) as got:
        asyncio.run(db.run_readonly("SELECT 1 AS n FROM curated.v_employment"))
    assert isinstance(got.value, asyncio.TimeoutError)          # router: 504 "narrower question"
    assert not db.is_connection_error(got.value)                # never "database unavailable"
    assert exc.sqlstate in str(got.value)                       # repair sees the reason


def test_other_database_errors_are_unchanged(monkeypatch):
    exc = asyncpg.exceptions.UndefinedColumnError('column "x" does not exist')
    _use_pool(monkeypatch, _raising(exc))
    with pytest.raises(asyncpg.exceptions.UndefinedColumnError):
        asyncio.run(db.run_readonly("SELECT x FROM curated.v_employment"))


def test_too_heavy_reaches_the_router_not_the_kb_fallback():
    err = db.QueryTooHeavyError("the database stopped this query as too heavy (57014: …)")
    with pytest.raises(db.QueryTooHeavyError):
        asyncio.run(p._data_path_error_result(err, "q", "q"))


# ── semantic.check_query pre-check ──────────────────────────────────────────

def test_precheck_reports_a_row_join(monkeypatch):
    seen = []

    async def fetch(sql, *args):
        seen.append((sql, args))
        return [{"check_name": "row_join", "detail": "fact_employment x fact_pmay"},
                {"check_name": "estimated_cost", "detail": "1234"}]
    _use_pool(monkeypatch, fetch)
    got = asyncio.run(db.precheck_readonly("SELECT 1 AS n FROM curated.v_employment"))
    assert got == "fact_employment x fact_pmay"
    assert "semantic.check_query" in seen[0][0]


def test_precheck_passes_a_clean_plan(monkeypatch):
    async def fetch(sql, *args):
        return [{"check_name": "estimated_cost", "detail": "10"}, {"check_name": "estimated_rows", "detail": "1"}]
    _use_pool(monkeypatch, fetch)
    assert asyncio.run(db.precheck_readonly("SELECT 1 AS n FROM curated.v_employment")) is None


def test_precheck_is_fail_open(monkeypatch):
    _use_pool(monkeypatch, _raising(asyncpg.exceptions.UndefinedFunctionError("no check_query")))
    assert asyncio.run(db.precheck_readonly("SELECT 1 AS n FROM curated.v_employment")) is None


def test_precheck_never_opens_a_pool_and_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(db, "_ro_pool", None)
    assert asyncio.run(db.precheck_readonly("SELECT 1 AS n FROM curated.v_employment")) is None
    _use_pool(monkeypatch, _raising(AssertionError("must not be called")))
    monkeypatch.setattr(settings, "SQL_DB_PRECHECK", False)
    assert asyncio.run(db.precheck_readonly("SELECT 1 AS n FROM curated.v_employment")) is None


def test_a_flagged_row_join_goes_to_repair_before_execution(monkeypatch):
    async def row_join(sql):
        return "fact_employment x fact_pmay"

    async def must_not_run(sql):
        raise AssertionError("the query must not run")
    monkeypatch.setattr(p, "db_precheck_readonly", row_join)
    monkeypatch.setattr(p, "run_readonly", must_not_run)
    sql = "SELECT SUM(person_days) AS person_days FROM curated.v_employment WHERE year_key = 2023"
    with pytest.raises(ValueError, match="plan check"):
        asyncio.run(p._execute_one_attempt("Total MGNREGA person days in 2023-24", ["MGNREGA"],
                                           {"resolved": {}, "unresolved": []}, sql))


# ── SQL guard: system-information functions ─────────────────────────────────

@pytest.mark.parametrize("sql", [
    "SELECT current_setting('search_path')", "SELECT version()", "SELECT current_database()",
    "SELECT inet_server_addr()", "SELECT pg_backend_pid()", "SELECT pg_get_viewdef(1)",
    "SELECT txid_current()", "SELECT lo_get(1)",
])
def test_system_functions_are_refused(sql):
    with pytest.raises(UnsafeSQLError) as got:
        prepare_readonly(sql, 10)
    assert got.value.rule == "forbidden_function"


@pytest.mark.parametrize("sql", [
    "SELECT lgd_district, ROUND(SUM(total_exp) / 100.0, 2) AS crore, COALESCE(MAX(year_key), 0) AS y, "
    "array_to_string(string_to_array('a,b', ','), '-') AS s, ascii('a') AS c "
    "FROM curated.v_expenditure GROUP BY 1",
    "SELECT AVG(person_days) AS a, TO_CHAR(NOW(), 'YYYY') AS y, RANK() OVER (ORDER BY SUM(person_days) DESC) AS r, "
    "STRING_AGG(lgd_block, ',') AS b FROM curated.v_employment GROUP BY lgd_district",
    "SELECT pg_id, COUNT(*) AS n FROM curated.v_focus_legacy GROUP BY pg_id",   # a column, not a function
])
def test_ordinary_functions_and_pg_columns_still_pass(sql):
    prepare_readonly(sql, 10)


# ── KI-429: a block officer with no block ───────────────────────────────────

def _bo(blocks=()):
    return auth.UserScope(user_id="ri-bhoi-bo", role="block_officer", granularity_cap="village",
                          schemes=list(SIX), geographies={"districts": ["RI BHOI"], "blocks": list(blocks)})


DISTRICT_SQL = ("SELECT lgd_block, SUM(person_days) AS pd FROM curated.v_employment "
                "WHERE lgd_district = 'RI BHOI' AND year_key = 2023 GROUP BY lgd_block")
BLOCK_SQL = ("SELECT SUM(person_days) AS pd FROM curated.v_employment "
             "WHERE lgd_district = 'RI BHOI' AND lgd_block = 'UMLING' AND year_key = 2023")
STATE_SQL = "SELECT SUM(person_days) AS pd FROM curated.v_employment WHERE year_key = 2023"


def _auth(scope, sql, resolved=None):
    return auth.authorize(scope, schemes=["MGNREGA"], resolved_entities=resolved or {}, sql=sql)


def test_unassigned_block_officer_is_refused_area_data():
    for sql, resolved in ((DISTRICT_SQL, {"district": "RI BHOI"}),
                          (BLOCK_SQL, {"district": "RI BHOI", "block": "UMLING"})):
        d = _auth(_bo(), sql, resolved)
        assert not d.allow and d.check == "geography"
        assert "no block assigned" in d.reason


def test_unassigned_block_officer_keeps_statewide_totals():
    assert _auth(_bo(), STATE_SQL).allow


def test_assigned_block_officer_is_unchanged():
    assert _auth(_bo(["UMLING"]), BLOCK_SQL, {"district": "RI BHOI", "block": "UMLING"}).allow
    assert not _auth(_bo(["UMLING"]), BLOCK_SQL.replace("UMLING", "UMSNING"),
                     {"district": "RI BHOI", "block": "UMSNING"}).allow


def test_district_officer_without_blocks_is_unchanged():
    do = auth.UserScope(user_id="d", role="district_officer", granularity_cap="block",
                        schemes=list(SIX), geographies={"districts": ["RI BHOI"], "blocks": []})
    assert _auth(do, DISTRICT_SQL, {"district": "RI BHOI"}).allow
