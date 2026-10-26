"""Job cards follow the year asked (MGNREGA sheet DATA-007, run 2026-10-21).

Every job-card question was pinned to FY 2025-26 (the latest year) whatever
was asked, and 24 of 24 answers said "across all financial years" over SQL
reading year_key = 2025. Now: the year asked -> that year; no year -> the
chat's year, else the year pause; all years -> one figure per year (a running
total is never added). The answer names the year the SQL read."""
import asyncio

import pytest

from app import pipeline as p

BARATO = {"village_code": 279198}


# ── the deterministic job-card query ───────────────────────────────────────
def test_year_asked_is_the_year_queried():
    sql, params, shown = p._mgnrega_job_cards_query("How many job cards were issued in BARATO?", ["MGNREGA"],
                                                    {**BARATO, "year_key": 2023})
    assert params == [279198, [2023]]
    assert "year_key = 2023" in shown and "2025" not in shown
    assert "/* mg-job-cards */" in sql


def test_several_years_asked_are_each_queried():
    _sql, params, shown = p._mgnrega_job_cards_query("job cards in BARATO in 2022-23 and 2024-25", ["MGNREGA"],
                                                     {**BARATO, "year_key_list": [2024, 2022]})
    assert params[-1] == [2022, 2024]
    assert "year_key IN (2022, 2024)" in shown


@pytest.mark.parametrize("q", [
    "How many job cards were issued in BARATO across all financial years?",
    "How many job cards were issued in BARATO till date?",
])
def test_all_years_is_one_row_per_year_never_a_sum_or_the_latest(q):
    _sql, _params, shown = p._mgnrega_job_cards_query(q, ["MGNREGA"], dict(BARATO))
    assert "year_key =" not in shown and "MAX(year_key)" not in shown
    assert "GROUP BY year_key" in shown


def test_no_year_anywhere_is_never_guessed():
    # the year pause asks first; this path never picks a year itself
    assert p._mgnrega_job_cards_query("How many job cards were issued in BARATO?", ["MGNREGA"], dict(BARATO)) is None


@pytest.mark.parametrize("q", [
    "Job cards by district in 2024-25",
    "Which district has the most job cards?",
    "How many job cards and person-days in Barato?",
    "How many households have job cards in Barato?",
    "job cards in each district across all financial years",
])
def test_rankings_breakdowns_and_other_measures_stay_with_the_generator(q):
    assert p._mgnrega_job_cards_query(q, ["MGNREGA"], {**BARATO, "year_key": 2023}) is None


def test_constituency_is_a_job_card_area():
    _sql, params, shown = p._mgnrega_job_cards_query("job cards in Gambegre constituency", ["MGNREGA"],
                                                     {"assembly_constituency": "GAMBEGRE", "year_key": 2023})
    assert "assembly_constituency_name" in shown and params[0] == "GAMBEGRE"


# ── the answer is written from the rows the query read ─────────────────────
def test_one_year_answer_names_that_year_only():
    a = p._mgnrega_job_cards_answer([{"year_key": 2023, "financial_year": "2023-24", "job_cards_issued": 967}],
                                    {"village": "Barato"})
    assert a == "967 MGNREGA job cards had been issued in Barato village as of FY 2023-24."
    assert "all financial years" not in a


def test_every_year_answer_lists_each_year_and_never_adds_them():
    rows = [{"year_key": y, "financial_year": f, "job_cards_issued": n}
            for y, f, n in [(2022, "2022-23", 958), (2023, "2023-24", 967), (2024, "2024-25", 976),
                            (2025, "2025-26", 1047)]]
    a = p._mgnrega_job_cards_answer(rows, {"district": "Ri Bhoi"})
    for line in ("FY 2022-23: 958", "FY 2023-24: 967", "FY 2024-25: 976", "FY 2025-26: 1,047"):
        assert line in a
    assert "3,948" not in a and "Ri Bhoi district" in a


# ── the generator-path safety net pins the year asked, not the latest ──────
BARE = "SELECT SUM(job_cards_issued_total) FROM curated.v_employment WHERE lgd_district = 'X'"


def test_safety_net_pins_the_resolved_year():
    out = p._mgnrega_job_cards_latest_year(["MGNREGA"], BARE, question="job cards in X", resolved={"year_key": 2023})
    assert "year_key = 2023" in out and "MAX(year_key)" not in out


def test_safety_net_leaves_an_all_years_question_to_the_per_year_guard():
    out = p._mgnrega_job_cards_latest_year(["MGNREGA"], BARE, question="job cards in X across all financial years",
                                           resolved={})
    assert out == BARE


