"""Cross-scheme answers: the headline figure is the welcome card's, the schemes are queried concurrently, and the
semantic cache keys the grain (2026-11-14). Offline: megh_db is faked (cross_figures.db.fetch_rows).

1. "The headline figures across all schemes" = each scheme's welcome-card lead figure (data/cross_scheme.yaml
   `headline`), by the SAME SQL the card runs (routers/stats.py builds its lead column from that declaration), with
   the scheme's cross-scheme count beside it when that is another figure. Truth fixtures (megh_db, verified earlier):
   CMSS 1,04,827 applications / 98,751 students paid / Rs 59,25,06,000; Homestay 1,297 applications.
2. Fan-out: one task per scheme, at most CROSS_SCHEME_CONCURRENCY at once, each with a timeout; a failed scheme is
   named, the rest answered; all failing raises; the SQL is listed in scheme order whatever finished first.
3. scope_signature carries the grain: "X by district" and "X in total" never share a semantic-cache entry."""
import asyncio
import json
import time

import pytest

from app import cross_figures as cf
from app import cross_registry as reg
from app import pipeline as p
from app import semantic_cache
from app.config import settings
from app.routers import stats

M = p._SCHEME_NAME_MATCHER
ALL = list(cf.SUPPORTED)

TRUTH = {"CMSS": {"applications": 104827, "paid": 98751, "rupees": 592506000}, "Homestay": {"applications": 1297}}
_VIEW_OF = {e.headline.view: e.name for e in reg.ENTRIES}


def _scheme_of(sql: str) -> str:
    # the longest view name that occurs ("v_cm_elevate_disbursement" before "v_cm_elevate")
    return _VIEW_OF[max((v for v in _VIEW_OF if v + " " in sql + " "), key=len)]


@pytest.fixture
def headline_db(monkeypatch):
    seen = []

    async def fetch_rows(sql, params):
        seen.append((sql, params))
        s = _scheme_of(sql)
        if "DISTINCT year_key AS y" in sql:
            return [{"y": 2025}]
        lead = {"CMSS": TRUTH["CMSS"]["applications"], "Homestay": TRUTH["Homestay"]["applications"]}.get(s, 1000)
        ben = {"CMSS": TRUTH["CMSS"]["paid"]}.get(s, 400)
        return [{"k": None, "headline": lead, "ben": ben}]
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)
    return seen


# ── 1. the headline figure ─────────────────────────────────────────────────────

@pytest.mark.parametrize("q", ["give me the headline figures across all schemes",
                               "Give me the headline figure of every scheme", "Give me each scheme's figures",
                               "key statistics for all the schemes", "headline figures for MGNREGA and PMAY-G"])
def test_headline_questions_plan_the_headline(q):
    det = p.cross_scheme.detect(q, list(p._named_schemes(q)))
    pl = cf.plan(q, det, {}, {}, M)
    assert pl is not None and pl.op == "headline" and pl.measures == ["headline"]


@pytest.mark.parametrize("q", ["Compare beneficiaries across all schemes", "How much money has each scheme disbursed?",
                               "Compare all eight schemes", "headline figures by district for all schemes",
                               "Give me an overview of all schemes"])
def test_other_shapes_keep_their_measures(q):
    pl = cf.plan(q, ALL, {}, {}, M)
    assert pl is not None and pl.op != "headline"


def test_headline_answer_is_the_cards_figure(headline_db):
    out = asyncio.run(cf.answer(cf.plan("give me the headline figures across all schemes", ALL, {}, {}, M)))
    text = out["answer"]
    assert "- **CMSS**: 1,04,827 applications (98,751 students paid)" in text
    assert "- **Homestay**: 1,297 applications" in text
    assert "not added" in text and "Combined" not in text
    rows = {r["scheme"]: r for r in out["rows"]}
    assert rows["CMSS"] == {"scheme": "CMSS", "measure": "Applications", "value": 104827, "beneficiaries": 98751}
    assert rows["Homestay"]["value"] == 1297 and rows["Homestay"]["beneficiaries"] == 1297
    assert set(rows) == set(ALL) and out["schemes_failed"] == []
    # one statement per scheme, the card's own expression on the card's own view
    for sql, _params in headline_db:
        s = _scheme_of(sql)
        h = reg.BY_NAME[s].headline
        assert f"({h.expr})::float8 AS headline" in sql and f"FROM {h.view} " in sql


def test_headline_in_a_district_and_a_year_is_filtered(headline_db):
    pl = cf.plan("headline figures of every scheme", ALL, {"district": "RI BHOI", "year_key": 2025},
                 {"district": "Ri Bhoi"}, M)
    assert pl.op == "headline"
    out = asyncio.run(cf.answer(pl))
    assert "CM Elevate records no financial year" in out["answer"]       # never a 0
    for sql, params in headline_db:
        if "AS headline" in sql:
            assert ["RI BHOI"] in params and 2025 in params


