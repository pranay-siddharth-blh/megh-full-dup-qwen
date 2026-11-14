"""Cross-scheme answers over EVERY onboarded scheme, every shape (2026-11-14).

Homestay (onboarded 2026-11-12) records no money and counts applications, but `cross_figures.NO_MONEY` and
`_APART_IN_COMBINED` still named only CM Elevate and `_MONEY_VERB` / `_PER` had no Homestay entry: "which scheme
disbursed the most" and "each year, for all schemes, what was disbursed" raised KeyError over all eight schemes and the
turn fell back to the documents. No existing test asked a money or per-year question of all eight.

Both sets are now derived from the per-scheme specs, so this file is a matrix: every question shape x all supported
schemes on a fake megh_db (the harness of test_cross_sheet_rerun_2026_10_30). A scheme onboarded later joins the matrix
by being in `cross_figures.SUPPORTED`; nothing here names the schemes."""
import asyncio

import pytest

from app import cross_figures as cf
from app import pipeline as p
from app import scheme_registry
from tests.test_cross_sheet_rerun_2026_10_30 import _DIST, _VIEW

M = p._SCHEME_NAME_MATCHER
ALL = list(cf.SUPPORTED)


@pytest.fixture
def fake_db(monkeypatch):
    """The sheet re-run's fake megh_db, plus a grouping by year (its keys are year keys, not districts)."""
    async def fetch_rows(sql, params):
        s = next(v for k, v in _VIEW.items() if k in sql)
        years = (2017, 2023) if s == "PMAY-G" else (2022, 2025)
        if "DISTINCT year_key AS y" in sql:
            return [{"y": y} for y in years]
        by_year = "year_key AS k" in sql or "year_key::text AS k" in sql
        keys = (list(years) if by_year else list(_DIST[s])) if "GROUP BY" in sql else [None]
        out = []
        for k in keys:
            vals = list(_DIST[s].values()) if (k is None or by_year) else [_DIST[s][k]]
            ben, money, vill = (sum(v[i] for v in vals) for i in range(3))
            out.append({"k": k, "ben": ben, "money": money, "villages": vill, "districts": 2, "blocks": 5,
                        "completed": ben // 2, "sanctioned": money * 1.02, "pgs": ben // 8, "payments": ben * 4,
                        "records": ben + 3})
        return out
    monkeypatch.setattr(cf.db, "fetch_rows", fetch_rows)

QUESTIONS = [
    "Which scheme has disbursed the most money?",
    "Each year, for all schemes, what was disbursed?",
    "How much money has each scheme disbursed?",
    "Compare beneficiaries across all schemes",
    "How many beneficiaries are there in total across all schemes?",
    "Which scheme has the widest coverage across the districts of Meghalaya?",
    "Which scheme leads in each district?",
    "Give me a district-wise summary comparing all schemes",
    "Compare the number of beneficiaries and the total amount for all schemes",
    "Which scheme gives the most money per beneficiary?",
    "Each year, for all schemes, how many beneficiaries were there?",
    "Which district gets the most money across all the schemes that have money?",
]


def test_no_money_and_applications_sets_follow_the_specs():
    for s in ALL:
        has_expr = any(m == "money" for _v, _d, _b, metrics in cf._QUERIES[s] for m, _e in metrics)
        assert (s in cf.NO_MONEY) == (not has_expr), s
        assert cf.has_measure(s, "money") == has_expr, s
        # the registry's own fact agrees: a dataset with no money unit holds no money
        facts = scheme_registry.DATASETS.get(s)
        if facts is not None:
            assert (facts.money_unit is None) == (s in cf.NO_MONEY), s
    assert {s for s in ALL if cf._BEN_NOUN[s] == "applications"} == set(cf._APART_IN_COMBINED)
    assert {"CM Elevate", "Homestay"} <= set(cf.NO_MONEY)


@pytest.mark.parametrize("q", QUESTIONS)
def test_every_shape_answers_over_all_schemes_without_raising(q, fake_db):
    pl = cf.plan(q, ALL, {}, {}, M)
    if pl is None:
        pytest.skip("not a shape cross_figures plans (the model path takes it)")
    out = asyncio.run(cf.answer(pl))
    text = out["answer"] if isinstance(out, dict) else str(out)
    assert text and "KeyError" not in text
    # a scheme with no money is never given an amount: it is said plainly or left out of a money ranking
    for s in cf.NO_MONEY:
        assert f"{cf.SHORT[s]}**: ₹" not in text and f"{cf.SHORT[s]}: ₹" not in text, (q, s)


@pytest.mark.parametrize("q", QUESTIONS)
@pytest.mark.parametrize("district", ["RI BHOI", "WEST GARO HILLS"])
def test_every_shape_answers_in_one_district(q, district, fake_db):
    pl = cf.plan(q, ALL, {"district": district}, {"district": district.title()}, M)
    if pl is None:
        pytest.skip("not planned for a district scope")
    out = asyncio.run(cf.answer(pl))
    assert (out["answer"] if isinstance(out, dict) else out)


def test_money_ranking_asks_only_schemes_that_record_money():
    money = [s for s in cf.SUPPORTED if cf.has_measure(s, "money")]
    assert "Homestay" not in money and "CM Elevate" not in money and "CMSS" in money
    assert cf._money_verb("Homestay") and cf._per("Homestay")      # never a KeyError, whatever is asked