def test_safety_net_latest_year_only_when_no_year_anywhere():
    assert "MAX(year_key)" in p._mgnrega_job_cards_latest_year(["MGNREGA"], BARE)


def test_all_years_combined_guard_keeps_job_cards_per_year():
    # the "one combined figure" guard must not send a job-card per-year split back
    sql = "SELECT year_key, SUM(job_cards_issued_total) AS j FROM curated.v_employment GROUP BY year_key"
    assert p._vr_grouped_by_year_only(sql) and p._vr_sums_column(sql, "job_cards_issued_total")


# ── the year pause: job cards are no longer exempt ─────────────────────────
@pytest.fixture
def _defaults_on(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "ANSWER_DEFAULTS_ENABLED", True)
    monkeypatch.setattr(settings, "YEAR_CLARIFY_ENABLED", True)


def _turn(question, resolved, prior_resolved=None):
    d = p._new_data_turn(question, prior_resolved=prior_resolved)
    d["schemes"] = ["MGNREGA"]
    d["chat_has_scope"] = True
    d["entity_result"] = {"resolved": dict(resolved), "display": {}, "question": None}
    return d


def test_job_card_question_with_no_year_asks_the_year(_defaults_on):
    with pytest.raises(p.ClarificationNeeded) as exc:
        asyncio.run(p._data_clarification_stage(_turn("How many job cards were issued in BARATO?", BARATO)))
    assert exc.value.rule == "year-not-specified"
    labels = [o["label"] for o in exc.value.options]
    assert "Every financial year (one figure each)" in labels
    assert "All financial years combined" not in labels
    assert "FY 2023-24" in labels


def test_job_card_follow_up_in_an_all_years_chat_is_answered_per_year(_defaults_on):
    d = _turn("How many job cards were issued in BARATO?", BARATO, prior_resolved={"year_all": True})
    asyncio.run(p._data_clarification_stage(d))
    assert d["question"].endswith("across all financial years")


# ── the composer is told the year the SQL read ─────────────────────────────
@pytest.mark.parametrize("sql,year", [
    ("SELECT SUM(x) FROM curated.v_employment WHERE village_code = 1 AND year_key = 2025 LIMIT 1", "FY 2025-26"),
    ("WITH a AS (SELECT SUM(x) s FROM curated.v_employment WHERE year_key = 2023), "
     "b AS (SELECT SUM(y) t FROM curated.v_expenditure WHERE year_key = 2023) SELECT * FROM a, b", "FY 2023-24"),
    ("SELECT SUM(x) FROM curated.v_employment WHERE year_key IN (2023, 2024)", None),
    ("SELECT year_key, SUM(x) FROM curated.v_employment GROUP BY year_key", None),
    ("SELECT SUM(CASE WHEN year_key = 2023 THEN x END) FROM curated.v_employment", None),
    ("SELECT SUM(x) FROM curated.v_employment WHERE year_key >= 2023", None),
])
def test_entities_carry_the_one_year_the_query_pins(sql, year):
    out = asyncio.run(p._entities_with_sql_year(sql, {"village": "Barato"}))
    assert out.get("year") == year


def test_a_year_the_question_named_is_kept():
    out = asyncio.run(p._entities_with_sql_year(
        "SELECT 1 FROM curated.v_employment WHERE year_key = 2025", {"year": "FY 2023-24"}))
    assert out == {"year": "FY 2023-24"}


def test_one_year_entities_make_the_closing_line_name_that_year():
    # _finish_answer drops "across all financial years" once the period is the SQL's year
    out = p._finish_answer("88 job cards were issued in Madansohmylleng across all financial years.",
                           [{"job_card_stock": 88}], ["MGNREGA"],
                           {"village": "Madansohmylleng", "year": "FY 2025-26"})
    assert "all financial years" not in out and "FY 2025-26" in out


# ── a place known only by its code is never "statewide" ───────────────────
def test_village_code_only_answer_is_not_called_statewide():
    result = {"route": "data", "schemes": ["MGNREGA"], "resolved_entities": {"year_key": 2023, "village_code": 279198},
              "rows": [{"job_cards_issued": 967}],
              "answer": "967 MGNREGA job cards had been issued in Barato village as of FY 2023-24."}
    p._finish_data_result(result)
    assert "statewide" not in result["answer"]
    assert result["answer"].startswith("967 MGNREGA job cards")


def test_a_truly_statewide_answer_still_says_so():
    result = {"route": "data", "schemes": ["MGNREGA"], "resolved_entities": {"year_key": 2023},
              "rows": [{"person_days": 27264054}], "answer": "27264054 person-days were generated in FY 2023-24."}
    p._finish_data_result(result)
    assert "Meghalaya" in result["answer"] and "27,264,054" in result["answer"]