OLD_CARD_SQL = json.loads(r'''{
 "mgnrega": "SELECT (SELECT SUM(person_days) FROM curated.v_employment) AS person_days,\n                         (SELECT SUM(total_exp) FROM curated.v_expenditure) AS exp_lakh,\n                         (SELECT COUNT(*) FROM (SELECT village_code FROM curated.v_employment\n                                                UNION SELECT village_code FROM curated.v_expenditure) v\n                          WHERE village_code IS NOT NULL) AS villages",
 "pmay_g": "SELECT COUNT(*) AS sanctioned, COUNT(*) FILTER (WHERE is_completed) AS completed,\n                        SUM(COALESCE(amount_released, 0)) AS released\n                 FROM curated.v_pmay",
 "focus_plus": "SELECT COUNT(*) AS payments, SUM(amount_disbursed) AS amount,\n                            COUNT(DISTINCT lgd_district) AS districts FROM curated.v_focus_plus",
 "cm_elevate": "SELECT COUNT(DISTINCT request_id) AS applications, COUNT(DISTINCT scheme_name) AS schemes,\n                            COUNT(DISTINCT lgd_district) AS districts FROM curated.v_cm_elevate",
 "focus_legacy": "SELECT COUNT(DISTINCT pg_id) AS groups, SUM(no_of_pg_members) AS memberships,\n                              SUM(amount_disbursed) AS amount FROM curated.v_focus_legacy",
 "cm_elevate_legacy": "SELECT COUNT(*) AS records, COUNT(DISTINCT scheme_name) AS schemes,\n                                   SUM(total_disbursement) AS disbursed FROM curated.v_cm_elevate_disbursement",
 "cmss": "SELECT COUNT(*) AS applications, COUNT(*) FILTER (WHERE is_disbursed) AS students_paid, SUM(amount_disbursed) AS amount_disbursed FROM curated.v_cmss",
 "homestay": "SELECT COUNT(*) AS applications, COUNT(DISTINCT member_key) AS applicants, COUNT(*) FILTER (WHERE file_status = 'Approved') AS approved FROM curated.v_homestay_api"
}''')


def test_the_card_statements_are_unchanged_and_lead_with_the_declared_headline():
    assert stats._SQL == OLD_CARD_SQL
    for e in reg.ENTRIES:
        h = e.headline
        sql = stats._SQL[h.card]
        lead = sql[len("SELECT "):].split(" AS ")[0]
        assert lead in (h.expr, f"(SELECT {h.expr} FROM {h.view})"), e.name
        assert sql[len("SELECT "):].split(" AS ")[1].split(",")[0] == h.figure
        assert h.view in sql


def test_the_card_leads_with_the_declared_label():
    rows = {"mgnrega": {"person_days": 1e7, "exp_lakh": 1, "villages": 1},
            "pmay_g": {"sanctioned": 1, "completed": 1, "released": 1},
            "focus_plus": {"payments": 1, "amount": 1, "districts": 1},
            "cm_elevate": {"applications": 1, "schemes": 1, "districts": 1},
            "focus_legacy": {"groups": 1, "memberships": 1, "amount": 1},
            "cm_elevate_legacy": {"records": 1, "schemes": 1, "disbursed": 1},
            "cmss": {"applications": TRUTH["CMSS"]["applications"], "students_paid": TRUTH["CMSS"]["paid"],
                     "amount_disbursed": TRUTH["CMSS"]["rupees"]},
            "homestay": {"applications": TRUTH["Homestay"]["applications"], "applicants": 1, "approved": 1}}
    cards = stats._cards(rows, {"mgnrega": ["2022-23", "2023-24"]})
    for e in reg.ENTRIES:
        assert cards[e.headline.card][0][1].startswith(e.headline.label), e.name
    assert cards["cmss"] == [["1,04,827", "Applications"], ["98,751", "Students paid"], ["₹59.25 Cr", "Amount disbursed"]]
    assert cards["homestay"][0] == ["1,297", "Applications"]


# ── 2. fan-out ─────────────────────────────────────────────────────────────────

def _slow_db(monkeypatch, delay: dict, fail: "dict | None" = None):
    state = {"now": 0, "max": 0, "done": []}

    async def fetch_rows(sql, params):
        s = _scheme_of(sql) if "AS headline" in sql else next(
            n for n, q in cf._QUERIES.items() if any(f"FROM {v} " in sql for v, *_ in q))
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        try:
            await asyncio.sleep(delay.get(s, 0.02))
            if fail and s in fail:
                raise fail[s]
            state["done"].append(s)
            if "DISTINCT year_key AS y" in sql:
                return [{"y": 2025}]
            return [{"k": None, "headline": 10, "ben": 5, "money": 1.0, "villages": 3, "districts": 2,
                     "blocks": 4, "completed": 1, "sanctioned": 1.0, "pgs": 1, "payments": 2, "records": 2}]
        finally:
            state["now"] -= 1
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)
    return state


def test_schemes_are_queried_concurrently_within_the_limit(monkeypatch):
    monkeypatch.setattr(settings, "CROSS_SCHEME_CONCURRENCY", 3)
    state = _slow_db(monkeypatch, {s: 0.1 for s in ALL})
    pl = cf.plan("Compare beneficiaries across all schemes", ALL, {}, {}, M)
    t0 = time.monotonic()
    out = asyncio.run(cf.answer(pl))
    took = time.monotonic() - t0
    assert state["max"] == 3                       # concurrent, and never past the limit
    assert took < 0.1 * len(ALL) * 0.75            # sequential would be ~0.8 s or more
    assert out["schemes_failed"] == [] and set(out["schemes_with_data"]) == set(ALL)


def test_sql_and_lines_follow_the_scheme_order_not_the_finish_order(monkeypatch):
    # the first scheme is the slowest: it finishes last
    _slow_db(monkeypatch, {s: 0.01 * (len(ALL) - i) for i, s in enumerate(ALL)})
    out = asyncio.run(cf.answer(cf.plan("Compare beneficiaries across all schemes", ALL, {}, {}, M)))
    order = [next(n for n, q in cf._QUERIES.items() if any(f"FROM {v} " in sql for v, *_ in q))
             for sql in out["sql"].split("\n;\n")]
    assert order == sorted(order, key=ALL.index)
    pos = [out["answer"].index(f"**{s}") for s in out["schemes_with_data"]]
    assert pos == sorted(pos)


def test_a_slow_scheme_is_named_and_the_rest_answered(monkeypatch):
    monkeypatch.setattr(settings, "CROSS_SCHEME_TIMEOUT_SECONDS", 0.2)
    _slow_db(monkeypatch, {"Homestay": 1.0})
    out = asyncio.run(cf.answer(cf.plan("give me the headline figures across all schemes", ALL, {}, {}, M)))
    assert out["schemes_failed"] == ["Homestay"]
    assert "Homestay is not in this answer: its figures took too long to read" in out["answer"]
    assert "Homestay" not in out["schemes_with_data"] and "**CMSS**" in out["answer"]


def test_a_failed_scheme_is_named_and_the_rest_answered(monkeypatch):
    _slow_db(monkeypatch, {}, fail={"PMAY-G": ConnectionError("db flapped")})
    out = asyncio.run(cf.answer(cf.plan("How much money has each scheme disbursed?", ALL, {}, {}, M)))
    assert out["schemes_failed"] == ["PMAY-G"]
    assert "PMAY-G is not in this answer: its figures could not be read just now" in out["answer"]
    assert "MGNREGA" in out["schemes_with_data"]


def test_every_scheme_failing_raises_as_before(monkeypatch):
    _slow_db(monkeypatch, {}, fail={s: ConnectionError("down") for s in ALL})
    with pytest.raises(ConnectionError):
        asyncio.run(cf.answer(cf.plan("Compare beneficiaries across all schemes", ALL, {}, {}, M)))


def test_an_overlap_needs_every_scheme(monkeypatch):
    async def fetch_rows(sql, params):
        if "v_pmay" in sql:
            raise ConnectionError("down")
        return [{"v": 1}, {"v": 2}]
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)
    pl = cf.plan("how many villages are covered by both MGNREGA and PMAY-G", ["MGNREGA", "PMAY-G"], {}, {}, M)
    assert pl.op == "overlap"
    with pytest.raises(ConnectionError):
        asyncio.run(cf.answer(pl))


# ── 3. the grain in the semantic-cache signature ───────────────────────────────

@pytest.mark.parametrize("a,b", [
    ("money spent in each scheme by district", "money spent in each scheme in total"),
    ("MGNREGA expenditure by district", "MGNREGA expenditure by block"),
    ("MGNREGA expenditure district-wise", "MGNREGA expenditure per year"),
    ("PMAY-G houses sanctioned each year", "PMAY-G houses sanctioned"),
    ("Compare beneficiaries across all schemes", "Compare beneficiaries across all schemes combined"),
    ("CMSS students paid by constituency", "CMSS students paid by block"),
    ("PMAY-G sanctions monthly", "PMAY-G sanctions yearly"),
])
def test_different_grains_never_share_a_signature(a, b):
    assert semantic_cache.scope_signature(a) != semantic_cache.scope_signature(b)


@pytest.mark.parametrize("a,b", [
    ("MGNREGA expenditure by district", "MGNREGA expenditure district wise"),
    ("money spent in each scheme in total", "money spent in each scheme altogether"),
])
def test_the_same_grain_in_other_words_still_shares_one(a, b):
    assert semantic_cache.grain_terms(a) == semantic_cache.grain_terms(b)
